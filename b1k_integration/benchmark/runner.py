"""Benchmark evaluation orchestrator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from b1k_integration.benchmark.backends.behavior1k_native import run_behavior1k_task
from b1k_integration.benchmark.registry import BenchmarkRegistry, PolicyRegistry
from b1k_integration.benchmark.schemas import BenchmarkEpisodeResult, BenchmarkRunReport
from b1k_integration.benchmark.session_builder import (
    build_benchmark_sessions,
    merge_sessions_document,
    stamp_run_id,
    write_sessions_document,
)
from b1k_integration.benchmark.task_sources.behavior1k import (
    list_tasks,
    resolve_behavior1k_root,
)
from PhyAgentOS.runtime.schemas import SessionsDocument, SessionStatus
from PhyAgentOS.runtime.state_io.markdown_yaml import read_yaml_block
from PhyAgentOS.runtime.state_io.workspace_paths import RuntimeWorkspacePaths
from PhyAgentOS.runtime.watchdog.errors import PolicyConnectionError, SchemaValidationError
from PhyAgentOS.runtime.watchdog.supervisor import WatchdogSupervisor


class BenchmarkRunner:
    """Select benchmark suite + policy, then run or materialize evaluation sessions."""

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.benchmark_registry = BenchmarkRegistry(self.workspace)
        self.policy_registry = PolicyRegistry(self.workspace)
        self.paths = RuntimeWorkspacePaths.from_path(self.workspace)

    def list_benchmarks(self) -> list[str]:
        return [b.id for b in self.benchmark_registry.load().benchmarks if b.enabled]

    def list_policies(self) -> list[dict[str, Any]]:
        return [
            {
                "id": p.id,
                "name": p.name,
                "status": p.status,
                "policy_endpoint": p.policy_endpoint,
            }
            for p in self.policy_registry.load().policies
        ]

    def list_suite_tasks(
        self,
        *,
        benchmark_id: str,
        suite_id: str,
        task_names: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        benchmark = self.benchmark_registry.get(benchmark_id)
        suite = self._resolve_suite(benchmark, suite_id)
        b1k_root = resolve_behavior1k_root(benchmark.behavior1k_root)
        tasks = list_tasks(
            task_source=suite.task_source,
            behavior1k_root=b1k_root,
            task_names=task_names or (suite.task_names or None),
        )
        return [
            {"name": t.name, "index": t.index, "instruction": t.instruction}
            for t in tasks
        ]

    def prepare_sessions(
        self,
        *,
        benchmark_id: str,
        suite_id: str,
        policy_id: str,
        task_names: list[str] | None = None,
        instance_ids: list[int] | None = None,
        run_id: str | None = None,
        max_steps: int = 200,
    ) -> str:
        benchmark = self.benchmark_registry.get(benchmark_id)
        suite = self._resolve_suite(benchmark, suite_id)
        policy = self.policy_registry.get(policy_id)
        if policy.status == "reserved":
            raise PolicyConnectionError(
                f"policy {policy_id!r} is reserved: {policy.notes or 'download and register first'}"
            )
        b1k_root = resolve_behavior1k_root(benchmark.behavior1k_root)
        tasks = list_tasks(
            task_source=suite.task_source,
            behavior1k_root=b1k_root,
            task_names=task_names or (suite.task_names or None),
        )
        inst = instance_ids if instance_ids is not None else list(suite.default_instance_ids)
        rid = run_id or stamp_run_id()
        sessions = build_benchmark_sessions(
            benchmark=benchmark,
            suite=suite,
            policy=policy,
            tasks=tasks,
            instance_ids=inst,
            run_id=rid,
            max_steps=max_steps,
        )
        doc = merge_sessions_document(self.paths.sessions, sessions, replace_run_id=rid)
        write_sessions_document(self.paths.sessions, doc)
        return rid

    def run(
        self,
        *,
        benchmark_id: str,
        suite_id: str,
        policy_id: str,
        task_names: list[str] | None = None,
        instance_ids: list[int] | None = None,
        run_id: str | None = None,
        headless: bool = False,
        write_video: bool = False,
        dry_run: bool = False,
        use_watchdog: bool = False,
        environment_workspace: str | Path | None = None,
        behavior1k_python: str | None = None,
    ) -> BenchmarkRunReport:
        benchmark = self.benchmark_registry.get(benchmark_id)
        suite = self._resolve_suite(benchmark, suite_id)
        policy = self.policy_registry.get(policy_id)
        if policy.status == "reserved" and not dry_run:
            raise PolicyConnectionError(
                f"policy {policy_id!r} is reserved: {policy.notes or 'download and register first'}"
            )

        b1k_root = resolve_behavior1k_root(benchmark.behavior1k_root)
        tasks = list_tasks(
            task_source=suite.task_source,
            behavior1k_root=b1k_root,
            task_names=task_names or (suite.task_names or None),
        )
        inst = instance_ids if instance_ids is not None else list(suite.default_instance_ids)
        rid = run_id or stamp_run_id()
        log_root = self.workspace / "artifacts" / "benchmark" / rid
        log_root.mkdir(parents=True, exist_ok=True)

        episodes = []
        backend = benchmark.execution_backend

        if use_watchdog or backend == "runtime_watchdog":
            rid = self.prepare_sessions(
                benchmark_id=benchmark_id,
                suite_id=suite_id,
                policy_id=policy_id,
                task_names=task_names,
                instance_ids=inst,
                run_id=rid,
            )
            if dry_run:
                doc = SessionsDocument.model_validate(read_yaml_block(self.paths.sessions))
                for session in doc.sessions:
                    if session.benchmark and session.benchmark.run_id == rid:
                        episodes.append(
                            BenchmarkEpisodeResult(
                                task_name=session.benchmark.task_name or "",
                                task_index=session.benchmark.task_index,
                                instance_id=int(session.benchmark.instance_id or 0),
                                metadata={"session_id": session.session_id},
                            )
                        )
                backend = "runtime_watchdog"
            else:
                supervisor = WatchdogSupervisor(
                    self.workspace,
                    environment_workspace=environment_workspace,
                )
                doc = SessionsDocument.model_validate(read_yaml_block(self.paths.sessions))
                for session in doc.sessions:
                    if not session.benchmark or session.benchmark.run_id != rid:
                        continue
                    if session.status != SessionStatus.PENDING:
                        continue
                    ok = supervisor.run_once(session_id=session.session_id)
                    result = session.result
                    episodes.append(
                        BenchmarkEpisodeResult(
                            task_name=session.benchmark.task_name or "",
                            task_index=session.benchmark.task_index,
                            instance_id=int(session.benchmark.instance_id or 0),
                            success=bool(result.success) if result.success is not None else ok,
                            num_steps=result.num_steps,
                            metadata={"session_id": session.session_id},
                        )
                    )
                backend = "runtime_watchdog"
        else:
            for task in tasks:
                episodes.extend(
                    run_behavior1k_task(
                        benchmark=benchmark,
                        behavior1k_root=b1k_root,
                        policy=policy,
                        task=task,
                        instance_ids=inst,
                        log_root=log_root,
                        headless=headless,
                        write_video=write_video,
                        dry_run=dry_run,
                        behavior1k_python=behavior1k_python,
                    )
                )

        report = self._report(
            rid,
            benchmark_id,
            suite_id,
            policy_id,
            backend,
            episodes,
            log_root,
            dry_run=dry_run,
        )
        summary_path = log_root / "summary.json"
        summary_path.write_text(
            report.model_dump_json(indent=2),
            encoding="utf-8",
        )
        report.summary_path = str(summary_path)
        return report

    @staticmethod
    def _report(
        run_id: str,
        benchmark_id: str,
        suite_id: str,
        policy_id: str,
        backend: str,
        episodes: list,
        log_root: Path,
        *,
        dry_run: bool,
    ) -> BenchmarkRunReport:
        succeeded = [e for e in episodes if e.success is True]
        q_scores = [e.q_score for e in episodes if e.q_score is not None]
        tasks = {e.task_name for e in episodes}
        report = BenchmarkRunReport(
            run_id=run_id,
            benchmark_id=benchmark_id,
            suite_id=suite_id,
            policy_id=policy_id,
            backend=backend,
            tasks_total=len(tasks),
            episodes_total=len(episodes),
            episodes_succeeded=len(succeeded),
            success_rate=(len(succeeded) / len(episodes)) if episodes else None,
            mean_q_score=(sum(q_scores) / len(q_scores)) if q_scores else None,
            episodes=episodes,
            metadata={"log_root": str(log_root), "dry_run": dry_run},
        )
        return report

    @staticmethod
    def _resolve_suite(benchmark, suite_id: str) -> BenchmarkSuiteSpec:
        for suite in benchmark.suites:
            if suite.id == suite_id:
                return suite
        raise SchemaValidationError(
            f"suite {suite_id!r} not found in benchmark {benchmark.id!r}"
        )
