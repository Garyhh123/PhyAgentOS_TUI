# PhyAgentOS × Minecraft — 开发路线

<p>
<table>
<tr><td width="25%"><b>已完成</b></td><td width="25%"><b>进行中</b></td><td width="25%"><b>计划中</b></td><td width="25%"><b>待定</b></td></tr>
<tr>
<td>#2 复杂任务闭环 ✅<br>#3 action 验证 ✅<br>#8 分层记忆 ✅<br>#9 自进化 ✅</td>
<td>#10 更多技能沉淀 🔄</td>
<td>#1 3D 观察视角<br>#4 动态编排<br>#7 Benchmark</td>
<td>#5 性能优化<br>#6 跨版本兼容<br>#11 多场景共享</td>
</tr>
</table>
</p>

---

## 1. 浏览器 3D 观察视角

**目标**：在浏览器中实时查看 bot 第一人称 3D 视角。

| 方案 | 说明 | 复杂度 |
|------|------|--------|
| A. prismarine-viewer | mineflayer 官方第一人称 viewer，需编译 canvas 原生模块 | 中 |
| B. Web Viewer | Three.js 轮询 bridge /state API 渲染 3D 俯视地图 | 低 |
| C. 屏幕截图流 | PowerShell 截图 → HTTP MJPEG 流 → 浏览器 | 低 |

**当前状态**：待选择方案实现。

---

## 2. 复杂任务 Agent 闭环 ✅

通过 `paos agent --workspace workspaces/minecraft` 实现，全链路贯通。

```
Agent 写 SESSIONS.md → WatchdogSupervisor 轮询 → Preflight 校验
→ SessionRunner 执行 → MinecraftSkillRuntime.run_builtin_loop()
→ SafetyClampBridge 透传 dict action → HTTP POST /action → mineflayer
→ 结果回写 ENVIRONMENT.md + LESSONS.md
→ Agent 读 ENVIRONMENT.md 验证 → 继续/重试
```

详见 [2_agent_loop.md](2_agent_loop.md)。

---

## 3. action 验证与错误恢复 ✅

`MinecraftSkillRuntime.run_builtin_loop()` 在每个 action 执行后通过 `ok` 字段校验结果，失败记录 `error_message`。Agent 读取 LESSONS.md 获取失败原因并调整策略。

---

## 4. 动态环境下的动作编排调整

**问题**：`perception_queries` 是 Agent 一次性预生成的全量动作序列。动态世界中预生成的后续动作可能在执行时已失效。

| 方案 | 说明 | 复杂度 |
|------|------|--------|
| **A. 小 session 拆分** | Agent 只规划 1-3 步短 session，每步验证后再写下一段 | 低 |
| **B. 条件动作** | `perception_queries` 支持 `if_fail` 回退动作 | 中 |
| **C. 运行时回调** | skill runtime 执行中途写 ENVIRONMENT.md，Agent 在心跳中追加 | 中 |

**推荐**：方案 A（Agent 行为调整，零代码改动）。

---

## 5. 性能优化

- bridge `/state` 缓存（避免每 1s 全量扫描 nearby_blocks）
- LLM 调用去重

---

## 6. 跨版本兼容

- 确认 mineflayer 支持 Minecraft 1.21.x
- 适配不同 ngrok 认证方式

---

## 7. Minecraft Benchmark 评测

**目标**：量化评估 Agent 能力。

**指标**：任务完成率、探索效率、生存能力、指令理解准确率。

---

## 8. 分层记忆（Hermes 三条机制） ✅

**目标**：三层经验分层 + 自动化技能沉淀。

| 层 | 文件 | 精炼策略 | 状态 |
|----|------|---------|------|
| 战术层 | `LESSONS.md` | YAML 解析 + ≤25 条规则筛选 | ✅ |
| 战略层 | `memory/MEMORY.md` | Agent 反思写入 + 4000 字符硬上限触发 LLM 压缩 | ✅ |
| 方法论层 | `skills/<name>/SKILL.md` | ≥2 次验证 → Agent 调用 `skill-creator` 自动沉淀 | ✅ |
| 时间线 | `memory/HISTORY.md` | Watchdog 写 session 记录 + MEMORY 精炼事件 | ✅ |

详见 [3_self_evo.md](3_self_evo.md)。

---

## 9. 闭环自主调整规划（自进化） ✅

**目标**：Agent 失败后不依赖人工介入，自主调整计划。

**实现**：
- Agent loop 中加入 failure reflection（9 步循环：Plan→Wait→Check→Reflect→Learn→Retry→Escalate→Abstract→Convert to Skill）
- 多次失败后自动降级（如 collect 失败 → 改用 dig 逐块挖掘）
- Step 8-9 实现经验 → 技能自动转化

详见 [3_self_evo.md](3_self_evo.md)。

---

## 10. 更多技能沉淀（进行中）

**目标**：将已验证的工作流持续转化为可复用技能。

**已沉淀**：
- `minecraft-navigation` — 洞穴逃脱、路径规划、分段移动、Bridge API 直连导航

**待沉淀**：
- `minecraft-collection` — 采集工作流（collect + inventory 检查 + 去重）
- `minecraft-crafting` — 合成链工作流（材料检查 → 合成台 → 中间产物 → 目标物品）
- `minecraft-building` — 建造工作流（clear→lay blocks→verify）

---

## 11. 多场景技能共享

**目标**：Minecraft 中验证的技能自动适配到 Stardew Valley 等场景。

**依赖**：
1. 技能格式标准化（`[Game]` 标签 + `Pattern:` 抽象原则）
2. 场景适配器（Minecraft action → Stardew action 的语义映射）
3. 跨游戏经验验证（Stardew 端到端链路打通后启动）
