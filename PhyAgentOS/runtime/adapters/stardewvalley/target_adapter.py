"""Stardew Valley target adapter for PhyAgentOS runtime contracts.

This adapter is intentionally lightweight: it normalizes StarDojo bridge
observations/actions into the generic runtime adapter shape without starting the
game or the HTTP bridge. The long-lived game connection remains in
``bridge/stardew_runtime.py`` and ``bridge/bridge_server.py``.
"""

from __future__ import annotations

from typing import Any


from PhyAgentOS.runtime.adapters.base import BaseTargetAdapter
from PhyAgentOS.runtime.adapters.stardewvalley.bridge.action_parser import (
    allowed_skill_names,
    parse_skill_expression,
)
from PhyAgentOS.runtime.adapters.stardewvalley.bridge.obs_compact import COMPACT_OBS_KEYS
from PhyAgentOS.runtime.watchdog.errors import AdapterError


class StardewValleyTargetAdapter(BaseTargetAdapter):
    """Normalize StarDojo bridge payloads for PhyAgentOS runtime code."""

    def output_observation_contract(self) -> dict[str, Any]:
        return {
            "sensors": {
                "latest_image_url": {
                    "kind": "image_url",
                    "observation_key": "latest_image_url",
                    "dtype": "string_or_null",
                },
                "proprio": {
                    "kind": "vector",
                    "observation_key": "stardew.health_energy_money_xy",
                    "dtype": "float32",
                    "shape": [5],
                },
            },
            "stardew": {"compact_obs_keys": list(COMPACT_OBS_KEYS)},
        }

    def input_action_contract(self) -> dict[str, Any]:
        return {
            "action": {
                "kind": "stardojo_skill_call",
                "format": "skill_name(literal_arg, ...)",
                "allowed_skills": list(allowed_skill_names()),
            }
        }

    def to_runtime_observation(self, raw_obs: dict[str, Any], target_info: dict[str, Any]) -> dict[str, Any]:
        obs = _unwrap_bridge_observation(raw_obs)
        target_info = dict(target_info)
        step_index = target_info.get("step_index", 0)

        return {
            "observation_id": obs.get("observation_id", f"stardew_obs_{step_index}"),
            "sensors": {
                "latest_image_url": {
                    "kind": "image_url",
                    "observation_key": "latest_image_url",
                    "data": obs.get("latest_image_url"),
                    "dtype": "string_or_null",
                },
                "proprio": {
                    "kind": "vector",
                    "observation_key": "stardew.health_energy_money_xy",
                    "data": _proprio_vector(obs),
                    "dtype": "float32",
                },
            },
            "target_info": target_info,
            "stardew": {key: obs.get(key) for key in COMPACT_OBS_KEYS},
        }

    def to_executable_action_chunk(
        self,
        action_chunk: dict[str, Any],
        target_info: dict[str, Any],
    ) -> dict[str, Any]:
        actions = action_chunk.get("actions")
        if actions is None:
            single_action = action_chunk.get("action")
            if single_action is None:
                raise AdapterError("Stardew action chunk must contain action or actions")
            actions = [single_action]

        normalized_actions = [_normalize_action(action) for action in actions]
        return {
            "chunk_id": action_chunk.get("chunk_id", "stardew_chunk"),
            "source_observation_id": action_chunk.get("source_observation_id"),
            "actions": normalized_actions,
            "safety": {
                "require_target_side_validation": True,
                "stop_on_timeout": True,
            },
            "target_info": dict(target_info),
        }


def _unwrap_bridge_observation(raw_obs: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_obs, dict):
        raise AdapterError(f"Stardew observation must be a dict, got {type(raw_obs).__name__}")
    if raw_obs.get("ok") is True and isinstance(raw_obs.get("obs"), dict):
        return raw_obs["obs"]
    return raw_obs


def _normalize_action(action: Any) -> dict[str, Any]:
    if isinstance(action, str):
        expression = action
    elif isinstance(action, dict) and isinstance(action.get("action"), str):
        expression = action["action"]
    else:
        raise AdapterError("Stardew actions must be strings or dicts with an action string")

    try:
        skill_name, args, kwargs = parse_skill_expression(expression)
    except Exception as exc:
        raise AdapterError(str(exc)) from exc

    return {
        "action": expression,
        "skill": skill_name,
        "args": args,
        "kwargs": kwargs,
    }


def _proprio_vector(obs: dict[str, Any]) -> list[float]:
    position = obs.get("position")
    if isinstance(position, dict):
        x = _float_or_zero(position.get("x"))
        y = _float_or_zero(position.get("y"))
    elif isinstance(position, (list, tuple)) and len(position) >= 2:
        x = _float_or_zero(position[0])
        y = _float_or_zero(position[1])
    else:
        x = 0.0
        y = 0.0

    return [
        _float_or_zero(obs.get("health")),
        _float_or_zero(obs.get("energy")),
        _float_or_zero(obs.get("money")),
        x,
        y,
    ]


def _float_or_zero(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0
