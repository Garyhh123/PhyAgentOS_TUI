# PhyAgentOS 运行手册

> 版本：0.2.1 · [English](README_en.md)

本手册面向部署、演示和运行维护人员，聚焦“如何稳定运行 Forge 执行—证据—验证—恢复闭环”。安装与任务写法见[用户手册](../zh/02-user-manual.md)，精确参数见[配置参考](../zh/04-forge-configuration-reference.md)。

## 1. 运行模型

```text
User/Channel → AgentLoop → Forge tools → ForgeSessionOrchestrator
                                            │
                       ┌────────────────────┼───────────────────┐
                       ▼                    ▼                   ▼
                 Forge Gateway       SQLite event log     Verifier process
                       │                    │                   │
                       └──────────── execution + evidence ──────┘
```

`paos agent` 用于交互或单消息；`paos gateway` 用于长期在线消息渠道、Cron 与 Heartbeat。两个入口都在 `forge.enabled=true` 时启动同一个 Orchestrator 语义。

## 2. 上线前检查

### PAOS 主机

- Python 3.11/3.12 环境可用，依赖已安装；
- `~/.PhyAgentOS/config.json` 权限受控，Provider 凭据未进入 Git；
- workspace 可写且有足够空间保存 Evidence；
- `agents.verification.servicePort` 未被其他进程占用；
- 机器时间可靠，便于跨组件审计；
- 长期服务有进程守护与日志收集。

### Forge Gateway

- `baseUrl` 从 PAOS 主机可达；
- `/agent/runtime/capabilities` 返回精确 API version 与 required supports；
- `/agent/runtime/status` 和 `/agent/runtime/context` 可用；
- 计划使用的 action 在 capabilities 中；
- `/ws/images` 发布所需 source，sequence 单调递增；
- 需要 robot state 时 `/ws/state` 可用；
- Gateway、Forge Runtime、Dora 和机器人/仿真器已按各自文档完成安全检查。

### Verification

- 非 `off` 模式已启用 `serviceEnabled`；
- verifier model 支持图片和严格 JSON；
- `evidenceRetention` 符合隐私、审计与磁盘策略；
- replan budget 与 deadline 符合现场响应要求。

### 经验与演化

- 当前部署明确设置了 `agents.evolution` 的门槛和 model/provider；
- workspace 权限允许 `.paos/evolution/` 与 `skills/` 原子写入；
- operator 知道启用 evolution 后，根目录 `LESSONS.md` 不再是全局 Agent context；
- 稳定 operator 安全约束保存在 `AGENTS.md` 和 `EMBODIED.md`，learned Lesson 不替代它们。

## 3. 启动与健康检查

推荐先 Forge 后 PAOS：

```bash
paos status
paos agent --config /path/to/config.json --workspace /path/to/workspace
```

长期运行：

```bash
paos gateway --config /path/to/config.json --workspace /path/to/workspace --verbose
```

启动后通过 Agent 执行只读检查：

```text
调用 forge_get_context。报告 Gateway API version、supports、actions、status、readiness 和图像 source，不执行 reset 或 action。
```

只有 capabilities 校验通过，Orchestrator 才会接收任务。Verification Service 启动失败会被缓存为明确错误；非 `off` 请求不会在 verifier 不可用时进入执行。

## 4. 任务监控

提交时记录返回的 `session_id` 与 `command_id`。通过 Agent 调用 `forge_get_session`，重点观察：

| 字段 | 运维意义 |
|:-----|:---------|
| `status` | PAOS 当前状态或最终任务结果 |
| `dispatch_attempted_at` | 是否已跨过“不得自动重发”边界 |
| `gateway_last_response` | Gateway 最后已知 session/command 响应 |
| `execution.status` | Gateway 执行事实 |
| `verification.status/verdict` | 验证阶段与任务语义结论 |
| `recovery_request.deadline` | Planner 必须创建 child 的最后时间 |
| `error_code/error_message` | 故障分层与具体原因 |

不要只看 Gateway `succeeded`。在 `enforce`/`recovery` 下，只有 PAOS `status=succeeded` 且 verdict 为 `success` 才表示任务成功。

经验处理为异步链路。Forge completion 报告时，episode assessment、Lesson cluster 合成或 Skill 晋升可能尚未完成。应在 `.paos/evolution/experience.sqlite3` event 和 `skills/<name>/references/LESSONS.md` 中查看独立状态；不能为了等待 evolution 而阻塞或重复物理任务。

## 5. 取消与 Reset

请求取消：

```text
使用 forge_cancel_session 取消 <session_id>，reason 写明运维原因。
```

如果任务已 dispatch，PAOS 会请求 Gateway cancel 并把 response 保存到 `gateway_cancel_response`。取消不是硬件急停；人员和物理系统必须保留独立的 E-stop、operator override 与安全停机流程。

Reset 仅用于没有活动 lineage 时：

```text
先调用 forge_get_session 确认任务终结，再调用 forge_reset；不要在运行中 reset。
```

Orchestrator 会拒绝活动期间的 reset。

## 6. 正常停机

1. 停止接收新任务；
2. 查询 non-terminal lineage；
3. 等待其终结，或显式取消并核实物理状态；
4. 发送 SIGINT/SIGTERM 停止 PAOS；
5. PAOS 会再次尝试取消活动 Gateway session 并保存响应；
6. 按 Forge/机器人文档停止下游服务。

不要直接 kill 后立即重启并重复用户指令。先根据 SQLite 和 Gateway session 确认 dispatch 边界。

