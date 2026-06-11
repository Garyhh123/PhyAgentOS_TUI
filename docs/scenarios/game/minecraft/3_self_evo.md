# PhyAgentOS × Minecraft — 经验自进化（三层分层记忆）

> 承接 [2_agent_loop.md](2_agent_loop.md)。实现了持久化任务循环 + 三层经验分层 + 自动化技能沉淀。
> **当前状态：已完成。**

<p><table><tr>
<td width="33%" align="center"><b>战术层</b><br><code>LESSONS.md</code><br><small>≤25 条注入</small></td>
<td width="33%" align="center"><b>战略层</b><br><code>memory/MEMORY.md</code><br><small>≤4000 字符硬上限</small></td>
<td width="33%" align="center"><b>方法论层</b><br><code>skills/SKILL.md</code><br><small>按需 read_file</small></td>
</tr></table></p>

---

## 一、三层经验体系

### 设计溯源

借鉴 Hermes 的三层记忆架构，但用 Markdown 文件替代 SQLite/向量 DB：

| 层 | Hermes 概念 | 我们的文件 | 注入方式 | 精炼策略 |
|----|-----------|----------|----------|---------|
| **战术层** | Episodic | `LESSONS.md` | 筛选后注入（≤25 条） | `_format_lessons()` YAML 解析 + 规则筛选 |
| **战略层** | Semantic | `memory/MEMORY.md` | 全文自动注入 | Agent 反思写入 + 硬上限 4000 字符触发 LLM 压缩 |
| **方法论层** | — | `skills/<name>/SKILL.md` | 按需 `read_file` | ≥2 次验证后，Agent 调用 `skill-creator` 生成 |

### 数据管道

```
Session 执行
  │
  ├─ Watchdog 自动写 LESSONS.md          (step 5: Learn  — 已有)
  │    └─ 战术经验：task/strategy/outcome/insight
  │
  ├─ Agent 反思 → 抽象写 MEMORY.md        (step 8: Abstract  — 新增)
  │    └─ 战略原则：[Game] + Pattern: 字段，跨游戏可迁移
  │
  └─ ≥2 次验证 → skill-creator 创建技能   (step 9: Convert to Skill  — 新增)
       └─ 方法论：可复现的工作流，Agent 按需加载
```

<p>
<details>
<summary><b>注入到系统提示词时的结构</b></summary>

```
Agent prompt
  ├─ LESSONS.md  (筛选后 ≤25 条, YAML 解析)
  │    └─ 原始 >25 条时显示 "(+N older lessons, use read_file to view)"
  ├─ memory/MEMORY.md  (全文, 压缩后 ≤4000 字符)
  │    └─ 超过 4000 字符时触发 LLM 精炼, 写入 HISTORY.md 记录
  └─ skills summary  (XML, 每项 source=workspace/builtin, available=true/false)
```

</details>
</p>

---

## 二、闭环自主调整规划（Reflection 9 步）

Agent 系统提示词中的完整反思循环：

| Step | 名称 | 说明 | 实现位置 |
|------|------|------|---------|
| 1 | **Plan** | 读 RUNTIME.md + TARGETS.md，写 SESSIONS.md | 已有 |
| 2 | **Wait** | watchdog 自动拾取 pending session | 已有 |
| 3 | **Check** | 读 ENVIRONMENT.md 验证结果 + LESSONS.md | 已有 |
| 4 | **Reflect** | 分析成败原因 | 已有 |
| 5 | **Learn** | `edit_file` 追加结构化 lesson 到 LESSONS.md | 已有 |
| 6 | **Retry** | 失败时调整策略重试（max 3 次同方法） | 已有 |
| 7 | **Escalate** | 3 次同方法失败 → 切根本不同的方法 | 已有 |
| 8 | **Abstract** | 提取跨游戏抽象原则 → `edit_file` 写 `memory/MEMORY.md` | **新增** |
| 9 | **Convert to Skill** | ≥2 次验证后 → `skill-creator` 生成 `skills/<name>/SKILL.md` | **新增** |

**实现位置**：`agent/context.py:_get_identity()` — "Task Persistence & Reflection (Self-Evolution)" 段落。

---

## 三、LESSONS.md 上下文筛选

### 问题

LESSONS.md 随 session 执行不断追加，100+ 次任务后注入全量到 prompt 会撑爆上下文。

### 方案：YAML 解析 + 规则筛选

`_format_lessons()` 在注入 prompt 前做筛选（`agent/context.py`）：

