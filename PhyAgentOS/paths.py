"""Repository layout helpers (package root, rollout configs, benchmark workspaces)."""

from __future__ import annotations

import sys
from pathlib import Path

# Inner Python package directory: .../PhyAgentOS/PhyAgentOS
PACKAGE_ROOT = Path(__file__).resolve().parent
# Git / project root: .../PhyAgentOS
REPO_ROOT = PACKAGE_ROOT.parent

ROLLOUT_ROOT = PACKAGE_ROOT / "rollout"
WORKSPACES_ROOT = PACKAGE_ROOT / "workspaces"


def ensure_import_paths() -> None:
    """Prepend repo + package roots so ``PhyAgentOS`` and ``rollout`` import cleanly."""
    for root in (str(REPO_ROOT), str(PACKAGE_ROOT)):
        if root not in sys.path:
            sys.path.insert(0, root)


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (REPO_ROOT / candidate).resolve()


def rollout_config(name: str) -> Path:
    """Return ``PhyAgentOS/rollout/configs/<name>``."""
    return (ROLLOUT_ROOT / "configs" / name).resolve()


def workspace_path(name: str) -> Path:
    """Return ``PhyAgentOS/workspaces/<name>``."""
    return (WORKSPACES_ROOT / name).resolve()


def resolve_workspace(path: str | Path) -> Path:
    """Resolve CLI workspace argument (absolute, cwd-relative, or under workspaces/)."""
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    if candidate.exists():
        return candidate.resolve()
    under_pkg = PACKAGE_ROOT / candidate
    if under_pkg.exists():
        return under_pkg.resolve()
    named = workspace_path(candidate.name if candidate.name else str(candidate))
    if named.exists():
        return named.resolve()
    return (REPO_ROOT / candidate).resolve()
