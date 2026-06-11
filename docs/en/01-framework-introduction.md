# PhyAgentOS-G Framework Introduction

> Project overview for everyone: game agent research philosophy, technical architecture, current progress, roadmap.

---

## Table of Contents

- [1.1 Project Overview](#11-project-overview)
- [1.2 Design Philosophy](#12-design-philosophy)
- [1.3 Technical Architecture](#13-technical-architecture)
- [1.4 Core Features](#14-core-features)
- [1.5 Current Progress](#15-current-progress)
- [1.6 Roadmap & TODO](#16-roadmap--todo)
- [1.7 Verified Pipelines](#17-verified-pipelines)
- [1.8 Project Structure](#18-project-structure)

---

## 1.1 Project Overview

**PhyAgentOS-G** is the Game Agent fork of [PhyAgentOS](https://github.com/PhyAgentOS/PhyAgentOS), rebuilt from the main branch **v0.1.4**, focused on **general game agent** research. The general HAL hardware driver layer has been removed; the Session-Centered Runtime core is retained. Versioning starts from v0.0.x to track the Game Agent branch independently. Jointly developed by **Sun Yat-sen University HCP Lab** and **Peng Cheng Laboratory**, built on [nanobot](https://github.com/HKUDS/nanobot).

### Core Value

By moving embodied intelligence learning and validation into game environments, we explore core intelligent behavior capabilities at minimal cost, then transfer proven strategies to simulation and real-robot environments:

- **Low-cost behavior validation**: Games provide complex interactions, long-term memory dependencies, and open worlds — iterate agent capabilities without hardware cost
- **One protocol, three environments**: Session protocol runs identically across Game / Simulation / Real Robot
- **Fully auditable**: State, actions, and perception results written to Markdown + YAML files; every step traceable
- **Three-way decoupling**: RolloutTarget + SkillRuntime + TargetAdapter separation; ~100 lines to add a new target

### Three Pillars

| Pillar | Exemplar | Status | Description |
|------|------|------|------|
| 🎮 **Game** | Minecraft | ✅ Ready | Full pipeline: Windows bridge → ngrok → Linux Agent |
| 🧪 **Simulation** | LIBERO + pi0.5 | ✅ Verified | Benchmark evaluation + policy closed-loop |
| 🤖 **Real Robot** | Real-world validation | 🔶 Planned | Strategy transfer validation |

### Key Metrics

| Metric | Value |
|------|------|
| Framework version | v0.0.3 (rebuilt from PhyAgentOS v0.1.4) |
| Python requirement | ≥ 3.11 |
| License | MIT |
| Runtime codebase | ~7200 lines (95 Python files) |
| Verified targets | Minecraft, DummySim, LIBERO |
| Verified skill runtimes | OpenPI (pi05), MinecraftSkill, BuiltinSkill |

---

## 1.2 Design Philosophy

### 1.2.1 State-as-a-File

All runtime state is exposed as Markdown files in the workspace. Track A (Agent brain) and Track B (Runtime plane) communicate through shared file reads/writes, not Python function calls:

```
Track A (Agent)          Workspace files          Track B (Runtime)
    │                                               │
    ├── reads ENVIRONMENT.md ────────────────→ writes state back
    │                                               │
    ├── writes SESSIONS.md ──────────────────→ consumes for execution
    │                                               │
    ├── reads LESSONS.md ←──────────────────── writes back experience
```

Three key benefits: **complete decoupling** (Agent and Runtime can be separate processes/machines), **extreme transparency** (view system state in Markdown files at any time), and **natural auditability** (historical state preserved as files).

### 1.2.2 Dual-Track Architecture

| Track | Responsibility | Entry Point |
|------|------|------|
| **Track A (Cognitive)** | Understand intent, plan actions, Critic validation, memory management | `paos agent` |
| **Track B (Execution)** | Session-level supervision, target/policy invocation, state & artifact writeback | Auto-launched with Agent |

The two tracks are strictly isolated by file protocol boundaries. Track A doesn't know whether the target is a game or simulation; Track B doesn't know about LLM prompts.

### 1.2.3 Session-Centered Runtime

The Runtime is centered on execution sessions:

- Agent packages tasks as Sessions and writes them to `SESSIONS.md`
- WatchdogSupervisor reads, validates (Preflight), dispatches, and executes sessions
- Results are written back to `SESSIONS.md`, `ENVIRONMENT.md`, `LESSONS.md`

The same Session protocol runs identically across game / debug / simulation / real_robot targets.

### 1.2.4 Three-Stage Validation Loop

```
Game Agent (low-cost iteration)
    → Validate long-term decisions, spatial reasoning, task planning
    → Simulation (benchmark evaluation + batch experience mining)
    → Real Robot (transfer validation)
```

---

## 1.3 Technical Architecture

### 1.3.1 Overall Architecture

```
                    ┌─────────────────────────────┐
                    │     Cognitive (Track A)       │
                    │  Planner / Critic / Memory    │
                    │     → writes SESSIONS.md      │
                    └──────────────┬──────────────┘
                                   │ File protocol boundary
                    ┌──────────────┴──────────────┐
                    │     Base Runtime             │
                    │  WatchdogSupervisor          │
                    │  SessionRegistry             │
                    │  LESSONS.md experience DB    │
                    └──────┬──────┬──────┬────────┘
                           │      │      │
              ┌────────────┼──────┼──────┼────────────┐
              ▼            ▼      ▼      ▼            ▼
    ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
    │ Game Target  │ │ Sim Target   │ │ Real Target  │
    │ Minecraft    │ │ LIBERO       │ │ Real robot   │
    └──────────────┘ └──────────────┘ └──────────────┘
```

### 1.3.2 Runtime Execution Pipeline

```
WatchdogSupervisor
  → SessionScheduler (reads SESSIONS.md, claims pending session)
    → RuntimeCompatibilityPreflight (strict validation)
      → SessionRunner (binds Target + SkillRuntime)
        → SkillRuntime (executes strategy loop: observe → predict → action → step)
          → TargetSessionHandle (drives Target.action_chunk())
            → writes back SESSIONS.md / ENVIRONMENT.md / LESSONS.md / artifacts
```

### 1.3.3 Three-Way Decoupling: Adapter + Bridge

```
Agent intent → SESSIONS.md
  → TargetAdapter (raw observation → Runtime unified observation format)
    → PolicyAdapter (Runtime observation → Policy input format)
      → ActionBridge (Policy output → Target executable action)
```

`AdapterPlan` auto-composes adapter steps, eliminating target × skill combinatorial explosion.

### 1.3.4 Core Interface: BaseRolloutTarget

The single entry point for all three scenarios:

```python
class BaseRolloutTarget(ABC):
    def build(self) -> None:          # Initialize target resources
    def describe(self) -> dict:       # Return capability declaration
    def reset(self, session_ctx) -> dict:  # Reset → return initial observation
    def observe(self) -> dict:        # Get current observation
    def action_chunk(self, action_chunk) -> dict:  # Execute action chunk
    def execution_status(self) -> dict:  # Return execution status
    def cancel(self, reason) -> None:    # Interrupt execution
    def close(self) -> None:          # Release resources
```

WatchdogSupervisor doesn't need to know whether the target is a game, simulation, or real robot.

### 1.3.5 Decoupling Boundaries

| Component | May Know | Must Never Know |
|------|---------|-----------|
| **RolloutTarget** | How to build/reset/step itself | Policy inference, Skill logic, upper Agent |
| **SkillRuntime** | How to call target and policy_client | Target internal implementation |
| **TargetAdapter** | How to transform data | Policy inference, Target internal state |
| **WatchdogSupervisor** | How to manage state machine, routing | How to execute individual steps |

---

## 1.4 Core Features

| Feature | Description |
|------|------|
| **Session-Centered Runtime** | WatchdogSupervisor → SessionRunner → SkillRuntime → TargetSessionHandle pipeline |
| **Target-Configured** | Four target kinds (game/debug/simulation/real_robot) registered in TARGETS.md |
| **Adapter + Bridge** | TargetAdapter + PolicyAdapter + ActionBridge three-way decoupling with AdapterPlan auto-composition |
| **Dual Skill Runtimes** | PolicySkillRuntime maintains policy closed-loop; BuiltinSkillRuntime manages Agent interactive loop |
| **Strict Preflight** | 6 validation checks (target/sensor/perception/adapter/action/tool); failures rejected |
| **File Protocol Matrix** | TARGETS.md · SKILLRUNTIME.md · SESSIONS.md · ENVIRONMENT.md · LESSONS.md |
| **Perception Plugin System** | SensorConfig/PerceptionConfig YAML + EnvironmentWriter auditable writeback |
| **Game Agent CLI** | `paos minecraft` direct game bot control |

---

## 1.5 Current Progress

### Version History

| Version | Date | Milestone |
|:-----|:-----|:-------|
| v0.1.4 | 2026-06-05 | Upstream: optimized onboarding, protocol spec, coding standards, Game Agent & Benchmarking ready |
| v0.0.1 | 2026-05-29 | Minecraft ready: cloud Agent connects to local Minecraft server |
| v0.0.2 | 2026-05-29 | Minecraft pipeline optimization: CLI + in-game chat dual control |
| v0.0.3 | 2026-06-11 | Repositioned: migrated from general HAL architecture to Game Agent research framework (PhyAgentOS-G) |

> PhyAgentOS-G is rebuilt from main branch v0.1.4. Versioning starts from 0.0.x.

### Achieved Capabilities

| Capability | Description |
|------|------|
| **Minecraft Game Agent** | Full pipeline: Windows mineflayer bridge → ngrok → Linux Agent. Zero pyCraft dependency |
| **Session-Centered Runtime** | WatchdogSupervisor full state machine (pending→claimed→running→succeeded/failed) |
| **Strict Preflight** | 6 validation checks before any execution |
| **LIBERO Benchmark** | TargetWS server + proxy + adapter; WebSocket + MsgPack communication |
| **pi0.5 Policy Closed-Loop** | LeRobot pi0 server + OpenPI client + skill runtime; action chunk support |
| **Perception Pipeline** | PerceptionRuntime + 5 plugins (dummy/sam3/yolo/rgbd/sim_oracle) + EnvironmentWriter |
| **E2E Acceptance Scripts** | run_pi05_libero_real_e2e.py (172 lines), executing through WatchdogSupervisor |

---

## 1.6 Roadmap & TODO

### Short-term (1-2 months)

**Game Agent Expansion**:
- [ ] Stardew Valley Game Target (SMAPI mod + HTTP bridge)
- [ ] Cross-season / cross-day long-term memory validation
- [ ] NPC relationship network & social memory
- [ ] 14-day unattended operation acceptance
- [ ] Minecraft multi-task parallel execution

**Runtime Enhancement**:
- [ ] Simulation Target implementation (MuJoCo / ManiSkill / RoboCasa)
- [ ] Real Robot validation Target (Franka / Go2)
- [ ] Session state machine completeness (timed_out transition)
- [ ] Fallback chain mechanism

**Perception Deepening**:
- [ ] Camera/LiDAR access standardization
- [ ] Scene graph construction & writeback protocol

### Medium-term (3-6 months)

- **Game→Sim experience transfer**: LESSONS.md from games auto-applied to simulation
- **Batch benchmark evaluation**: BenchmarkHarness automated evaluation framework
- **Policy Server standardization**: Unified WebSocket + msgpack protocol
- **Real-robot strategy transfer validation**

---

## 1.7 Verified Pipelines

### Minecraft Game Agent Full Pipeline

```
[Windows 11]
  Minecraft Java Edition (1.20.4)
       ↑ localhost:25565
  mineflayer bridge (Node.js)           ← Bot engine
       ↑ localhost:3001 (HTTP API)
  ngrok tunnel                          ← Public exposure
       ↓ HTTPS

[Linux Cloud — PhyAgentOS-G]
  MinecraftTarget                       ← HTTP client
       ↑
  MinecraftSkillRuntime                 ← Episode driver loop
       ↑
  WatchdogSupervisor                    ← Session supervisor
       ↑
  Agent (Planner/Critic)               ← Dispatches tasks via SESSIONS.md
```

See [Minecraft Scenario Docs](../scenarios/game/minecraft/en/deployment.md) for complete deployment guide.

### LIBERO Benchmark + pi0.5 Closed-Loop

```bash
# TargetWS machine
MUJOCO_GL=egl PYTHONWARNINGS=ignore \
python PhyAgentOS/runtime/targets/remote/libero/server.py --host 0.0.0.0 --port 9002

# Policy machine
python -m PhyAgentOS.runtime.policy.openpi.lerobot_pi0_server \
  --model-dir /path/to/pi05/checkpoint --host 0.0.0.0 --port 8000

# E2E verification
python scripts/run_pi05_libero_real_e2e.py
```

### DummySimTarget Smoke Test

```bash
paos agent -m "run a smoke test using the dummy_sim target"
```

---

## 1.8 Project Structure

```
PhyAgentOS-G/
│
├── PhyAgentOS/agent/          # Track A — Agent Brain
│   ├── loop.py                #   Main agent loop
│   ├── context.py             #   Context window builder
│   ├── memory.py              #   Memory system
│   ├── skills.py              #   Skill loading and execution
│   └── tools/                 #   Built-in tools (file, shell, web)
│
├── PhyAgentOS/runtime/        # Track B — Execution Plane
│   ├── watchdog/              #   WatchdogSupervisor · scheduler · registry
│   ├── sessions/              #   SessionRunner · TargetSessionHandle
│   ├── targets/               #   RolloutTarget implementations
│   │   ├── game/              #   Minecraft target
│   │   ├── local/             #   DummySimTarget
│   │   └── remote/libero/     #   LIBERO TargetWS server + proxy
│   ├── skillruntime/          #   PolicySkillRuntime · BuiltinSkillRuntime
│   │   ├── policy/            #   OpenPI policy runtime
│   │   └── game/              #   Minecraft skill runtime
│   ├── adapters/              #   TargetAdapter · PolicyAdapter · ActionBridge
│   │   ├── libero/            #   LIBERO target adapter
│   │   ├── openpi/            #   OpenPI policy adapters (pi05/dummy)
│   │   └── minecraft/         #   Minecraft adapter
│   ├── policy/openpi/         #   OpenPI client + LeRobot pi0 server
│   ├── perception/            #   Perception runtime · EnvironmentWriter · plugin pipeline
│   ├── preflight/             #   RuntimeCompatibilityPreflight
│   ├── schemas/               #   Pydantic Session/Contract Schema
│   ├── workspace/             #   Runtime workspace lifecycle management
│   └── communication/         #   MsgPack · WebSocket communication
│
├── PhyAgentOS/cli/            # CLI entry (paos agent / onboard / minecraft)
├── PhyAgentOS/skills/         # Agent built-in skills (benchmarking, etc.)
├── PhyAgentOS/config/         # Pydantic configuration model
├── PhyAgentOS/templates/      # Workspace template files (TARGETS.md, etc.)
├── scripts/                   # E2E acceptance scripts · workspace init
├── bridge/                    # TypeScript bridge layer
├── docs/                      # Documentation (Chinese/English)
│   ├── zh/                    #   Chinese docs (framework · user · developer)
│   ├── en/                    #   English docs
│   └── scenarios/game/        #   Game scenario docs (Minecraft)
└── pyproject.toml             # Python package config
```

---

## Further Reading

- [Part 2: User Manual](02-user-manual.md) — Quick start, Minecraft setup, simulation validation, troubleshooting
- [Part 3: Developer Manual](03-developer-manual.md) — API reference, Target/Adapter/Skill development, coding style

> **Next step**: To get the system running, go directly to the [User Manual](02-user-manual.md).
