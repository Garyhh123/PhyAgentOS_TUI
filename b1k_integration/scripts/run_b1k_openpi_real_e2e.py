"""External acceptance: B1K OpenPI policy server -> B1K TargetWS via Watchdog.

Assumes two servers are already running:
  - B1K pi0 policy server (serve_b1k.py): b1k-ws://127.0.0.1:8000
  - B1K TargetWS simulation: targetws://127.0.0.1:9004

This script writes a minimal runtime workspace and executes one Watchdog pass.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from b1k_integration.scripts._bootstrap import ensure_repo_on_path

ensure_repo_on_path()

os.environ.setdefault("no_proxy", "*")
os.environ.setdefault("NO_PROXY", "*")

from b1k_integration.benchmark.task_sources.behavior1k import (
    load_task_instructions,
    resolve_behavior1k_root,
)
from b1k_integration.paths import DEFAULT_WORKSPACE_REL, REPO_ROOT
from PhyAgentOS.runtime.state_io.markdown_yaml import read_yaml_block, write_yaml_block
from PhyAgentOS.runtime.watchdog.supervisor import WatchdogSupervisor

DEFAULT_BEHAVIOR1K_ROOT = "/home/zyserver/work/BEHAVIOR-1K"


def _task_description(task_name: str, behavior1k_root: Path) -> str:
    instructions = load_task_instructions(behavior1k_root)
    return instructions.get(task_name) or task_name.replace("_", " ")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one real B1K/pi0 session through WatchdogSupervisor")
    parser.add_argument("--workspace", default="/tmp/phyagentos_b1k_openpi_e2e")
    parser.add_argument("--policy-endpoint", default="b1k-ws://127.0.0.1:8000")
    parser.add_argument("--target-endpoint", default="targetws://127.0.0.1:9004")
    parser.add_argument("--task-name", default="turning_on_radio")
    parser.add_argument("--instance-id", type=int, default=0)
    parser.add_argument("--task-description", default=None)
    parser.add_argument("--max-steps", type=int, default=200, help="Watchdog policy loop step limit")
    parser.add_argument(
        "--env-max-steps",
        type=int,
        default=None,
        help="OmniGibson episode horizon (default: max(max-steps, 500); separate from --max-steps)",
    )
    parser.add_argument("--replan-every-steps", type=int, default=1)
    parser.add_argument("--behavior1k-root", default=DEFAULT_BEHAVIOR1K_ROOT)
    args = parser.parse_args()

    b1k_root = resolve_behavior1k_root(args.behavior1k_root)
    task_description = args.task_description or _task_description(args.task_name, b1k_root)

    workspace = Path(args.workspace).expanduser()
    _write_workspace(workspace, args, task_description)
    supervisor = WatchdogSupervisor(workspace)
    ran = supervisor.run_once()
    if not ran:
        print("No pending runtime session was executed.")
        return 1

    sessions_doc = read_yaml_block(workspace / "SESSIONS.md")
    session = sessions_doc["sessions"][0]
    result = session.get("result", {})
    print("=== RESULT ===")
    print("status:", session.get("status"))
    print("success:", result.get("success"))
    print("num_steps:", result.get("num_steps"))
    print("artifact_dir:", result.get("artifact_dir"))
    if result.get("error_message"):
        print("error:", result.get("error_message"))
    if result.get("num_steps") and not result.get("success"):
        print("note: status=failed with num_steps>0 means the loop ran but the task was not completed")
    artifact_dir = result.get("artifact_dir")
    if artifact_dir:
        episode_path = workspace / artifact_dir / "episode.json"
        if episode_path.exists():
            payload = json.loads(episode_path.read_text(encoding="utf-8"))
            print("benchmark:", json.dumps(payload.get("benchmark"), ensure_ascii=False, sort_keys=True))
    return 0 if result.get("success") else 2


def _write_workspace(workspace: Path, args, task_description: str) -> None:
    env_max_steps = args.env_max_steps if args.env_max_steps is not None else max(int(args.max_steps), 500)
    workspace.mkdir(parents=True, exist_ok=True)
    contract_path = workspace / "configs/runtime/contracts/behavior1k_r1pro.runtime.yaml"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_src = REPO_ROOT / "PhyAgentOS/templates/configs/runtime/contracts/behavior1k_r1pro.runtime.yaml"
    contract_path.write_text(contract_src.read_text(encoding="utf-8"), encoding="utf-8")
    write_yaml_block(
        workspace / "TARGETS.md",
        "Runtime Targets",
        {
            "version": "runtime_target_registry_v1",
            "targets": [
                {
                    "id": "behavior1k_r1pro_sim",
                    "target_class": "remote",
                    "target_kind": "simulation",
                    "enabled": True,
                    "workspace": DEFAULT_WORKSPACE_REL,
                    "supported_skillruntimes": ["behavior1k_pi0_openpi"],
                    "runtime": {
                        "target_runtime": "Behavior1KRemoteTargetProxy",
                        "target_endpoint": args.target_endpoint,
                        "target_adapter": "target_adapter://behavior1k_openpi_adapter",
                        "runtime_contract_ref": "configs/runtime/contracts/behavior1k_r1pro.runtime.yaml",
                    },
                    "observation": {"observation_type": "multimodal", "empty_observation_allowed": False},
                    "perception": {"enabled": False, "strict_preflight": True},
                    "config": {
                        "task_name": args.task_name,
                        "instance_id": args.instance_id,
                        "action_dim": 23,
                        "max_chunk_size": 50,
                        "env_max_steps": env_max_steps,
                        "target_ws_timeout_s": 300,
                        "chunk_size": 1,
                    },
                }
            ],
        },
    )
    write_yaml_block(
        workspace / "SKILLRUNTIME.md",
        "Runtime Skill Runtimes",
        {
            "version": "runtime_skill_registry_v1",
            "skillruntimes": [
                {
                    "id": "behavior1k_pi0_openpi",
                    "runtime": "OpenPISkillRuntime",
                    "runtime_kind": "policy",
                    "loop_mode": "policy_closed_loop",
                    "agent_exposure": "none",
                    "supported_target_kinds": ["simulation"],
                    "policy": {
                        "policy_client": "openpi",
                        "policy_adapter": "policy_adapter://b1k_openpi_policy_adapter",
                        "supports_chunk": True,
                    },
                    "observation_contract": {"observation_type": "multimodal", "empty_observation_allowed": False},
                    "requires": {"sensors": [], "environment_outputs": [], "strict_environment_contract": True},
                    "output_contract": {
                        "action": {
                            "action_space_id": "behavior1k_r1pro_joint_v1",
                            "shape": ["T", 23],
                            "dtype": "float32",
                            "normalized": False,
                            "representation": "joint_position",
                            "frame": "robot",
                            "chunk": {"policy_hz": 20},
                        }
                    },
                    "adapter_requirements": {"allowed_bridges": ["bridge://safety_clamp"]},
                }
            ],
        },
    )
    write_yaml_block(
        workspace / "SESSIONS.md",
        "Runtime Sessions",
        {
            "version": "runtime_sessions_v1",
            "sessions": [
                {
                    "session_id": f"b1k_{args.task_name}_i{args.instance_id}",
                    "target_ref": "target://behavior1k_r1pro_sim",
                    "skillruntime_ref": "skillruntime://behavior1k_pi0_openpi",
                    "task_description": task_description,
                    "status": "pending",
                    "routing": {
                        "target_endpoint": args.target_endpoint,
                        "policy_endpoint": args.policy_endpoint,
                    },
                    "execution": {
                        "max_steps": args.max_steps,
                        "replan_every_steps": args.replan_every_steps,
                        "action_chunk_mode": "open_loop",
                    },
                    "timeouts": {"execute_timeout_s": 3600, "policy_timeout_s": 300},
                    "safety_profile": {"profile": "default_simulation", "stop_on_policy_timeout": True},
                    "benchmark": {
                        "benchmark_id": "behavior-1k",
                        "task_name": args.task_name,
                        "instance_id": args.instance_id,
                    },
                    "result": {},
                }
            ],
        },
    )


if __name__ == "__main__":
    raise SystemExit(main())
