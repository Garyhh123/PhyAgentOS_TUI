"""Manifest loader for the Minecraft tech-tree benchmark."""

from __future__ import annotations

import json
from pathlib import Path

from PhyAgentOS.benchmarks.minecraft.techtree.schema import TaskManifest, TechTreeTask

DEFAULT_MANIFEST_PATH = Path(__file__).with_name("manifest.json")


def load_manifest(path: str | Path | None = None) -> TaskManifest:
    """Load the tech-tree manifest from JSON."""

    manifest_path = Path(path) if path is not None else DEFAULT_MANIFEST_PATH
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = TaskManifest.from_dict(data)
    _validate_manifest(manifest)
    return manifest


def list_tasks(
    *,
    tier: str | None = None,
    family: str | None = None,
    manifest_path: str | Path | None = None,
) -> list[TechTreeTask]:
    """List manifest tasks, optionally filtering by tier or family."""

    tasks = list(load_manifest(manifest_path).tasks)
    if tier is not None:
        tasks = [task for task in tasks if task.tier == tier]
    if family is not None:
        tasks = [task for task in tasks if task.family == family]
    return tasks


def load_task(task_id: str, manifest_path: str | Path | None = None) -> TechTreeTask:
    """Load a single task by id."""

    manifest = load_manifest(manifest_path)
    tasks = manifest.task_map()
    try:
        return tasks[task_id]
    except KeyError as exc:
        available = ", ".join(sorted(tasks))
        raise KeyError(f"unknown Minecraft tech-tree task {task_id!r}; available: {available}") from exc


def _validate_manifest(manifest: TaskManifest) -> None:
    seen: set[str] = set()
    for task in manifest.tasks:
        if task.id in seen:
            raise ValueError(f"duplicate task id: {task.id}")
        seen.add(task.id)
        if not task.target_item:
            raise ValueError(f"{task.id}: target_item is required")
        if task.success_criterion.type != "inventory_contains":
            raise ValueError(f"{task.id}: unsupported success criterion {task.success_criterion.type!r}")
        if task.success_criterion.item != task.target_item:
            raise ValueError(f"{task.id}: success criterion item must match target_item")
        initial_items = {item.item for item in task.setup.inventory}
        if task.target_item in initial_items:
            raise ValueError(f"{task.id}: setup inventory already contains target_item {task.target_item!r}")
