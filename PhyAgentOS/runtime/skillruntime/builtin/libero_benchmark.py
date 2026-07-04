"""Target-native LIBERO benchmark skill runtime."""

from __future__ import annotations

from typing import Any

from PhyAgentOS.runtime.schemas import AdapterPlan
from PhyAgentOS.runtime.sessions.models import SkillContext, SkillRuntimeResult
from PhyAgentOS.runtime.skillruntime.builtin.base import BuiltinSkillRuntime
from PhyAgentOS.runtime.verification.benchmark_episode_verifier import BenchmarkEpisodeVerifier
from PhyAgentOS.runtime.watchdog.errors import AdapterError


class LiberoBenchmarkSkillRuntime(BuiltinSkillRuntime):
    """Run a complete LIBERO benchmark through the target runtime."""

    def __init__(self) -> None:
        self._snapshot: dict[str, Any] = {}

    def start(self, skill_ctx: SkillContext) -> None:
        self._snapshot = {"session_id": skill_ctx.session.session_id, "started": True}

    def cancel(self, skill_ctx: SkillContext, reason: str) -> None:
        self._snapshot = {**self._snapshot, "cancelled": True, "cancel_reason": reason}

    def snapshot(self, skill_ctx: SkillContext) -> dict:
        return dict(self._snapshot)

    def run_builtin_loop(
        self,
        skill_ctx: SkillContext,
        target_handle,
        adapter_plan: AdapterPlan,
    ) -> SkillRuntimeResult:
        del adapter_plan
        payload = _benchmark_payload(skill_ctx)
        assist = _agent_assist_config(skill_ctx)
        if assist["enabled"]:
            payload["assist_mode"] = str(assist["mode"])
            payload["evidence_mode"] = "failed"
            payload["agent_assist"] = {
                key: value
                for key, value in assist.items()
                if value is not None
            }
        result = target_handle.run_benchmark(payload)
        if assist["enabled"] and not assist["inline"]:
            result = _run_failure_only_assist(
                target_handle=target_handle,
                base_payload=payload,
                first_pass=result,
                assist=assist,
            )
        episodes = list(result.get("episodes") or [])
        total = int(result.get("total_episodes") or len(episodes))
        successes = int(result.get("successes") or sum(1 for episode in episodes if episode.get("success")))
        status = str(result.get("status") or ("succeeded" if total else "failed"))
        success_rate = float(result.get("success_rate") or (successes / total if total else 0.0))
        self._snapshot = {
            "session_id": skill_ctx.session.session_id,
            "status": status,
            "successes": successes,
            "total_episodes": total,
            "success_rate": success_rate,
        }
        return SkillRuntimeResult(
            status=status if status in {"succeeded", "failed", "timed_out", "cancelled"} else "failed",
            success=bool(total and status == "succeeded"),
            final_status={
                "target_step_index": int(result.get("num_steps") or 0),
                "executed_steps": int(result.get("num_steps") or 0),
                "success": bool(total and status == "succeeded"),
                "done": True,
                "reward": float(successes),
                "benchmark": {
                    "suite_id": payload.get("suite"),
                    "successes": successes,
                    "total_episodes": total,
                    "success_rate": success_rate,
                },
            },
            error_code=result.get("error_code"),
            error_message=result.get("error_message"),
            metadata={
                "benchmark_result": result,
                "return_value": float(successes),
                "mean_policy_latency_ms": result.get("mean_policy_latency_ms"),
            },
        )


def _benchmark_payload(skill_ctx: SkillContext) -> dict[str, Any]:
    session = skill_ctx.session
    benchmark = session.benchmark
    suite = benchmark.suite_id if benchmark and benchmark.suite_id else None
    if not suite:
        raise AdapterError("LIBERO benchmark session requires benchmark.suite_id")
    policy_endpoint = session.routing.policy_endpoint
    if not policy_endpoint:
        raise AdapterError("LIBERO benchmark session requires routing.policy_endpoint")
    payload = {
        "session_id": session.session_id,
        "run_id": benchmark.run_id if benchmark else session.session_id,
        "suite": suite,
        "policy_endpoint": policy_endpoint,
        "task_ids": _runtime_hint(session, "task_ids", list(range(10))),
        "init_state_ids": _runtime_hint(session, "init_state_ids", list(range(50))),
        "max_steps": int(session.execution.max_steps),
        "num_steps_wait": int(_target_config(skill_ctx, "num_steps_wait", 10)),
        "control_mode": str(_target_config(skill_ctx, "control_mode", "relative")),
        "camera_height": int(_target_config(skill_ctx, "camera_height", 256)),
        "camera_width": int(_target_config(skill_ctx, "camera_width", 256)),
        "policy_timeout_s": float(session.timeouts.policy_timeout_s),
        "record_dir": _runtime_hint(session, "record_dir", None),
        "attempt_index": 0,
        "evidence_mode": str(_runtime_hint(session, "evidence_mode", "none")),
    }
    return payload


