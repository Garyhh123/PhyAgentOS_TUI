"""Observation compaction and JSON-safety helpers for StarDojo."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from pathlib import Path
from typing import Any

RAW_COMPACT_OBS_KEYS = (
    "basic_knowledge",
    "health",
    "energy",
    "money",
    "location",
    "position",
    "facing_direction",
    "inventory",
    "chosen_item",
    "time",
    "day",
    "season",
    "farm_animals",
    "farm_pets",
    "farm_buildings",
    "surroundings",
    "crops",
    "exits",
    "buildings",
    "furniture",
    "npcs",
    "shop_counters",
    "current_menu",
)

DERIVED_COMPACT_OBS_KEYS = ("latest_image_url",)

COMPACT_OBS_KEYS = RAW_COMPACT_OBS_KEYS + DERIVED_COMPACT_OBS_KEYS


def compact_obs(obs: Mapping[str, Any]) -> dict[str, Any]:
    """Return the default compact observation payload for Track A."""

    compact = {key: to_jsonable(obs.get(key)) for key in RAW_COMPACT_OBS_KEYS}
    compact["latest_image_url"] = None
    return compact


def with_latest_image_url(obs: Mapping[str, Any], latest_image_url: str | None) -> dict[str, Any]:
    """Attach the bridge-served latest screenshot URL to an observation."""

    result = dict(obs)
    result["latest_image_url"] = latest_image_url
    return result


def to_jsonable(value: Any) -> Any:
    """Recursively convert common runtime values into JSON-safe values."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, Mapping):
        return {str(key): to_jsonable(inner) for key, inner in value.items()}

    if isinstance(value, deque):
        return [to_jsonable(inner) for inner in list(value)]

    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(inner) for inner in value]

    item = getattr(value, "item", None)
    if callable(item):
        try:
            return to_jsonable(item())
        except Exception:
            pass

    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        try:
            return to_jsonable(tolist())
        except Exception:
            pass

    return str(value)


def image_paths_from_obs(obs: Mapping[str, Any]) -> list[str]:
    """Return raw StarDojo image paths as strings for internal bridge serving."""

    value = to_jsonable(obs.get("image_paths"))
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item)]
    if str(value):
        return [str(value)]
    return []
