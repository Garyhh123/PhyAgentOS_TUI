"""Execute BEHAVIOR-1K evaluation via upstream ``eval.py`` subprocess."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from PhyAgentOS.runtime.benchmark.backends.behavior1k_env import build_behavior1k_subprocess_env
from PhyAgentOS.runtime.benchmark.schemas import (
    BenchmarkEpisodeResult,
    BenchmarkPolicySpec,
    BenchmarkSpec,
    BenchmarkTaskSpec,
)
from PhyAgentOS.runtime.watchdog.errors import PolicyConnectionError


class Behavior1KEnvironmentError(RuntimeError):
    """BEHAVIOR-1K/OmniGibson Python environment is misconfigured."""


def resolve_behavior1k_python(
    benchmark: BenchmarkSpec,
    override: str | None = None,
) -> str:
    """Python for BEHAVIOR eval.py subprocess (driver may stay in paos)."""
    candidates: list[str] = []
    if override:
        candidates.append(override.strip())
    env_py = os.environ.get("BEHAVIOR1K_PYTHON", "").strip()
    if env_py:
        candidates.append(env_py)
    cfg_py = str((benchmark.config or {}).get("behavior1k_python", "")).strip()
    if cfg_py:
        candidates.append(cfg_py)
    for name in ("behavior", "omnigibson", "b1k"):
        guess = Path.home() / "miniconda3" / "envs" / name / "bin" / "python"
        if guess.is_file():
            candidates.append(str(guess))

    seen: set[str] = set()
    for raw in candidates:
        path = str(Path(raw).expanduser())
        if not path or path in seen:
            continue
        seen.add(path)
        if Path(path).is_file() or shutil.which(path):
            return path
    return sys.executable


def verify_behavior1k_python(
    python: str, *, benchmark: BenchmarkSpec, behavior1k_root: Path
) -> None:
    env = build_behavior1k_subprocess_env(benchmark, behavior1k_root, headless=True)
    proc = subprocess.run(
        [
            python,
            "-c",
            "import hydra, omnigibson, gello, pandas, cv2, av, torch, omni, tree, msgpack; "
            "from google.oauth2.service_account import Credentials; "
            "from omnigibson.learning.policies import LocalPolicy",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        return
    hint = (
        f"Python {python!r} cannot import eval.py dependencies.\n"
        "Orchestrator runs in paos; eval subprocess uses behavior conda — install packages there, not paos:\n"
        "  conda activate behavior\n"
        "  python -m pip install 'coverage>=7.6' pandas google-auth dm-tree msgpack\n"
        "  (do NOT pip install the unrelated PyPI package named 'google')\n"
        "  cd $BEHAVIOR1K_ROOT/joylo && python -m pip install -e .\n"
        "Then from paos: export BEHAVIOR1K_PYTHON=$HOME/miniconda3/envs/behavior/bin/python\n"
        "If scipy/torch import from isaacsim/exts/.../pip_prebundle, unset polluted PYTHONPATH\n"
        "  (do not source isaacsim/setup_python_env.sh in the paos shell)."
    )
    detail = (proc.stderr or proc.stdout or "").strip()
    raise Behavior1KEnvironmentError(f"{hint}\n{detail}")


def _parse_host_port(endpoint: str) -> tuple[str, int]:
    parsed = urlparse(endpoint)
    host = parsed.hostname or "127.0.0.1"
    port = int(parsed.port or 8000)
    return host, port


def policy_hydra_overrides(policy: BenchmarkPolicySpec) -> list[str]:
    if policy.hydra_policy:
        overrides = [f"policy={policy.hydra_policy}"]
    else:
        parsed = urlparse(policy.policy_endpoint)
        scheme = parsed.scheme
        if scheme == "dummy":
            overrides = ["policy=local"]
        elif scheme in ("b1k-ws", "openpi", "websocket"):
            host, port = _parse_host_port(policy.policy_endpoint)
            overrides = [
                "policy=websocket",
                f"model.host={host}",
                f"model.port={port}",
            ]
        elif scheme == "reserved":
            raise PolicyConnectionError(
                f"policy {policy.id!r} is reserved and not installed yet: {policy.notes or policy.policy_endpoint}"
            )
        else:
            raise PolicyConnectionError(f"unsupported benchmark policy endpoint: {policy.policy_endpoint}")

    for key, value in policy.hydra_overrides.items():
        if value is None:
            continue
        overrides.append(f"{key}={value}")
    return overrides


def run_behavior1k_task(
    *,
    benchmark: BenchmarkSpec,
    behavior1k_root: Path,
    policy: BenchmarkPolicySpec,
    task: BenchmarkTaskSpec,
    instance_ids: list[int],
    log_root: Path,
    headless: bool = False,
    write_video: bool = False,
    dry_run: bool = False,
    behavior1k_python: str | None = None,
) -> list[BenchmarkEpisodeResult]:
    eval_script = behavior1k_root / benchmark.eval_script
    if not eval_script.is_file():
        raise FileNotFoundError(f"BEHAVIOR-1K eval script not found: {eval_script}")

    python = resolve_behavior1k_python(benchmark, behavior1k_python)
    if not dry_run:
        verify_behavior1k_python(python, benchmark=benchmark, behavior1k_root=behavior1k_root)

    task_log = log_root / task.name
    task_log.mkdir(parents=True, exist_ok=True)
    results: list[BenchmarkEpisodeResult] = []

    for instance_id in instance_ids:
        cfg = dict(benchmark.config or {})
        max_steps = int(cfg.get("max_steps", 200))
        overrides = [
            f"task.name={task.name}",
            f"log_path={task_log / f'inst_{instance_id}'}",
            f"eval_instance_ids=[{instance_id}]",
            f"headless={str(headless).lower()}",
            f"write_video={str(write_video).lower()}",
            f"max_steps={max_steps}",
            *policy_hydra_overrides(policy),
        ]
        cmd = [python, str(eval_script), *overrides]
        if dry_run:
            results.append(
                BenchmarkEpisodeResult(
                    task_name=task.name,
                    task_index=task.index,
                    instance_id=instance_id,
                    log_path=str(task_log / f"inst_{instance_id}"),
                    metadata={"command": cmd, "python": python, "headless": headless},
                )
            )
            continue

        print(
            f"[benchmark] task={task.name} instance={instance_id} "
            f"headless={headless} python={python}",
            flush=True,
        )
        print(f"[benchmark] cmd: {' '.join(cmd)}", flush=True)

        env = build_behavior1k_subprocess_env(
            benchmark, behavior1k_root, headless=headless
        )

        # Stream eval logs live; headless Isaac startup can take 10+ minutes with no output if captured.
        proc = subprocess.run(
            cmd,
            cwd=str(behavior1k_root),
            env=env,
        )
        stdout_tail = ""
        stderr_tail = ""

        metrics_path = task_log / f"inst_{instance_id}" / "metrics"
        success, q_score = _read_latest_metrics(metrics_path, task.name, instance_id)
        err = None
        if proc.returncode != 0:
            err = stderr_tail or stdout_tail or "eval.py failed"
        results.append(
            BenchmarkEpisodeResult(
                task_name=task.name,
                task_index=task.index,
                instance_id=instance_id,
                success=success if proc.returncode == 0 else False,
                q_score=q_score,
                log_path=str(task_log / f"inst_{instance_id}"),
                metrics_path=str(metrics_path),
                error_message=err,
                metadata={
                    "returncode": proc.returncode,
                    "python": python,
                    "headless": headless,
                },
            )
        )
    return results


def _read_latest_metrics(
    metrics_dir: Path, task_name: str, instance_id: int
) -> tuple[bool | None, float | None]:
    if not metrics_dir.is_dir():
        return None, None
    pattern = f"{task_name}_{instance_id}_"
    files = sorted(metrics_dir.glob(f"{pattern}*.json"))
    if not files:
        return None, None
    with files[-1].open(encoding="utf-8") as handle:
        payload = json.load(handle)
    success = payload.get("success")
    if success is None:
        success = payload.get("task_success")
    q_score = payload.get("q_score")
    if q_score is None:
        q_score = payload.get("final_q_score")
    return bool(success) if success is not None else None, float(q_score) if q_score is not None else None
