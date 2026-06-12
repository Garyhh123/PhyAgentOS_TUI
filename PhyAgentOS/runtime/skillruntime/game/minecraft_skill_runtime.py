"""Minecraft skill runtime: drives an episode on a MinecraftTarget.

Supports two execution modes:
  1. TaskPlan mode (hierarchical): subgoals with pre/post checks and retry.
  2. Flat action plan mode (backward compatible): sequential action list.

Supports interrupt: set the `_cancelled` event or call `cancel()` to
gracefully stop execution between tasks/subgoals.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Any

from PhyAgentOS.runtime.schemas import AdapterPlan, SessionResult, SessionSpec
from PhyAgentOS.runtime.schemas.task_plan import TaskPlan
from PhyAgentOS.runtime.skillruntime.base import BaseSkillRuntime
from PhyAgentOS.runtime.skillruntime.game.task_verifier import TaskVerifier
from PhyAgentOS.runtime.watchdog.errors import SessionTimeoutError

logger = logging.getLogger(__name__)


class InterruptedError(Exception):
    """Raised when a running session is interrupted by user command."""

    def __init__(self, reason: str = "interrupted"):
        super().__init__(reason)
        self.reason = reason


class MinecraftSkillRuntime(BaseSkillRuntime):
    """Execute a Minecraft episode: TaskPlan → verify → execute → verify.

    Falls back to flat action-list execution if no TaskPlan is provided.

    Set `runtime._cancelled` (a threading.Event) or call `runtime.cancel()`
    to interrupt the current session gracefully.
    """

    runtime_kind = "builtin"

    def __init__(self):
        super().__init__()
        self._cancelled = threading.Event()
        self._target = None

    def start(self, skill_ctx) -> None:
        self._cancelled.clear()

    def cancel(self, skill_ctx=None, reason: str = "interrupted") -> None:
        self._cancelled.set()
        logger.info("session cancelled: %s", reason)
        if self._target and hasattr(self._target, "cancel"):
            try:
                self._target.cancel(reason)
            except Exception:
                pass

    def snapshot(self, skill_ctx) -> dict:
        return {"status": "cancelled" if self._cancelled.is_set() else "idle"}

    def _check_cancel(self) -> None:
        if self._cancelled.is_set():
            raise InterruptedError("session interrupted by user")

    # ── Main entry point ────────────────────────────────────────────

    def run(
        self,
        session: SessionSpec,
        target,
        target_adapter,
        policy_adapter,
        action_bridges,
        policy_client,
        adapter_plan: AdapterPlan,
    ) -> SessionResult:
        self._cancelled.clear()
        self._target = target
        target.build()
        session_ctx = session.model_dump(mode="json")
        session_ctx["adapter_plan"] = adapter_plan.model_dump(mode="json")

        target.configure_session({
            "session_id": session.session_id,
            "task_description": session.task_description,
            "target_ref": session.target_ref,
            "skillruntime_ref": session.skillruntime_ref,
        })

        raw_obs = target.reset(session_ctx)
        hints = session.runtime_hints
        queries = hints.perception_queries if hints else []

        # Detect TaskPlan from perception_queries
        task_plan = _detect_task_plan(queries)
        if task_plan is not None:
            return self._run_task_plan(task_plan, target, target_adapter,
                                       action_bridges, raw_obs, session)

        # Backward-compatible flat action list execution
        return self._run_flat(queries, session, target, target_adapter,
                              action_bridges, raw_obs)

    # ── TaskPlan execution ──────────────────────────────────────────

    def _run_task_plan(
        self,
        plan: TaskPlan,
        target,
        target_adapter,
        action_bridges,
        raw_obs: dict[str, Any],
        session: SessionSpec,
    ) -> SessionResult:
        num_steps = 0
        total_reward = 0.0
        start_time = time.monotonic()
        timeout_s = session.timeouts.execute_timeout_s
        max_steps = session.execution.max_steps
        failed_subgoals: list[str] = []

        for sg in plan.subgoals:
            self._check_cancel()
            if time.monotonic() - start_time > timeout_s:
                raise SessionTimeoutError(f"session {session.session_id} exceeded {timeout_s}s")

            # Resolve dependencies: skip if a dependency failed
            blocked = [d for d in sg.depends_on if d in failed_subgoals]
            if blocked:
                logger.warning("skipping subgoal %s (deps failed: %s)", sg.name, blocked)
                sg.state = "failed"
                failed_subgoals.append(sg.id)
                continue

            # Refresh observation before subgoal
            raw_obs = target.observe()
            verifier = TaskVerifier(target, raw_obs)

            # Precheck
            sg.state = "running"
            if sg.precheck:
                ok, failures = verifier.verify_all(sg.precheck)
                if not ok:
                    logger.warning("subgoal %s precheck failed: %s", sg.name, failures)
                    sg.state = "failed"
                    failed_subgoals.append(sg.id)
                    continue

            logger.info("subgoal: %s (%d tasks)", sg.name, len(sg.tasks))
            for task in sg.tasks:
                self._check_cancel()
                if time.monotonic() - start_time > timeout_s:
                    raise SessionTimeoutError(f"session {session.session_id} exceeded {timeout_s}s")
                if num_steps >= max_steps:
                    logger.warning("max_steps (%d) reached", max_steps)
                    break

                task.state = "running"
                task.attempts = 0

                for attempt in range(task.max_retries):
                    self._check_cancel()
                    task.attempts = attempt + 1

                    # Refresh + verify preconditions
                    raw_obs = target.observe()
                    verifier = TaskVerifier(target, raw_obs)
                    if task.preconditions:
                        ok, failures = verifier.verify_all(task.preconditions)
                        if not ok:
                            logger.warning("task %s preconditions failed: %s (attempt %d/%d)",
                                           task.name, failures, task.attempts, task.max_retries)
                            task.last_error = f"precondition failed: {failures}"
                            if task.on_fail == "abort":
                                break
                            if task.on_fail == "skip":
                                task.state = "skipped"
                                break
                            continue  # retry

                    # Execute actions
                    task_success = True
                    for action_spec in task.actions:
                        if num_steps >= max_steps:
                            break
                        action = {"type": action_spec.type, "params": action_spec.params}
                        bridged_action = action
                        for bridge in action_bridges:
                            bridged_action = bridge.apply(bridged_action, {})

                        transition = target.step(bridged_action)
                        num_steps += 1
                        raw_obs = transition.get("obs", target.observe())
                        total_reward += float(transition.get("reward", 0.0))

                        # Wait for move arrival
                        if action_spec.type == "move" and action_spec.params.get("absolute"):
                            raw_obs = _wait_for_arrival(
                                target, raw_obs,
                                target_xyz=(
                                    float(action_spec.params["dx"]),
                                    float(action_spec.params["dy"]),
                                    float(action_spec.params["dz"]),
                                ),
                                timeout_s=min(30.0, timeout_s - (time.monotonic() - start_time)),
                                step_delay=0.5,
                            )

                        # Check action feedback
                        info = transition.get("info", {})
                        if not info.get("ok", False):
                            logger.warning("task %s action %s failed: %s",
                                           task.name, action_spec.type, info.get("result", "?"))
                            task.last_error = info.get("result", "action failed")
                            task_success = False
                            break

                    if not task_success:
                        if task.on_fail == "retry" and attempt < task.max_retries - 1:
                            time.sleep(0.5)
                            continue
                        elif task.on_fail == "skip":
                            task.state = "skipped"
                            break
                        else:
                            task.state = "failed"
                            break

                    # Verify post-conditions
                    raw_obs = target.observe()
                    verifier = TaskVerifier(target, raw_obs)
                    if task.verify:
                        ok, failures = verifier.verify_all(task.verify)
                        if not ok:
                            logger.warning("task %s verify failed: %s (attempt %d/%d)",
                                           task.name, failures, task.attempts, task.max_retries)
                            task.last_error = f"verify failed: {failures}"
                            if task.on_fail == "abort":
                                task.state = "failed"
                                break
                            if task.on_fail == "skip":
                                task.state = "skipped"
                                break
                            continue  # retry

                    # Success
                    task.state = "done"
                    logger.info("task %s done (attempts=%d)", task.name, task.attempts)
                    break
                else:
                    # Exhausted retries
                    if task.state != "done" and task.state != "skipped":
                        task.state = "failed"
                    logger.warning("task %s failed after %d retries", task.name, task.max_retries)

            # Postcheck
            raw_obs = target.observe()
            verifier = TaskVerifier(target, raw_obs)
            if sg.postcheck:
                ok, failures = verifier.verify_all(sg.postcheck)
                if ok:
                    sg.state = "done"
                else:
                    logger.warning("subgoal %s postcheck failed: %s", sg.name, failures)
                    sg.state = "failed"
                    failed_subgoals.append(sg.id)
            else:
                # No postcheck: count as done if all tasks done
                all_done = all(t.state in ("done", "skipped") for t in sg.tasks)
                sg.state = "done" if all_done else "failed"
                if not all_done:
                    failed_subgoals.append(sg.id)

            if bool(transition.get("done", False)):
                break

        all_ok = all(sg.state == "done" for sg in plan.subgoals)
        return SessionResult(
            status="succeeded" if all_ok else "failed",
            success=all_ok,
            num_steps=num_steps,
            return_value=total_reward,
            metadata={"subgoals_done": sum(1 for sg in plan.subgoals if sg.state == "done"),
                      "subgoals_total": len(plan.subgoals)},
        )

    # ── Flat action list execution (backward-compatible) ────────────

    def _run_flat(
        self,
        queries: list[dict[str, Any]],
        session: SessionSpec,
        target,
        target_adapter,
        action_bridges,
        raw_obs: dict[str, Any],
    ) -> SessionResult:
        action_plan: list[dict[str, Any]] = _extract_action_plan(queries)
        num_steps = 0
        total_reward = 0.0
        start_time = time.monotonic()
        timeout_s = session.timeouts.execute_timeout_s

        for step_idx in range(session.execution.max_steps):
            self._check_cancel()
            if time.monotonic() - start_time > timeout_s:
                raise SessionTimeoutError(
                    f"session {session.session_id} exceeded {timeout_s}s"
                )

            target_info = {
                "step_index": step_idx,
                "task_description": session.task_description,
            }
            runtime_obs = target_adapter.to_runtime_observation(raw_obs, target_info)

            if step_idx >= len(action_plan):
                return SessionResult(
                    status="succeeded",
                    success=True,
                    num_steps=num_steps,
                    return_value=total_reward,
                )

            action = _pick_action(action_plan, step_idx, runtime_obs)

            bridged_action = action
            for bridge in action_bridges:
                bridged_action = bridge.apply(bridged_action, target_info)

            transition = target.step(bridged_action)
            num_steps += 1
            raw_obs = transition.get("obs", target.observe())

            if action.get("type") == "move" and action.get("params", {}).get("absolute"):
                raw_obs = _wait_for_arrival(
                    target, raw_obs,
                    target_xyz=(
                        float(action["params"]["dx"]),
                        float(action["params"]["dy"]),
                        float(action["params"]["dz"]),
                    ),
                    timeout_s=min(30.0, timeout_s - (time.monotonic() - start_time)),
                    step_delay=0.5,
                )

            total_reward += float(transition.get("reward", 0.0))

            if bool(transition.get("done", False)) or bool(
                transition.get("info", {}).get("success", False)
            ):
                return SessionResult(
                    status="succeeded",
                    success=True,
                    num_steps=num_steps,
                    return_value=total_reward,
                    metadata={"done": True},
                )

        return SessionResult(
            status="failed",
            success=False,
            num_steps=num_steps,
            return_value=total_reward,
            error_code="MAX_STEPS_EXCEEDED",
            error_message="session reached max_steps without success",
        )


# ── Helpers ─────────────────────────────────────────────────────────

def _detect_task_plan(queries: list[dict[str, Any]]) -> TaskPlan | None:
    """If queries contain a TaskPlan dict, parse and return it."""
    if not queries:
        return None
    first = queries[0]
    if isinstance(first, dict) and "subgoals" in first:
        try:
            return TaskPlan.model_validate(first)
        except Exception as e:
            logger.warning("failed to parse TaskPlan from query: %s", e)
            return None
    return None


def _extract_action_plan(queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    for q in queries:
        if isinstance(q, dict) and "type" in q:
            plan.append(q)
    return plan


def _pick_action(
    action_plan: list[dict[str, Any]],
    step_idx: int,
    runtime_obs: dict[str, Any],
) -> dict[str, Any]:
    """Pick the next action, resolving dynamic targets at runtime."""
    action = action_plan[step_idx].copy()

    if action.get("type") == "move":
        target_type = action.get("params", {}).get("target")
        if target_type:
            entity = _find_nearest_entity(runtime_obs, target_type)
            if entity is None:
                label = "player nearby" if target_type == "player" else f"any {target_type} nearby"
                return {"type": "chat", "params": {"message": f"I can't see {label}."}}
            logger.info("resolved target %s → (%.1f, %.1f, %.1f)",
                         target_type,
                         entity["position"]["x"], entity["position"]["y"], entity["position"]["z"])
            return _build_move_to_entity(entity)

    return action


def _find_nearest_entity(
    runtime_obs: dict[str, Any], target_type: str
) -> dict[str, Any] | None:
    entities = runtime_obs.get("nearby_entities", [])
    info = runtime_obs.get("info", {})

    bot_pos = None
    pos = info.get("position")
    if pos:
        bot_pos = (pos.get("x", 0), pos.get("y", 0), pos.get("z", 0))

    accepted = {target_type, target_type.lower(), target_type.capitalize()}
    if target_type == "player":
        accepted.update(info.get("player_list", []))

    matches = []
    for e in entities:
        if not isinstance(e, dict):
            continue
        if e.get("type", "") in accepted and e.get("position"):
            matches.append(e)

    if not matches and target_type == "player":
        bot_name = (runtime_obs.get("bot") or {}).get("username", "")
        for p in runtime_obs.get("players", []):
            if not isinstance(p, dict):
                continue
            if p.get("username", "") == bot_name:
                continue
            if p.get("position"):
                matches.append({
                    "type": p.get("username", "player"),
                    "position": p["position"],
                })

    if not matches:
        return None
    if bot_pos:
        def _dist(m):
            pp = m["position"]
            return ((pp["x"] - bot_pos[0]) ** 2 +
                    (pp["y"] - bot_pos[1]) ** 2 +
                    (pp["z"] - bot_pos[2]) ** 2)
        matches.sort(key=_dist)
    return matches[0]


def _build_move_to_entity(entity: dict[str, Any]) -> dict[str, Any]:
    pos = entity["position"]
    return {
        "type": "move",
        "params": {
            "dx": float(pos.get("x", 0)) + 1.0,
            "dy": float(pos.get("y", 0)),
            "dz": float(pos.get("z", 0)),
            "absolute": True,
        },
    }


def _wait_for_arrival(
    target,
    raw_obs: dict[str, Any],
    target_xyz: tuple[float, float, float],
    timeout_s: float = 30.0,
    step_delay: float = 0.5,
    arrival_radius: float = 2.0,
) -> dict[str, Any]:
    """Poll observe() until the bot reaches target_xyz or timeout."""
    deadline = time.monotonic() + max(0.0, timeout_s)
    tx, ty, tz = target_xyz
    while time.monotonic() < deadline:
        pos = raw_obs.get("info", {}).get("position", {})
        bx = float(pos.get("x", 0))
        by = float(pos.get("y", 0))
        bz = float(pos.get("z", 0))
        dist = math.sqrt((bx - tx) ** 2 + (by - ty) ** 2 + (bz - tz) ** 2)
        if dist <= arrival_radius:
            logger.info("arrived at target (dist=%.1f)", dist)
            return raw_obs
        time.sleep(step_delay)
        raw_obs = target.observe()
    logger.warning("move timed out after %.1fs", timeout_s)
    return raw_obs
