"""Repository layout helpers (package root, rollout configs, integration workspaces)."""

from __future__ import annotations

import sys
from pathlib import Path

# Python package: .../PhyAgentOS/PhyAgentOS
PACKAGE_ROOT = Path(__file__).resolve().parent
# Git / project root: .../PhyAgentOS
REPO_ROOT = PACKAGE_ROOT.parent

ROLLOUT_ROOT = REPO_ROOT / "rollout"
WORKSPACES_ROOT = REPO_ROOT / "workspaces"
B1K_INTEGRATION_ROOT = REPO_ROOT / "b1k_integration"


def ensure_import_paths() -> None:
    """Prepend repo root so ``PhyAgentOS`` and ``rollout`` import cleanly."""
    root = str(REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (REPO_ROOT / candidate).resolve()


def rollout_config(name: str) -> Path:
    """Return ``rollout/configs/<name>`` under the repo root."""
    return (ROLLOUT_ROOT / "configs" / name).resolve()


def workspace_path(name: str) -> Path:
    """Return ``workspaces/<name>`` under the repo root."""
    return (WORKSPACES_ROOT / name).resolve()


def resolve_workspace(path: str | Path) -> Path:
    """Resolve CLI workspace argument (absolute, cwd-relative, or under workspaces/)."""
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    if candidate.exists():
        return candidate.resolve()
    named = workspace_path(candidate.name if candidate.name else str(candidate))
    if named.exists():
        return named.resolve()
    return (REPO_ROOT / candidate).resolve()
