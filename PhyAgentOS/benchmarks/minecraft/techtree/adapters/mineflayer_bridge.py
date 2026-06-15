"""Reference world adapter for a mineflayer HTTP bridge.

This adapter is intentionally outside the benchmark core.  Users may provide
their own adapter as long as it implements ``reset(setup)`` and ``observe()``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

import httpx

from PhyAgentOS.benchmarks.minecraft.techtree.schema import ArenaSetup, SetupItem, WorldSetup


@dataclass
class MineflayerBridgeAdapter:
    bridge_url: str = "http://127.0.0.1:3000"
    timeout_s: float = 20.0
    verify_ssl: bool = False

    def reset(self, setup: WorldSetup) -> Mapping[str, Any]:
        self._set_phase("reset", reset_counters=True)
        try:
            if setup.arena.enabled:
                self._prepare_arena(setup.arena)
            if setup.clear_inventory:
                self._command("/clear @s")
            for item in setup.inventory:
                self._command(_give_command(item))
            origin = setup.arena.origin if setup.arena.enabled else _origin_from_state(self.observe())
            for block in setup.blocks:
                x = origin[0] + block.relative[0]
                y = origin[1] + block.relative[1]
                z = origin[2] + block.relative[2]
                self._command(f"/setblock {x} {y} {z} {_minecraft_name(block.block)}")
            return self.observe()
        finally:
            self._set_phase("idle", reset_counters=False)

    def observe(self) -> Mapping[str, Any]:
        with httpx.Client(timeout=self.timeout_s, verify=self.verify_ssl, trust_env=False) as client:
            response = client.get(f"{self.bridge_url.rstrip('/')}/state")
            response.raise_for_status()
            return response.json()

    def execute_action(self, action: str, params: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        with httpx.Client(timeout=self.timeout_s, verify=self.verify_ssl, trust_env=False) as client:
            response = client.post(
                f"{self.bridge_url.rstrip('/')}/action",
                json={"action": action, "params": dict(params or {})},
            )
            response.raise_for_status()
            return response.json()

    def _command(self, command: str) -> Mapping[str, Any]:
        return self.execute_action("chat", {"message": command, "allowCommand": True})

    def _prepare_arena(self, arena: ArenaSetup) -> None:
        x, y, z = arena.origin
        radius = max(1, int(arena.clear_radius))
        height = max(1, int(arena.clear_height))
        floor_y = y - 1
        min_x = x - radius
        max_x = x + radius
        min_z = z - radius
        max_z = z + radius
        self._command(f"/tp @s {x} {y} {z} 0 0")
        self._command(f"/fill {min_x} {y} {min_z} {max_x} {y + height} {max_z} air")
        self._command(
            f"/fill {min_x} {floor_y} {min_z} {max_x} {floor_y} {max_z} "
            f"{_minecraft_name(arena.floor_block)}"
        )
        boundary = _minecraft_name(arena.boundary_block)
        self._command(f"/fill {min_x} {floor_y} {min_z} {max_x} {floor_y} {min_z} {boundary}")
        self._command(f"/fill {min_x} {floor_y} {max_z} {max_x} {floor_y} {max_z} {boundary}")
        self._command(f"/fill {min_x} {floor_y} {min_z} {min_x} {floor_y} {max_z} {boundary}")
        self._command(f"/fill {max_x} {floor_y} {min_z} {max_x} {floor_y} {max_z} {boundary}")

    def _set_phase(self, phase: str, *, reset_counters: bool) -> None:
        with httpx.Client(timeout=self.timeout_s, verify=self.verify_ssl, trust_env=False) as client:
            response = client.post(
                f"{self.bridge_url.rstrip('/')}/phase",
                json={"phase": phase, "reset_counters": reset_counters, "source": "minecraft_techtree"},
            )
            response.raise_for_status()


def _give_command(item: SetupItem) -> str:
    item_name = _minecraft_name(item.item)
    suffix = ""
    if item.enchantments:
        entries = []
        for enchantment in item.enchantments:
            enchant_id = str(enchantment.get("id") or "").replace("minecraft:", "")
            level = int(enchantment.get("level", 1) or 1)
            entries.append(f'{{id:"minecraft:{enchant_id}",lvl:{level}}}')
        suffix = "{Enchantments:[" + ",".join(entries) + "]}"
    return f"/give @s {item_name}{suffix} {max(1, int(item.count or 1))}"


def _minecraft_name(name: str) -> str:
    return name if name.startswith("minecraft:") else f"minecraft:{name}"


def _origin_from_state(state: Mapping[str, Any]) -> tuple[int, int, int]:
    position = state.get("position")
    if not isinstance(position, Mapping):
        bot = state.get("bot")
        if isinstance(bot, Mapping):
            position = bot.get("position")
    if not isinstance(position, Mapping):
        raise ValueError("bridge state does not contain bot position")
    return (
        math.floor(float(position.get("x", 0))),
        math.floor(float(position.get("y", 0))),
        math.floor(float(position.get("z", 0))),
    )
