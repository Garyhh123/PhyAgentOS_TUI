"""Isaac / OmniGibson subprocess environment helpers for BEHAVIOR-1K eval."""

from __future__ import annotations

import os
from pathlib import Path

from b1k_integration.benchmark.schemas import BenchmarkSpec

# Drop Isaac kit/prebundle paths from PYTHONPATH (isaacsim, isaacsim3, isaac-sim, …).
_PYTHONPATH_DROP_MARKERS = (
    "/isaacsim",
    "/isaac-sim",
    "pip_prebundle",
    "/extscache/",
)


def behavior1k_omnigibson_paths(behavior1k_root: Path) -> list[str]:
    """Prefer official BEHAVIOR-1K ``OmniGibson/`` tree (not ``src/omnigibson`` copy)."""
    primary = (behavior1k_root / "OmniGibson").resolve()
    if primary.is_dir():
        return [str(primary)]
    fallback = (behavior1k_root / "src" / "omnigibson" / "OmniGibson").resolve()
    if fallback.is_dir():
        return [str(fallback)]
    return []


def behavior1k_python_paths(behavior1k_root: Path) -> list[str]:
    """Paths required by upstream ``eval.py`` (OmniGibson + joylo/gello)."""
    paths: list[str] = []
    joylo = (behavior1k_root / "joylo").resolve()
    if joylo.is_dir() and (joylo / "gello").is_dir():
        paths.append(str(joylo))
    fallback_joylo = (behavior1k_root / "src" / "omnigibson" / "joylo").resolve()
    if fallback_joylo.is_dir() and (fallback_joylo / "gello").is_dir():
        if str(fallback_joylo) not in paths:
            paths.append(str(fallback_joylo))
    paths.extend(behavior1k_omnigibson_paths(behavior1k_root))
    return paths


# Legacy src checkout breaks numba/coverage when placed ahead of OmniGibson/.
_SRC_OMNIGIBSON_MARKERS = ("/src/omnigibson/",)


def sanitize_pythonpath(existing: str, *, behavior1k_root: Path) -> str:
    kept: list[str] = []
    for part in existing.split(os.pathsep):
        if not part:
            continue
        if any(marker in part for marker in _PYTHONPATH_DROP_MARKERS):
            continue
        if any(marker in part for marker in _SRC_OMNIGIBSON_MARKERS):
            continue
        if part not in kept:
            kept.append(part)
    for extra in reversed(behavior1k_python_paths(behavior1k_root)):
        if extra not in kept:
            kept.insert(0, extra)
    return os.pathsep.join(kept)


_DEFAULT_ISAAC_PATH = "/home/zyserver/isaacsim3"


def isaac_runtime_python_paths(isaac_path: str) -> list[str]:
    """Isaac paths for ``import omni`` without kit stdlib or pip_prebundle."""
    root = Path(isaac_path.rstrip("/"))
    candidates = [
        root / "python_packages",
        root / "exts" / "isaacsim.simulation_app",
        root / "extsDeprecated" / "omni.isaac.kit",
        root / "kit" / "kernel" / "py",
        root / "kit" / "plugins" / "bindings-python",
    ]
    return [str(path) for path in candidates if path.is_dir()]


def _isaac_ld_library_prefix(isaac_path: str) -> list[str]:
    root = isaac_path.rstrip("/")
    candidates = [
        root,
        f"{root}/.",
        f"{root}/exts/omni.usd.schema.isaac/plugins/IsaacSensorSchema/lib",
        f"{root}/exts/omni.usd.schema.isaac/plugins/RangeSensorSchema/lib",
        f"{root}/kit",
        f"{root}/kit/kernel/plugins",
        f"{root}/kit/libs/iray",
        f"{root}/kit/plugins",
        f"{root}/kit/plugins/bindings-python",
        f"{root}/kit/plugins/carb_gfx",
        f"{root}/kit/plugins/rtx",
        f"{root}/kit/plugins/gpu.foundation",
    ]
    return [path for path in candidates if Path(path).exists()]


def _sanitize_ld_library_path(existing: str, *, isaac_path: str) -> str:
    """Drop stale Isaac install paths, then prepend the configured Isaac tree."""
    kept: list[str] = []
    for part in existing.split(os.pathsep):
        if not part:
            continue
        if "/isaacsim" in part or "/isaac-sim" in part:
            continue
        if part not in kept:
            kept.append(part)
    return os.pathsep.join(_isaac_ld_library_prefix(isaac_path) + kept)


def phyagent_repo_root() -> Path:
    """Repo root so ``import PhyAgentOS...`` and ``b1k_integration...`` work in subprocess."""
    from b1k_integration.paths import REPO_ROOT

    return REPO_ROOT


def build_behavior1k_subprocess_env(
    benchmark: BenchmarkSpec,
    behavior1k_root: Path,
    *,
    headless: bool,
) -> dict[str, str]:
    """Build env for eval.py: keep conda python clean, add Isaac runtime vars."""
    env = dict(os.environ)
    cfg = dict(benchmark.config or {})
    isaac_cfg = dict(cfg.get("isaac_env") or {})

    isaac_path = str(
        isaac_cfg.get("isaac_path")
        or (isaac_cfg.get("env") or {}).get("ISAAC_PATH")
        or _DEFAULT_ISAAC_PATH
    ).rstrip("/")

    nested = dict(isaac_cfg.get("env") or {})
    # Benchmark config wins over a polluted parent shell (e.g. ISAAC_PATH from isaacsim 5.1).
    env["ISAAC_PATH"] = nested.get("ISAAC_PATH", isaac_path)
    env["CARB_APP_PATH"] = nested.get("CARB_APP_PATH", f"{isaac_path}/kit")
    env["EXP_PATH"] = nested.get("EXP_PATH", f"{isaac_path}/apps")
    env["OMNI_KIT_ACCEPT_EULA"] = nested.get("OMNI_KIT_ACCEPT_EULA", "YES")

    env["LD_LIBRARY_PATH"] = _sanitize_ld_library_path(
        env.get("LD_LIBRARY_PATH", ""),
        isaac_path=isaac_path,
    )

    env["PYTHONPATH"] = sanitize_pythonpath(env.get("PYTHONPATH", ""), behavior1k_root=behavior1k_root)
    py_parts = [p for p in env["PYTHONPATH"].split(os.pathsep) if p]
    repo_root = str(phyagent_repo_root())
    if repo_root not in py_parts:
        py_parts.insert(0, repo_root)
    for isaac_py in isaac_runtime_python_paths(isaac_path):
        if isaac_py not in py_parts:
            py_parts.append(isaac_py)
    env["PYTHONPATH"] = os.pathsep.join(py_parts)

    if not headless:
        # Prefer the caller's active DISPLAY; BENCHMARKS.md :0 breaks when only :1 exists.
        display = env.get("DISPLAY") or isaac_cfg.get("display") or ":0"
        env["DISPLAY"] = str(display)

    return env
