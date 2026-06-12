"""Minecraft task verification primitives.

Supported descriptors:
    has_item:name        → bot inventory contains item named 'name'
    has_item:name×N      → bot inventory contains at least N of 'name'
    block_at:x,y,z,name  → block at (x,y,z) is exactly 'name'
    block_at:x,y,z       → any non-air block exists at (x,y,z)
    block_near:name,max  → block 'name' found within max blocks
    bot_near:x,y,z,dist  → bot is within 'dist' meters of (x,y,z)
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any

from PhyAgentOS.runtime.skillruntime.game.condition_verifier import GameConditionVerifier

logger = logging.getLogger(__name__)

_HAS_ITEM_RE = re.compile(r"has_item:(\w[\w_:]*?)(?:×(\d+))?$")
_BLOCK_AT_RE = re.compile(r"block_at:(-?\d+),(-?\d+),(-?\d+)(?:,(\w[\w_:]*))?$")
_BLOCK_NEAR_RE = re.compile(r"block_near:(\w[\w_:]*?),(\d+)$")
_BOT_NEAR_RE = re.compile(
    r"bot_near:(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(\d+(?:\.\d+)?)$"
)


class MinecraftTaskVerifier(GameConditionVerifier):
    """Checks Minecraft task preconditions and post-conditions."""

    def __init__(self, target, raw_obs: dict[str, Any]):
        super().__init__(target, raw_obs)
        self._inv_cache: dict[str, int] | None = None

    def _get_inventory(self) -> dict[str, int]:
        if self._inv_cache is not None:
            return self._inv_cache
        inventory = self._obs.get("inventory", {})
        hotbar = inventory.get("hotbar", [])
        by_name: dict[str, int] = {}
        for slot in hotbar:
            if isinstance(slot, dict):
                name = slot.get("name", "")
                count = int(slot.get("count", 0))
                if name:
                    by_name[name] = by_name.get(name, 0) + count
        if hasattr(self._target, "inventory_query"):
            try:
                inv = self._target.inventory_query()
                if inv.get("ok"):
                    by_name = inv.get("by_name", by_name)
                    return by_name
            except Exception as e:
                logger.debug("full inventory query failed: %s", e)
        self._inv_cache = by_name
        return by_name

    def verify(self, descriptor: str) -> bool:
        m = _HAS_ITEM_RE.match(descriptor)
        if m:
            name = m.group(1)
            required = int(m.group(2) or "1")
            return self._has_item(name, required)

        m = _BLOCK_AT_RE.match(descriptor)
        if m:
            x, y, z = int(m.group(1)), int(m.group(2)), int(m.group(3))
            name = m.group(4)
            return self._block_at(x, y, z, name)

        m = _BLOCK_NEAR_RE.match(descriptor)
        if m:
            name = m.group(1)
            max_dist = int(m.group(2))
            return self._block_near(name, max_dist)

        m = _BOT_NEAR_RE.match(descriptor)
        if m:
            x, y, z = float(m.group(1)), float(m.group(2)), float(m.group(3))
            dist = float(m.group(4))
            return self._bot_near(x, y, z, dist)

        logger.warning("unknown descriptor: %s", descriptor)
        return False

    def _has_item(self, name: str, count: int = 1) -> bool:
        inv = self._get_inventory()
        return inv.get(name, 0) >= count

    def _block_at(self, x: int, y: int, z: int, name: str | None = None) -> bool:
        if not hasattr(self._target, "block_query"):
            nearby = self._obs.get("nearby_blocks", [])
            for b in nearby:
                pos = b.get("position", {})
                if (int(pos.get("x", 0)) == x
                        and int(pos.get("y", 0)) == y
                        and int(pos.get("z", 0)) == z):
                    if name is None:
                        return True
                    return b.get("name", "") == name
            return False
        block = self._target.block_query(x, y, z)
        if block is None:
            return False
        if name is None:
            return True
        return block.get("name") == name

    def _block_near(self, name: str, max_dist: int) -> bool:
        pos = self._obs.get("info", {}).get("position", {})
        bx = float(pos.get("x", 0))
        by = float(pos.get("y", 0))
        bz = float(pos.get("z", 0))
        nearby = self._obs.get("nearby_blocks", [])
        for b in nearby:
            if b.get("name", "") == name:
                bp = b.get("position", {})
                dx = float(bp.get("x", 0)) - bx
                dy = float(bp.get("y", 0)) - by
                dz = float(bp.get("z", 0)) - bz
                if math.sqrt(dx * dx + dy * dy + dz * dz) <= max_dist:
                    return True
        return False

    def _bot_near(self, x: float, y: float, z: float, max_dist: float) -> bool:
        pos = self._obs.get("info", {}).get("position", {})
        bx = float(pos.get("x", 0))
        by = float(pos.get("y", 0))
        bz = float(pos.get("z", 0))
        dist = math.sqrt((bx - x) ** 2 + (by - y) ** 2 + (bz - z) ** 2)
        return dist <= max_dist


TaskVerifier = MinecraftTaskVerifier
