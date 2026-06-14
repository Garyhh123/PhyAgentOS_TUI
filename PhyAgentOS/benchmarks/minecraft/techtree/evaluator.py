"""Programmatic evaluators for Minecraft tech-tree observations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from PhyAgentOS.benchmarks.minecraft.techtree.schema import TechTreeTask


@dataclass(frozen=True)
class EvaluationResult:
    success: bool
    reward: float
    reason: str
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "reward": self.reward,
            "reason": self.reason,
            "metrics": dict(self.metrics),
        }


def evaluate_task(task: TechTreeTask, observation: Mapping[str, Any] | None) -> EvaluationResult:
    """Evaluate a task against a normalized or raw Minecraft observation."""

    observation = observation or {}
    criterion = task.success_criterion
    if criterion.type != "inventory_contains":
        return EvaluationResult(
            success=False,
            reward=0.0,
            reason=f"unsupported_success_criterion:{criterion.type}",
            metrics={"criterion": criterion.to_dict()},
        )

    item = criterion.item or task.target_item
    observed = inventory_count(observation, item)
    success = observed >= criterion.count
    return EvaluationResult(
        success=success,
        reward=1.0 if success else 0.0,
        reason="inventory_contains" if success else "inventory_missing",
        metrics={
            "target_item": item,
            "required_count": criterion.count,
            "observed_count": observed,
            "inventory_counts": inventory_counts(observation),
        },
    )


def inventory_count(observation: Mapping[str, Any], item_name: str) -> int:
    return inventory_counts(observation).get(normalize_item_name(item_name), 0)


def inventory_counts(observation: Mapping[str, Any]) -> dict[str, int]:
    """Extract item counts from common Minecraft observation shapes."""

    counts: dict[str, int] = {}

    def add(name: Any, count: Any = 1) -> None:
        if not name:
            return
        key = normalize_item_name(str(name))
        try:
            amount = int(count or 0)
        except (TypeError, ValueError):
            amount = 1
        counts[key] = counts.get(key, 0) + max(0, amount)

    def read_item_list(items: Any) -> bool:
        if not isinstance(items, list):
            return False
        found = False
        for item in items:
            if isinstance(item, Mapping):
                add(item.get("name") or item.get("item"), item.get("count", 1))
                found = True
        return found

    found_items = read_item_list(observation.get("inventory_items"))
    info = observation.get("info")
    if isinstance(info, Mapping):
        found_items = read_item_list(info.get("inventory_items")) or found_items
    if found_items:
        return counts

    inventory = observation.get("inventory")
    if isinstance(inventory, Mapping):
        raw_counts = inventory.get("counts") if isinstance(inventory.get("counts"), Mapping) else inventory
        for name, count in raw_counts.items():
            if isinstance(count, Mapping):
                add(name, count.get("count", 1))
            else:
                add(name, count)
    elif isinstance(inventory, list):
        read_item_list(inventory)

    return counts


def normalize_item_name(name: str) -> str:
    name = str(name).strip().lower()
    if name.startswith("minecraft:"):
        return name.split(":", 1)[1]
    return name