<p>
<table>
<tr><td>1.</td><td>按 <code>session_id</code> 去重（保留最新条目）</td></tr>
<tr><td>2.</td><td>保留最近 15 条（按写入时间顺序）</td></tr>
<tr><td>3.</td><td>额外保留 summary 含 <code>"succeeded"</code> 的成功条目</td></tr>
<tr><td>4.</td><td>总上限 <b>25 条</b></td></tr>
<tr><td>5.</td><td>原始 > 注入时，末尾追加 <code>"(+N older lessons, use read_file to view)"</code></td></tr>
</table>
</p>

### 实现文件

| 文件 | 函数/方法 | 职责 |
|------|----------|------|
| `agent/context.py` | `_parse_lessons_yaml()` | 从 LESSONS.md 提取 YAML `lessons` 列表 |
| `agent/context.py` | `_filter_recent_and_successful()` | 去重 + 最近 15 + 成功条目 + 上限 25 |
| `agent/context.py` | `_format_lessons()` | 筛选入口 + YAML 重建 + 省略提示 |
| `runtime/watchdog/result_writer.py` | `write_lesson()` | 写入 LESSONS.md（YAML 格式，不修改） |
| `runtime/state_io/markdown_yaml.py` | `read_yaml_block()` / `write_yaml_block()` | YAML 序列化/反序列化 |

### 验证标准

| 验证项 | 量化标准 |
|--------|---------|
| 注入条目 ≤25 | `len(filtered) ≤ 25` |
| 成功条目优先 | 所有 succeeded 条目被保留 |
| 省略提示显示 | 原始 >25 时显示 `(+N older lessons…)` |
| YAML 解析失败回退 | 回退到原始行为（计数非空行决定是否加提示） |

<p>
<details>
<summary><b>🔍 YAML 处理细节</b></summary>

- LESSONS.md 是 YAML 格式：`ResultWriter.write_lesson()` 使用 `write_yaml_block()` 写入
- `_format_lessons()` 的筛选逻辑需要用 `read_yaml_block()` 解析（位于 `PhyAgentOS/runtime/state_io/markdown_yaml.py`），不能做简单字符串匹配
- 解析失败时回退到原有行为（简单计数行数决定是否加提示前缀）
- 过滤后重建 YAML block 替换原内容

</details>
</p>

---

## 四、MEMORY.md 强制精炼（Hermes 硬上限）

### 问题

MEMORY.md 没有大小限制。Agent 不断追加抽象原则，100+ 次任务后可能膨胀到 20000+ 字符。

### 方案：硬上限触发 LLM 压缩

在 `MemoryConsolidator.maybe_consolidate_by_tokens()` 中增加检查：

```
MEMORY.md > 4000 chars
  → 5 分钟节流（避免频繁触发）
    → _compact_long_term_memory()
      → LLM 纯文本精炼（不调用 tool）
        → 仅当结果 < 原长的 90% 时落盘
          → 写入 HISTORY.md 记录精炼事件
```

### 精炼 Prompt 指令

1. 合并相似原则为单条目
2. 仅保留 ≥2 次观察确认的模式
3. 移除一次性观察或已解决的问题
4. 保留所有 `[Cross-game]` 和 `Pattern:` 字段
5. 按重要性排序（最常使用的优先）

### 实现文件

| 文件 | 方法 | 职责 |
|------|------|------|
| `agent/memory.py` | `MemoryConsolidator.maybe_consolidate_by_tokens()` | 硬上限检查 + 5 分钟节流 |
| `agent/memory.py` | `MemoryConsolidator._compact_long_term_memory()` | LLM 精炼 + 回写 + HISTORY 记录 |

### 验证标准

| 验证项 | 量化标准 |
|--------|---------|
| MEMORY.md 超过 4000 字符时触发 | `len(read_long_term()) > 4000` → `_compact_long_term_memory()` |
| 压缩后字符数下降 | `len(new) < len(old) * 0.9` |
| HISTORY.md 记录精炼事件 | `[YYYY-MM-DD HH:MM] MEMORY.md refined: N→M chars` |
| 核心原则不丢失 | 压缩后仍含 `[Cross-game]` 和 `Pattern:` 字段 |
| 5 分钟节流 | 两次压缩间隔 ≥300s |

<p>
<details>
<summary><b>⚠️ 精炼不调用 _SAVE_MEMORY_TOOL</b></summary>

`MemoryConsolidator.consolidate()` 使用 `_SAVE_MEMORY_TOOL` 让 LLM 输出 `history_entry` + `memory_update`。
但 `_compact_long_term_memory()` 是压缩 MEMORY.md 自身，应直接用 text response（不调用 tool），
因为只需要返回压缩后的文本，不需要追加到 HISTORY.md。

