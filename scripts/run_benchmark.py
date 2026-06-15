#!/usr/bin/env python
"""Run PhyAgentOS benchmark evaluation (task suite + policy selection)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if sys.version_info < (3, 11):
    raise SystemExit(
        "run_benchmark.py must run from the paos conda env (Python 3.11+).\n"
        "The behavior env (Python 3.10) is only for eval.py subprocess:\n"
        "  conda activate paos\n"
        "  export BEHAVIOR1K_PYTHON=$HOME/miniconda3/envs/behavior/bin/python\n"
        "  python scripts/run_benchmark.py ..."
    )

from PhyAgentOS.runtime.benchmark.runner import BenchmarkRunner


def _split_csv(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [part.strip() for part in raw.split(",") if part.strip()]


def _split_int_csv(raw: str | None) -> list[int] | None:
    parts = _split_csv(raw)
    if parts is None:
        return None
    return [int(x) for x in parts]


def main() -> int:
    parser = argparse.ArgumentParser(description="PhyAgentOS benchmark runner")
    parser.add_argument(
        "--workspace",
        default="PhyAgentOS/workspaces/behavior1k_eval",
        help="Benchmark workspace (BENCHMARKS.md + POLICIES.md)",
    )
    parser.add_argument("--list-benchmarks", action="store_true")
    parser.add_argument("--list-policies", action="store_true")
    parser.add_argument("--list-tasks", action="store_true")
    parser.add_argument("--benchmark", default="behavior-1k", help="Benchmark id from BENCHMARKS.md")
    parser.add_argument("--suite", default="smoke3", help="Task suite id")
    parser.add_argument("--policy", default="dummy_baseline", help="Policy id from POLICIES.md")
    parser.add_argument("--tasks", help="Comma-separated task names (override suite list)")
    parser.add_argument("--instance-ids", help="Comma-separated instance ids, e.g. 0,1")
    parser.add_argument("--run-id", help="Optional run id tag")
    parser.add_argument("--dry-run", action="store_true", help="Print planned commands/sessions only")
    parser.add_argument("--prepare-sessions", action="store_true", help="Write SESSIONS.md only")
    parser.add_argument(
        "--use-watchdog",
        action="store_true",
        help="Materialize SESSIONS.md and run runtime watchdog backend",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run without Isaac Sim GUI (default: show GUI)",
    )
    parser.add_argument(
        "--b1k-python",
        help="Python for BEHAVIOR-1K eval.py subprocess (default: BEHAVIOR1K_PYTHON or behavior conda)",
    )
    parser.add_argument("--write-video", action="store_true")
    parser.add_argument(
        "--json-summary",
        action="store_true",
        help="Print full JSON report to stdout (default in --headless mode)",
    )
    parser.add_argument(
        "--environment-workspace",
        help="Shared ENVIRONMENT workspace for watchdog backend",
    )
    args = parser.parse_args()

    runner = BenchmarkRunner(args.workspace)

    if args.list_benchmarks:
        print(json.dumps(runner.list_benchmarks(), indent=2))
        return 0
    if args.list_policies:
        print(json.dumps(runner.list_policies(), indent=2, ensure_ascii=False))
        return 0
    if args.list_tasks:
        tasks = runner.list_suite_tasks(
            benchmark_id=args.benchmark,
            suite_id=args.suite,
            task_names=_split_csv(args.tasks),
        )
        print(json.dumps(tasks, indent=2, ensure_ascii=False))
        return 0

    task_names = _split_csv(args.tasks)
    instance_ids = _split_int_csv(args.instance_ids)
    headless = args.headless

    if args.prepare_sessions:
        run_id = runner.prepare_sessions(
            benchmark_id=args.benchmark,
            suite_id=args.suite,
            policy_id=args.policy,
            task_names=task_names,
            instance_ids=instance_ids,
            run_id=args.run_id,
        )
        print(f"[benchmark] prepared SESSIONS.md run_id={run_id}")
        return 0

    report = runner.run(
        benchmark_id=args.benchmark,
        suite_id=args.suite,
        policy_id=args.policy,
        task_names=task_names,
        instance_ids=instance_ids,
        run_id=args.run_id,
        headless=headless,
        write_video=args.write_video,
        dry_run=args.dry_run,
        use_watchdog=args.use_watchdog,
        environment_workspace=args.environment_workspace,
        behavior1k_python=args.b1k_python,
    )
    if args.json_summary or headless:
        print(json.dumps(report.model_dump(), indent=2, ensure_ascii=False))
    else:
        print(
            f"[benchmark] done run_id={report.run_id} "
            f"success_rate={report.success_rate} "
            f"episodes={report.episodes_succeeded}/{report.episodes_total}",
            flush=True,
        )
    if report.summary_path:
        print(f"[benchmark] summary written to {report.summary_path}")
    return 0 if report.episodes_total == 0 or report.episodes_succeeded is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
