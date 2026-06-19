"""Glue between the runtime MinecraftTarget and the tech-tree benchmark.

The benchmark core is executor-independent: it only knows the
``WorldAdapter`` interface (``reset(setup)`` / ``observe()``) and an
injected ``agent_fn``.  This module is the only place that knows about
both the OS runtime and the benchmark — it wraps a production
``MinecraftTarget`` as a benchmark ``WorldAdapter`` and offers helpers to
turn a runtime action sequence into the ``agent_fn`` the harness expects.

For a full planner-driven OS agent, wrap ``MinecraftSkillRuntime`` the
same way the legacy ``run()`` entry does; this module intentionally stops
at the execution layer, which is what the tech-tree benchmark measures.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Mapping

from PhyAgentOS.benchmarks.minecraft.techtree.schema import TechTreeTask, WorldSetup

if TYPE_CHECKING:
    from PhyAgentOS.runtime.targets.game.minecraft_target import MinecraftTarget


class MinecraftTargetWorldAdapter:
    """Benchmark ``WorldAdapter`` backed by a runtime ``MinecraftTarget``.

    - ``reset(setup)`` POSTs ``/benchmark/reset`` to the same bridge the
      target already uses, so arena isolation, inventory reset, item
      grants and block placement all run server-side, then observes.
    - ``observe()`` delegates to ``MinecraftTarget.observe()``, whose rich
      state (``inventory.hotbar`` etc.) the unified evaluator scores
      directly.
    - ``execute_action`` exposes ``MinecraftTarget.step`` so an injected
      agent can drive the bot through this same adapter instead of a
      second HTTP client.
    """

    def __init__(self, target: "MinecraftTarget"):
        self._target = target

    def reset(self, setup: WorldSetup) -> Mapping[str, Any]:
        if not getattr(self._target, "_built", False):
            self._target.build()
        client = self._target._get_http()
        bridge_url = self._target._bridge_url
        timeout = float(self._target.config.get("action_timeout", 60.0))
        response = client.post(
            f"{bridge_url}/benchmark/reset",
            json=setup.to_dict(),
            timeout=timeout,
        )
        response.raise_for_status()
        return self._target.observe()

    def observe(self) -> Mapping[str, Any]:
        return self._target.observe()

    def execute_action(self, action_type: str, params: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        return self._target.step({"type": action_type, "params": dict(params or {})})


AgentFn = Callable[[TechTreeTask, "MinecraftTargetWorldAdapter"], Any]


def make_action_agent_fn(
    actions: list[Mapping[str, Any]],
) -> AgentFn:
    """Build an ``agent_fn`` that executes a static action list.

    For an execution-layer benchmark the injected agent is often a scripted
    or learned action sequence; this helper turns such a sequence into the
    ``agent_fn(task, world)`` the harness expects.  Actions are
    ``{"type": ..., "params": {...}`` dicts forwarded to
    ``world.execute_action``.
    """

    def agent_fn(task: TechTreeTask, world: MinecraftTargetWorldAdapter) -> dict[str, Any]:
        results = []
        for action in actions:
            results.append(world.execute_action(action["type"], action.get("params", {})))
        return {"actions_executed": len(results), "results": results}

    return agent_fn


def task_verify_descriptors(task: TechTreeTask) -> list[str]:
    """Render a benchmark task's success criterion as runtime verifier descriptors.

    A TaskPlan built for a benchmark task can self-verify with the same
    ``has_item:...`` vocabulary the OS verifier uses, instead of a parallel
    success model.
    """

    return [task.success_criterion.to_descriptor()]
