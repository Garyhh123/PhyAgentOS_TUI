"""Stardew Valley benchmark supervisor CLI commands."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import typer
from rich.console import Console

console = Console()
stardew_app = typer.Typer(help="Stardew Valley benchmark runner")


_ACTION_SCHEMA = """Available Stardew actions:
- move(x, y): relative movement by tile offset. x/y are integers. Prefer small local moves such as -1, 0, 1 when doing tool work; larger offsets like move(2, 0) are allowed when navigating.
- use(direction): use current item/tool toward "up", "right", "down", or "left".
- interact(direction): interact/harvest/talk/open toward "up", "right", "down", or "left".
- choose_item(slot_index): choose inventory slot 0-35. Pick the slot that matches the needed tool/item in observation.inventory.
- craft(item_name): craft by item name string, for example craft("Chest").
- attach_item(slot_index): attach inventory slot 0-35 to current tool.
- unattach_item(): unattach current attachment.
- menu(option, menu_name): option is "open" or "close"; currently menu_name is "map" or "current_menu".
- choose_option(option_index, quantity=None, direction=None): menu/NPC/shop choice. option_index starts at 0 for close, 1 for first option/continue; direction is "in" or "out" when buying/taking or selling/putting.
"""


@stardew_app.command("benchmark")
def stardew_benchmark(
    task_name: str = typer.Argument("farming_lite", help="StarDojo task suite name"),
    task_id: int = typer.Argument(0, help="Task id in the yaml suite, starting from 0"),
    bridge_url: str = typer.Option(
        "http://127.0.0.1:8765",
        "--bridge-url",
        "-u",
        help="Stardew bridge HTTP base URL",
    ),
    max_steps: int = typer.Option(30, "--max-steps", "-n", help="Maximum benchmark steps"),
    timeout: float = typer.Option(180.0, "--timeout", help="HTTP timeout in seconds"),
    agent_timeout: float = typer.Option(900.0, "--agent-timeout", help="Maximum seconds to wait for paos agent"),
    config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    action_retries: int = typer.Option(
        2,
        "--action-retries",
        help="Deprecated compatibility option; the Track A supervisor does not parse ACTION text.",
    ),
    log_dir: str | None = typer.Option(None, "--log-dir", help="Directory for benchmark run logs"),
    no_log: bool = typer.Option(False, "--no-log", help="Disable benchmark run log files"),
    runtime: bool = typer.Option(False, "--runtime", help="Use full runtime pipeline with SESSIONS.md and Watchdog"),
):
    """Run a Stardew benchmark task through the normal Track A paos agent."""
    if runtime:
        _run_benchmark_runtime(task_name, task_id, bridge_url, max_steps, timeout, agent_timeout, config, workspace, log_dir, no_log)
        return

    from PhyAgentOS.cli.commands import _load_runtime_config

    _ = action_retries
    runtime_config = _load_runtime_config(config, workspace)
    supervisor = _StardewBenchmarkSupervisor(
        bridge_url=bridge_url,
        task_name=task_name,
        task_id=task_id,
        max_steps=max_steps,
        timeout=timeout,
        agent_timeout=agent_timeout,
        config=config,
        workspace=workspace,
        workspace_path=runtime_config.workspace_path,
        log_dir=log_dir,
        enable_log=not no_log,
    )

    try:
        result = supervisor.run()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user.[/yellow]")
        raise typer.Exit(130)
    except Exception as exc:
        console.print(f"[red]Stardew benchmark failed:[/red] {exc}")
        raise typer.Exit(1)

    status = "completed" if result.get("completed") else "truncated" if result.get("truncated") else "stopped"
    color = "green" if result.get("completed") else "yellow"
    console.print(
        f"\n[{color}]Result: {status}[/] "
        f"steps={result.get('step')} quantity={result.get('quantity')}"
    )
    if result.get("run_dir"):
        console.print(f"[dim]Run dir:[/dim] {result['run_dir']}")
    if result.get("actions"):
        console.print("[dim]Actions:[/dim]")
        for idx, action in enumerate(result["actions"], start=1):
            console.print(f"  {idx}. {action}")


class _StardewBenchmarkSupervisor:
    def __init__(
        self,
        *,
        bridge_url: str,
        task_name: str,
        task_id: int,
        max_steps: int,
        timeout: float,
        agent_timeout: float,
        config: str | None,
        workspace: str | None,
        workspace_path: Path,
        log_dir: str | None,
        enable_log: bool,
    ) -> None:
        self.bridge_url = bridge_url.rstrip("/")
        self.task_name = task_name
        self.task_id = task_id
        self.max_steps = max_steps
        self.timeout = timeout
        self.agent_timeout = agent_timeout
        self.config = config
        self.workspace = workspace
        self.workspace_path = workspace_path
        self.enable_log = enable_log
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_key = f"stardew-benchmark:{task_name}-{task_id}-{self.run_id}"
        self.run_dir = self._resolve_run_dir(log_dir) if enable_log else None

    def run(self) -> dict[str, Any]:
        console.print(
            f"[cyan]Stardew benchmark[/cyan] task={self.task_name}[{self.task_id}] "
            f"bridge={self.bridge_url} max_steps={self.max_steps} mode=track-a"
        )
        with httpx.Client(base_url=self.bridge_url, timeout=self.timeout, trust_env=False) as client:
            start_payload = _request_json(
                client,
                "POST",
                "/benchmark/start",
                json={"task_name": self.task_name, "task_id": self.task_id, "max_steps": self.max_steps},
            )
            initial_obs = start_payload["obs"]
            initial_benchmark = start_payload["benchmark"]
            _print_benchmark_state("start", initial_benchmark)
            self._write_json("initial.json", start_payload)

            prompt = self._build_agent_prompt(initial_obs, initial_benchmark)
            self._write_text("agent_prompt.txt", prompt)
            completed_process = self._run_agent(prompt)

            final_payload = _request_json(client, "GET", "/benchmark/status")
            final_benchmark = final_payload["benchmark"]
            if final_benchmark.get("active") and not final_benchmark.get("completed") and not final_benchmark.get("truncated"):
                final_payload = _request_json(client, "POST", "/benchmark/stop")
                final_benchmark = final_payload["benchmark"]

        actions = self._read_actions()
        result = {
            "run_id": self.run_id,
            "session_key": self.session_key,
            "task_name": self.task_name,
            "task_id": self.task_id,
            "completed": bool(final_benchmark.get("completed")),
            "truncated": bool(final_benchmark.get("truncated")),
            "stopped": bool(final_benchmark.get("stopped")),
            "step": final_benchmark.get("step"),
            "quantity": (final_benchmark.get("eval") or {}).get("quantity"),
            "actions": actions,
            "benchmark": final_benchmark,
            "agent_returncode": completed_process.returncode,
            "run_dir": str(self.run_dir) if self.run_dir else None,
        }
        self._write_json("final_status.json", final_payload)
        self._write_json("summary.json", result)
        self._write_text("summary.md", _format_summary(result))
        return result

    def _run_agent(self, prompt: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(
            {
                "PHYAGENTOS_STARDEW_ENABLED": "1",
                "PHYAGENTOS_STARDEW_BRIDGE_URL": self.bridge_url,
                "PHYAGENTOS_STARDEW_MODE": "benchmark",
                "PHYAGENTOS_STARDEW_TIMEOUT": str(self.timeout),
            }
        )
        if self.run_dir:
            env["PHYAGENTOS_STARDEW_RUN_DIR"] = str(self.run_dir)

        cmd = [
            sys.executable,
            "-m",
            "PhyAgentOS.cli.commands",
            "agent",
            "-m",
            prompt,
            "--session",
            self.session_key,
            "--no-markdown",
        ]
        if self.config:
            cmd.extend(["--config", self.config])
        if self.workspace:
            cmd.extend(["--workspace", self.workspace])

        try:
            completed = subprocess.run(
                cmd,
                cwd=str(Path(__file__).resolve().parents[2]),
                env=env,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=self.agent_timeout,
            )
        except subprocess.TimeoutExpired as exc:
            self._write_text("agent_stdout.txt", exc.stdout or "")
            self._write_text("agent_stderr.txt", (exc.stderr or "") + f"\nTimed out after {self.agent_timeout}s.\n")
            raise RuntimeError(f"paos agent timed out after {self.agent_timeout}s") from exc

        self._write_text("agent_stdout.txt", completed.stdout)
        self._write_text("agent_stderr.txt", completed.stderr)
        if completed.stdout:
            console.print(completed.stdout)
        if completed.returncode != 0:
            raise RuntimeError(f"paos agent exited with code {completed.returncode}. See agent_stderr.txt.")
        return completed

    def _build_agent_prompt(self, obs: dict[str, Any], benchmark: dict[str, Any]) -> str:
        description = benchmark.get("description") or f"Complete Stardew benchmark {self.task_name}[{self.task_id}]."
        # Do not expose evaluator internals/quantity/target fields to the agent.
        return (
            "你正在进行 Stardew Valley benchmark。请使用正常 Track A tool-calling 完成任务。\n\n"
            f"Task instruction:\n{description}\n\n"
            f"Action budget: at most {self.max_steps} calls to stardew_action.\n\n"
            f"{_ACTION_SCHEMA}\n"
            "可用 Stardew 工具：\n"
            "- stardew_action(action: str): 执行一个原始 StarDojo action，并返回新的 observation。\n"
            "- stardew_observe(): 只观察，不执行动作。\n\n"
            "严格要求：\n"
            "- 不要调用 curl、exec、HTTP、/benchmark/start、/benchmark/execute。\n"
            "- 不要输出 ACTION: 文本；必须真实调用 stardew_action 工具。\n"
            "- 每次只执行一个 Stardew action。\n"
            "- tool result 只会给 observation 和 done/truncated 停止信号，不会给 evaluator 细节。\n"
            "- 如果 done=true 或 truncated=true，停止调用 Stardew 工具并总结。\n\n"
            "Initial observation:\n"
            f"{_json_for_prompt(obs, max_chars=12000)}\n\n"
            "现在开始，先根据 observation 选择第一步 stardew_action。"
        )

    def _resolve_run_dir(self, log_dir: str | None) -> Path:
        base = Path(log_dir).expanduser() if log_dir else self.workspace_path / "stardew_benchmark_runs"
        return base / f"{self.task_name}_{self.task_id}_{self.run_id}"

    def _write_json(self, filename: str, payload: Any) -> None:
        if not self.run_dir:
            return
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    def _write_text(self, filename: str, text: str) -> None:
        if not self.run_dir:
            return
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / filename).write_text(text or "", encoding="utf-8")

    def _read_actions(self) -> list[str]:
        if not self.run_dir:
            return []
        path = self.run_dir / "tool_calls.jsonl"
        if not path.exists():
            return []
        actions: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("tool") == "stardew_action" and record.get("type") == "tool_call":
                actions.append(record.get("action"))
        return [action for action in actions if isinstance(action, str)]


def _request_json(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        response = client.request(method, path, json=json)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Bridge request failed: {exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Bridge returned non-JSON response: HTTP {response.status_code}") from exc

    if response.status_code >= 400 or payload.get("ok") is False:
        raise RuntimeError(payload.get("error") or f"Bridge returned HTTP {response.status_code}")
    return payload


def _json_for_prompt(value: Any, max_chars: int = 6000) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str, indent=2)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... (truncated)"


def _format_summary(result: dict[str, Any]) -> str:
    lines = [
        f"# Stardew Benchmark {result.get('run_id')}",
        "",
        f"- task: `{result.get('task_name')}[{result.get('task_id')}]`",
        f"- completed: `{result.get('completed')}`",
        f"- truncated: `{result.get('truncated')}`",
        f"- stopped: `{result.get('stopped')}`",
        f"- steps: `{result.get('step')}`",
        f"- quantity: `{result.get('quantity')}`",
        f"- session: `{result.get('session_key')}`",
        "",
        "## Actions",
        "",
    ]
    for idx, action in enumerate(result.get("actions") or [], start=1):
        lines.append(f"{idx}. `{action}`")
    return "\n".join(lines)


def _run_benchmark_runtime(task_name, task_id, bridge_url, max_steps, timeout, agent_timeout, config, workspace, log_dir, no_log):
    """Run benchmark through Runtime pipeline: SESSIONS.md -> Watchdog -> Target -> SkillRuntime."""
    import httpx as _httpx
    import uuid as _uuid
    from PhyAgentOS.config.schema import Config
    from PhyAgentOS.cli.commands import _load_runtime_config

    console.print(f"[cyan]Runtime benchmark[/cyan] task={task_name}[{task_id}] bridge={bridge_url}")

    runtime_config = _load_runtime_config(config, workspace)
    client = _httpx.Client(base_url=bridge_url, timeout=timeout, trust_env=False)

    # Clean + start benchmark on bridge
    try:
        client.post("/benchmark/stop", timeout=5)
    except Exception:
        pass
    start_payload = client.post("/benchmark/start", json={"task_name": task_name, "task_id": task_id, "max_steps": max_steps}, timeout=30).json()
    initial_benchmark = start_payload["benchmark"]
    _print_benchmark_state("start", initial_benchmark)
    task_description = initial_benchmark.get("description") or f"{task_name}[{task_id}]"

    # Generate TaskPlan via LLM
    from PhyAgentOS.cli.commands import _make_provider
    provider = _make_provider(runtime_config)
    import asyncio as _asyncio
    initial_obs = start_payload["obs"]
    prompt = f"""Generate a TaskPlan for this Stardew Valley goal: {task_description}
