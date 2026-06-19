# PhyAgentOS × Minecraft — Agent 闭环

> 承接 [1_hello.md](1_hello.md)。Agent 通过 SESSIONS.md 下发给 WatchdogSupervisor 执行，形成多轮观察-推理-交互闭环。
> <br>**当前状态：已完整可运行。** 同时支持 <b>Runtime Session Protocol</b> 和 <b>Direct Bridge API</b> 两条路径。

---

## 已验证链路

<p>
<table>
<tr><td>✅</td><td><code>paos agent --workspace</code> 启动</td><td>RuntimeWorkspaceManager 部署模板 + 启动 watchdog</td></tr>
<tr><td>✅</td><td>ContextBuilder 注入 TARGETS.md/SKILLRUNTIME.md</td><td>Agent 系统提示词自动感知</td></tr>
<tr><td>✅</td><td>EMBODIED.md 自动部署</td><td>检测 minecraft_java_env，部署 16 种动作 + Critic Guidance</td></tr>
<tr><td>✅</td><td>Agent 用 write_file 写 SESSIONS.md</td><td>YAML 格式正确</td></tr>
<tr><td>✅</td><td>WatchdogSupervisor 拾取 session</td><td>Preflight 通过</td></tr>
<tr><td>✅</td><td>SessionRunner → SafetyClampBridge</td><td>dict action 自动透传</td></tr>
<tr><td>⚠️</td><td>MinecraftTarget.build()</td><td>需要 bridge_url 非空，否则 TARGET_CONNECTION</td></tr>
<tr><td>✅</td><td>action_chunk → bridge HTTP POST</td><td>MinecraftAdapter → MinecraftTarget → HTTP</td></tr>
<tr><td>✅</td><td>动作结果校验</td><td>run_builtin_loop() 检查 ok/result</td></tr>
<tr><td>✅</td><td>ENVIRONMENT.md 回写</td><td>ResultWriter 自动更新</td></tr>
<tr><td>✅</td><td>Agent 读结果验证</td><td>Agent 读 ENVIRONMENT.md 确认</td></tr>
</table>
</p>

<p>
<details>
<summary><b>📐 运行时架构图</b></summary>

```
paos agent --workspace workspaces/minecraft
  │
  ├─ RuntimeWorkspaceManager     ← 部署 TARGETS.md/SKILLRUNTIME.md/EMBODIED.md
  ├─ BackgroundWatchdog          ← daemon 线程，轮询 SESSIONS.md
  │    └─ WatchdogSupervisor     ← preflight → resolve → SessionRunner
  │         ├─ TargetRegistry    ← MinecraftTargetRuntime (factory.py:82)
  │         ├─ SkillRegistry     ← MinecraftSkillRuntime (runtime_registry.py)
  │         └─ SessionRunner     ← build → observe → run_builtin_loop
  │              ├─ SafetyClampBridge    ← dict action 自动透传
  │              ├─ MinecraftAdapter     ← to_executable_action_chunk
  │              ├─ TargetSessionHandle  ← action_chunk/observe 封装
  │              └─ MinecraftSkillRuntime ← episode 驱动循环
  │
  └─ AgentLoop                   ← LLM 推理循环
       └─ ContextBuilder         ← 自动注入文件到系统提示词
```

</details>
</p>

---

## 完整数据通路

<p>
<details open>
<summary><b>📦 workspace 文件布局</b></summary>

```
              workspace: workspaces/minecraft/
              ┌──────────────────────────────────────────────────────┐
              │  EMBODIED.md    ← _deploy_embodied_from_targets 自动部署 │
              │  ENVIRONMENT.md ← watchdog 写入（执行后回写）        │
              │  SESSIONS.md    ← Agent 写 / watchdog 消费           │
              │  LESSONS.md     ← ResultWriter 写入（成功+失败经验）  │
              │  TARGETS.md     ← 包含 minecraft_java_env 条目       │
              │  SKILLRUNTIME.md ← 包含 minecraft_navigate 条目     │
              │  memory/                                             │
              │   ├─ MEMORY.md  ← Agent 反思写抽象原则（战略层）     │
              │   └─ HISTORY.md ← Watchdog 写 session 时间线         │
              │  skills/                                            │
              │   └─ minecraft-navigation/SKILL.md ← 方法论层       │
              └──────────────────────────────────────────────────────┘
```

</details>
</p>

---

## 执行时序

<p>
<details open>
<summary><b>🔄 完整交互流程</b></summary>

