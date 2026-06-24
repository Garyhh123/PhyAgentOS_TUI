# PhyAgentOS User Manual

> An operations manual for users, integrators, and demo operators. Covers single-machine mode, Fleet multi-robot mode, scenario configuration, and troubleshooting.

---

## Table of Contents

- [2.1 About This Manual](#21-about-this-manual)
- [2.2 How the System Works](#22-how-the-system-works)
- [2.3 Installation & Environment Setup](#23-installation--environment-setup)
- [2.4 5-Minute Quick Start](#24-5-minute-quick-start)
- [2.5 Configuration Details](#25-configuration-details)
- [2.6 Scenario Usage Guide](#26-scenario-usage-guide)
  - [2.6.1 Simulation](#261-simulation)
  - [2.6.2 Real Robot Arm (Franka Research 3)](#262-real-robot-arm-franka-research-3)
  - [2.6.3 Mobile Robot (Go2)](#263-mobile-robot-go2)
  - [2.6.4 Remote Chassis (XLeRobot)](#264-remote-chassis-xlerobot)
  - [2.6.5 ReKep Real-Robot Plugin](#265-rekep-real-robot-plugin)
  - [2.6.6 Fleet Multi-Robot Coordination](#266-fleet-multi-robot-coordination)
- [2.7 Runtime File Reference](#27-runtime-file-reference)
- [2.8 Common Interaction Examples](#28-common-interaction-examples)
- [2.9 Troubleshooting](#29-troubleshooting)

---

## 2.1 About This Manual

### Who This Is For

- First-time users wanting to get PhyAgentOS running
- Integrators needing command-line or gateway-based Agent interaction
- Demo operators starting simulation, Go2, remote chassis, or real-robot plugins
- Debuggers needing to understand runtime workspace file changes

### Who This Is NOT For

If you need secondary development, driver authoring, plugin development, or internal architecture research, read [Part 3: API Developer Manual](../03-developer-manual.md).

---

## 2.2 How the System Works

### 2.2.1 Dual-Track Structure

PhyAgentOS is an explicitly decoupled dual-track runtime architecture:

- **Track A (Agent / Brain)**: Handles user input understanding, action planning, tool invocation, and Critic validation. Started via `paos agent` or `paos gateway`.
- **Track B (Runtime / Execution Layer)**: Handles instruction reading, hardware driving, action execution, and state writeback. Started via `python -m PhyAgentOS.runtime.watchdog`.

Shared state between the two is expressed through Markdown files in the workspace, not through cross-layer Python function calls.

### 2.2.2 Single Mode vs Fleet Mode

| Mode | Workspace | Use Case |
|------|-----------|----------|
| **Single** | `~/.PhyAgentOS/workspace` | Single robot or simulation quick validation |
| **Fleet** | Shared + per-robot workspaces | Heterogeneous multi-robot coordination |

### 2.2.3 A Typical Run Cycle

1. Run `paos onboard` to initialize config and workspace
2. Start `paos agent` or `paos gateway`
3. When runtime is enabled, PhyAgentOS provisions the runtime workspace and starts the session watchdog
4. User inputs a natural language task
5. Agent reads agent context files plus runtime state such as `TARGETS.md`, `SKILLRUNTIME.md`, and `ENVIRONMENT.md`
6. Agent appends executable work to `SESSIONS.md`
7. Watchdog claims a pending session, runs preflight, executes the target/skill runtime, and writes results and artifacts
8. Runtime/perception writers refresh `ENVIRONMENT.md` as state changes

---

## 2.3 Installation & Environment Setup

### Prerequisites

- Python 3.11 or higher
- Git
- Accessible LLM provider API or compatible service
- Optional for simulation: `pybullet`, Isaac Sim
- Optional for bridge/frontend: Node.js 18+

### Clone & Install

```bash
git clone https://github.com/PhyAgentOS/PhyAgentOS.git
cd PhyAgentOS
pip install -e .             # Python ≥ 3.11
pip install -e ".[dev]"      # Dev dependencies
```

### What You Get After Installation

The CLI entry point `paos` comes from the project's Python package:

- `paos onboard` — Initialize workspace
- `paos agent` — Start interactive Agent CLI
- `paos agent -m "..."` — Single-turn message call
- `paos gateway` — Start long-running gateway service

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

This command: creates/refreshes `~/.PhyAgentOS/config.json`, prepares default workspace, syncs template files.

### Step 3: Start Runtime (Track B)

Open Terminal A:

```bash
python -m PhyAgentOS.runtime.watchdog
```

Uses the built-in simulation driver by default — zero hardware needed for full pipeline validation.

### Step 4: Start Agent (Track A)

Open Terminal B:

```bash
paos agent
```

Enter interactive mode and type natural language tasks, for example:

```text
Look around the room and tell me what objects you see.
```

### Verify Pipeline Without Hardware

```bash
python scripts/init_runtime_workspace.py --workspace /tmp/paos_runtime_smoke
python scripts/run_runtime_watchdog.py --workspace /tmp/paos_runtime_smoke --once
# → session marked succeeded, results in artifacts/
```

---

## 2.5 Configuration Details

### Minimal Configuration

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

Location: `~/.PhyAgentOS/config.json`

### Key Configuration Domains

| Domain | Purpose |
|--------|---------|
| `agents.defaults` | Default model, workspace path |
| `providers` | LLM provider API keys and addresses |
| `gateway` | Gateway service configuration |
| `tools` | Tool enable/disable |
| `embodiments` | Embodiment config (single / fleet mode) |

### Fleet Mode Minimum Configuration

```json
{
  "embodiments": {
    "mode": "fleet",
    "shared_workspace": "~/.workspaces/shared",
    "instances": [
      {
        "robot_id": "go2_edu_001",
        "driver": "go2_edu",
        "workspace": "~/.workspaces/go2_edu_001"
      }
    ]
  }
}
```

### Workspace Paths

| Mode | Path |
|------|------|
| Single mode | `~/.PhyAgentOS/workspace` |
| Fleet shared workspace | `~/.workspaces/shared` |
| Fleet robot workspace | `~/.workspaces/<robot_id>` |

> After each config change, re-run `paos onboard` to refresh templates and add new fields.

---

## 2.6 Scenario Usage Guide

### 2.6.1 Simulation

The built-in `simulation` driver is the fastest way to validate the full pipeline.

```bash
# Terminal 1: Start simulation Watchdog
python -m PhyAgentOS.runtime.watchdog

# Terminal 2: Start Agent
paos agent
```

**Isaac Sim High-Fidelity Simulation (PIPER + Go2 Composite)**:

```bash
# GUI mode (requires local X display)
python hal/hal_watchdog.py --gui --interval 0.05 \
  --driver pipergo2_manipulation \
  --driver-config examples/pipergo2_manipulation_driver.json

# VNC mode (remote server/container, browser access)
python hal/hal_watchdog.py --vnc --interval 0.05 \
  --driver pipergo2_manipulation \
  --driver-config examples/pipergo2_manipulation_driver.json
# Open http://<host>:31315/vnc.html in browser
```

Then send Agent commands:

```bash
paos agent -m "open simulation"
paos agent -m "go to desk"
paos agent -m "pick up the red cube and return to the starting position"
```

> `--gui` and `--vnc` are mutually exclusive. Without either flag, runs headless.

---

### 2.6.2 Real Robot Arm (Franka Research 3)

#### Network Architecture

```
WorkStation PC → Control Box (Shop Floor: 172.16.0.x) → Robot Arm
```

#### First-Time Setup

1. Ethernet cable: PC ↔ Control Box (Shop Floor port)
2. Set PC wired network IP to `172.16.0.x` (e.g., `172.16.0.1`)
3. Activate FCI in Control Box Desk interface
4. Install backend drivers

#### Backend Installation

```bash
# pylibfranka (official Python bindings)
pip install pylibfranka

# franky-control (alternative high-level library, looser compatibility)
pip install git+https://github.com/TimSchneider42/franky.git
```

#### Driver Selection

| Driver Name | Description | Use Case |
|:------------|:------------|:---------|
| `franka_research3` | Raw pylibfranka driver | Precise control or real-time 1kHz |
| `franka_multi` | Multi-backend negotiation driver | Auto-selects available backend |

#### Launch

```bash
# Multi-backend auto-negotiation (recommended)
python hal/hal_watchdog.py --driver franka_multi

# Raw pylibfranka driver
python hal/hal_watchdog.py --driver franka_research3

# Custom configuration
python hal/hal_watchdog.py \
  --driver franka_multi \
  --driver-config examples/franka_research3.driver.json
```

#### Supported Actions

`move_to` (Cartesian position), `move_joints` (joint positions), `grasp`, `move_gripper`, `stop`, etc.

#### Real-Time Control Mode

Set `realtime_mode: true` to enable 1 kHz real-time control (requires real-time kernel).

> Before installation, verify library version compatibility with your robot system version.

---

### 2.6.3 Mobile Robot (Go2)

```bash
python hal/hal_watchdog.py \
  --driver go2_edu \
  --driver-config examples/go2_driver_config.json
```

The driver config JSON is passed through to the Go2 driver for remote ROS2, video, state streaming, and motion backend initialization.

---

### 2.6.4 Remote Chassis (XLeRobot)

```bash
python hal/hal_watchdog.py \
  --driver xlerobot_2wheels_remote \
  --driver-config examples/xlerobot_2wheels_remote.driver.json
```

Configuration includes ZMQ communication parameters, remote host address, etc.

---

### 2.6.5 ReKep Real-Robot Plugin

`rekep_real` is integrated via an external plugin repository:

```bash
# Deploy plugin
python scripts/deploy_rekep_real_plugin.py \
  --repo-url https://github.com/baiyu858/PhyAgentOS-rekep-real-plugin.git

# Start
python hal/hal_watchdog.py --driver rekep_real
```

---

### 2.6.6 Fleet Multi-Robot Coordination

#### When to Use

- One Agent coordinates multiple robot instances
- Separate shared environment, target registry, and session queue
- Manage execution through `TARGETS.md`, `SKILLRUNTIME.md`, and `SESSIONS.md`

#### Startup Sequence

1. Set `embodiments.mode = "fleet"`
2. Run `paos onboard`
3. Start `paos agent` or `paos gateway`
4. Runtime workspace provisioning and the session watchdog start automatically when runtime is enabled

```bash
paos agent
```

#### Fleet Mode File Layout

| File | Location | Purpose |
|------|----------|---------|
| `ENVIRONMENT.md` | shared/ | Global environment state |
| `TARGETS.md` | runtime/shared | Target registry |
| `SKILLRUNTIME.md` | runtime/shared | Skill runtime registry |
| `SESSIONS.md` | runtime/shared | Session queue and results |
| `TASK.md` | shared/ | Multi-step task state |
| `ORCHESTRATOR.md` | shared/ | Global orchestration state |

---

---

## 2.7 Protocol File Reference

| Context Loading | File | Location | Purpose |
|------|------|----------|---------|
| Always loaded into the agent system prompt | `AGENTS.md` | Agent workspace | Project-level operating rules |
| Always loaded into the agent system prompt | `SOUL.md` | Agent workspace | Identity and assistant behavior |
| Always loaded into the agent system prompt | `USER.md` | Agent workspace | User preferences and durable profile notes |
| Always loaded into the agent system prompt | `TOOLS.md` | Agent workspace | Tool usage policy |
| Always loaded into the agent system prompt | `SKILLS.md` | Agent workspace | Agent skill discovery and loading rules |
| Loaded when present; filtered by enabled runtime targets where applicable | `EMBODIED.md` | Agent workspace | Human-readable target capability descriptions |
| Loaded when present as state | `ENVIRONMENT.md` | Agent/runtime workspace | Current target, scene, object, and environment state |
| Loaded when present as memory/state | `LESSONS.md` | Agent workspace | Operational lessons and failure notes |
| Loaded when present as task state | `TASK.md` | Agent workspace | Multi-step task decomposition state |
| Runtime protocol; read before scheduling sessions | `RUNTIME.md` | Runtime workspace | Instructions for writing valid runtime sessions |
| Runtime protocol; read before scheduling sessions | `TARGETS.md` | Runtime workspace | Target registry, endpoints, adapters, configs, supported skill runtimes |
| Runtime protocol; read before scheduling sessions | `SKILLRUNTIME.md` | Runtime workspace | Policy/builtin skill runtime registry and execution contracts |
| Runtime queue/state | `SESSIONS.md` | Runtime workspace | Execution session queue and results |

---

## 2.8 Common Interaction Examples

### Environment Query

```text
Look around and tell me what objects are present.
```

Verify: Agent can read `ENVIRONMENT.md`, environment state has been correctly written back by Watchdog.

### Robot Arm Manipulation Task

```text
Pick up the red apple on the table and place it on the tray.
```

Verify: Target object exists in environment state, robot profile declares corresponding actions, Watchdog successfully executes and clears the action queue.

### Mobile Robot Navigation

```text
Move near the refrigerator and stop.
```

Verify: Target semantic location exists in scene graph, current mobile robot supports navigation actions.

### Fleet Multi-Robot Coordination

```text
Send Go2 to patrol the doorway first, then have the robot arm grab the package on the table for handoff.
```

Verify: Agent recognizes the intended target, the session uses the correct `target_ref`, and `SESSIONS.md` / `ENVIRONMENT.md` update correctly.

### Isaac Sim Environment Manipulation

```bash
paos agent -m "open simulation"
paos agent -m "go to desk"
paos agent -m "pick up the red cube and return to the starting position"
```

### VLA Model Grasping

```bash
paos agent -m "deploy a VLA to pick up the red cube"
```

Customize your VLA checkpoint by editing the `vla` block in `examples/pipergo2_manipulation_driver.json`.

---

## 2.9 Troubleshooting

### No API Key

**Symptom**: Agent starts but reports missing API key.

**Resolution**:
1. Check `~/.PhyAgentOS/config.json` for `providers.<name>.api_key`
2. Verify `agents.defaults.model` matches the provider
3. Ensure API key format is correct with no extra whitespace

### Runtime Protocol Files Missing

**Symptom**: `TARGETS.md`, `SKILLRUNTIME.md`, or `SESSIONS.md` is missing.

**Resolution**:
1. Confirm `runtime.enabled` is true in config
2. Check whether `runtime.workspace` points to a separate directory
3. Start `paos agent` / `paos gateway`, or initialize manually with `python scripts/init_runtime_workspace.py --workspace <path>`
4. In Fleet mode, verify you're inspecting the shared/runtime workspace

### SESSIONS.md Has Pending Work But No Execution

**Resolution**:
1. Confirm the session watchdog is running
2. Check that `target_ref` and `skillruntime_ref` exist
3. Check that the target is `enabled: true` in `TARGETS.md`
4. Check Watchdog output for preflight or runtime errors

### Session Rejected by Preflight

**Resolution**:
1. Check the session result/error in `SESSIONS.md`
2. Verify the target supports the requested `skillruntime_ref`
3. Check that `SKILLRUNTIME.md` observation/action contracts match the target runtime contract
4. Check `ENVIRONMENT.md` for required object, map, or connection state

### Fleet Mode Task Not Dispatched to Correct Robot

**Resolution**:
1. Verify `robot_id`, `driver`, `workspace` in config match
2. Check target id, workspace, and enabled state in `TARGETS.md`
3. Check the session `target_ref` in `SESSIONS.md`
4. Confirm task semantics explicitly identify target robot

### rekep_real Driver Not Found

**Resolution**:
1. Confirm plugin deployment script was executed: `python scripts/deploy_rekep_real_plugin.py`
2. Confirm plugin repo is registered in `~/.PhyAgentOS/plugins/`
3. Restart Watchdog for plugin to take effect

### Isaac Sim Startup Failure

**Resolution**:
1. Confirm Isaac Sim is correctly installed
2. Check path config in `pipergo2_manipulation_driver.json` `isaac_env` block
3. In `--vnc` mode, inspect first-start re-exec logs
4. Verify `LD_LIBRARY_PATH` is correctly set (auto-handled in VNC mode)

---

## Further Reading

- [Part 1: Framework Introduction](../01-framework-introduction.md) — Design philosophy, architecture, roadmap
- [Part 3: API Developer Manual](../03-developer-manual.md) — API reference, secondary development, coding style
