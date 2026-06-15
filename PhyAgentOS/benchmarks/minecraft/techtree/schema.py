"""Data structures for the executor-independent Minecraft tech-tree benchmark."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

JsonDict = dict[str, Any]

DEFAULT_ARENA_ORIGIN = (-2000, 80, -2000)
DEFAULT_ARENA_CLEAR_RADIUS = 8
DEFAULT_ARENA_CLEAR_HEIGHT = 6
DEFAULT_ARENA_FLOOR_BLOCK = "smooth_stone"
DEFAULT_ARENA_BOUNDARY_BLOCK = "stone_bricks"


@dataclass(frozen=True)
class SetupItem:
    item: str
    count: int = 1
    enchantments: tuple[JsonDict, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SetupItem":
        return cls(
            item=str(data["item"]),
            count=int(data.get("count", 1) or 1),
            enchantments=tuple(dict(entry) for entry in data.get("enchantments", []) or []),
        )

    def to_dict(self) -> JsonDict:
        payload: JsonDict = {"item": self.item, "count": self.count}
        if self.enchantments:
            payload["enchantments"] = [dict(entry) for entry in self.enchantments]
        return payload


@dataclass(frozen=True)
class SetupBlock:
    block: str
    relative: tuple[int, int, int]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SetupBlock":
        relative = data.get("relative")
        if not isinstance(relative, list | tuple) or len(relative) != 3:
            raise ValueError(f"setup block requires relative [x,y,z]: {data!r}")
        return cls(
            block=str(data["block"]),
            relative=(int(relative[0]), int(relative[1]), int(relative[2])),
        )

    def to_dict(self) -> JsonDict:
        return {"block": self.block, "relative": list(self.relative)}


@dataclass(frozen=True)
class ArenaSetup:
    enabled: bool = True
    origin: tuple[int, int, int] = DEFAULT_ARENA_ORIGIN
    clear_radius: int = DEFAULT_ARENA_CLEAR_RADIUS
    clear_height: int = DEFAULT_ARENA_CLEAR_HEIGHT
    floor_block: str = DEFAULT_ARENA_FLOOR_BLOCK
    boundary_block: str = DEFAULT_ARENA_BOUNDARY_BLOCK

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ArenaSetup":
        data = dict(data or {})
        origin = data.get("origin", DEFAULT_ARENA_ORIGIN)
        if not isinstance(origin, list | tuple) or len(origin) != 3:
            raise ValueError(f"arena origin must be [x,y,z]: {data!r}")
        return cls(
            enabled=bool(data.get("enabled", True)),
            origin=(int(origin[0]), int(origin[1]), int(origin[2])),
            clear_radius=max(1, int(data.get("clear_radius", DEFAULT_ARENA_CLEAR_RADIUS) or DEFAULT_ARENA_CLEAR_RADIUS)),
            clear_height=max(1, int(data.get("clear_height", DEFAULT_ARENA_CLEAR_HEIGHT) or DEFAULT_ARENA_CLEAR_HEIGHT)),
            floor_block=str(data.get("floor_block") or DEFAULT_ARENA_FLOOR_BLOCK),
            boundary_block=str(data.get("boundary_block") or DEFAULT_ARENA_BOUNDARY_BLOCK),
        )

    def to_dict(self) -> JsonDict:
        return {
            "enabled": self.enabled,
            "origin": list(self.origin),
            "clear_radius": self.clear_radius,
            "clear_height": self.clear_height,
            "floor_block": self.floor_block,
            "boundary_block": self.boundary_block,
        }


@dataclass(frozen=True)
class WorldSetup:
    clear_inventory: bool = True
    arena: ArenaSetup = field(default_factory=ArenaSetup)
    inventory: tuple[SetupItem, ...] = ()
    blocks: tuple[SetupBlock, ...] = ()
    raw: JsonDict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "WorldSetup":
        data = dict(data or {})
        return cls(
            clear_inventory=bool(data.get("clear_inventory", True)),
            arena=ArenaSetup.from_dict(data.get("arena")),
            inventory=tuple(SetupItem.from_dict(entry) for entry in data.get("inventory", []) or []),
            blocks=tuple(SetupBlock.from_dict(entry) for entry in data.get("blocks", []) or []),
            raw=data,
        )

    def to_dict(self) -> JsonDict:
        payload = dict(self.raw)
        payload["clear_inventory"] = self.clear_inventory
        payload["arena"] = self.arena.to_dict()
        payload["inventory"] = [item.to_dict() for item in self.inventory]
        payload["blocks"] = [block.to_dict() for block in self.blocks]
        return payload


@dataclass(frozen=True)
class SuccessCriterion:
    type: str
    item: str | None = None
    count: int = 1
    raw: JsonDict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SuccessCriterion":
        return cls(
            type=str(data["type"]),
            item=str(data["item"]) if data.get("item") is not None else None,
            count=int(data.get("count", 1) or 1),
            raw=dict(data),
        )

    def to_dict(self) -> JsonDict:
        payload = dict(self.raw)
        payload["type"] = self.type
        if self.item is not None:
            payload["item"] = self.item
        payload["count"] = self.count
        return payload


@dataclass(frozen=True)
class TechTreeTask:
    id: str
    tier: str
    family: str
    title: str
    target_item: str
    success_criterion: SuccessCriterion
    setup: WorldSetup
    source_refs: tuple[JsonDict, ...] = ()
    vetting: JsonDict = field(default_factory=dict)
    raw: JsonDict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TechTreeTask":
        return cls(
            id=str(data["id"]),
            tier=str(data["tier"]),
            family=str(data["family"]),
            title=str(data.get("title") or data["id"]),
            target_item=str(data["target_item"]),
            success_criterion=SuccessCriterion.from_dict(data["success_criterion"]),
            setup=WorldSetup.from_dict(data.get("setup")),
            source_refs=tuple(dict(entry) for entry in data.get("source_refs", []) or []),
            vetting=dict(data.get("vetting") or {}),
            raw=dict(data),
        )

    def to_dict(self) -> JsonDict:
        payload = dict(self.raw)
        payload.update(
            {
                "id": self.id,
                "tier": self.tier,
                "family": self.family,
                "title": self.title,
                "target_item": self.target_item,
                "success_criterion": self.success_criterion.to_dict(),
                "setup": self.setup.to_dict(),
                "source_refs": [dict(entry) for entry in self.source_refs],
                "vetting": dict(self.vetting),
            }
        )
        return payload


@dataclass(frozen=True)
class TaskManifest:
    version: str
    name: str
    tasks: tuple[TechTreeTask, ...]
    raw: JsonDict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskManifest":
        return cls(
            version=str(data["version"]),
            name=str(data["name"]),
            tasks=tuple(TechTreeTask.from_dict(entry) for entry in data.get("tasks", []) or []),
            raw=dict(data),
        )

    def task_map(self) -> dict[str, TechTreeTask]:
        return {task.id: task for task in self.tasks}

    def to_dict(self) -> JsonDict:
        payload = dict(self.raw)
        payload["version"] = self.version
        payload["name"] = self.name
        payload["tasks"] = [task.to_dict() for task in self.tasks]
        return payload
