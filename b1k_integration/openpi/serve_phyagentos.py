"""BEHAVIOR-1K policy server entrypoint for PhyAgentOS (no /scr dataset required).

Same as upstream ``scripts/serve_b1k.py``, but loads the language prompt from
``BEHAVIOR-1K/docs/challenge/task_data.json`` instead of
``BehaviorLerobotDatasetMetadata`` (which expects LeRobot demo files on disk).

Run inside the b1k-baselines openpi uv venv (``uv sync`` only — OmniGibson not required).
Started via ``b1k_integration/scripts/start_b1k_openpi_policy_server.sh``.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import socket
import sys
from pathlib import Path

import tyro

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from b1k_integration.openpi.omnigibson_shim import install_omnigibson_eval_utils_shim

install_omnigibson_eval_utils_shim()

from b1k_integration.openpi.websocket_policy_server import WebsocketPolicyServer
from openpi.policies import policy as _policy
from openpi.policies import policy_config as _policy_config
from openpi.shared.eval_b1k_wrapper import B1KPolicyWrapper
from openpi.training import config as _config


@dataclasses.dataclass
class Checkpoint:
    config: str
    dir: str


@dataclasses.dataclass
class Default:
    pass


@dataclasses.dataclass
class Args:
    default_prompt: str | None = None
    behavior1k_root: str | None = None
    task_name: str = "turning_on_radio"
    port: int = 8000
    record: bool = False
    policy: Checkpoint | Default = dataclasses.field(default_factory=Default)


def _resolve_behavior1k_root(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if path.is_dir():
            return path
    env_root = __import__("os").environ.get("BEHAVIOR1K_ROOT")
    if env_root:
        path = Path(env_root).expanduser().resolve()
        if path.is_dir():
            return path
    default = Path("/home/zyserver/work/BEHAVIOR-1K")
    if default.is_dir():
        return default.resolve()
    raise FileNotFoundError("BEHAVIOR-1K root not found; set --behavior1k-root or BEHAVIOR1K_ROOT")


def _task_prompt(behavior1k_root: Path, task_name: str) -> str:
    task_data_path = behavior1k_root / "docs" / "challenge" / "task_data.json"
    if not task_data_path.is_file():
        raise FileNotFoundError(f"task metadata not found: {task_data_path}")
    payload = json.loads(task_data_path.read_text(encoding="utf-8"))
    tasks = payload.get("tasks") or []
    for item in tasks:
        if isinstance(item, dict) and item.get("id") == task_name:
            instruction = item.get("instruction") or item.get("name")
            if instruction:
                return str(instruction)
    raise ValueError(f"task {task_name!r} not found in {task_data_path}")


def create_policy(args: Args) -> _policy.Policy:
    if isinstance(args.policy, Default):
        raise ValueError("policy checkpoint is required: policy:checkpoint --policy.config=... --policy.dir=...")
    return _policy_config.create_trained_policy(
        _config.get_config(args.policy.config),
        args.policy.dir,
        default_prompt=args.default_prompt,
    )


def main(args: Args) -> None:
    b1k_root = _resolve_behavior1k_root(args.behavior1k_root)
    prompt = args.default_prompt or _task_prompt(b1k_root, args.task_name)
    logging.info("Using prompt: %s", prompt)

    policy = create_policy(args)
    policy_metadata = policy.metadata
    if args.record:
        policy = _policy.PolicyRecorder(policy, "policy_records")
    policy = B1KPolicyWrapper(policy, text_prompt=prompt)

    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    logging.info("Creating server (host: %s, ip: %s)", hostname, local_ip)

    server = WebsocketPolicyServer(
        policy=policy,
        host="0.0.0.0",
        port=args.port,
        metadata=policy_metadata,
    )
    server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, force=True)
    main(tyro.cli(Args))
