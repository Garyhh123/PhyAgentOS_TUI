"""Stardew Valley task verification primitives.

Supported descriptors:
    has_item:name          → inventory contains item named 'name'
    has_item:name×N        → inventory contains at least N of 'name'
    has_tool:name          → currently equipped tool is 'name'
    object_near:name,dist  → nearby tile has object/terrain matching 'name' within dist
    position_at:x,y        → player at exact tile (x,y)
    bot_near:x,y,dist      → player within 'dist' tiles of (x,y)
    energy_above:N         → energy greater than N
    location:name          → player in location 'name'
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any

from PhyAgentOS.runtime.skillruntime.game.condition_verifier import GameConditionVerifier

logger = logging.getLogger(__name__)

_HAS_ITEM_RE = re.compile(r"has_item:([\w \-\']+?)(?:×(\d+))?$")
_HAS_TOOL_RE = re.compile(r"has_tool:([\w \-\']+)$")
_OBJECT_NEAR_RE = re.compile(r"object_near:([\w \-\']+?),(\d+)$")
_POSITION_AT_RE = re.compile(r"position_at:(-?\d+),(-?\d+)$")
_BOT_NEAR_RE = re.compile(
    r"bot_near:(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(\d+(?:\.\d+)?)$"
)
_ENERGY_ABOVE_RE = re.compile(r"energy_above:(\d+(?:\.\d+)?)$")
_LOCATION_RE = re.compile(r"location:([\w \-\']+)$")


class StardewValleyTaskVerifier(GameConditionVerifier):
    """Checks Stardew Valley task preconditions and post-conditions."""

    def __init__(self, target, raw_obs: dict[str, Any]):
        super().__init__(target, raw_obs)
        self._inv_cache: dict[str, int] | None = None

    def _get_inventory(self) -> dict[str, int]:
        if self._inv_cache is not None:
            return self._inv_cache
        inventory = self._obs.get("inventory", [])
        by_name: dict[str, int] = {}
        for slot in inventory:
            if isinstance(slot, dict):
                name = slot.get("Name", "")
                count = int(slot.get("Quantity", 0))
                if name:
                    by_name[name] = by_name.get(name, 0) + count
        return by_name

    def _get_position(self) -> tuple[float, float]:
        info = self._obs.get("info", {})
        pos = info.get("position", [0, 0])
        if isinstance(pos, list) and len(pos) == 2:
            try:
                return float(pos[0]), float(pos[1])
            except (ValueError, TypeError):
                pass
        return 0.0, 0.0

    def verify(self, descriptor: str) -> bool:
        try:
            return self._verify_impl(descriptor)
        except Exception as e:
            import traceback
            logging.error("TaskVerifier.verify('%s') failed: %s\n%s", descriptor, e, traceback.format_exc())
            return False

    def _verify_impl(self, descriptor: str) -> bool:
        m = _HAS_ITEM_RE.match(descriptor)
        if m:
            name = m.group(1)
            required = int(m.group(2) or "1")
            return self._has_item(name, required)

        m = _HAS_TOOL_RE.match(descriptor)
        if m:
            return self._has_tool(m.group(1))

        m = _OBJECT_NEAR_RE.match(descriptor)
        if m:
            return self._object_near(m.group(1), int(m.group(2)))

        m = _POSITION_AT_RE.match(descriptor)
        if m:
            return self._position_at(int(m.group(1)), int(m.group(2)))

        m = _BOT_NEAR_RE.match(descriptor)
        if m:
            x, y, dist = float(m.group(1)), float(m.group(2)), float(m.group(3))
            return self._bot_near(x, y, dist)

        m = _ENERGY_ABOVE_RE.match(descriptor)
        if m:
            return self._energy_above(float(m.group(1)))

        m = _LOCATION_RE.match(descriptor)
        if m:
            return self._location(m.group(1))

        logger.warning("unknown descriptor: %s", descriptor)
        return False

    def _has_item(self, name: str, count: int = 1) -> bool:
        inv = self._get_inventory()
        result = inv.get(name, 0) >= count
        if not result:
            logger.debug("has_item(%s×%d): inventory has %s", name, count, dict(inv))
        return result

    def _has_tool(self, name: str) -> bool:
        chosen = (self._obs.get("info", {}) or {}).get("chosen_item") or \
                 (self._obs.get("stardew", {}) or {}).get("chosen_item") or {}
        if isinstance(chosen, dict):
            current = chosen.get("CurrentItem") or chosen.get("currentitem", "")
            return str(current).lower() == name.lower()
        return False

    def _object_near(self, name: str, max_dist: int) -> bool:
        pos = self._obs.get("info", {}).get("position", [0, 0])
        px = float(pos[0]) if isinstance(pos, list) else 0.0
        py = float(pos[1]) if isinstance(pos, list) else 0.0

        name_lower = name.lower()
        surroundings = self._obs.get("nearby_objects", [])
        for tile in surroundings:
            if not isinstance(tile, dict):
                continue
            for key in ("object_at_tile", "terrain_at_tile"):
                val = tile.get(key)
                if val and name_lower in str(val).lower():
                    tile_pos = tile.get("position", "")
                    parts = str(tile_pos).split()
                    if len(parts) >= 2:
                        try:
                            tx, ty = int(parts[0]), int(parts[1])
                            dist = math.sqrt((tx - px) ** 2 + (ty - py) ** 2)
                            if dist <= max_dist:
                                return True
                        except (ValueError, TypeError):
                            pass
        return False

    def _position_at(self, x: int, y: int) -> bool:
        px, py = self._get_position()
        return int(px) == x and int(py) == y

    def _bot_near(self, x: float, y: float, max_dist: float) -> bool:
        px, py = self._get_position()
        dist = math.sqrt((px - x) ** 2 + (py - y) ** 2)
        return dist <= max_dist

    def _energy_above(self, min_energy: float) -> bool:
        info = self._obs.get("info", {})
        energy = float(info.get("energy", 0))
        return energy > min_energy

    def _location(self, name: str) -> bool:
        info = self._obs.get("info", {})
        loc = str(info.get("location", "")).lower()
        return loc == name.lower()


StardewTaskVerifier = StardewValleyTaskVerifier