```
用户: paos agent --workspace workspaces/minecraft

paos agent 自动:
  ├─ 启动 RuntimeWorkspaceManager（部署模板 + 启动 watchdog）
  └─ 启动 Agent 推理循环

  Agent 上下文（ContextBuilder 自动加载）:
    ├─ TARGETS.md          → 看到 minecraft_java_env 可用
    ├─ SKILLRUNTIME.md     → 看到 minecraft_navigate runtime
    ├─ EMBODIED.md         → 看到 16 种动作 + Critic Guidance
    ├─ ENVIRONMENT.md      → 看到 bot 当前状态（watchdog 回写）
    └─ LESSONS.md          → 看到历史经验（筛选后 ≤25 条）

用户: "采集5个橡木原木"

Agent 内部循环:
  iter 1: read_file ENVIRONMENT.md     → pos, nearby_blocks, inventory
  iter 2: LLM 推理 → write_file SESSIONS.md:
            sessions:
              - session_id: mc_001
                target_ref: target://minecraft_java_env
                skill_ref: skill://minecraft_navigate
                task_description: "采集5个橡木原木"
                execution: {max_steps: 30}
                runtime_hints:
                  perception_queries:
                    - {type: collect, params: {block_type: "oak_log", count: 5}}

Watchdog: 轮询到 pending session
  → resolve TARGETS.md → MinecraftTarget(bridge_url=ngrok_url)
  → resolve SKILLRUNTIME.md → MinecraftSkillRuntime
  → SessionRunner.start():
      build target → start_session → observe (写 ENVIRONMENT.md 初始值)
      run_builtin_loop():
        for action in perception_queries:
          target_handle.action_chunk()  → POST /action
          target_handle.observe()       → GET /state
          写 ENVIRONMENT.md
      → 返回 SkillRuntimeResult

Agent:
  iter 3: read_file ENVIRONMENT.md → last_action=collect, last_action_ok=true
                                   → inventory.hotbar[0]: oak_log×5
  iter 4: LLM: "完成！已采集5个橡木原木" → 回复用户

失败反思:
  iter N: read_file ENVIRONMENT.md → last_action_ok=false
  iter N+1: read_file LESSONS.md → "附近没有橡木，向东走10格找到"
  iter N+2: write_file SESSIONS.md → 新 session: move(forward:10) + collect(...)
  ...循环直到成功
```

</details>
</p>

---

## 链路逐条验证

| 链路 | 状态 | 实现位置 |
|------|------|---------|
| watchdog → ENVIRONMENT.md | ✅ | `WatchdogSupervisor` → `ResultWriter` — 执行后自动回写 |
| ENVIRONMENT.md → Agent 系统提示词（自动） | ✅ | `ContextBuilder` — 启动时自动注入 |
| Agent → SESSIONS.md | ✅ | Agent 使用 `write_file` 写入 session 定义 |
| SESSIONS.md → WatchdogSupervisor 调度 | ✅ | `scheduler.py` — 解析 SessionSpec，resolve target/skill |
| SessionRunner → TargetSessionHandle | ✅ | `session_runner.py:start()` — 封装 target 访问 |
| TargetSessionHandle.action_chunk → bridge | ✅ | `target_session_handle.py:67` → adapter → target → HTTP |
| 动作结果校验 | ✅ | `minecraft_skill_runtime.py:run_builtin_loop()` — 检查 `ok`/`result` |
| 成功/失败 → LESSONS.md | ✅ | `WatchdogSupervisor` → `ResultWriter` — 自动记录 |
| LESSONS.md → 筛选后注入 prompt | ✅ | `agent/context.py:_format_lessons()` — YAML 解析 + ≤25 |
| session → HISTORY.md | ✅ | `supervisor.py:_write_session_lesson()` + `MemoryStore.append_history()` |
| MEMORY.md > 4000 chars → 自动压缩 | ✅ | `agent/memory.py:maybe_consolidate_by_tokens()` |

---

## 关键设计决策

### 1. MinecraftSkillRuntime 继承 BuiltinSkillRuntime

对齐 v0.1.4 框架，`minecraft_skill_runtime.py` 从 `BaseSkillRuntime` 改为继承 `BuiltinSkillRuntime`，实现 `run_builtin_loop(skill_ctx, target_handle, adapter_plan) -> SkillRuntimeResult`。

旧版直接调用 `target.step()` 和 `target.observe()`；新版通过 `TargetSessionHandle.action_chunk()` 和 `.observe()` 访问 target，由 SessionRunner 管理完整生命周期（build → configure → start → loop → result）。