def _runtime_hint(session, key: str, default: Any) -> Any:
    for query in session.runtime_hints.perception_queries:
        if isinstance(query, dict) and key in query:
            return query[key]
    return default


def _target_config(skill_ctx: SkillContext, key: str, default: Any) -> Any:
    return skill_ctx.target.config.get(key, default)


def _agent_assist_config(skill_ctx: SkillContext) -> dict[str, Any]:
    config = _runtime_hint(skill_ctx.session, "agent_assist", None)
    if not isinstance(config, dict):
        config = _target_config(skill_ctx, "agent_assist", {})
    if not isinstance(config, dict):
        config = {}
    mode = str(config.get("mode") or config.get("assist_mode") or ("retry" if config.get("enabled") else "disabled"))
    enabled = bool(config.get("enabled")) and mode != "disabled"
    return {
        "enabled": enabled,
        "mode": mode,
        "trigger": str(config.get("trigger") or "failed_only"),
        "max_replans_per_episode": int(config.get("max_replans_per_episode") or 1),
        "max_verifier_calls_per_suite": int(config.get("max_verifier_calls_per_suite") or 50),
        "success_authority": str(config.get("success_authority") or "target"),
        "verifier_endpoint": config.get("verifier_endpoint"),
        "verifier_timeout_s": float(config.get("verifier_timeout_s") or 60.0),
        "verifier_failure_policy": str(config.get("verifier_failure_policy") or "skip"),
        "retry_instruction_mode": str(config.get("retry_instruction_mode") or "verifier_rewrite"),
        "inline": bool(config.get("inline", True)),
    }


def _run_failure_only_assist(
    *,
    target_handle,
    base_payload: dict[str, Any],
    first_pass: dict[str, Any],
    assist: dict[str, Any],
) -> dict[str, Any]:
    episodes = [dict(episode) for episode in list(first_pass.get("episodes") or [])]
    failed = [episode for episode in episodes if not bool(episode.get("success"))]
    verifier = BenchmarkEpisodeVerifier(
        endpoint=assist.get("verifier_endpoint"),
        timeout_s=float(assist["verifier_timeout_s"]),
        failure_policy=str(assist["verifier_failure_policy"]),
    )
    verifier_attempts: list[dict[str, Any]] = []
    retry_by_key: dict[tuple[int, int], dict[str, Any]] = {}
    verifier_budget = max(0, int(assist["max_verifier_calls_per_suite"]))
    max_replans = max(0, int(assist["max_replans_per_episode"]))
    if max_replans <= 0:
        verifier_budget = 0

    for episode in failed:
        if len(verifier_attempts) >= verifier_budget:
            break
        bundle = _episode_verification_bundle(base_payload, episode)
        verdict = verifier.verify(bundle)
        record = {
            "run_id": base_payload.get("run_id"),
            "suite": base_payload.get("suite"),
            "episode_id": episode.get("episode_id"),
            "task_id": episode.get("task_id"),
            "init_state_id": episode.get("init_state_id"),
            "attempt_index": episode.get("attempt_index", 0),
            "verdict": verdict.get("verdict"),
            "evidence": verdict.get("evidence"),
            "failure_reason": verdict.get("failure_reason"),
            "replan_task_description": verdict.get("replan_task_description"),
            "lesson": verdict.get("lesson"),
            "verifier_status": verdict.get("verifier_status"),
        }
        verifier_attempts.append(record)
        if verdict.get("verdict") != "replan" or assist["mode"] != "retry":
            continue
        task_id = int(episode["task_id"])
        init_state_id = int(episode["init_state_id"])
        retry_by_key[(task_id, init_state_id)] = {
            "verdict": verdict,
            "first_episode": episode,
        }

    retry_result: dict[str, Any] | None = None
    if retry_by_key:
        retry_payload = dict(base_payload)
        retry_payload.update(
            {
                "episodes": [
                    {"task_id": task_id, "init_state_id": init_state_id}
                    for task_id, init_state_id in sorted(retry_by_key)
                ],
                "attempt_index": 1,
                "assist_mode": "retry",
                "evidence_mode": "failed",
                "session_id": f"{base_payload.get('session_id')}_retry1",
            }
        )
        retry_result = target_handle.run_benchmark(retry_payload)

    return _merge_assisted_result(
        first_pass=first_pass,
        retry_result=retry_result,
        retry_by_key=retry_by_key,
        verifier_attempts=verifier_attempts,
        assist=assist,
    )