精炼后手动调用 `self.store.append_history()` 记录事件。

</details>
</p>

---

## 五、HISTORY.md Session 记录

### 变更

`WatchdogSupervisor._write_session_lesson()` 中增加 `MemoryStore.append_history()` 调用：

```
[YYYY-MM-DD HH:MM] session <session_id> on <target_id>: <summary>
```

### 实现文件

| 文件 | 变更 | 职责 |
|------|------|------|
| `runtime/watchdog/supervisor.py` | `__init__` 创建 `MemoryStore(self.environment_workspace)` | 访问 workspace 的 memory 目录 |
| `runtime/watchdog/supervisor.py` | `_write_session_lesson()` 追加 `append_history()` | 每次 session 完成写一行 |
| `agent/memory.py` | `MemoryStore.append_history()` | 已有接口，直接调用 |

### 验证标准

| 验证项 | 量化标准 |
|--------|---------|
| 每次 session 完成后 HISTORY.md 新增一行 | `grep "session " HISTORY.md | wc -l` = 执行过的 session 数 |
| Agent 可 grep HISTORY 回溯 | `exec grep mc_nav HISTORY.md` 返回相关 session |

---

## 六、方法论沉淀：skills/ 目录

### 问题

`workspaces/minecraft/skills/` 目录存在但从未被使用。有效经验应转换为可复用的方法论 / 工作流指导。

### 方案

Agent 在 Reflection step 9 中，当同场景下 ≥2 次成功验证后，调用 `skill-creator` 技能生成 `skills/<skill-name>/SKILL.md`。

### 已沉淀技能

| 技能 | 来源 | 描述 |
|------|------|------|
| `minecraft-navigation` | 7 次 mc_nav session + 洞穴逃脱成功 | Bridge API 直连导航：洞穴逃脱、路径规划、分段移动、已知陷阱 |

### 关键设计

| 条件 | 写 MEMORY.md | 创建 Skill |
|------|-------------|-----------|
| 触发时机 | 每次 session 完成后 | ≥2 次同场景成功验证后 |
| 内容性质 | 事实 / 原则 / 教训 | 可复现的工作流 / 方法论 |
| 工具 | `edit_file` | `skill-creator` 技能 |
| 加载方式 | 自动注入 prompt | SkillsLoader → 按需 `read_file` |

---

## 七、实现详情

### 架构变更

```
AgentLoop
├── _run_agent_loop()                ← 原有：单次 LLM 推理循环
└── _run_persistent_task_loop()      ← 新增：外层级持久化循环
    ├── while continue_count ≤ max_task_continues:
    │   ├── _run_agent_loop()
    │   ├── 检测 max_iterations 中止 → [Auto-continue]
    │   └── continue_count++

ContextBuilder
├── _get_identity()                  ← 新增 Reflection 9 步循环 (step 8, 9)
├── _format_lessons()                ← 重写：YAML 解析 + ≤25 筛选 + 省略提示
│   ├── _parse_lessons_yaml()         ← 新增：提取 YAML lessons 列表
│   └── _filter_recent_and_successful() ← 新增：去重 + 最近 15 + 成功条目
└── add_system_continue()            ← 已有：延续提示注入

MemoryConsolidator
├── maybe_consolidate_by_tokens()    ← 新增 MEMORY.md 硬上限检查 + 5 分钟节流
└── _compact_long_term_memory()      ← 新增：LLM 精炼 + 回写 + HISTORY 记录

WatchdogSupervisor
├── _write_session_lesson()          ← 新增 HISTORY.md 记录
└── __init__                         ← 新增 MemoryStore 实例
```

### 文件变更清单

| 文件 | 行变更 | 说明 |
|------|--------|------|
| `agent/loop.py` | +68 / -7 | `_run_persistent_task_loop()` + `_process_message()` 路由 |
| `agent/context.py` | +125 / -14 | 反思 step 8-9 + `_format_lessons()` 重写 + `_parse_lessons_yaml()` + `_filter_recent_and_successful()` |
| `agent/memory.py` | +53 | `_compact_long_term_memory()` + `may_consolidate_by_tokens()` 硬上限检查 |
| `runtime/watchdog/supervisor.py` | +35 | `_write_session_lesson()` + HISTORY 记录 + `MemoryStore` 实例 |
| `runtime/watchdog/runtime_registry.py` | +2 | 注册 `MinecraftSkillRuntime` |
| `runtime/watchdog/result_writer.py` | 不变 | `write_lesson()` 原有逻辑 |
| `workspaces/minecraft/skills/minecraft-navigation/SKILL.md` | +102 | Agent 技能：minecraft 导航工作流 |
| `templates/LESSONS.md` | +18 | 结构化 lesson 模板格式 |
| **总计** | **+403 / -21** | **8 文件** |

