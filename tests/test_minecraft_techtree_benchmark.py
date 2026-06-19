from __future__ import annotations

from typing import Any, Mapping

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
from PhyAgentOS.benchmarks.minecraft.techtree.adapters.adapter import (
    MineflayerBridgeAdapter,
)
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


def test_evaluator_accepts_bridge_and_target_observation_shapes() -> None:
    task = load_task("wooden.obtain_oak_log")

    # mineflayer bridge /state and MinecraftTarget.observe() emit hotbar slots
    assert evaluate_task(
        task, {"inventory": {"hotbar": [{"slot": 0, "name": "oak_log", "count": 1}]}}
    ).success
    # inventory_query() result shape: top-level by_name / slots
    assert evaluate_task(task, {"by_name": {"oak_log": 1}}).success
    assert evaluate_task(task, {"slots": [{"name": "minecraft:oak_log", "count": 2}]}).success
    # hotbar must not be misread as an item name
    assert inventory_counts({"inventory": {"hotbar": [{"slot": 0, "name": "dirt", "count": 3}]}}) == {"dirt": 3}


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
    """Records HTTP calls instead of touching the network."""

    def __init__(self) -> None:
        super().__init__("http://example.invalid")
        self.calls: list[tuple[str, str, Any]] = []  # (method, path, body|None)

    def _get(self, path: str) -> dict[str, Any]:
        self.calls.append(("GET", path, None))
        x, y, z = DEFAULT_ARENA_ORIGIN
        return {"position": {"x": x, "y": y, "z": z}, "inventory": {}}

    def _post(self, path: str, body: Mapping[str, Any]) -> dict[str, Any]:
        self.calls.append(("POST", path, dict(body)))
        return {"ok": True, "commands": 1, "phase": "idle"}


def test_mineflayer_adapter_reset_delegates_full_setup_to_bridge() -> None:
    task = load_task("wooden.obtain_oak_log")
    adapter = RecordingBridgeAdapter()

    result = adapter.reset(task.setup)

    methods = [(method, path) for method, path, _ in adapter.calls]
    assert ("POST", "/benchmark/reset") in methods
    assert ("GET", "/state") in methods

    reset_calls = [body for method, path, body in adapter.calls if path == "/benchmark/reset"]
    assert len(reset_calls) == 1
    body = reset_calls[0]
    assert body["clear_inventory"] is True
    # the whole arena contract is forwarded, so the bridge (not the adapter)
    # is responsible for tp/fill/floor/boundary
    assert body["arena"]["enabled"] is True
    assert body["arena"]["origin"] == list(DEFAULT_ARENA_ORIGIN)
    assert body["arena"]["clear_radius"] == DEFAULT_ARENA_CLEAR_RADIUS
    assert body["arena"]["clear_height"] == DEFAULT_ARENA_CLEAR_HEIGHT
    assert body["arena"]["floor_block"] == DEFAULT_ARENA_FLOOR_BLOCK
    assert body["arena"]["boundary_block"] == DEFAULT_ARENA_BOUNDARY_BLOCK
    # wooden.obtain_oak_log stages a wooden_axe and an oak_log block
    given = {item["item"]: item["count"] for item in body["inventory"]}
    assert given.get("wooden_axe") == 1
    placed = body["blocks"]
    assert any(block["block"] == "oak_log" for block in placed)
    assert all(isinstance(block["relative"], list) and len(block["relative"]) == 3 for block in placed)

    # phase ordering: reset-counter phase first, idle phase last
    phase_calls = [body for method, path, body in adapter.calls if path == "/phase"]
    assert phase_calls[0]["phase"] == "reset" and phase_calls[0]["reset_counters"] is True
    assert phase_calls[-1]["phase"] == "idle" and phase_calls[-1]["reset_counters"] is False

    # reset returns the post-reset observation
    assert result["inventory"] == {}


def test_mineflayer_adapter_reset_survives_missing_phase_endpoint() -> None:
    # A bridge without /phase must not break reset; the benchmark reset
    # endpoint sets phase internally regardless.
    task = load_task("wooden.obtain_oak_log")
    adapter = RecordingBridgeAdapter()
    original_post = adapter._post
    forwarded: list[tuple[str, Any]] = []

    def post_without_phase(path: str, body: Mapping[str, Any]) -> dict[str, Any]:
        forwarded.append((path, dict(body)))
        if path == "/phase":
            import httpx

            raise httpx.ConnectError("phase endpoint missing")
        return original_post(path, body)

    adapter._post = post_without_phase  # type: ignore[method-assign]
    result = adapter.reset(task.setup)

    # benchmark/reset still ran and observe still ran
    assert any(path == "/benchmark/reset" for path, _ in forwarded)
    assert result["inventory"] == {}


