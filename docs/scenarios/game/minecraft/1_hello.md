# PhyAgentOS × Minecraft — 智能控制

> 承接 [0_start.md](0_start.md)。假设环境已通，bridge 正常运行。

<p>
<details>
<summary><b>🔄 两条交互路径</b></summary>

- **路径 A** — Runtime Session Protocol：Agent 写 SESSIONS.md → WatchdogSupervisor 调度执行
- **路径 B** — Direct Bridge API：Agent exec curl 直接调 bridge HTTP API（Minecraft 推荐）

</details>
</p>

---

## 一、启动 Agent

Minecraft 交互全部通过标准 `paos agent` 完成，不再有独立的 `minecraft` 子命令。

```bash
paos agent --workspace workspaces/minecraft
```

<p>
<details open>
<summary><b>启动时自动发生了什么</b></summary>

1. `paos agent` 自动检测 runtime 配置，启动 `RuntimeWorkspaceManager`
2. RuntimeWorkspaceManager 将 `TARGETS.md`、`SKILLS.md` 复制到 workspace；检测到 `minecraft_java_env` 目标，自动将 `configs/runtime/embodied/minecraft.md` 部署为 `EMBODIED.md`
3. 自动启动 `WatchdogSupervisor` —— 后台 daemon 线程轮询 `SESSIONS.md`，调度执行 session
4. Agent 推理循环启动 —— `ContextBuilder` 自动注入 `EMBODIED.md`（16 种动作）、`ENVIRONMENT.md`（目标快照）、`LESSONS.md`（历史经验）、`TARGETS.md`、`SKILLS.md`、`RUNTIME.md`

</details>
</p>

**首次使用注意**：`TARGETS.md` 中 `bridge_url` 默认为空，需先填入 ngrok URL 再下达任务。`connection_state` 在 `bridge_url` 为空时显示 `unconfigured`。

---

## 二、对话式控制

在 Agent 交互界面中，直接用自然语言下达任务：

```
You: 采集5个橡木原木

Agent:
  1. 读 ENVIRONMENT.md → 获取 bot 当前位置和周围方块
  2. LLM 推理 → 生成 SessionSpec → 写入 SESSIONS.md
  3. WatchdogSupervisor 轮询到 pending session:
     - resolve MinecraftTarget + MinecraftSkillRuntime
     - SessionRunner 执行: build → observe → action_chunk → 循环
     - 写 LESSONS.md（经验记录）
  4. 读 ENVIRONMENT.md 验证结果
  5. 回复用户
```

**对比旧版（已删除）**：
- 旧版 `paos minecraft say "挖5个橡木"` → 单次 LLM 盲生成全量动作 → 直接执行，无环境感知
- 新版 `paos agent` → 多轮观察-推理-交互闭环，watchdog 自动执行，失败自动反思

---

## 三、动作空间（16 种）

所有动作已定义在 `EMBODIED.md`（由 `templates/minecraft_embodied.md` 部署到 workspace）。

<p>
<details>
<summary><b>移动与视角</b></summary>

```python
# 面朝方向前进（相对）
t.step({"type": "move", "params": {"forward": 5}})    # 前进5步
t.step({"type": "move", "params": {"forward": -3}})   # 后退3步

# 追踪实体（相对）
t.step({"type": "move", "params": {"target": "player"}})
t.step({"type": "move", "params": {"target": "pig"}})

# 路径规划到绝对坐标
t.step({"type": "move", "params": {"dx": 100, "dy": 64, "dz": 200, "absolute": True}})

# 转向（角度制）
t.step({"type": "look", "params": {"yaw": 90.0, "pitch": 0.0}})
```

</details>
</p>

<p>
<details>
<summary><b>按键控制 &amp; 方块操作</b></summary>

```python
t.step({"type": "jump",     "params": {"duration_ms": 500}})
t.step({"type": "sneak",    "params": {"start": True}})
t.step({"type": "sprint",   "params": {"start": True}})
t.step({"type": "dig",   "params": {"x": 100, "y": 63, "z": 200}})
t.step({"type": "place", "params": {"x": 100, "y": 63, "z": 200, "face": 1}})
```

</details>
</p>

<p>
<details>
<summary><b>实体 &amp; 物品 &amp; 高级动作</b></summary>

```python
t.step({"type": "attack",   "params": {"target_type": "pig"}})
t.step({"type": "interact", "params": {"entity_id": "..."}})
t.step({"type": "use",         "params": {}})
t.step({"type": "select_slot", "params": {"slot": 0}})
t.step({"type": "drop",        "params": {}})
t.step({"type": "chat", "params": {"message": "hello"}})
t.step({"type": "collect", "params": {"block_type": "oak_log", "count": 10}})
t.step({"type": "craft",   "params": {"recipe_id": "crafting_table", "count": 1}})
t.step({"type": "equip",   "params": {"item": "stone_pickaxe", "destination": "hand"}})
```

</details>
</p>

---

## 四、动作验证清单

以下指令在 Agent 闭环模式下可用（agent 自动将自然语言转为 SessionSpec，watchdog 执行）。

| 类别 | 示例指令 |
|------|---------|
| 聊天 | "说你好"、"打个招呼" |
| 移动（面朝方向） | "往前走5步"、"后退3步" |
| 移动（追踪） | "来到我身边"、"去找猪" |
| 转向 | "向后转"、"右转90度"、"左转90度" |
| 按键 | "跳一下"、"潜行"、"开始疾跑" |
| 物品栏 | "切到第2格"、"使用手中的物品"、"扔掉手里的东西" |
| 组合任务 | "采集5个橡木原木"、"往前走到树那里，砍3棵树，然后回来" |

