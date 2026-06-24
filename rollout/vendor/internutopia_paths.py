"""Install bundled InternUtopia layout (under ``rollout/vendor/``) onto ``sys.path``.

Vendored layout::

    rollout/vendor/
      internutopia/     # shim package (see ``internutopia/__init__.py``)
      core/             # ``internutopia.core``
      bridge/           # ``internutopia.bridge``
      internutopia_extension/  # top-level ``internutopia_extension``

External ``pythonpath`` entries in driver JSON remain supported and are
applied after this hook (they can override a system-wide install).

Robot weights / USD paths in configs use ``internutopia.macros.gm.ASSET_PATH``.
If ``INTERNUTOPIA_ASSETS_PATH`` is unset, it defaults to ``<repo>/examples`` so
``... + '/robots/g1/policy/...'`` resolves to ``asserts/robots/g1/...`` (or
``examples/robots/...`` when ``asserts/`` is absent).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_done = False


def hal_package_root() -> Path:
    """Directory that contains ``core/``, ``bridge/``, ``internutopia/`` (``rollout/vendor``)."""
    return Path(__file__).resolve().parent


def prepend_internutopia_root(root: str | Path) -> None:
    """Prepend an external InternUtopia repo (e.g. ``~/work/InternUtopia``) ahead of vendor."""
    path = str(Path(root).expanduser().resolve())
    if path and path not in sys.path:
        sys.path.insert(0, path)


def ensure_bundled_internutopia_sys_path(
    *,
    extern_root: str | Path | None = None,
) -> None:
    """Prepend external InternUtopia (optional) then ``rollout/vendor`` once."""
    global _done
    if _done:
        return
    ext = str(extern_root or os.environ.get("INTERNUTOPIA_ROOT", "")).strip()
    if ext:
        prepend_internutopia_root(ext)
    root = str(hal_package_root())
    if root not in sys.path:
        sys.path.insert(0, root)
    _done = True
