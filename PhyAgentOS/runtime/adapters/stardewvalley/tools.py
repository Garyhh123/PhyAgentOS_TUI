"""Track A tools for controlling Stardew Valley through the bridge."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from PhyAgentOS.agent.tools.base import Tool
from PhyAgentOS.agent.tools.registry import ToolRegistry
from PhyAgentOS.runtime.adapters.stardewvalley.bridge.action_parser import (
    ActionParseError,
    parse_skill_expression,
)


_DEFAULT_BRIDGE_URL = "http://127.0.0.1:8765"
_BUSY_RETRY_DELAYS = (2.0, 5.0, 10.0)


class BridgeBusyError(RuntimeError):
    """Raised when the bridge reports an in-flight Stardew call."""


class StardewActionTool(Tool):
    """Execute one Stardew action through the normal or benchmark bridge API."""

    def __init__(
        self,
        *,
        bridge_url: str = _DEFAULT_BRIDGE_URL,
        mode: str = "normal",
        timeout: float = 180.0,
        run_dir: str | Path | None = None,
    ) -> None:
        self.bridge_url = bridge_url.rstrip("/")
        self.mode = mode
        self.timeout = timeout
        self.run_dir = Path(run_dir).expanduser() if run_dir else None

    @property
    def name(self) -> str:
        return "stardew_action"

    @property
    def description(self) -> str:
        return (
            "Execute exactly one Stardew Valley StarDojo action string, then return the new observation. "
            "Use this for Stardew control instead of curl, exec, HTTP, or ACTION text. "
            "If the result has done=true or truncated=true, stop calling this tool and summarize."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": (
                        'A raw StarDojo action string, for example move(1, 0), use("down"), '
                        'interact("up"), choose_item(4), menu("open", "map"), or unattach_item().'
                    ),
                }
            },
            "required": ["action"],
        }

    async def execute(self, action: str) -> str:
        action = action.strip() if isinstance(action, str) else action
        try:
            parse_skill_expression(action)
        except ActionParseError as exc:
            record = {
                "timestamp": _now_iso(),
                "tool": self.name,
                "type": "invalid_action",
                "action": action,
                "error": str(exc),
            }
            self._append_log(record)
            return f"Error: Invalid Stardew action: {exc}"

        path = "/benchmark/execute" if self.mode == "benchmark" else "/execute"
        try:
            async with httpx.AsyncClient(base_url=self.bridge_url, timeout=self.timeout, trust_env=False) as client:
                payload = await _request_json_with_busy_retry(client, "POST", path, json={"action": action})
        except BridgeBusyError as exc:
            record = {
                "timestamp": _now_iso(),
                "tool": self.name,
                "type": "bridge_busy",
                "mode": self.mode,
                "action": action,
                "error": str(exc),
            }
            self._append_log(record)
            return json.dumps(
                {
                    "ok": False,
                    "busy": True,
                    "action": action,
                    "error": str(exc),
                    "instruction": "The bridge is still processing a previous Stardew call. Do not issue another different Stardew action immediately; wait briefly and retry or summarize the environment issue.",
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            record = {
                "timestamp": _now_iso(),
                "tool": self.name,
                "type": "tool_error",
                "mode": self.mode,
                "action": action,
                "error": str(exc),
            }
            self._append_log(record)
            return f"Error: {exc}"

        obs = payload.get("obs")
        benchmark = payload.get("benchmark") if isinstance(payload.get("benchmark"), dict) else {}
        done = bool(benchmark.get("completed", False)) if self.mode == "benchmark" else False
        truncated = bool(benchmark.get("truncated", False)) if self.mode == "benchmark" else False

        record = {
            "timestamp": _now_iso(),
            "tool": self.name,
            "type": "tool_call",
            "mode": self.mode,
            "action": action,
            "payload": payload,
        }
        self._append_log(record)

        result = {
            "ok": True,
            "action": action,
            "obs": obs,
            "done": done,
            "truncated": truncated,
            "instruction": (
                "Stop calling Stardew tools and summarize the run."
                if done or truncated
                else "Choose the next single Stardew action from the new observation."
            ),
        }
        return json.dumps(result, ensure_ascii=False, default=str)

    def _append_log(self, record: dict[str, Any]) -> None:
        if not self.run_dir:
            return
        self.run_dir.mkdir(parents=True, exist_ok=True)
        with (self.run_dir / "tool_calls.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


class StardewObserveTool(Tool):
    """Return the current compact Stardew observation through the bridge."""

    def __init__(
        self,
        *,
        bridge_url: str = _DEFAULT_BRIDGE_URL,
        timeout: float = 180.0,
        run_dir: str | Path | None = None,
    ) -> None:
        self.bridge_url = bridge_url.rstrip("/")
        self.timeout = timeout
        self.run_dir = Path(run_dir).expanduser() if run_dir else None

    @property
    def name(self) -> str:
        return "stardew_observe"

    @property
    def description(self) -> str:
        return "Return the current compact Stardew Valley observation without executing an action."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self) -> str:
        try:
            async with httpx.AsyncClient(base_url=self.bridge_url, timeout=self.timeout, trust_env=False) as client:
                payload = await _request_json_with_busy_retry(client, "GET", "/observe")
        except BridgeBusyError as exc:
            self._append_log({"timestamp": _now_iso(), "tool": self.name, "type": "bridge_busy", "error": str(exc)})
            return json.dumps(
                {
                    "ok": False,
                    "busy": True,
                    "error": str(exc),
                    "instruction": "The bridge is still processing a previous Stardew call. Wait briefly before observing again.",
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            self._append_log({"timestamp": _now_iso(), "tool": self.name, "type": "tool_error", "error": str(exc)})
            return f"Error: {exc}"

        self._append_log({"timestamp": _now_iso(), "tool": self.name, "type": "tool_call", "payload": payload})
        return json.dumps({"ok": True, "obs": payload.get("obs")}, ensure_ascii=False, default=str)

    def _append_log(self, record: dict[str, Any]) -> None:
        if not self.run_dir:
            return
        self.run_dir.mkdir(parents=True, exist_ok=True)
        with (self.run_dir / "tool_calls.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def register_stardew_tools_from_env(registry: ToolRegistry) -> bool:
    """Register Stardew tools when the Track A environment enables them."""

    if not _truthy(os.environ.get("PHYAGENTOS_STARDEW_ENABLED")):
        return False

    bridge_url = os.environ.get("PHYAGENTOS_STARDEW_BRIDGE_URL", _DEFAULT_BRIDGE_URL)
    mode = os.environ.get("PHYAGENTOS_STARDEW_MODE", "normal").strip().lower() or "normal"
    run_dir = os.environ.get("PHYAGENTOS_STARDEW_RUN_DIR") or None
    timeout = _float_env("PHYAGENTOS_STARDEW_TIMEOUT", 180.0)

    registry.register(StardewActionTool(bridge_url=bridge_url, mode=mode, timeout=timeout, run_dir=run_dir))
    registry.register(StardewObserveTool(bridge_url=bridge_url, timeout=timeout, run_dir=run_dir))
    return True



async def _request_json_with_busy_retry(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    last_busy: BridgeBusyError | None = None
    for attempt, delay in enumerate((*_BUSY_RETRY_DELAYS, 0.0), start=1):
        response = await client.request(method, path, json=json)
        try:
            return _response_json(response)
        except BridgeBusyError as exc:
            last_busy = exc
            if delay <= 0:
                break
            await asyncio.sleep(delay)
    if last_busy is not None:
        raise last_busy
    raise RuntimeError("Bridge request failed without a response payload.")


def _response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Bridge returned non-JSON response: HTTP {response.status_code}") from exc
    if response.status_code == 409:
        raise BridgeBusyError(payload.get("error") or "Stardew bridge is busy.")
    if response.status_code >= 400 or payload.get("ok") is False:
        raise RuntimeError(payload.get("error") or f"Bridge returned HTTP {response.status_code}")
    return payload


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