> 复杂任务（采集、合成、建造、环境感知）需要 Agent 闭环——见 [2_agent_loop.md](2_agent_loop.md)。

---

## 五、踩坑记录

<p>
<details>
<summary><b>#1 – #10：基础连通性问题</b></summary>

| # | 问题 | 原因 | 修复 |
|---|------|------|------|
| 1 | `SSL: CERTIFICATE_VERIFY_FAILED` | ngrok 免费版证书不完整 | `httpx.Client(verify=False)`，config 加 `"verify_ssl": false` |
| 2 | `Expecting value: line 1 column 1` | ngrok 返回 HTML 确认页 | 加 header `ngrok-skip-browser-warning: true` |
| 3 | `Request URL is missing protocol` | bridge_url 前后有空格 | `__init__` 中 `.strip()` |
| 4 | `Can't instantiate abstract class MinecraftTarget` | 基类新增抽象方法 | 补齐 describe/configure_session/start_session/action_chunk 等 |
| 5 | `Can't instantiate abstract class MinecraftSkillRuntime` | 同上 | 补齐 start/cancel/snapshot + 继承 BuiltinSkillRuntime |
| 6 | Pipeline 只跑 1 步就停 | `step()` 中 success 用了 ok 语义 | 改 success → ok，仅 done 控制终止 |
| 7 | bridge 传送不生效 | bot 在出生点，玩家超出 render distance | 改用 `/tp @s <玩家>` 命令 |
| 8 | `/op` 命令不存在 | LAN 模式不需要 OP | `Esc → 对局域网开放 → 允许作弊: 开` |
| 9 | `JSONDecodeError: Expecting value` | LLM 返回空响应 | 检查 API key 和网络，确认 LLM 调用正常 |
| 10 | `Cannot read properties of undefined (reading 'chestLocations')` | mineflayer-collectblock 插件未初始化 | bridge 中 spawn 事件内手动初始化 |

</details>
</p>

<p>
<details>
<summary><b>#11 – #21：Schema &amp; Pipeline 问题</b></summary>

| # | 问题 | 原因 | 修复 |
|---|------|------|------|
| 11 | LLM 生成不存在动作 | 系统 Prompt 未约束动作空间 | EMBODIED.md 列出 16 种有效动作，Critic 校验 |
| 12 | chat 监听无响应 | observe() 未透传 last_chats | observe() 返回值中加入 last_chats 字段 |
| 13 | look bot 不转向 | bridge bot.look() 接受弧度，Python 传角度 | bridge 端加 `* Math.PI / 180` 转换 |
| 14 | dig/place 坐标不准 | LLM 不知道 bot 周围的地形 | 用 collect 代替 dig；精确操作需读 ENVIRONMENT.md |
| 15 | runtime_contract_ref 缺失 | TargetSpec schema 中必填 Path | 创建 minecraft.runtime.yaml 占位文件 |
| 16 | Pydantic extra="forbid" 拒绝模板字段 | type:sim/category:builtin 等非法字段 | 模板与 schema 完全对齐 |
| 17 | RUNTIME_PREFLIGHT_FAILED: contract invalid | require_target_side_validation: false | 改为 true |
| 18 | perception.enabled must be true | SKILLRUNTIME.md 中 environment_outputs 触发 perception 检查 | 改为 environment_outputs: [] |
| 19 | SafetyClampBridge 报 float() argument | np.asarray 对 dict action 失败 | dict action 检测后直接透传 |
| 20 | Agent 用 edit_file 写 SESSIONS.md → YAML 崩溃 | 字符串替换丢缩进 | 改用 write_file 整体重写 |
| 21 | Agent 写 action:move 但 runtime 认 type:move | RUNTIME.md 模板无示例 | 新增格式示例 |

</details>
</p>

<p>
<details>
<summary><b>#22 – #25：2026-06 近期修复</b></summary>

| # | 问题 | 原因 | 修复 |
|---|------|------|------|
| 22 | `pos.floored is not a function` — dig/place 失败 | bridge 中 bot.blockAt({x,y,z}) 传普通对象，mineflayer 需要 Vec3 实例 | 改用 `new Vec3(x, y, z)` 通过 bot.entity.position.constructor 构造 |
| 23 | `SKILL_RUNTIME_MISSING: MinecraftSkillRuntime` | runtime_registry.py 未注册 MinecraftSkillRuntime | 添加导入 + register_skill_runtime() |
| 24 | Runtime session protocol 7 次全部 preflight 失败 | perception/sensor/runtime 配置链复杂 | 改用 bridge HTTP API 直连（exec curl） |
| 25 | workspaces/minecraft/skills/ 目录存在但为空 | 从未沉淀技能 | 基于 7 次导航经验创建 minecraft-navigation skill，Reflection step 9 实现自动化沉淀 |

</details>
</p>

---

## 六、脚本速查

| 脚本 | 功能 | 用法 |
|------|------|------|
| `test/test_1.py` | 验证 Target 连通 | `python test/test_1.py` — 见 0_start §3.2 |
| `test/test_2.py` | 完整 Pipeline 演示 | `python test/test_2.py` — 见 0_start §7 |
| `test/tp_bot.py` | 传送 bot | 改坐标后 `python test/tp_bot.py` |
| CLI `agent` | 标准 Agent 交互 | `paos agent --workspace workspaces/minecraft` |
| 计划 | 未来功能 | 见 `docs/scenarios/game/minecraft/todo_list.md` |
