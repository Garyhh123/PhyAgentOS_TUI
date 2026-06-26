"""Launch the PiperGo2 manipulation rollout WebSocket server."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _bootstrap_process(config: dict, gui: bool) -> None:
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from rollout.bootstrap import bootstrap_rollout_process

    bootstrap_rollout_process(config, gui=gui)


def main() -> int:
    parser = argparse.ArgumentParser(description="PhyAgentOS Isaac Sim rollout server")
    default_config = _REPO_ROOT / "rollout/configs/pipergo2_manipulation.json"
    parser.add_argument(
        "--config",
        type=str,
        default=str(default_config),
        help="Runner JSON config (default: rollout/configs/pipergo2_manipulation.json)",
    )
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--gui", action="store_true", help="Open Isaac Sim GUI (sets force_gui)")
    parser.add_argument("--headless", action="store_true", help="Force headless sim")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config_path = Path(args.config).expanduser().resolve()
    with config_path.open(encoding="utf-8") as handle:
        config = json.load(handle)

    gui = bool(args.gui) and not args.headless
    _bootstrap_process(config, gui)

    from rollout.server import serve_blocking

    try:
        serve_blocking(args.host, args.port, config, gui=gui)
    except KeyboardInterrupt:
        print("\n[rollout] stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
