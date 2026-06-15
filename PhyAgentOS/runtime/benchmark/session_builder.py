"""Build runtime SESSIONS.md entries from benchmark selections."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from PhyAgentOS.runtime.benchmark.schemas import (
    BenchmarkPolicySpec,
    BenchmarkSpec,
    BenchmarkSuiteSpec,
    BenchmarkTaskSpec,
)
from PhyAgentOS.runtime.schemas import SessionExecution, SessionResult, SessionRetry, SessionRouting, SessionSpec, SessionStatus, SessionsDocument
from PhyAgentOS.runtime.schemas.session import SessionBenchmarkMeta, SessionTimeouts


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip()).strip("_").lower()
    return slug[:48] or "task"


def build_benchmark_sessions(
    *,
    benchmark: BenchmarkSpec,
    suite: BenchmarkSuiteSpec,
    policy: BenchmarkPolicySpec,
    tasks: list[BenchmarkTaskSpec],
    instance_ids: list[int],
    run_id: str,
    max_steps: int = 200,
) -> list[SessionSpec]:
    sessions: list[SessionSpec] = []
    for task in tasks:
        for instance_id in instance_ids:
            sid = f"sess_b1k_{_slug(task.name)}_{instance_id}_{_slug(run_id)}"
            sessions.append(
                SessionSpec(
                    session_id=sid,
                    goal_id=f"goal_b1k_{_slug(task.name)}_{instance_id}",
                    target_ref=benchmark.default_target_ref,
                    skillruntime_ref=benchmark.default_skillruntime_ref or benchmark.default_skill_ref,
                    task_description=task.instruction or task.name.replace("_", " "),
                    status=SessionStatus.PENDING,
                    priority="normal",
                    routing=SessionRouting(
                        target_endpoint=str(
                            benchmark.config.get("target_endpoint") or "targetws://127.0.0.1:9004"
                        ),
                        policy_endpoint=policy.policy_endpoint,
                    ),
                    execution=SessionExecution(
                        max_steps=max_steps,
                        replan_every=1,
                        action_chunk_mode="open_loop",
                        steps=[
                            {
                                "mode": "benchmark",
                                "benchmark_id": benchmark.id,
                                "task_name": task.name,
                                "instance_id": instance_id,
                            }
                        ],
                    ),
                    benchmark=SessionBenchmarkMeta(
                        benchmark_id=benchmark.id,
                        suite_id=suite.id,
                        task_name=task.name,
                        task_index=task.index,
                        instance_id=instance_id,
                        policy_id=policy.id,
                        run_id=run_id,
                    ),
                    result=SessionResult(),
                )
            )
    return sessions


def merge_sessions_document(
    workspace_sessions_path: Any,
    new_sessions: list[SessionSpec],
    *,
    replace_run_id: str | None = None,
) -> SessionsDocument:
    from pathlib import Path

    from PhyAgentOS.runtime.state_io.markdown_yaml import read_yaml_block

    path = Path(workspace_sessions_path)
    if path.is_file():
        payload = read_yaml_block(path)
        doc = SessionsDocument.model_validate(payload)
        kept = [
            s
            for s in doc.sessions
            if not (
                replace_run_id
                and s.benchmark
                and s.benchmark.run_id == replace_run_id
            )
        ]
    else:
        kept = []
    merged = kept + new_sessions
    return SessionsDocument(sessions=merged)


def write_sessions_document(path: Any, document: SessionsDocument) -> None:
    from pathlib import Path

    from PhyAgentOS.runtime.state_io.markdown_yaml import write_yaml_block

    write_yaml_block(
        Path(path),
        "Runtime Sessions",
        document.model_dump(mode="json", exclude_none=True),
    )


def stamp_run_id(prefix: str = "b1k") -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}_{ts}"