Current state: pos={initial_obs.get('position')} inv={[i.get('Name') for i in initial_obs.get('inventory',[]) if i.get('Name')][:5]}
Actions: move(dx,dy), use(direction), choose_item(slot), craft(name), interact(direction)
Verify: has_item:NamexN, has_tool:Name, bot_near:x,y,dist
Each task should have 1-2 actions max. Precheck=[] (empty). Return ONLY JSON."""
    loop = _asyncio.get_event_loop()
    if loop.is_running():
        import nest_asyncio; nest_asyncio.apply()
    resp = loop.run_until_complete(provider.chat([{"role": "user", "content": prompt}]))
    raw = (resp.content or "").strip()
    if raw.startswith("```"): raw = "\n".join(raw.split("\n")[1:]).rsplit("```", 1)[0]
    try:
        task_plan = __import__("json").loads(raw)
    except Exception:
        task_plan = {"goal": task_description, "subgoals": []}
    console.print(f"[dim]TaskPlan: {len(task_plan.get('subgoals', []))} subgoals[/dim]")

    # Start Watchdog + write SESSIONS.md
    overrides = {"runtime": {"enabled": True, "autostart_watchdog": True, "target_enabled": {"stardewvalley_smapi": True}}}
    new_config = Config.model_validate({**runtime_config.model_dump(mode="json"), **overrides})
    from PhyAgentOS.runtime.workspace import RuntimeWorkspaceManager
    mgr = RuntimeWorkspaceManager(new_config)
    mgr.start_watchdog()

    sid = f"stardew-runtime-{_uuid.uuid4().hex[:8]}"
    import yaml as _yaml
    data = {"version": "runtime_sessions_v1", "sessions": [{
        "session_id": sid, "target_ref": "stardewvalley_smapi", "skillruntime_ref": "stardewvalley_navigate",
        "task_description": task_description, "status": "pending",
        "timeouts": {"execute_timeout_s": min(agent_timeout, 600), "preflight_timeout_s": 30, "queue_timeout_s": 60, "policy_timeout_s": 5},
        "execution": {"action_chunk_mode": "single_step", "max_steps": max_steps},
        "safety_profile": {"profile": "default"},
        "runtime_hints": {"perception_queries": [task_plan]},
    }]}
    sp = new_config.runtime_workspace_path / "SESSIONS.md"
    sp.write_text("```yaml\n" + _yaml.dump(data, allow_unicode=True, default_flow_style=False) + "```", encoding="utf-8")
    console.print(f"[dim]SESSIONS.md written[/dim]")

    # Wait for execution
    import time as _time
    start = _time.monotonic()
    while _time.monotonic() - start < agent_timeout:
        _time.sleep(2)
        if sp.exists():
            text = sp.read_text(encoding="utf-8")
            import re as _re
            m = _re.search(r'status: (\w+)', text)
            if m and m.group(1) in ("succeeded", "failed", "rejected", "timed_out"):
                console.print(f"[cyan]Session status: {m.group(1)}[/cyan]")
                for kw in ("num_steps", "subgoals_done", "error_message"):
                    mk = _re.search(rf'{kw}: (.*)', text)
                    if mk: console.print(f"[dim]{kw}={mk.group(1).strip()}[/dim]")
                break
        ep = new_config.runtime_workspace_path / "ENVIRONMENT.md"
        if ep.exists() and "Stardew Snapshot" in ep.read_text(encoding="utf-8"):
            break
    else:
        console.print("[yellow]Runtime timeout[/yellow]")

    # Final benchmark status
    try:
        final = client.get("/benchmark/status", timeout=10).json()
        fb = final.get("benchmark", {})
        status = "completed" if fb.get("completed") else "truncated"
        qty = (fb.get("eval") or {}).get("quantity", 0)
        console.print(f"\n[bold]Result: {status}[/bold] steps={fb.get('step')} quantity={qty}")
    except Exception:
        console.print("[yellow]Failed to get benchmark status[/yellow]")

    client.close()


def _print_benchmark_state(label: str, benchmark: dict[str, Any]) -> None:
    eval_result = benchmark.get("eval") or {}
    console.print(
        "[dim]step={step}/{max_steps} completed={completed} truncated={truncated} "
        "quantity={quantity} action={label}[/dim]".format(
            step=benchmark.get("step"),
            max_steps=benchmark.get("max_steps"),
            completed=benchmark.get("completed"),
            truncated=benchmark.get("truncated"),
            quantity=eval_result.get("quantity"),
            label=label,
        )
    )
