"""Layout helpers for the BEHAVIOR-1K integration package (sibling of ``PhyAgentOS/``)."""

from __future__ import annotations

import sys
from pathlib import Path

# .../PhyAgentOS/b1k_integration
PACKAGE_ROOT = Path(__file__).resolve().parent
# Git / project root: .../PhyAgentOS
REPO_ROOT = PACKAGE_ROOT.parent
WORKSPACES_ROOT = PACKAGE_ROOT / "workspaces"
DEFAULT_WORKSPACE = WORKSPACES_ROOT / "behavior1k_eval"
DEFAULT_WORKSPACE_REL = "b1k_integration/workspaces/behavior1k_eval"


def ensure_import_paths() -> None:
    """Prepend repo root so ``PhyAgentOS`` and ``b1k_integration`` import cleanly."""
    root = str(REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def resolve_workspace(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    if candidate.exists():
        return candidate.resolve()
    named = WORKSPACES_ROOT / candidate.name
    if named.exists():
        return named.resolve()
    return (REPO_ROOT / candidate).resolve()