## 7. 异常重启处置

PAOS 启动后自动加载 non-terminal records：

| 崩溃位置 | 自动行为 | 运维动作 |
|:---------|:---------|:---------|
| dispatch 前 | 继续采集或派发 | 观察即可 |
| dispatch intent 后 | GET 原 session，不 POST | 核对 Gateway identity |
| Gateway 404 | `FORGE_EXECUTION_STATE_LOST` | 核实现场和 Gateway 日志；不要复制旧 command ID |
| finalizing | 尝试补采 after、写 contract | 检查 image source/sequence |
| verifying | 旧 attempt 标记 abandoned，重新验证 | 检查 Provider 与 service |
| awaiting replan | 可重发同一 recovery event | 检查 Planner 是否创建 child、deadline 是否到期 |
| evolution job running | 重启时恢复为 pending | 让后台继续处理；Forge 不受影响 |

如果物理状态未知，应停止自动任务并由 operator 确认，而不是用新任务“试探”状态。

## 8. Artifact 与磁盘

```text
<workspace>/.paos/forge/orchestrator.sqlite3
<workspace>/.paos/forge/orchestrator.sqlite3-wal
<workspace>/.paos/forge/orchestrator.sqlite3-shm
<workspace>/.paos/evolution/experience.sqlite3
<workspace>/.paos/evolution/experience.sqlite3-wal
<workspace>/.paos/evolution/revisions/
<workspace>/skills/<skill>/references/LESSONS.md
<workspace>/artifacts/forge/<session_id>/
```

备份建议：

- 最稳妥的方式是在 PAOS 停止后备份 SQLite 文件及整个 `artifacts/forge/`；
- 运行中复制时必须使用 SQLite-aware backup，不能只复制主 `.sqlite3` 而忽略 WAL；
- Artifact 与数据库需要来自同一时间点；
- 不要手工编辑 `record_json` 或 event rows；
- 配置 retention 后仍应监控 Bundle、Execution 和事件日志的增长。

`maxArtifactBytes` 限制单个实体，不是 session 或 workspace 总配额。

Evolution 数据库是事实源，per-Skill `LESSONS.md` 是生成投影。备份时同时包含 database/WAL 与 Skill/revision tree；不要通过直接编辑 SQLite 或投影来修复 blocked cluster/candidate。

## 9. 故障分层

### A. 启动契约

`FORGE_GATEWAY_API_UNSUPPORTED`、`FORGE_GATEWAY_CAPABILITY_MISSING`：停止接单，修正 Gateway 版本或 supports，不做降级。

### B. 执行身份

identity mismatch 或 `FORGE_EXECUTION_STATE_LOST`：视为潜在重复动作风险，人工核查后重新规划。

### C. 证据

`FORGE_EVIDENCE_CONFIGURATION_REQUIRED`、`FORGE_EVIDENCE_UNAVAILABLE`：检查 source、WebSocket、sequence、media type、实体上限和 capture timeout。

### D. Verification

`VERIFICATION_EVIDENCE_UNAVAILABLE`、`VERIFICATION_INVALID_VERDICT`、`VERIFICATION_SERVICE_UNAVAILABLE`：检查 artifact 完整性、retention、模型、Provider、端口和 timeout。不要通过改用 `off` 隐藏本应强制验证的业务要求。

### E. Recovery

`VERIFICATION_REPLAN_LIMIT_REACHED`、`VERIFICATION_REPLAN_TIMEOUT`：root lineage 已无法自动继续。检查 lessons、未满足 criteria 与现场状态，再由用户决定新任务。

### F. 经验演化

Collecting/blocked Lesson cluster 和 blocked Skill candidate 是后台学习状态，不是 task failure。检查独立 root 支持、适用范围、静态策略、抽象置信度、冲突、Skill 结构与 reload/rollback event。Evolution model/store 错误必须 fail-open；若其改变 Forge 状态或延迟 completion notification，应视为实现缺陷。

## 10. 运行验收清单

- [ ] Gateway API/version/supports 校验通过。
- [ ] action capability 与 required inputs 可见。
- [ ] 所需 before source 在 POST 前到达。
- [ ] session/command/request/action identity 全部匹配。
- [ ] 终态来自 session GET，而非固定等待或静稳推断。
- [ ] after source sequence 高于 before，且在终态观察后接收。
- [ ] Execution Record 与 Evidence Bundle 已写入。
- [ ] 非 `off` 任务具有 goal 和 criteria，Verifier 已返回或明确失败。
- [ ] 最终用户报告区分 execution status 与 verification verdict。
- [ ] Recovery child 使用全新 ID，parent/child lineage 可追踪。
- [ ] 匹配工作流在执行前激活注册 primary Skill，直接文件读取不计为 activation。
- [ ] Evolution 对 root lineage 只计一次，无关/不确定失败只保留诊断。
- [ ] 只动态加载 active scoped Lesson，operator 安全文件不变。
- [ ] 晋升 Skill 具有配置要求的三个独立成功、managed block、revision history 和可 reload workspace 文件。

## 后续阅读

- [用户手册](../zh/02-user-manual.md)
- [配置参考](../zh/04-forge-configuration-reference.md)
- [通信架构](../user_development_guide/COMMUNICATION.md)
- [Forge 接入契约](../forge/README_zh.md)
- [Agent 经验与 Skill 自进化](../zh/05-agent-experience-and-skill-evolution.md)
