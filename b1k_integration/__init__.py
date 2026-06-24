"""BEHAVIOR-1K integration for PhyAgentOS (benchmark, OpenPI policy server, workspaces)."""

from b1k_integration.paths import (
    DEFAULT_WORKSPACE,
    DEFAULT_WORKSPACE_REL,
    PACKAGE_ROOT,
    REPO_ROOT,
    WORKSPACES_ROOT,
    ensure_import_paths,
    resolve_workspace,
)

__all__ = [
    "DEFAULT_WORKSPACE",
    "DEFAULT_WORKSPACE_REL",
    "PACKAGE_ROOT",
    "REPO_ROOT",
    "WORKSPACES_ROOT",
    "ensure_import_paths",
    "resolve_workspace",
]