### 2. 模板对齐 Pydantic Schema

`TARGETS.md` 和 `SKILLRUNTIME.md` 模板字段完全对齐 `TargetSpec` / `SkillSpec` 的 Pydantic schema（`extra="forbid"`）：

| 旧字段 | 新字段 | 原因 |
|--------|--------|------|
| `type: sim` | `target_class: local` + `target_kind: game` | TargetSpec schema |
| `target_endpoint` | 删除 | local target 不需要 |
| `perception` 块 | 删除 | 使用默认值 |
| `category: builtin` | `runtime_kind: builtin` | SkillSpec schema |
| `supported_targets: [...]` | `supported_target_kinds: [game]` | 按 kind 匹配，非 target ID |
| - | `runtime_contract_ref` | 必填 Path 字段 |
| - | `loop_mode: open_loop_step` | 必填 |
| - | `agent_exposure: none` | 必填 |
| - | `observation_contract` | 必填 |

### 3. 场景区分：不同 workspace = 不同配置

```bash
paos agent --workspace workspaces/minecraft    → EMBODIED.md(16种MC动作) → 游戏场景
paos agent --workspace workspaces/libero_real  → EMBODIED.md(仿真动作)   → 仿真场景
```

ContextBuilder 自动加载对应 workspace 下的文件。新增场景只需对 workspace 部署对应的 EMBODIED.md + TARGETS.md + SKILLRUNTIME.md。

---

## CLI 使用方式

```bash
# 一切通过 paos agent 完成，watchdog 自动启动
paos agent --workspace workspaces/minecraft
```

**已删除的命令**（不再需要）：
- `paos minecraft say` → 由 `paos agent` 对话替代
- `paos minecraft listen` → 由 `paos agent` + HEARTBEAT.md 替代
- `paos minecraft watchdog` → `paos agent` 自动启动 WatchdogSupervisor
- `paos minecraft tp` → 删除。如需传送，Agent 可使用 `move` + `absolute:true`

---

## 文件清单

| 文件 | 说明 |
|------|------|
| `runtime/targets/game/minecraft_target.py` | MinecraftTarget — HTTP 客户端，继承 BaseLocalTarget |
| `runtime/adapters/minecraft/minecraft_adapter.py` | Observation/Action 归一化 |
| `runtime/skills/game/minecraft_skill_runtime.py` | Episode 驱动循环，继承 BuiltinSkillRuntime |
| `runtime/watchdog/runtime_registry.py` | 注册 MinecraftSkillRuntime |
| `templates/TARGETS.md` | 含 minecraft_java_env |
| `templates/SKILLRUNTIME.md` | 含 minecraft_navigate（runtime_kind: builtin） |
| `templates/configs/runtime/embodied/minecraft.md` | 16 种动作 + Critic Guidance |
| `templates/configs/runtime/contracts/minecraft.runtime.yaml` | 运行时契约 |
| `runtime/adapters/bridges.py` | SafetyClampBridge — dict action 透传修复 |
| `docs/scenarios/game/minecraft/bridge_server.js` | mineflayer bridge（部署到 Windows） |
| `workspaces/minecraft/skills/minecraft-navigation/SKILL.md` | Agent 技能：导航工作流 |

<p>
<details>
<summary><b>🔑 关键术语区分</b></summary>

| 文件 | 类型 | 使用者 | 内容 |
|------|------|--------|------|
| `SKILLRUNTIME.md` | Runtime YAML registry | WatchdogSupervisor | 可执行的 skill runtime 定义 |
| `SKILLS.md` | Agent Markdown index | Agent (ContextBuilder) | Agent 可用技能列表（方法论指导） |
| `skills/<name>/SKILL.md` | Agent Markdown skill | Agent（按需读取） | 具体方法论/工作流指导 |

> `SKILLRUNTIME.md` 定义 *能执行什么*（runtime 层），`skills/*/SKILL.md` 定义 *应该怎么做*（方法论层）。

</details>
</p>

---

## 经验自进化管道

完整的自进化闭环见 [3_self_evo.md](3_self_evo.md)，三层分层：

```
LESSONS.md (战术) → MEMORY.md (战略) → skills/SKILL.md (方法论)
     ↑                    ↑                     ↑
 Watchdog 自动写      Agent step 8 反思    Agent step 9 沉淀
 ≤25 条注入 prompt      ≤4000 字符硬上限    ≥2 次验证后自动化
```
