# PhyAgentOS-G 开发者手册

> 面向二次开发者与研究者：Runtime 架构深度解析、API 接口文档、Target/Adapter/Skill 开发指南。

---

## 目录

- [3.1 手册定位](#31-手册定位)
- [3.2 架构深度解析](#32-架构深度解析)
- [3.3 API 接口文档](#33-api-接口文档)
  - [3.3.1 BaseRolloutTarget 接口](#331-baserollouttarget-接口)
  - [3.3.2 BaseSkillRuntime 接口](#332-baseskillruntime-接口)
  - [3.3.3 TargetAdapter / PolicyAdapter 接口](#333-targetadapter--policyadapter-接口)
  - [3.3.4 WatchdogSupervisor 内部架构](#334-watchdogsupervisor-内部架构)
  - [3.3.5 Agent 侧 API](#335-agent-侧-api)
  - [3.3.6 配置 Schema](#336-配置-schema)
  - [3.3.7 文件协议约定](#337-文件协议约定)
- [3.4 二次开发指南](#34-二次开发指南)
  - [3.4.1 添加新 Game Target](#341-添加新-game-target)
  - [3.4.2 添加新 Adapter](#342-添加新-adapter)
  - [3.4.3 添加新 SkillRuntime](#343-添加新-skillruntime)
  - [3.4.4 扩展感知管线](#344-扩展感知管线)
  - [3.4.5 添加新 Skill](#345-添加新-skill)
- [3.5 代码风格规范](#35-代码风格规范)
- [3.6 实现边界](#36-实现边界)
- [3.7 贡献与提交规则](#37-贡献与提交规则)
- [3.8 模块路径速查](#38-模块路径速查)

---

## 3.1 手册定位

### 适合谁

如果你的目标已经不是"把系统跑起来"，而是：

- 理解 Runtime 架构与各模块分工
- 新增 Game Target（如星露谷、新的游戏环境）
- 编写 TargetAdapter 或 PolicyAdapter
- 开发新的 SkillRuntime
- 扩展感知插件管道
- 为项目补测试、补文档

那么本文档是你的主要参考资料。

### 推荐阅读路径

| 目标 | 建议先读 |
|------|---------|
| 理解 Runtime 通信 | [§3.2](#32-架构深度解析) → [§3.3.7](#337-文件协议约定) |
| 添加新 Game Target | [§3.4.1](#341-添加新-game-target)（参考 MinecraftTarget） |
| 开发 Adapter | [§3.4.2](#342-添加新-adapter)（参考 Libero/OpenPI adapter） |
| 开发 SkillRuntime | [§3.4.3](#343-添加新-skillruntime) |
| 理解架构全貌 | [Part 1 §1.3](01-framework-introduction.md#13-技术架构) → [§3.2](#32-架构深度解析) |

---

## 3.2 架构深度解析

### 3.2.1 核心设计：认知与执行解耦

PhyAgentOS-G 的核心价值是将认知层与执行层通过显式协议解耦。**很多"接口"本质上是文件协议与运行时约定，而不是 Python 函数签名。**

- **Track A（认知层）**：Planner / Critic / Tool / Memory
- **Track B（执行层）**：WatchdogSupervisor / SessionRunner / SkillRuntime / RolloutTarget
- **协议边界**：Markdown 文件承载共享状态，而非跨层 Python 调用

### 3.2.2 运行时文件是"真实状态面"

以下文件通常比类图更重要：

| 文件 | 逻辑含义 |
|------|---------|
| `TARGETS.md` | Target registry 与 endpoint / adapter / config |
| `SKILLRUNTIME.md` | 可执行 skill runtime 声明 |
| `SESSIONS.md` | 执行意图与结果真相 |
| `ENVIRONMENT.md` | 环境状态真相 |
| `EMBODIED.md` | 面向 Agent 的 target 能力描述 |
| `SKILLS.md` | 面向 Agent 的 skill 发现与加载规则 |
| `LESSONS.md` | 失败经验真相 |

**只看代码不看文件会误解系统行为。**

### 3.2.3 模板与运行时文件的区别

| 概念 | 位置 | 含义 |
|------|------|------|
| **模板（templates）** | `PhyAgentOS/templates/` | 定义文件结构与建议字段 |
| **运行时文件** | workspace/ | 真正被 Agent、Watchdog 与 runtime writer 读写的状态面 |

模板定义结构，运行时文件承载真实状态。

---

## 3.3 API 接口文档

### 3.3.1 BaseRolloutTarget 接口

**位置**：`PhyAgentOS/runtime/targets/base.py`

所有 Target 实现的唯一切入点。WatchdogSupervisor 不需要知道 Target 是游戏、仿真还是真机。

```python
class BaseRolloutTarget(ABC):
    def build(self) -> None:
        """初始化目标资源（连接游戏、启动仿真、建立硬件会话等）"""

    def describe(self) -> dict[str, Any]:
        """返回 target 运行时能力声明"""

    def configure_session(self, session_ctx: dict) -> dict:
        """Preflight 接受后，配置 target 端 session 参数"""

    def start_session(self, session_ctx: dict) -> dict:
        """启动 target 端 session 状态"""

    def reset(self, session_ctx: dict) -> dict:
        """重置到初始状态，返回初始观测"""

    def observe(self) -> dict:
        """获取当前观测（图像、状态、游戏快照等）"""

    def action_chunk(self, executable_action_chunk: dict) -> dict:
        """执行动作块，返回 target 执行状态"""

    def execution_status(self) -> dict:
        """返回当前执行状态"""

    def cancel(self, reason: str) -> None:
        """中断执行"""

    def close(self) -> None:
        """释放资源"""

    def describe_target_tools(self) -> dict:
        """返回 target 工具元数据（供 builtin runtime 使用）"""

    def call_target_tool(self, tool_name: str, arguments: dict) -> dict:
        """调用 target 暴露的工具"""
```

#### 参考实现

- **MinecraftTarget**（267 行）：干净的 HTTP 客户端，连接外部 mineflayer bridge。是 Game Target 的最佳参考模板。
  - 位置：`PhyAgentOS/runtime/targets/game/minecraft_target.py`
- **DummySimTarget**（118 行）：全模拟 target，返回 numpy 零数组，5 步后自动 success。适合冒烟测试。
  - 位置：`PhyAgentOS/runtime/targets/local/dummy_sim_target.py`

### 3.3.2 BaseSkillRuntime 接口

**位置**：`PhyAgentOS/runtime/skillruntime/base.py`

SkillRuntime 负责"怎么跑"的执行策略：

```python
class BaseSkillRuntime(ABC):
    def start(self, skill_ctx: SkillContext) -> None:
        """初始化 skill 执行上下文"""

    def cancel(self, skill_ctx: SkillContext, reason: str) -> None:
        """中断执行"""

    def snapshot(self, skill_ctx: SkillContext) -> dict:
        """返回 skill 当前快照"""
```

#### Skill Runtime 分类

```
BaseSkillRuntime
├── PolicySkillRuntime       # 维护策略闭环（observe → predict → action → step）
│   └── OpenPISkillRuntime  # pi0.5 OpenPI 策略循环（100 行）
└── BuiltinSkillRuntime      # 管理 Agent 交互闭环
    └── MinecraftSkillRuntime  # Minecraft episode 驱动循环（241 行）
```

**关键设计**：skill runtime 专注"怎么跑"，target 专注"怎么执行"，adapter 专注"怎么翻译"。三者职责清晰分离。

### 3.3.3 TargetAdapter / PolicyAdapter 接口

**位置**：`PhyAgentOS/runtime/adapters/base.py`

**TargetAdapter**：将 Target 原始观测转换为 Runtime 统一格式。

```python
class BaseTargetAdapter(ABC):
    def output_observation_contract(self) -> dict:
        """声明本 adapter 输出的观测格式契约"""

    def input_action_contract(self) -> dict:
        """声明本 adapter 期望的动作格式契约"""

    def to_runtime_observation(self, raw_obs: dict, target_info: dict) -> dict:
        """将原始观测转换为 Runtime 统一观测"""
```

**PolicyAdapter**：将 Runtime 观测转换为 Policy 输入格式。

```python
class BasePolicyAdapter(ABC):
    def input_observation_contract(self) -> dict:
        """声明本 adapter 输入的观测格式"""

    def output_action_contract(self) -> dict:
        """声明本 adapter 输出的动作格式"""

    def to_policy_input(self, runtime_obs: dict) -> dict:
        """将 Runtime 观测转换为 Policy 输入"""

    def from_policy_output(self, policy_output: dict) -> dict:
        """将 Policy 输出转换为 Runtime 动作"""
```

**ActionBridge**：桥接 Policy 输出到 Target 输入。

#### 已实现 Adapter

| Adapter | 类型 | 位置 |
|---------|------|------|
| LiberoTargetAdapter | TargetAdapter | `PhyAgentOS/runtime/adapters/libero/target_adapter.py` |
| OpenPIPi05Adapter | PolicyAdapter | `PhyAgentOS/runtime/adapters/openpi/pi05_policy_adapter.py` |
| DummyOpenPIAdapter | PolicyAdapter | `PhyAgentOS/runtime/adapters/openpi/dummy_openpi_adapter.py` |
| MinecraftAdapter | TargetAdapter | `PhyAgentOS/runtime/adapters/minecraft/minecraft_adapter.py` |

### 3.3.4 WatchdogSupervisor 内部架构

**位置**：`PhyAgentOS/runtime/watchdog/supervisor.py`（248 行）

```
WatchdogSupervisor
├── WorkspaceWatcher         # 监听 SESSIONS.md / TARGETS.md 变化
├── SessionRegistry          # Session 生命周期管理
├── SessionScheduler         # 根据 target/skill/priority 分发
├── TargetRuntimeRegistry    # Target 工厂/清单
├── SkillRuntimeRegistry     # Skill runtime 工厂/清单
├── HealthMonitor            # Policy server / target / session 健康监控
├── ResultWriter             # 统一写回 SESSIONS.md / ENVIRONMENT.md / LESSONS.md
└── FailureEscalator         # retry / reset / cancel / notify
```

#### Session 状态机

```
pending → claimed → running → succeeded / failed / timed_out
pending → rejected
running → cancelling → cancelled
```

#### Session 校验-分发-执行链路

```
1. Agent 形成任务意图
2. Agent 从 TARGETS.md / SKILLRUNTIME.md 解析 target 与 skill runtime
3. Agent 向 SESSIONS.md 追加 pending session
4. WatchdogSupervisor claim session，执行 RuntimeCompatibilityPreflight
5. SessionRunner 运行 target/skill runtime
6. 结果回写到 SESSIONS.md、ENVIRONMENT.md、artifacts
```

排查时要区分：任务生成有问题 / target 或 skillruntime 不匹配 / preflight 拒绝 / Watchdog 执行失败 / 执行成功但环境未回写。

### 3.3.5 Agent 侧 API

#### Agent Loop

**位置**：`PhyAgentOS/agent/loop.py`

工作流：
1. 从 bootstrap 文件（`AGENTS.md`、`SOUL.md`、`USER.md`、`SKILLS.md`）以及 `ENVIRONMENT.md`、`EMBODIED.md`、`LESSONS.md` 等状态文件构建上下文
2. 调用 LLM 进行规划和推理
3. 处理工具调用与 skill 引导的工作流
4. 需要 Runtime 执行时，读取 `TARGETS.md` / `SKILLRUNTIME.md` 并将任务追加到 `SESSIONS.md`

#### Skill 系统

**位置**：`PhyAgentOS/agent/skills.py`

每个 Skill 是一个目录，包含 `SKILL.md` 定义文件和可选执行脚本。现有内置 Skill 包括：
`agent-mode`、`benchmarking`、`clawhub`、`cron`、`github`、`image`、`memory`、
`pipergo2-demo`、`rekep-robot-onboarding`、`robot-management-guideline`、
`skill-creator`、`summarize`、`tmux`、`weather`。

#### CLI 入口

| 命令 | 说明 |
|------|------|
| `paos onboard` | 初始化工作区，同步模板文件 |
| `paos agent` | 启动交互式 Agent CLI |
| `paos agent -m "..."` | 单轮消息调用 |
| `paos minecraft` | Minecraft 游戏控制命令 |

### 3.3.6 配置 Schema

**位置**：`PhyAgentOS/config/schema.py`

Pydantic 配置模型核心结构：

```python
class Config(BaseModel):
    agents: AgentsConfig
    providers: ProvidersConfig
    gateway: GatewayConfig | None
    tools: ToolsConfig | None
    runtime: RuntimeConfig | None    # Runtime workspace 配置
```

### 3.3.7 文件协议约定

#### SESSIONS.md 格式

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

#### TARGETS.md 格式

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

#### SKILLRUNTIME.md 格式

```yaml
version: skillruntimes_v1
skillruntimes:
  - id: skillruntime://minecraft_game/v1
    kind: builtin
    module: PhyAgentOS.runtime.skillruntime.game.minecraft_skill_runtime
    class: MinecraftSkillRuntime
```

---

## 3.4 二次开发指南

### 3.4.1 添加新 Game Target

引入新游戏只需实现 `BaseRolloutTarget` 子类（约 100-300 行）。推荐参考 `MinecraftTarget`。

**步骤**：

1. 在 `PhyAgentOS/runtime/targets/game/` 中新增 Target 实现
2. 继承 `BaseRolloutTarget`（local target 可继承 `BaseLocalTarget`）
3. 实现全部 12 个抽象方法
4. 在 `PhyAgentOS/runtime/targets/factory.py` 中注册
5. 在 `TARGETS.md` 中配置 endpoint、adapter、supported_skillruntimes

**最小实现模板**：

```python
class StardewTarget(BaseRolloutTarget):
    def build(self) -> None:
        # 连接 SMAPI mod (HTTP)
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
        # 重置到新的一天，返回初始观测
        return self.observe()

    def observe(self) -> dict:
        # HTTP GET /state → 返回游戏快照
        return {"position": ..., "time": ..., "inventory": ..., "npc_relations": ...}

    def action_chunk(self, action_chunk: dict) -> dict:
        # HTTP POST /action → 执行动作
        return {"accepted": True, "obs": self.observe()}

    def execution_status(self) -> dict:
        return {"health": "ok"}

    def configure_session(self, ctx): return {}
    def start_session(self, ctx): return {}
    def cancel(self, reason): pass
    def close(self): pass
```

**不需要懂**：WatchdogSupervisor、Session 状态机、Preflight、文件协议——Base 层和 Runtime 已处理。

### 3.4.2 添加新 Adapter

#### TargetAdapter

用于转换 Target 原始观测格式。参考 `LiberoTargetAdapter`（152 行）。

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
        return {
            "id": "my_action_v1",
            "shape": ["T", 7],
        }

    def to_runtime_observation(self, raw_obs: dict, target_info: dict) -> dict:
        # 转换原始观测 → Runtime 统一格式
        return {
            "image": {"front_rgb": raw_obs["rgb"]},
            "state": {"position": raw_obs["pos"]},
        }
```

#### PolicyAdapter

用于转换 Runtime 观测 ↔ Policy 输入/输出。参考 `OpenPIPi05Adapter`（75 行）。

### 3.4.3 添加新 SkillRuntime

```python
class MySkillRuntime(PolicySkillRuntime):
    def start(self, skill_ctx: SkillContext) -> None:
        # 初始化策略参数
        pass

    def run_policy_loop(
        self,
        skill_ctx: SkillContext,
        policy_client: BasePolicyClient,
        handle: TargetSessionHandle,
        max_steps: int,
    ) -> SkillRuntimeResult:
        # observe → adapt → predict → adapt → act → loop
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

参考：`OpenPISkillRuntime`（100 行）、`MinecraftSkillRuntime`（241 行）。

### 3.4.4 扩展感知管线

**位置**：`PhyAgentOS/runtime/perception/`

感知管线分层结构：

```
PerceptionRuntime
  → SensorFrameBuilder      # 从 Target 观测构建 SensorFrame
    → PluginPipeline         # 执行感知插件链
      → EnvironmentWriter    # 将感知结果写入 ENVIRONMENT.md
```

**已有插件**（`PhyAgentOS/plugins/perception_plugins/`）：

| 插件 | 说明 |
|------|------|
| `dummy_segmenter` | 冒烟测试分割器 |
| `sam3_open_vocab` | SAM3 开放词汇分割 |
| `yolo_seg` | YOLO 实例分割 |
| `rgbd_object_builder` | RGBD 物体构建 |
| `sim_oracle` | 仿真 oracle 感知 |

**添加新插件**：继承 `BasePerceptionPlugin`，实现 `process(sensor_frame) → SensorFrame`。

### 3.4.5 添加新 Skill

每个 Skill 是一个目录，包含 `SKILL.md` 定义文件：

```
PhyAgentOS/skills/my-skill/
├── SKILL.md      # Skill 元数据与 Prompt
└── run.sh        # 执行入口（可选）
```

**SKILL.md 格式**：

```markdown
# Skill Name
Description of what this skill does.

## Parameters
- param1: description

## Usage
...
```

参考：`PhyAgentOS/skills/benchmarking/SKILL.md`

---

## 3.5 代码风格规范

### Python

| 规范项 | 要求 |
|--------|------|
| Python 版本 | ≥ 3.11 |
| 行长度 | 最大 100 字符 |
| Lint 工具 | ruff |
| Lint 规则 | E / F / I / N / W |
| 忽略规则 | E501（行长度由 ruff formatter 处理） |
| 类型注解 | 所有公开函数必须添加类型注解 |
| 文档字符串 | 使用 Google 风格 docstring |
| 导入顺序 | isort 自动排序（标准库 → 第三方 → 项目内部） |

### Pydantic Schema 惯例

- 所有运行时数据结构使用 Pydantic BaseModel 定义
- 字段使用明确的类型注解和 default 值
- 复杂嵌套字段单独定义 model

### 文件组织

- 每个模块一个明确职责
- Target、Adapter、SkillRuntime 各自独立
- 感知管线分层清晰

---

## 3.6 实现边界

### 绝对禁止的跨界行为

| 组件 | 绝不能知道 |
|------|-----------|
| **RolloutTarget** | Policy 推理、Skill 逻辑、上层 Agent |
| **SkillRuntime** | Target 内部实现细节 |
| **TargetAdapter** | Policy 推理、Target 内部状态 |
| **WatchdogSupervisor** | 具体怎么执行 step |

### 设计护栏

1. **Base 层不 import 任何场景模块**
2. **每新增场景 = ~100 行 BaseRolloutTarget 子类**
3. **三个场景（Game / Simulation / Real Robot）并行不阻塞**
4. **真实机器人最终安全裁决必须留在本地控制机**（不在云端 Agent 侧做最终 stop 决定）

---

## 3.7 贡献与提交规则

### Commit 规范

- 使用语义化提交信息：`feat:` / `fix:` / `docs:` / `refactor:` / `test:` / `chore:`
- 一个 commit 做一件事
- 不要在 commit 中包含 secrets（`.env`、credentials 等）

### 文档维护分层

| 文档层 | 目标读者 | 变更触发条件 |
|--------|---------|-------------|
| README | 所有人 | 重大特性变更 |
| 框架介绍 | 所有人 | 架构演进、新特性、路线图更新 |
| 用户手册 | 使用者 | 命令变更、配置变化、新场景支持 |
| 开发者手册 | 开发者 | API 变更、新模块、流程变化 |

---

## 3.8 模块路径速查

| 功能 | 路径 |
|------|------|
| Runtime Watchdog | `PhyAgentOS/runtime/watchdog/supervisor.py` |
| Session Runner | `PhyAgentOS/runtime/sessions/` |
| Target 基类 | `PhyAgentOS/runtime/targets/base.py` |
| Minecraft Target | `PhyAgentOS/runtime/targets/game/minecraft_target.py` |
| DummySim Target | `PhyAgentOS/runtime/targets/local/dummy_sim_target.py` |
| LIBERO TargetWS | `PhyAgentOS/runtime/targets/remote/libero/server.py` |
| Skill Runtime 基类 | `PhyAgentOS/runtime/skillruntime/base.py` |
| OpenPI SkillRuntime | `PhyAgentOS/runtime/skillruntime/policy/openpi.py` |
| Minecraft SkillRuntime | `PhyAgentOS/runtime/skillruntime/game/minecraft_skill_runtime.py` |
| Adapter 基类 | `PhyAgentOS/runtime/adapters/base.py` |
| LIBERO TargetAdapter | `PhyAgentOS/runtime/adapters/libero/target_adapter.py` |
| OpenPI PolicyAdapter | `PhyAgentOS/runtime/adapters/openpi/pi05_policy_adapter.py` |
| Preflight | `PhyAgentOS/runtime/preflight/runtime_compatibility_preflight.py` |
| Perception Runtime | `PhyAgentOS/runtime/perception/perception_runtime.py` |
| Agent Loop | `PhyAgentOS/agent/loop.py` |
| Agent Context | `PhyAgentOS/agent/context.py` |
| Agent Skill 系统 | `PhyAgentOS/agent/skills.py` |
| 配置 Schema | `PhyAgentOS/config/schema.py` |
| CLI 入口 | `PhyAgentOS/cli/commands.py` |
| E2E 脚本 | `scripts/run_pi05_libero_real_e2e.py` |

---

## 后续阅读

- [Part 1: 框架介绍](01-framework-introduction.md) — 设计理念、架构、路线图
- [Part 2: 用户手册](02-user-manual.md) — 快速开始、场景配置、排障指南
