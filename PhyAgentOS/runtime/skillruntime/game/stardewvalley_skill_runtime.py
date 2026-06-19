"""Stardew Valley skill runtime: drives an episode on a StardewValleyTarget.

Mirrors MinecraftSkillRuntime in structure:
  1. TaskPlan mode (hierarchical): subgoals with pre/post checks and retry.
  2. Flat action plan mode (backward compatible): sequential action list.

Supports interrupt: set the `_cancelled` event or call `cancel()` to
gracefully stop execution between tasks/subgoals.

The SessionRunner-based architecture routes through *run_builtin_loop*
which uses TargetSessionHandle for all target interactions.  A legacy
``run()`` entrypoint is kept for backward compatibility.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from PhyAgentOS.runtime.schemas import AdapterPlan, SessionResult, SessionSpec
from PhyAgentOS.runtime.schemas.task_plan import TaskPlan
from PhyAgentOS.runtime.sessions.models import SkillContext, SkillRuntimeResult
from PhyAgentOS.runtime.skillruntime.builtin.base import BuiltinSkillRuntime
from PhyAgentOS.runtime.skillruntime.game.stardewvalley_task_verifier import (
    StardewTaskVerifier,
)
from PhyAgentOS.runtime.watchdog.errors import SessionTimeoutError

logger = logging.getLogger(__name__)


class InterruptedError(Exception):
    def __init__(self, reason: str = "interrupted"):
        super().__init__(reason)
        self.reason = reason


class StardewValleySkillRuntime(BuiltinSkillRuntime):
    """Execute a Stardew Valley episode: TaskPlan → verify → execute → verify.

    Falls back to flat action-list execution if no TaskPlan is provided.
    """

    runtime_kind = "builtin"

    def __init__(self):
        super().__init__()
        self._cancelled = threading.Event()
        self._raw_target = None

    def start(self, skill_ctx: SkillContext) -> None:
        self._cancelled.clear()

    def cancel(self, skill_ctx: SkillContext | None = None, reason: str = "interrupted") -> None:
        self._cancelled.set()
        logger.info("session cancelled: %s", reason)
        if self._raw_target and hasattr(self._raw_target, "cancel"):
            try:
                self._raw_target.cancel(reason)
            except Exception:
                pass

    def snapshot(self, skill_ctx: SkillContext | None = None) -> dict:
        return {"status": "cancelled" if self._cancelled.is_set() else "idle"}

    def _check_cancel(self) -> None:
        if self._cancelled.is_set():
            raise InterruptedError("session interrupted by user")

    # ── SessionRunner entry point ──────────────────────────────────

    def run_builtin_loop(
        self,
        skill_ctx: SkillContext,
        target_handle,
        adapter_plan: AdapterPlan,
    ) -> SkillRuntimeResult:
        self._cancelled.clear()
        session = skill_ctx.session
        hints = session.runtime_hints
        queries = hints.perception_queries if hints else []

        task_plan = _detect_task_plan(queries)
        if task_plan is not None:
            result = self._run_task_plan_handle(task_plan, target_handle, session)
        else:
            result = self._run_flat_handle(queries, session, target_handle, adapter_plan)

        return SkillRuntimeResult(
            status=result.status or ("succeeded" if result.success else "failed"),
            success=result.success or False,
            final_status={"target_step_index": result.num_steps, "reward": result.return_value},
            error_code=result.error_code,
            error_message=result.error_message,
            metadata=result.metadata,
        )

    # ── TaskPlan execution via TargetSessionHandle ─────────────────

    def _run_task_plan_handle(
        self,
        plan: TaskPlan,
        handle,
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

            blocked = [d for d in sg.depends_on if d in failed_subgoals]
            if blocked:
                logger.warning("skipping subgoal %s (deps failed: %s)", sg.name, blocked)
                sg.state = "failed"
                failed_subgoals.append(sg.id)
                continue

            raw_obs = handle.observe()
            verifier = StardewTaskVerifier(handle._target, raw_obs.data)

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

                    raw_obs = handle.observe()
                    verifier = StardewTaskVerifier(handle._target, raw_obs.data)
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
                            continue

                    task_success = True
                    for action_spec in task.actions:
                        if num_steps >= max_steps:
                            break
                        action = {"type": action_spec.type, "params": action_spec.params}
                        chunk_result = handle.action_chunk({"actions": [action]})
                        num_steps += 1

                        if action_spec.type == "move":
                            time.sleep(0.3)

                        info = chunk_result.get("info", {})
                        if isinstance(info, dict) and not info.get("ok", True):
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

                    raw_obs = handle.observe()
                    verifier = StardewTaskVerifier(handle._target, raw_obs.data)
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
                            continue

                    task.state = "done"
                    logger.info("task %s done (attempts=%d)", task.name, task.attempts)
                    break
                else:
                    if task.state != "done" and task.state != "skipped":
                        task.state = "failed"
                    logger.warning("task %s failed after %d retries", task.name, task.max_retries)

            raw_obs = handle.observe()
            verifier = StardewTaskVerifier(handle._target, raw_obs.data)
            if sg.postcheck:
                ok, failures = verifier.verify_all(sg.postcheck)
                if ok:
                    sg.state = "done"
                else:
                    logger.warning("subgoal %s postcheck failed: %s", sg.name, failures)
                    sg.state = "failed"
                    failed_subgoals.append(sg.id)
            else:
                all_done = all(t.state in ("done", "skipped") for t in sg.tasks)
                sg.state = "done" if all_done else "failed"
                if not all_done:
                    failed_subgoals.append(sg.id)

        all_ok = all(sg.state == "done" for sg in plan.subgoals)
        result = SessionResult(
            status="succeeded" if all_ok else "failed",
            success=all_ok,
            num_steps=num_steps,
            return_value=total_reward,
            metadata={"subgoals_done": sum(1 for sg in plan.subgoals if sg.state == "done"),
                      "subgoals_total": len(plan.subgoals)},
        )
        return result

    # ── Flat action list via TargetSessionHandle ───────────────────

    def _run_flat_handle(
        self,
        queries: list[dict[str, Any]],
        session: SessionSpec,
        handle,
        adapter_plan: AdapterPlan,
    ) -> SessionResult:
        action_plan: list[dict[str, Any]] = _extract_action_plan(queries)
        num_steps = 0
        total_reward = 0.0
        start_time = time.monotonic()
        timeout_s = session.timeouts.execute_timeout_s

        for step_idx in range(session.execution.max_steps):
            self._check_cancel()
            if time.monotonic() - start_time > timeout_s:
                raise SessionTimeoutError(f"session {session.session_id} exceeded {timeout_s}s")

            if step_idx >= len(action_plan):
                return SessionResult(
                    status="succeeded",
                    success=True,
                    num_steps=num_steps,
                    return_value=total_reward,
                )

            action = action_plan[step_idx]
            chunk_result = handle.action_chunk({"actions": [action]})
            num_steps += 1

            if action.get("type") == "move":
                time.sleep(0.3)

            if bool(chunk_result.get("done", False)):
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

    # ── Legacy entry point ────────────────────────────────────────

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
        self._raw_target = target
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

        task_plan = _detect_task_plan(queries)
        if task_plan is not None:
            return self._run_task_plan(task_plan, target, target_adapter,
                                       action_bridges, raw_obs, session)

        return self._run_flat(queries, session, target, target_adapter,
                              action_bridges, raw_obs)

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

            blocked = [d for d in sg.depends_on if d in failed_subgoals]
            if blocked:
                logger.warning("skipping subgoal %s (deps failed: %s)", sg.name, blocked)
                sg.state = "failed"
                failed_subgoals.append(sg.id)
                continue

            raw_obs = target.observe()
            verifier = StardewTaskVerifier(target, raw_obs)

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

                    raw_obs = target.observe()
                    verifier = StardewTaskVerifier(target, raw_obs)
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
                            continue

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

                        if action_spec.type == "move":
                            time.sleep(0.3)

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

                    raw_obs = target.observe()
                    verifier = StardewTaskVerifier(target, raw_obs)
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
                            continue

                    task.state = "done"
                    logger.info("task %s done (attempts=%d)", task.name, task.attempts)
                    break
                else:
                    if task.state != "done" and task.state != "skipped":
                        task.state = "failed"
                    logger.warning("task %s failed after %d retries", task.name, task.max_retries)

            raw_obs = target.observe()
            verifier = StardewTaskVerifier(target, raw_obs)
            if sg.postcheck:
                ok, failures = verifier.verify_all(sg.postcheck)
                if ok:
                    sg.state = "done"
                else:
                    logger.warning("subgoal %s postcheck failed: %s", sg.name, failures)
                    sg.state = "failed"
                    failed_subgoals.append(sg.id)
            else:
                all_done = all(t.state in ("done", "skipped") for t in sg.tasks)
                sg.state = "done" if all_done else "failed"
                if not all_done:
                    failed_subgoals.append(sg.id)

        all_ok = all(sg.state == "done" for sg in plan.subgoals)
        return SessionResult(
            status="succeeded" if all_ok else "failed",
            success=all_ok,
            num_steps=num_steps,
            return_value=total_reward,
            metadata={"subgoals_done": sum(1 for sg in plan.subgoals if sg.state == "done"),
                      "subgoals_total": len(plan.subgoals)},
        )

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
                raise SessionTimeoutError(f"session {session.session_id} exceeded {timeout_s}s")

            target_info = {
                "step_index": step_idx,
                "task_description": session.task_description,
            }

            if step_idx >= len(action_plan):
                return SessionResult(
                    status="succeeded",
                    success=True,
                    num_steps=num_steps,
                    return_value=total_reward,
                )

            action = action_plan[step_idx].copy()

            bridged_action = action
            for bridge in action_bridges:
                bridged_action = bridge.apply(bridged_action, target_info)

            transition = target.step(bridged_action)
            num_steps += 1
            total_reward += float(transition.get("reward", 0.0))

            if action.get("type") == "move":
                time.sleep(0.3)

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
