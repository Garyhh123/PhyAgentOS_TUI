"""Shared sys.path bootstrap for b1k_integration CLI scripts."""

from __future__ import annotations

import sys
from pathlib import Path

B1K_PKG_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = B1K_PKG_ROOT.parent


def ensure_repo_on_path() -> None:
    root = str(REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