---

## 八、跨场景经验示例

### Minecraft → Stardew Valley 知识迁移

| Minecraft 经验 | 抽象原则 | Stardew 适配 |
|---------------|----------|-------------|
| 洞穴中 pathfinder 卡住 | 受约束空间内导航不可靠，先进入开放区域 | 农田里有树桩阻塞 → 先清理或绕行 |
| collect oak_log 需靠近到 4.5 格内 | 资源收集需 bot 到达目标附近 | till soil 需站在耕地旁边 |
| 用 ENVIRONMENT.md 验证动作结果 | 永远不声称成功而不读取环境数据 | 用 ENVIRONMENT.md 确认作物是否已种植 |
| dig 有 bug → 用 move(dy:2) 替代 | 遇到动作 bug 时寻找功能等价替代 | place 有 bug → 用其他交互方式 |
| 长距离移动拆分为 5 步短距离 | 复杂任务分解为小步骤减少失败率 | 大面积耕种分块进行 |

---

## 九、三文件协同使用场景

<p>
<details>
<summary><b>场景 A：Agent 第二次启动，回溯"上周 minecraft 导航为什么不 work"</b></summary>

```
1. grep HISTORY.md for "mc_nav" → 7 次 session，时间集中在 13:09~13:16
2. 读 LESSONS.md → 筛选后看到最近 15 条中的 7 条 mc_nav 经验
3. 发现 Pattern: 所有都被 RUNTIME_PREFLIGHT_FAILED / SCHEMA_VALIDATION 拒绝
4. 写 MEMORY.md: "[Configuration] 启动前验证 runtime pipeline 配置完整性"
5. MEMORY.md 已有这条原则 → 在 Stardew 中，Agent 首先验证 pipeline 配置
```

</details>
</p>

<p>
<details>
<summary><b>场景 B：MEMORY.md 硬上限触发（Hermes 强制精炼）</b></summary>

```
1. MEMORY.md 已积累 8500 字符（导航策略 ×5 + 收集策略 ×3 + 配置原则 ×4 + ...）
2. MemoryConsolidator 检测到 >4000 chars → 触发 _compact_long_term_memory()
3. LLM 精炼: 导航策略 ×5 → 合并为 2 条；收集策略 ×3 → 合并为 1 条
4. 压缩后: 2900 字符，核心原则全部保留
5. HISTORY.md: "[2026-06-12 13:00] MEMORY.md refined: 8500→2900 chars"
6. Agent 下次启动时，prompt 中的 # Memory 段从 8500 字降到 2900 字
```

</details>
</p>

<p>
<details>
<summary><b>场景 C：技能自动沉淀</b></summary>

```
1. Agent 完成 3 次洞穴逃脱任务（dy-based climbing）
2. 均在 MEMORY.md 中记录了 Pattern: "Underground navigation: use dy-based climbing"
3. step 9 触发：≥2 次成功验证 → 调用 skill-creator
4. 生成 skills/minecraft-navigation/SKILL.md（含工作流 + 参数速查表）
5. 后续任务中 Agent 看到 skills summary → read_file 加载 → 立即获得完整策略
6. 不再需要每次读 LESSONS.md + 推理 → 减少 3-5 次工具调用
```

</details>
</p>

---

## 十、后续优化方向

| 方向 | 说明 | 优先级 |
|------|------|--------|
| 更多技能沉淀 | 收集、合成、建造等工作流的技能化 | 高 |
| 向量检索经验 | LESSONS.md 嵌入，相似场景自动检索相关教训 | 中 |
| 成功经验加权 | 根据成功次数动态调整策略偏好 | 低 |
| Session 级 lesson 关联 | 每条 lesson 关联 ENVIRONMENT.md 快照，便于分析原因 | 低 |
| 多场景技能共享 | Minecraft → Stardew 跨游戏技能自动迁移 | 中 |

---

## 十一、参考资料

| 资料 | 内容 |
|------|------|
| 设计方案 | `.kilo/plans/hierarchical-lessons.md` — 三层分层经验体系完整设计 |
| Hermes 论文 | [Hermes: A Large Language Model Framework for Episodic and Semantic Memory](https://arxiv.org/abs/2502.01928) |
| nanobot 架构 | `memory/MEMORY.md` + `HISTORY.md` 基础记忆架构 |
| 上层闭环 | [2_agent_loop.md](2_agent_loop.md) |
| 部署文档 | [0_start.md](0_start.md) |
| TODO 列表 | [todo_list.md](todo_list.md) |
