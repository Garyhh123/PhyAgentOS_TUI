# PhyAgentOS-G Developer Manual

> For secondary developers and researchers: Runtime architecture deep dive, API reference, Target/Adapter/Skill development guide.

---

## Table of Contents

- [3.1 Manual Scope](#31-manual-scope)
- [3.2 Architecture Deep Dive](#32-architecture-deep-dive)
- [3.3 API Reference](#33-api-reference)
  - [3.3.1 BaseRolloutTarget Interface](#331-baserollouttarget-interface)
  - [3.3.2 BaseSkillRuntime Interface](#332-baseskillruntime-interface)
  - [3.3.3 TargetAdapter / PolicyAdapter Interface](#333-targetadapter--policyadapter-interface)
  - [3.3.4 WatchdogSupervisor Internals](#334-watchdogsupervisor-internals)
  - [3.3.5 Agent-Side API](#335-agent-side-api)
  - [3.3.6 Configuration Schema](#336-configuration-schema)
  - [3.3.7 File Protocol Conventions](#337-file-protocol-conventions)
- [3.4 Development Guide](#34-development-guide)
  - [3.4.1 Adding a New Game Target](#341-adding-a-new-game-target)
  - [3.4.2 Adding a New Adapter](#342-adding-a-new-adapter)
  - [3.4.3 Adding a New SkillRuntime](#343-adding-a-new-skillruntime)
  - [3.4.4 Extending Perception Pipeline](#344-extending-perception-pipeline)
  - [3.4.5 Adding a New Skill](#345-adding-a-new-skill)
- [3.5 Code Style](#35-code-style)
- [3.6 Implementation Boundaries](#36-implementation-boundaries)
- [3.7 Contribution Guidelines](#37-contribution-guidelines)
- [3.8 Module Path Quick Reference](#38-module-path-quick-reference)

---

## 3.1 Manual Scope

### Who This Is For

If your goal goes beyond "getting the system running":

- Understanding Runtime architecture and module responsibilities
- Adding new Game Targets (e.g., Stardew Valley, new game environments)
- Writing TargetAdapters or PolicyAdapters
- Developing new SkillRuntimes
- Extending perception plugin pipelines
- Contributing tests or documentation

Then this document is your primary reference.

### Recommended Reading Path

| Goal | Start With |
|------|-----------|
| Understand Runtime communication | [§3.2](#32-architecture-deep-dive) → [§3.3.7](#337-file-protocol-conventions) |
| Add a new Game Target | [§3.4.1](#341-adding-a-new-game-target) (reference MinecraftTarget) |
| Develop an Adapter | [§3.4.2](#342-adding-a-new-adapter) (reference Libero/OpenPI adapters) |
| Develop a SkillRuntime | [§3.4.3](#343-adding-a-new-skillruntime) |
| Understand full architecture | [Part 1 §1.3](01-framework-introduction.md#13-technical-architecture) → [§3.2](#32-architecture-deep-dive) |

---

## 3.2 Architecture Deep Dive

### 3.2.1 Core Design: Cognitive-Execution Decoupling

PhyAgentOS-G's core value is decoupling the cognitive layer from the execution layer through explicit protocols. **Many "interfaces" are file protocols and runtime conventions, not Python function signatures.**

- **Track A (Cognitive)**: Planner / Critic / Tool / Memory
- **Track B (Execution)**: WatchdogSupervisor / SessionRunner / SkillRuntime / RolloutTarget
- **Protocol Boundary**: Markdown files carry shared state, not cross-layer Python calls

### 3.2.2 Runtime Files Are the "Truth Surface"

These files are usually more important than class diagrams:

| File | Logical Meaning |
|------|---------|
| `TARGETS.md` | Target registry with endpoint/adapter/config |
| `SKILLRUNTIME.md` | Executable skill runtime declarations |
| `SESSIONS.md` | Execution intent and result truth |
| `ENVIRONMENT.md` | Environment state truth |
| `EMBODIED.md` | Agent-facing target capability descriptions |
| `SKILLS.md` | Agent-facing skill discovery and loading rules |
| `LESSONS.md` | Failure experience truth |

**Reading code without reading files will mislead your understanding of system behavior.**

### 3.2.3 Templates vs Runtime Files

| Concept | Location | Meaning |
|------|------|------|
| **Templates** | `PhyAgentOS/templates/` | Define file structure and suggested fields |
| **Runtime Files** | workspace/ | The actual state surface read/written by Agent, Watchdog, and runtime writers |

Templates define structure; runtime files carry real state.

---

## 3.3 API Reference

### 3.3.1 BaseRolloutTarget Interface

**Location**: `PhyAgentOS/runtime/targets/base.py`

The single entry point for all Target implementations. WatchdogSupervisor doesn't need to know whether the Target is a game, simulation, or real robot.

```python
class BaseRolloutTarget(ABC):
    def build(self) -> None:
        """Initialize target resources (connect game, start sim, establish hardware session)"""

    def describe(self) -> dict[str, Any]:
        """Return target runtime capability declaration"""

    def configure_session(self, session_ctx: dict) -> dict:
        """Configure target-side session after preflight acceptance"""

    def start_session(self, session_ctx: dict) -> dict:
        """Start target-side session state"""

    def reset(self, session_ctx: dict) -> dict:
        """Reset to initial state, return initial observation"""

    def observe(self) -> dict:
        """Get current observation (images, state, game snapshot, etc.)"""

    def action_chunk(self, executable_action_chunk: dict) -> dict:
        """Execute action chunk, return target execution status"""

    def execution_status(self) -> dict:
        """Return current execution status"""

    def cancel(self, reason: str) -> None:
        """Interrupt execution"""

    def close(self) -> None:
        """Release resources"""

    def describe_target_tools(self) -> dict:
        """Return target tool metadata (for builtin runtimes)"""

    def call_target_tool(self, tool_name: str, arguments: dict) -> dict:
        """Call a target-exposed tool"""
```

#### Reference Implementations

- **MinecraftTarget** (267 lines): Clean HTTP client connecting to external mineflayer bridge. Best reference for Game Targets.
  - Location: `PhyAgentOS/runtime/targets/game/minecraft_target.py`
- **DummySimTarget** (118 lines): Fully mocked target, returns numpy zero arrays, auto-succeeds after 5 steps.
  - Location: `PhyAgentOS/runtime/targets/local/dummy_sim_target.py`

### 3.3.2 BaseSkillRuntime Interface

**Location**: `PhyAgentOS/runtime/skillruntime/base.py`

SkillRuntime is responsible for "how to run" the execution strategy:

```python
class BaseSkillRuntime(ABC):
    def start(self, skill_ctx: SkillContext) -> None:
        """Initialize skill execution context"""

    def cancel(self, skill_ctx: SkillContext, reason: str) -> None:
        """Interrupt execution"""

    def snapshot(self, skill_ctx: SkillContext) -> dict:
        """Return current skill snapshot"""
```

#### Skill Runtime Hierarchy

```
BaseSkillRuntime
├── PolicySkillRuntime       # Maintains policy closed-loop (observe→predict→action→step)
│   └── OpenPISkillRuntime  # pi0.5 OpenPI policy loop (100 lines)
└── BuiltinSkillRuntime      # Manages Agent interactive loop
    └── MinecraftSkillRuntime  # Minecraft episode driver loop (241 lines)
```

**Key design**: Skill runtime focuses on "how to run", target on "how to execute", adapter on "how to translate". Clear separation of concerns.

### 3.3.3 TargetAdapter / PolicyAdapter Interface

**Location**: `PhyAgentOS/runtime/adapters/base.py`

**TargetAdapter**: Converts Target raw observations to Runtime unified format.

```python
class BaseTargetAdapter(ABC):
    def output_observation_contract(self) -> dict:
        """Declare the observation format contract output by this adapter"""

    def input_action_contract(self) -> dict:
        """Declare the action format contract expected by this adapter"""

    def to_runtime_observation(self, raw_obs: dict, target_info: dict) -> dict:
        """Convert raw observation to Runtime unified observation"""
```

**PolicyAdapter**: Converts Runtime observations to/from Policy input/output.

```python
class BasePolicyAdapter(ABC):
    def input_observation_contract(self) -> dict: ...
    def output_action_contract(self) -> dict: ...
    def to_policy_input(self, runtime_obs: dict) -> dict: ...
    def from_policy_output(self, policy_output: dict) -> dict: ...
```

#### Implemented Adapters

| Adapter | Type | Location |
|---------|------|------|
| LiberoTargetAdapter | TargetAdapter | `PhyAgentOS/runtime/adapters/libero/target_adapter.py` |
| OpenPIPi05Adapter | PolicyAdapter | `PhyAgentOS/runtime/adapters/openpi/pi05_policy_adapter.py` |
| DummyOpenPIAdapter | PolicyAdapter | `PhyAgentOS/runtime/adapters/openpi/dummy_openpi_adapter.py` |
| MinecraftAdapter | TargetAdapter | `PhyAgentOS/runtime/adapters/minecraft/minecraft_adapter.py` |

### 3.3.4 WatchdogSupervisor Internals

**Location**: `PhyAgentOS/runtime/watchdog/supervisor.py` (248 lines)

```
WatchdogSupervisor
├── WorkspaceWatcher         # Monitors SESSIONS.md / TARGETS.md changes
├── SessionRegistry          # Session lifecycle management
├── SessionScheduler         # Dispatches by target/skill/priority
├── TargetRuntimeRegistry    # Target factory/manifest
├── SkillRuntimeRegistry     # Skill runtime factory/manifest
├── HealthMonitor            # Policy server / target / session health
├── ResultWriter             # Unified writeback to SESSIONS.md / ENVIRONMENT.md / LESSONS.md
└── FailureEscalator         # retry / reset / cancel / notify
```

#### Session State Machine

```
pending → claimed → running → succeeded / failed / timed_out
pending → rejected
running → cancelling → cancelled
```

#### Session Validation-Dispatch-Execution Chain

```
1. Agent forms task intent
2. Agent resolves target & skill runtime from TARGETS.md / SKILLRUNTIME.md
3. Agent appends pending session to SESSIONS.md
4. WatchdogSupervisor claims session, runs RuntimeCompatibilityPreflight
5. SessionRunner executes target/skill runtime
6. Results written back to SESSIONS.md, ENVIRONMENT.md, artifacts
```

### 3.3.5 Agent-Side API

#### Agent Loop

**Location**: `PhyAgentOS/agent/loop.py`

Workflow:
1. Build context from bootstrap files (`AGENTS.md`, `SOUL.md`, `USER.md`, `SKILLS.md`) and state files (`ENVIRONMENT.md`, `EMBODIED.md`, `LESSONS.md`)
2. Call LLM for planning and reasoning
3. Process tool calls and skill-guided workflows
4. When Runtime execution needed, read `TARGETS.md` / `SKILLRUNTIME.md` and append tasks to `SESSIONS.md`

#### CLI Entry Points

| Command | Description |
|------|------|
| `paos onboard` | Initialize workspace, sync template files |
| `paos agent` | Start interactive Agent CLI |
| `paos agent -m "..."` | Single-turn message call |
| `paos minecraft` | Minecraft game control commands |

### 3.3.6 Configuration Schema

**Location**: `PhyAgentOS/config/schema.py`

```python
class Config(BaseModel):
    agents: AgentsConfig
    providers: ProvidersConfig
    gateway: GatewayConfig | None
    tools: ToolsConfig | None
    runtime: RuntimeConfig | None    # Runtime workspace config
```

### 3.3.7 File Protocol Conventions

#### SESSIONS.md Format

```yaml
version: runtime_sessions_v1
sessions:
  - session_id: sess_example
    target_ref: target://dummy_sim
    skillruntime_ref: skillruntime://openpi_sim_vla
    task_description: run a smoke test
    status: pending
    priority: normal
```

#### TARGETS.md Format

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

---

## 3.4 Development Guide

### 3.4.1 Adding a New Game Target

Adding a new game requires only a `BaseRolloutTarget` subclass (~100-300 lines). Reference `MinecraftTarget`.

**Steps**:

1. Create Target implementation in `PhyAgentOS/runtime/targets/game/`
2. Inherit from `BaseRolloutTarget` (local targets can use `BaseLocalTarget`)
3. Implement all abstract methods
4. Register in `PhyAgentOS/runtime/targets/factory.py`
5. Configure endpoint, adapter, supported_skillruntimes in `TARGETS.md`

**Minimal Template**:

```python
class StardewTarget(BaseRolloutTarget):
    def build(self) -> None:
        # Connect to SMAPI mod (HTTP)
        pass

    def describe(self) -> dict:
        return {
            "runtime": "StardewGameRuntime",
            "observation_schema": {
                "position": {"dtype": "int", "shape": [2]},
                "time": {"dtype": "str"},
                "inventory": {"dtype": "list"},
            },
            "action_contract": {
                "id": "stardew_game_v1",
                "types": ["move_to", "use_tool", "interact", "sleep"],
            },
        }

    def reset(self, session_ctx: dict) -> dict:
        return self.observe()

    def observe(self) -> dict:
        return {"position": ..., "time": ..., "inventory": ..., "npc_relations": ...}

    def action_chunk(self, action_chunk: dict) -> dict:
        return {"accepted": True, "obs": self.observe()}

    def execution_status(self) -> dict:
        return {"health": "ok"}

    def configure_session(self, ctx): return {}
    def start_session(self, ctx): return {}
    def cancel(self, reason): pass
    def close(self): pass
```

### 3.4.2 Adding a New Adapter

#### TargetAdapter

Converts target raw observation format. Reference `LiberoTargetAdapter` (152 lines).

```python
class MyTargetAdapter(BaseTargetAdapter):
    def output_observation_contract(self) -> dict:
        return {
            "sensors": {
                "front_rgb": {"kind": "image", "dtype": "uint8", "layout": "HWC"},
            },
            "state": {
                "position": {"dtype": "float32", "shape": [3]},
            },
        }

    def input_action_contract(self) -> dict:
        return {"id": "my_action_v1", "shape": ["T", 7]}

    def to_runtime_observation(self, raw_obs: dict, target_info: dict) -> dict:
        return {
            "image": {"front_rgb": raw_obs["rgb"]},
            "state": {"position": raw_obs["pos"]},
        }
```

### 3.4.3 Adding a New SkillRuntime

```python
class MySkillRuntime(PolicySkillRuntime):
    def start(self, skill_ctx: SkillContext) -> None: ...

    def run_policy_loop(
        self, skill_ctx, policy_client, handle, max_steps
    ) -> SkillRuntimeResult:
        for _ in range(max_steps):
            obs = handle.observe()
            runtime_obs = handle.adapt_observation(obs)
            action = policy_client.predict(runtime_obs)
            status = handle.execute_action(action)
            if status.get("done"):
                break
        return SkillRuntimeResult(success=True, metrics={})

    def cancel(self, skill_ctx, reason): ...
    def snapshot(self, skill_ctx) -> dict: ...
```

Reference: `OpenPISkillRuntime` (100 lines), `MinecraftSkillRuntime` (241 lines).

### 3.4.4 Extending Perception Pipeline

**Location**: `PhyAgentOS/runtime/perception/`

Pipeline structure:

```
PerceptionRuntime
  → SensorFrameBuilder      # Builds SensorFrame from Target observation
    → PluginPipeline         # Executes perception plugin chain
      → EnvironmentWriter    # Writes perception results to ENVIRONMENT.md
```

**Existing plugins** (`PhyAgentOS/plugins/perception_plugins/`):

| Plugin | Description |
|------|------|
| `dummy_segmenter` | Smoke test segmenter |
| `sam3_open_vocab` | SAM3 open-vocabulary segmentation |
| `yolo_seg` | YOLO instance segmentation |
| `rgbd_object_builder` | RGBD object builder |
| `sim_oracle` | Simulation oracle perception |

**Adding a new plugin**: Inherit from `BasePerceptionPlugin`, implement `process(sensor_frame) → SensorFrame`.

### 3.4.5 Adding a New Skill

Each skill is a directory containing a `SKILL.md` definition file:

```
PhyAgentOS/skills/my-skill/
├── SKILL.md      # Skill metadata & prompt
└── run.sh        # Execution entry (optional)
```

Reference: `PhyAgentOS/skills/benchmarking/SKILL.md`

---

## 3.5 Code Style

### Python

| Rule | Requirement |
|------|------|
| Python version | ≥ 3.11 |
| Line length | Max 100 chars |
| Lint tool | ruff |
| Lint rules | E / F / I / N / W |
| Ignored rules | E501 (line length handled by ruff formatter) |
| Type hints | All public functions must have type annotations |
| Docstrings | Google style |
| Import order | isort auto-sorted (stdlib → third-party → project internal) |

### File Organization

- Each module has a single clear responsibility
- Target, Adapter, SkillRuntime are independent
- Perception pipeline is cleanly layered

---

## 3.6 Implementation Boundaries

### Strictly Forbidden Cross-Layer Access

| Component | Must Never Know |
|------|-----------|
| **RolloutTarget** | Policy inference, Skill logic, upper Agent |
| **SkillRuntime** | Target internal implementation details |
| **TargetAdapter** | Policy inference, Target internal state |
| **WatchdogSupervisor** | How to execute individual steps |

### Design Guardrails

1. **Base layer never imports scenario modules**
2. **Each new scenario ≈ 100-line BaseRolloutTarget subclass**
3. **Three scenarios (Game / Simulation / Real Robot) develop in parallel without blocking**
4. **Real robot final safety arbitration must stay on local control machine**

---

## 3.7 Contribution Guidelines

### Commit Convention

- Use semantic commit messages: `feat:` / `fix:` / `docs:` / `refactor:` / `test:` / `chore:`
- One commit per logical change
- Never include secrets in commits (`.env`, credentials, etc.)

### Documentation Maintenance Layers

| Layer | Audience | Change Trigger |
|------|---------|-------------|
| README | Everyone | Major feature changes |
| Framework Introduction | Everyone | Architecture evolution, new features, roadmap updates |
| User Manual | Users | Command changes, config structure changes, new scenario support |
| Developer Manual | Developers | API changes, new modules, process changes |

---

## 3.8 Module Path Quick Reference

| Functionality | Path |
|------|------|
| Runtime Watchdog | `PhyAgentOS/runtime/watchdog/supervisor.py` |
| Session Runner | `PhyAgentOS/runtime/sessions/` |
| Target Base | `PhyAgentOS/runtime/targets/base.py` |
| Minecraft Target | `PhyAgentOS/runtime/targets/game/minecraft_target.py` |
| DummySim Target | `PhyAgentOS/runtime/targets/local/dummy_sim_target.py` |
| LIBERO TargetWS | `PhyAgentOS/runtime/targets/remote/libero/server.py` |
| Skill Runtime Base | `PhyAgentOS/runtime/skillruntime/base.py` |
| OpenPI SkillRuntime | `PhyAgentOS/runtime/skillruntime/policy/openpi.py` |
| Minecraft SkillRuntime | `PhyAgentOS/runtime/skillruntime/game/minecraft_skill_runtime.py` |
| Adapter Base | `PhyAgentOS/runtime/adapters/base.py` |
| LIBERO TargetAdapter | `PhyAgentOS/runtime/adapters/libero/target_adapter.py` |
| OpenPI PolicyAdapter | `PhyAgentOS/runtime/adapters/openpi/pi05_policy_adapter.py` |
| Preflight | `PhyAgentOS/runtime/preflight/runtime_compatibility_preflight.py` |
| Perception Runtime | `PhyAgentOS/runtime/perception/perception_runtime.py` |
| Agent Loop | `PhyAgentOS/agent/loop.py` |
| Agent Context | `PhyAgentOS/agent/context.py` |
| Agent Skill System | `PhyAgentOS/agent/skills.py` |
| Configuration Schema | `PhyAgentOS/config/schema.py` |
| CLI Entry | `PhyAgentOS/cli/commands.py` |
| E2E Scripts | `scripts/run_pi05_libero_real_e2e.py` |

---

## Further Reading

- [Part 1: Framework Introduction](01-framework-introduction.md) — Design philosophy, architecture, roadmap
- [Part 2: User Manual](02-user-manual.md) — Quick start, scenario setup, troubleshooting
