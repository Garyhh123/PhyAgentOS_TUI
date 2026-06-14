from __future__ import annotations

from typing import Any

from PhyAgentOS.benchmarks.minecraft.techtree import (
    DEFAULT_ARENA_BOUNDARY_BLOCK,
    DEFAULT_ARENA_CLEAR_HEIGHT,
    DEFAULT_ARENA_CLEAR_RADIUS,
    DEFAULT_ARENA_FLOOR_BLOCK,
    DEFAULT_ARENA_ORIGIN,
    evaluate_task,
    inventory_count,
    inventory_counts,
    list_tasks,
    load_manifest,
    load_task,
    run_task,
)
from PhyAgentOS.benchmarks.minecraft.techtree.adapters.mineflayer_bridge import MineflayerBridgeAdapter
from PhyAgentOS.benchmarks.minecraft.techtree.loader import DEFAULT_MANIFEST_PATH
from PhyAgentOS.benchmarks.minecraft.techtree.schema import WorldSetup


def test_manifest_is_vetted_and_non_degenerate() -> None:
    manifest = load_manifest()
    tasks = list(manifest.tasks)
    assert manifest.name == "minecraft_techtree"
    assert len(tasks) == 40
    assert len({task.id for task in tasks}) == len(tasks)

    allowed_tiers = {"Wooden", "Stone", "Iron", "Gold-Redstone", "Diamond", "Armor"}
    allowed_families = {"dig_pickup", "crafting_inventory", "crafting_table", "smelting"}
    for task in tasks:
        assert task.tier in allowed_tiers
        assert task.family in allowed_families
        assert task.target_item
        assert task.success_criterion.type == "inventory_contains"
        assert task.success_criterion.item == task.target_item
        assert task.success_criterion.count >= 1
        assert task.target_item not in {item.item for item in task.setup.inventory}
        assert task.setup.arena.enabled is True
        assert task.setup.arena.origin == DEFAULT_ARENA_ORIGIN
        assert task.vetting["target_item_correct"] is True
        assert task.vetting["non_degenerate_setup"] is True
        assert task.vetting["mineflayer_executable"] is True
        assert task.vetting["programmatic_scorable"] is True


def test_loader_filters_tasks_by_tier_and_family() -> None:
    assert load_task("stone.craft_furnace").target_item == "furnace"

    wooden_tasks = list_tasks(tier="Wooden")
    assert len(wooden_tasks) == 10
    assert {task.tier for task in wooden_tasks} == {"Wooden"}

    smelting_tasks = list_tasks(family="smelting")
    assert {task.id for task in smelting_tasks} == {
        "iron.smelt_iron_ingot",
        "gold_redstone.smelt_gold_ingot",
    }


def test_evaluator_accepts_common_inventory_shapes() -> None:
    task = load_task("wooden.obtain_oak_log")

    assert evaluate_task(task, {"inventory": {"oak_log": 1}}).success
    assert evaluate_task(task, {"inventory": {"counts": {"oak_log": 1}}}).success
    assert evaluate_task(task, {"inventory_items": [{"name": "minecraft:oak_log", "count": 1}]}).success
    assert evaluate_task(task, {"info": {"inventory_items": [{"name": "oak_log", "count": 1}]}}).success
    assert not evaluate_task(task, {"inventory": {"dirt": 1}}).success


def test_evaluator_prefers_slot_item_list_over_summary_counts() -> None:
    task = load_task("wooden.obtain_oak_log")
    verdict = evaluate_task(
        task,
        {
            "inventory_items": [{"name": "minecraft:oak_log", "count": 1}],
            "inventory": {"oak_log": 99},
        },
    )

    assert verdict.success
    assert verdict.metrics["observed_count"] == 1
    assert inventory_count({"info": {"inventory_items": [{"name": "minecraft:dirt", "count": 2}]}}, "dirt") == 2
    assert inventory_counts({"inventory": [{"name": "minecraft:stick", "count": 4}]}) == {"stick": 4}