def test_manifest_file_is_packaged_next_to_loader() -> None:
    assert DEFAULT_MANIFEST_PATH.exists()
    assert DEFAULT_MANIFEST_PATH.name == "manifest.json"
    assert "external MineStudio" in load_manifest().raw["source_notes"]["self_contained_pr_policy"]


def test_success_criterion_maps_to_verifier_descriptor() -> None:
    from PhyAgentOS.benchmarks.minecraft.techtree.schema import SuccessCriterion

    one = SuccessCriterion(type="inventory_contains", item="oak_log", count=1)
    many = SuccessCriterion(type="inventory_contains", item="oak_log", count=4)
    assert one.to_descriptor() == "has_item:oak_log"
    assert many.to_descriptor() == "has_item:oak_log×4"


def test_task_verify_descriptors_align_with_runtime_verifier() -> None:
    from PhyAgentOS.runtime.benchmark.minecraft_glue import task_verify_descriptors
    from PhyAgentOS.runtime.skillruntime.game.task_verifier import MinecraftTaskVerifier

    task = load_task("iron.smelt_iron_ingot")
    descriptors = task_verify_descriptors(task)
    assert descriptors == ["has_item:iron_ingot"]

    # the descriptor must round-trip through the runtime verifier against the
    # same observation the evaluator would score
    obs = {"inventory": {"hotbar": [{"slot": 0, "name": "iron_ingot", "count": 1}]}}
    verifier = MinecraftTaskVerifier(target=None, raw_obs=obs)
    assert verifier.verify(descriptors[0]) is True
    # and the evaluator agrees on the same observation → no scoring drift
    assert evaluate_task(task, obs).success


class _FakeTarget:
    """Minimal MinecraftTarget stand-in for glue tests."""

    def __init__(self) -> None:
        self.config = {"action_timeout": 5.0}
        self._built = True
        self._bridge_url = "http://example.invalid"
        self._posted: list[tuple[str, dict[str, Any]]] = []
        self._observe_count = 0

    def build(self) -> None:
        self._built = True

    def observe(self) -> dict[str, Any]:
        self._observe_count += 1
        return {"inventory": {"hotbar": [{"slot": 0, "name": "oak_log", "count": 1}]}}

    def step(self, action: dict[str, Any]) -> dict[str, Any]:
        self._posted.append(("action", dict(action)))
        return {"ok": True, "obs": self.observe()}

    class _Resp:
        def raise_for_status(self) -> None:
            return None

    class _Client:
        def __init__(self, posted):
            self._posted = posted

        def post(self, url, json, timeout):  # noqa: ARG002
            self._posted.append((url, dict(json)))
            return _FakeTarget._Resp()

    def _get_http(self):
        return _FakeTarget._Client(self._posted)


def test_minecraft_target_world_adapter_reset_and_observe() -> None:
    from PhyAgentOS.runtime.benchmark.minecraft_glue import MinecraftTargetWorldAdapter

    task = load_task("wooden.obtain_oak_log")
    target = _FakeTarget()
    world = MinecraftTargetWorldAdapter(target)

    initial = world.reset(task.setup)
    # reset issued one POST /benchmark/reset carrying the full setup
    posts = [body for url, body in target._posted if url.endswith("/benchmark/reset")]
    assert len(posts) == 1
    assert posts[0]["arena"]["enabled"] is True
    # observe returns the target's rich state
    assert initial["inventory"]["hotbar"][0]["name"] == "oak_log"


def test_action_agent_fn_drives_target_through_adapter() -> None:
    from PhyAgentOS.runtime.benchmark.minecraft_glue import (
        MinecraftTargetWorldAdapter,
        make_action_agent_fn,
    )

    task = load_task("wooden.obtain_oak_log")
    target = _FakeTarget()
    world = MinecraftTargetWorldAdapter(target)

    agent_fn = make_action_agent_fn([{"type": "dig", "params": {"x": 1, "y": 2, "z": 3}}])
    out = agent_fn(task, world)
    assert out["actions_executed"] == 1
    assert target._posted[-1] == ("action", {"type": "dig", "params": {"x": 1, "y": 2, "z": 3}})
