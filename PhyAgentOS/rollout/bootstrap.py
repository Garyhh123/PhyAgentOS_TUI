"""Rollout process bootstrap: repo paths, bundled InternUtopia, Isaac env defaults."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

ROLLOUT_ROOT = Path(__file__).resolve().parent
PACKAGE_ROOT = ROLLOUT_ROOT.parent
REPO_ROOT = PACKAGE_ROOT.parent


def repo_root() -> Path:
    return REPO_ROOT


def resolve_repo_path(path: str | Path) -> Path:
    p = Path(path).expanduser()
    if p.is_absolute():
        return p.resolve()
    return (REPO_ROOT / p).resolve()


def ensure_repo_on_sys_path() -> None:
    for root in (str(REPO_ROOT), str(PACKAGE_ROOT)):
        if root not in sys.path:
            sys.path.insert(0, root)


def ensure_bundled_internutopia(*, extern_root: str | None = None) -> None:
    """Prepend optional external InternUtopia, then ``rollout/vendor``."""
    from rollout.vendor.internutopia_paths import ensure_bundled_internutopia_sys_path

    ensure_bundled_internutopia_sys_path(extern_root=extern_root)


def apply_isaac_env_defaults(cfg: dict[str, Any] | None, *, gui: bool) -> None:
    """Set asset + display env vars before Isaac bootstrap (OS3 layout)."""
    cfg = dict(cfg or {})
    env_block = dict(cfg.get("env") or {})

    asserts_root = resolve_repo_path("asserts")
    if asserts_root.is_dir():
        env_block.setdefault("INTERNUTOPIA_ASSETS_PATH", str(asserts_root))
    else:
        env_block.setdefault("INTERNUTOPIA_ASSETS_PATH", str(REPO_ROOT / "examples"))

    for key, value in env_block.items():
        os.environ.setdefault(str(key), str(value))

    if gui:
        os.environ.setdefault("DISPLAY", str(cfg.get("display", ":99")))
    else:
        os.environ.pop("DISPLAY", None)


def bootstrap_rollout_process(config: dict[str, Any], *, gui: bool) -> None:
    """Call once at rollout server startup before any sim import."""
    ensure_repo_on_sys_path()
    ext_root = str(config.get("internutopia_root", "") or os.environ.get("INTERNUTOPIA_ROOT", "")).strip()
    ensure_bundled_internutopia(extern_root=ext_root or None)
    apply_isaac_env_defaults(config.get("isaac_env"), gui=gui)

    isaac_cfg = config.get("isaac_env")
    if gui and isaac_cfg:
        from rollout.simulation.isaac_bootstrap import bootstrap_isaac_env

        bootstrap_isaac_env(isaac_cfg, want_gui=True)