class MockWorld:
    def __init__(self) -> None:
        self.inventory: dict[str, int] = {}
        self.reset_setup: WorldSetup | None = None

    def reset(self, setup: WorldSetup) -> dict[str, Any]:
        self.reset_setup = setup
        self.inventory = {item.item: item.count for item in setup.inventory}
        return {"inventory": dict(self.inventory)}

    def observe(self) -> dict[str, Any]:
        return {"inventory": dict(self.inventory)}


def test_harness_runs_injected_agent_and_world_adapter() -> None:
    world = MockWorld()

    def agent(task, adapter: MockWorld) -> dict[str, Any]:
        adapter.inventory[task.target_item] = adapter.inventory.get(task.target_item, 0) + 1
        return {"agent": "mock"}

    result = run_task("wooden.obtain_oak_log", agent, world)

    assert result.success
    assert result.reward == 1.0
    assert result.agent_result == {"agent": "mock"}
    assert result.metadata["benchmark"] == "minecraft_techtree"
    assert world.reset_setup is not None
    assert result.verdict.metrics["observed_count"] == 1


def test_harness_reports_agent_error_without_hiding_final_success() -> None:
    world = MockWorld()

    def agent(task, adapter: MockWorld) -> None:
        adapter.inventory[task.target_item] = 1
        raise RuntimeError("agent failed after acting")

    result = run_task("wooden.obtain_oak_log", agent, world)

    assert result.success
    assert result.reward == 1.0
    assert result.error == "RuntimeError: agent failed after acting"


class RecordingBridgeAdapter(MineflayerBridgeAdapter):
    def __init__(self) -> None:
        super().__init__("http://example.invalid")
        self.commands: list[str] = []
        self.phases: list[tuple[str, bool]] = []

    def _set_phase(self, phase: str, *, reset_counters: bool) -> None:
        self.phases.append((phase, reset_counters))

    def _command(self, command: str) -> dict[str, Any]:
        self.commands.append(command)
        return {"ok": True}

    def observe(self) -> dict[str, Any]:
        x, y, z = DEFAULT_ARENA_ORIGIN
        return {"position": {"x": x, "y": y, "z": z}, "inventory": {}}


def test_mineflayer_adapter_reset_builds_fixed_isolated_arena() -> None:
    task = load_task("wooden.obtain_oak_log")
    adapter = RecordingBridgeAdapter()

    adapter.reset(task.setup)

    x, y, z = DEFAULT_ARENA_ORIGIN
    radius = DEFAULT_ARENA_CLEAR_RADIUS
    height = DEFAULT_ARENA_CLEAR_HEIGHT
    floor_y = y - 1
    assert adapter.phases == [("reset", True), ("idle", False)]
    assert adapter.commands[0] == f"/tp @s {x} {y} {z} 0 0"
    assert adapter.commands[1] == (
        f"/fill {x - radius} {y} {z - radius} {x + radius} {y + height} {z + radius} air"
    )
    assert adapter.commands[2] == (
        f"/fill {x - radius} {floor_y} {z - radius} {x + radius} {floor_y} {z + radius} "
        f"minecraft:{DEFAULT_ARENA_FLOOR_BLOCK}"
    )
    assert any(f"minecraft:{DEFAULT_ARENA_BOUNDARY_BLOCK}" in command for command in adapter.commands[3:7])
    assert "/clear @s" in adapter.commands
    assert "/give @s minecraft:wooden_axe 1" in adapter.commands
    assert f"/setblock {x + 2} {y} {z} minecraft:oak_log" in adapter.commands


def test_manifest_file_is_packaged_next_to_loader() -> None:
    assert DEFAULT_MANIFEST_PATH.exists()
    assert DEFAULT_MANIFEST_PATH.name == "manifest.json"
    assert "external MineStudio" in load_manifest().raw["source_notes"]["self_contained_pr_policy"]
