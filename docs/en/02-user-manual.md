# PhyAgentOS-G User Manual

> Operations guide for users: installation, Game Agent setup, simulation validation, troubleshooting.

---

## Table of Contents

- [2.1 Manual Scope](#21-manual-scope)
- [2.2 How the System Works](#22-how-the-system-works)
- [2.3 Installation & Environment Setup](#23-installation--environment-setup)
- [2.4 5-Minute Quick Start](#24-5-minute-quick-start)
- [2.5 Configuration Details](#25-configuration-details)
- [2.6 Scenario Usage Guide](#26-scenario-usage-guide)
  - [2.6.1 DummySimTarget Smoke Test](#261-dummysimtarget-smoke-test)
  - [2.6.2 Minecraft Game Agent](#262-minecraft-game-agent)
  - [2.6.3 LIBERO Benchmark Validation](#263-libero-benchmark-validation)
- [2.7 Runtime File Reference](#27-runtime-file-reference)
- [2.8 Common Interaction Examples](#28-common-interaction-examples)
- [2.9 Troubleshooting](#29-troubleshooting)

---

## 2.1 Manual Scope

### Who This Is For

- First-time users wanting to get PhyAgentOS-G running quickly
- Researchers deploying Minecraft Game Agent
- Researchers running simulation benchmarks
- Debuggers needing to understand workspace file changes

### Who This Is NOT For

For secondary development, adding new Game Targets, or writing Adapters, see [Part 3: Developer Manual](03-developer-manual.md).

---

## 2.2 How the System Works

### 2.2.1 Dual-Track Structure

PhyAgentOS-G is an explicitly decoupled dual-track runtime architecture:

- **Track A (Agent / Brain)**: Understands user input, plans actions, calls tools, performs Critic validation. Launched via `paos agent`.
- **Track B (Runtime / Execution)**: Session-level execution supervision, target/policy invocation, state writeback. Runtime watchdog auto-launches with Agent; remote target/policy servers deployed separately.

Shared state is expressed through Markdown files in the workspace, not cross-layer Python calls.

### 2.2.2 A Complete Run Cycle

1. Run `paos onboard` to initialize config and workspace
2. Start `paos agent`
3. User enters a natural language task
4. Agent reads `TARGETS.md`, `SKILLRUNTIME.md`, `ENVIRONMENT.md` to plan
5. Agent appends executable task to `SESSIONS.md`
6. WatchdogSupervisor claims pending session, runs preflight, executes target/skill
7. Results written back to `SESSIONS.md`, `ENVIRONMENT.md`, `LESSONS.md`, and artifacts directory

---

## 2.3 Installation & Environment Setup

### Prerequisites

- Python 3.11 or higher
- Git
- Accessible LLM provider API key or compatible service
- Minecraft scenario additionally requires: Windows 11 + Minecraft Java 1.20.4 + Node.js + ngrok

### Clone & Install

```bash
git clone https://github.com/PhyAgentOS/PhyAgentOS.git
cd PhyAgentOS
pip install -e .
```

### CLI Entry Points

After installation, the `paos` command is available:

- `paos onboard` — Initialize workspace
- `paos agent` — Start interactive Agent
- `paos agent -m "..."` — Single-turn message call
- `paos minecraft` — Minecraft game control commands

---

## 2.4 5-Minute Quick Start

### Step 1: Install

```bash
git clone https://github.com/PhyAgentOS/PhyAgentOS.git && cd PhyAgentOS
pip install -e .
```

### Step 2: Initialize Workspace

```bash
paos onboard
```

This creates `~/.PhyAgentOS/config.json`, prepares the default workspace, and syncs template files.

### Step 3: Configure API Key

Edit `~/.PhyAgentOS/config.json`:

```json
{
  "agents": {
    "defaults": {
      "model": "openrouter/openai/gpt-4o-mini"
    }
  },
  "providers": {
    "openrouter": {
      "api_key": "YOUR_API_KEY"
    }
  }
}
```

### Step 4: Start Agent

```bash
paos agent
```

In interactive mode, enter natural language tasks. For one-shot:

```bash
paos agent -m "run a smoke test using the dummy_sim target"
```

---

## 2.5 Configuration Details

### Runtime Configuration

```json
{
  "runtime": {
    "enabled": true,
    "workspace": "~/.PhyAgentOS/runtime_workspace"
  }
}
```

When `runtime.enabled` is `true`, the Agent will:
1. Create/refresh the runtime workspace
2. Sync `TARGETS.md`, `SKILLRUNTIME.md`, `SESSIONS.md` templates
3. Start the Session Watchdog

---

## 2.6 Scenario Usage Guide

### 2.6.1 DummySimTarget Smoke Test

The fastest validation — zero external dependencies:

```bash
paos agent -m "run a smoke test using the dummy_sim target"
```

DummySimTarget is a fully mocked local target. It returns numpy zero arrays as observations and auto-succeeds after 5 steps. Ideal for verifying the Agent → Runtime pipeline.

### 2.6.2 Minecraft Game Agent

PhyAgentOS-G's first Game Target, with a fully verified end-to-end pipeline.

#### Architecture

```
[Windows 11]                              [Linux Cloud]
  Minecraft ← mineflayer bridge           PhyAgentOS-G Agent
       ↑           ↑                            ↑
  localhost:25565  localhost:3001               │
                   ngrok → HTTPS → MinecraftTarget (HTTP client)
                                           ↑
                                   WatchdogSupervisor
```

**Key design**: MinecraftTarget contains zero Minecraft protocol code — it communicates with the external mineflayer bridge via HTTP only.

#### Windows Deployment

Full deployment guide: [Minecraft Deployment Docs](../../scenarios/game/minecraft/en/deployment.md)

Quick start:

```powershell
cd mc_bridge
$env:MC_HOST="localhost"; $env:MC_PORT="25565"; $env:BOT_NAME="paos"
$env:MC_VERSION="1.20.4"; $env:API_PORT="3001"
node bridge_server.js

# In another terminal
ngrok http 3001 --region=ap
```

Record the ngrok HTTPS URL (e.g., `https://xxxx.ngrok-free.app`).

#### Linux Configuration

Edit `TARGETS.md` in the runtime workspace to add the Minecraft target:

```yaml
version: targets_v1
targets:
  - id: target://minecraft
    kind: game
    enabled: true
    adapter: target_adapter://minecraft/v1
    config:
      bridge_url: "https://xxxx.ngrok-free.app"
      verify_ssl: false
    supported_skillruntimes:
      - skillruntime://minecraft_game/v1
```

Edit `SKILLRUNTIME.md` to register the Minecraft skill runtime:

```yaml
version: skillruntimes_v1
skillruntimes:
  - id: skillruntime://minecraft_game/v1
    kind: builtin
    module: PhyAgentOS.runtime.skillruntime.game.minecraft_skill_runtime
    class: MinecraftSkillRuntime
```

#### Usage

```bash
# Direct CLI control
paos minecraft say "Mine 5 oak logs and come to me"

# Via Agent
paos agent -m "tell the Minecraft bot to mine 10 oak logs and craft a crafting table"
```

#### Action Space

16 action types: `move`, `look`, `jump`, `sneak`, `sprint`, `attack`, `interact`, `place`, `dig`, `use`, `select_slot`, `drop`, `chat`, `collect`, `equip`, `craft`.

### 2.6.3 LIBERO Benchmark Validation

LIBERO is a standard robot manipulation benchmark. PhyAgentOS-G supports it through the TargetWS remote protocol.

#### Start Services

```bash
# TargetWS machine (requires LIBERO environment)
MUJOCO_GL=egl PYTHONWARNINGS=ignore \
python PhyAgentOS/runtime/targets/remote/libero/server.py \
  --host 0.0.0.0 --port 9002

# Policy machine (requires pi0.5 checkpoint)
python -m PhyAgentOS.runtime.policy.openpi.lerobot_pi0_server \
  --model-dir /path/to/pi05/checkpoint --host 0.0.0.0 --port 8000
```

#### Run E2E Validation

```bash
python scripts/run_pi05_libero_real_e2e.py \
  --policy-endpoint openpi://127.0.0.1:8000 \
  --target-endpoint targetws://127.0.0.1:9002 \
  --benchmark-name libero_spatial --task-id 0
```

Or via Agent:
```bash
paos agent -m "run the configured LIBERO benchmark task"
```

---

## 2.7 Runtime File Reference

| File | Owner | Purpose |
|------|------|------|
| `AGENTS.md` | Agent workspace | Project-level operating rules |
| `SOUL.md` | Agent workspace | Identity and assistant behavior |
| `USER.md` | Agent workspace | User preferences and profile |
| `SKILLS.md` | Agent workspace | Skill discovery and loading rules |
| `EMBODIED.md` | Agent workspace | Human-readable target capability descriptions |
| `ENVIRONMENT.md` | Agent/runtime workspace | Current target, scene, and environment state |
| `LESSONS.md` | Agent workspace | Operational lessons and failure notes |
| `TASK.md` | Agent workspace | Multi-step task decomposition state |
| `TARGETS.md` | Runtime workspace | Target registry, endpoint, adapter, config |
| `SKILLRUNTIME.md` | Runtime workspace | Skill runtime registry and execution contracts |
| `SESSIONS.md` | Runtime workspace | Session queue and execution results |

---

## 2.8 Common Interaction Examples

### DummySimTarget Smoke Test

```bash
paos agent -m "run a smoke test using the dummy_sim target"
```

### Minecraft Natural Language Control

```bash
paos minecraft say "Mine 5 oak logs and come to me"
```

### Minecraft In-Game Chat Control

Type in game chat:
```text
paos mine 5 oak logs
```

### LIBERO Benchmark Evaluation

```bash
python scripts/run_pi05_libero_sweep.py --benchmark-name libero_spatial
```

---

## 2.9 Troubleshooting

### No API Key

1. Check `~/.PhyAgentOS/config.json` for `providers.<name>.api_key`
2. Ensure `agents.defaults.model` matches the provider
3. Verify API key format and no extra spaces

### Missing Runtime Protocol Files

1. Ensure `runtime.enabled` is `true` in config
2. Check `runtime.workspace` path
3. Start `paos agent`, or manually initialize:
   ```bash
   python scripts/init_runtime_workspace.py --workspace <path>
   ```

### SESSIONS.md Has Pending But Not Executing

1. Confirm WatchdogSupervisor is running (auto-launched with Agent)
2. Check session's `target_ref` and `skillruntime_ref` exist in TARGETS.md/SKILLRUNTIME.md
3. Check target is `enabled: true`
4. Check Agent logs for preflight errors

### Session Rejected by Preflight

1. View the session's result/error in SESSIONS.md
2. Check target supports the `skillruntime_ref`
3. Check SKILLRUNTIME.md observation/action contract compatibility with target runtime contract

### Minecraft Bridge Connection Failed (SSL Error)

1. Add `"verify_ssl": false` in TARGETS.md config (ngrok free tier has incomplete certs)
2. Ensure bridge_url has no trailing spaces

### Minecraft API Returns Empty or HTML

1. The `ngrok-skip-browser-warning: true` header is already added in minecraft_target.py
2. Check ngrok tunnel is still running
3. Ensure bridge URL includes `https://` prefix

### Minecraft Bot Teleport Not Working

1. Enable cheats in world (Esc → Open to LAN → Allow Cheats: ON)
2. Player must be within bot's render distance

---

## Further Reading

- [Part 1: Framework Introduction](01-framework-introduction.md) — Design philosophy, architecture, roadmap
- [Part 3: Developer Manual](03-developer-manual.md) — API reference, Target/Adapter/Skill development
- [Minecraft Deployment Guide](../scenarios/game/minecraft/en/deployment.md) — Full deployment walkthrough

> **Next step**: To add a new game or custom Target, go to the [Developer Manual](03-developer-manual.md).