def _episode_verification_bundle(base_payload: dict[str, Any], episode: dict[str, Any]) -> dict[str, Any]:
    evidence = episode.get("evidence") if isinstance(episode.get("evidence"), dict) else {}
    return {
        "version": "benchmark_episode_verification_v1",
        "run_id": base_payload.get("run_id"),
        "suite_id": base_payload.get("suite"),
        "episode_id": episode.get("episode_id"),
        "task_index": episode.get("task_id"),
        "instance_id": episode.get("init_state_id"),
        "attempt_index": episode.get("attempt_index", 0),
        "task_description": episode.get("task_description"),
        "runtime_claim": {
            "success": bool(episode.get("success")),
            "source": "target_environment",
            "authority": "target",
        },
        "initial_observation": evidence.get("initial_observation"),
        "final_observation": evidence.get("final_observation"),
        "final_status": {
            "steps": episode.get("num_steps"),
            "reward": episode.get("return_value"),
            "done": True,
        },
    }


def _merge_assisted_result(
    *,
    first_pass: dict[str, Any],
    retry_result: dict[str, Any] | None,
    retry_by_key: dict[tuple[int, int], dict[str, Any]],
    verifier_attempts: list[dict[str, Any]],
    assist: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(first_pass)
    first_episodes = [dict(episode) for episode in list(first_pass.get("episodes") or [])]
    retry_episodes = [dict(episode) for episode in list((retry_result or {}).get("episodes") or [])]
    retry_lookup = {
        (int(episode.get("task_id")), int(episode.get("init_state_id"))): episode
        for episode in retry_episodes
    }
    final_successes = 0
    recovered = 0
    episodes_replanned = 0
    output_episodes: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    for episode in first_episodes:
        key = (int(episode.get("task_id")), int(episode.get("init_state_id")))
        first_success = bool(episode.get("success"))
        retry_episode = retry_lookup.get(key)
        final_success = first_success
        episode_attempts = [_attempt_record(episode)]
        if retry_episode is not None:
            episodes_replanned += 1
            retry_episode = dict(retry_episode)
            retry_episode["episode_id"] = episode.get("episode_id")
            final_success = bool(retry_episode.get("success"))
            episode_attempts.append(_attempt_record(retry_episode))
            if final_success and not first_success:
                recovered += 1
        elif key in retry_by_key:
            episodes_replanned += 1
        item = dict(episode)
        item.pop("evidence", None)
        item["first_attempt_success"] = first_success
        item["final_success"] = final_success
        item["final_status"] = "succeeded" if final_success else "failed"
        item["attempts"] = episode_attempts
        output_episodes.append(item)
        attempts.extend(episode_attempts)
        final_successes += 1 if final_success else 0
    first_successes = int(first_pass.get("successes") or sum(1 for episode in first_episodes if episode.get("success")))
    total = int(first_pass.get("total_episodes") or len(first_episodes))
    merged.update(
        {
            "assist_mode": str(assist["mode"]),
            "first_attempt_successes": first_successes,
            "final_successes": final_successes,
            "successes": first_successes,
            "success_rate": float(first_successes / total) if total else 0.0,
            "final_success_rate": float(final_successes / total) if total else 0.0,
            "episodes_replanned": episodes_replanned,
            "recovered_after_replan": recovered,
            "total_attempts": len(attempts),
            "verifier_calls": len(verifier_attempts),
            "verifier_skipped": sum(1 for item in verifier_attempts if item.get("verdict") == "skipped"),
            "episodes": output_episodes,
            "attempts": attempts,
            "verifier_attempts": verifier_attempts,
            "agent_assist": {
                key: value
                for key, value in assist.items()
                if key not in {"verifier_endpoint"}
            },
        }
    )
    if retry_result is not None:
        merged["retry_result"] = {
            key: value
            for key, value in retry_result.items()
            if key not in {"episodes", "attempts", "verifier_attempts"}
        }
    return merged


def _attempt_record(episode: dict[str, Any]) -> dict[str, Any]:
    return {
        "episode_id": episode.get("episode_id"),
        "suite": episode.get("suite"),
        "task_id": episode.get("task_id"),
        "init_state_id": episode.get("init_state_id"),
        "attempt_index": int(episode.get("attempt_index") or 0),
        "policy_session_id": episode.get("policy_session_id"),
        "success": bool(episode.get("success")),
        "status": episode.get("status"),
        "num_steps": episode.get("num_steps"),
        "return_value": episode.get("return_value"),
        "mean_policy_latency_ms": episode.get("mean_policy_latency_ms"),
        "error_code": episode.get("error_code"),
        "error_message": episode.get("error_message"),
    }
