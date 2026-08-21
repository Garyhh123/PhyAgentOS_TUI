# PhyAgentOS 运行手册

[English](README_en.md) · [文档索引](../README.md)

> 版本：0.2.2

## 1. 运行模型

```text
用户/渠道 → AgentLoop → Forge task 与 Tool API tools
                              │
                       绑定或无任务调用
                              ▼
                     ForgeToolClient
                              ▼
Gateway /tools → ToolInvocation → ToolEndpoint → Dora → 机器人/仿真器

绑定调用 → AgentTask SQLite → evidence → verification → experience/evolution
```

Gateway 负责执行，PAOS 负责用户任务聚合与语义判定。Skill Runtime 负责已安装 Bundle profile
的显式生命周期，但不替代 Gateway execution truth。

## 2. 上线前检查

### PAOS 主机

- 已安装 Python 3.11/3.12 和目标 v0.2.2 环境；
- `paos status` 指向预期 config、workspace、model 和 provider；
- Workspace、PAOS data paths 和 artifact paths 具备权限与磁盘空间；
- 允许非 `off` 任务时，Verification provider 凭据可用。

### Skill Runtime

- Registry/index metadata 含 artifact size 与 SHA-256，锁定 Node digest 可解析；
- required binaries 可执行，required assets 存在，required environment 已设置；
- Dora 已安装且位于 `PATH`；
- profile Gateway 地址没有被非托管进程占用。

### Forge Gateway

- `GET /tools` 返回成功 object envelope；
- required ToolSpecs 与 `/tools/{tool_id}/context` 存在并 ready；
- Endpoint operation `max_concurrency` 符合机器人安全并发；
- move-arm profile 中 `agent.enabled: false`。

### 持久化

- `.paos/agent_tasks`、`.paos/evolution`、Agent conversation history 与 Skill Runtime state 位于可靠存储；
- 轮转机器人证据时，备份和 retention 不删除 evolution 数据。

## 3. 启动与健康检查

托管 Skill profile：

```bash
paos skill inspect move-arm-by-ee
paos skill start move-arm-by-ee --profile mujoco
paos skill status move-arm-by-ee
paos agent
# 或：paos gateway
```

Runtime 健康要求持久化状态为 `running`、命名 Dora flow 存活、Gateway `/tools` 可用，并且
manifest 中每个 `required_tool` context ready。使用 `paos skill logs <name>` 查看生命周期和
Dora launch 日志。

若 Gateway 由外部管理，应独立启动，并通过 Agent 的 `forge_tool_context` 验证 Tool context；
`paos status` 只检查本地配置。

## 4. 任务监控

分别记录以下 identity：

| Identity | 责任方 | 用途 |
|:---------|:-------|:-----|
| `task_id` | PAOS | 用户任务聚合与验证 |
| `revision_id` | PAOS | 只追加规划世代 |
| Query `record_id` | PAOS | 一次绑定同步 Query |
| `invocation_id` | Gateway | 一次异步 Action 生命周期 |
| `attempt_id` | Gateway | 一次执行尝试 |

使用 `forge_task_get(task_id)` 读取聚合状态与 Tool records；使用
`forge_tool_action_status(invocation_id)` 和 `forge_tool_action_result(invocation_id)` 读取执行
事实。result endpoint 在 pending 时可以返回 HTTP 202。

任务状态：

| 状态 | 运维含义 |
|:-----|:---------|
| `executing` | 规划或绑定 Tool calls 仍在继续。 |
| `cancelling` | 已请求取消，但尚未证明物理停止。 |
| `awaiting_replan` | Verification 允许在 deadline 前追加有预算 PlanRevision。 |
| `succeeded` / `failed` / `cancelled` | PAOS 聚合终结；必要时仍独立检查 invocation facts。 |

## 5. 取消与停止

取消单个 Action 时调用 `forge_tool_cancel_action(invocation_id)`，随后继续核对 status/result。
取消一个任务的全部 Action 时调用 `forge_task_cancel(task_id, reason)`，核对每个 invocation，
物理效果不确定时检查现场，最后 finalize。

绝不能把 `requested`、`accepted`、timeout 或 `unknown` 报告成物理停止证明。效果核实完成前
不要重试运动。

被追踪 invocation 全部终结后再停止托管 Runtime：

```bash
paos skill stop move-arm-by-ee
```

`--force` 只供已独立评估物理系统的运维人员使用。它停止托管 Dora flow，但不改写 Gateway
invocation result。

## 6. 正常停机

1. 停止接纳新用户任务；
2. 读取活动 AgentTask 并核对每个 Action invocation；
3. Finalize，或 cancel 后 finalize AgentTask；
4. 停止 PAOS channels 或 Agent；
5. 停止 Skill Runtime profile；
6. 只有没有其他 profile 使用时才停止共享基础设施。

## 7. 异常重启

PAOS 重启后，用已知 `task_id` 打开持久化 AgentTask。不要根据本地 intent 重建或重发 Action。
查询每个已保存 `invocation_id`，根据 Gateway status/result 更新 record。Gateway 无法解析
invocation 时，将效果视为 unknown 并升级到物理现场检查。

`paos skill status <name>` 会根据 Dora 与 Gateway health 核对 Runtime state。当 flow 或 Tool
contexts 不可用时，它可将持久化 starting/running 改为 failed；重新启动前先诊断原 flow。

## 8. 备份与磁盘管理

停止 PAOS 后，将数据库、WAL/SHM 和引用目录一起备份：

```text
<workspace>/.paos/agent_tasks/tasks.sqlite3*
<workspace>/.paos/evolution/experience.sqlite3*
<workspace>/.paos/evolution/revisions/
<workspace>/artifacts/agent_tasks/
<workspace>/skills/
```

还应按部署的 PAOS data-path 策略保留 installed Bundle/Node manifest、Runtime state 与生命周期
日志。Evidence retention 可以在验证后清理实体文件，但不能删除 task records、invocation
references 或 evolution 历史。

## 9. 故障分层

| 层级 | 常见现象 | 首要处置 |
|:-----|:---------|:---------|
| Registry/install | Digest、size、manifest 或 lock 失败 | 修正可信 metadata 或 artifact，不绕过校验。 |
| Runtime | Dora flow 或 Gateway health 不可用 | 检查 `paos skill status` 与 `logs`。 |
| Tool context | Tool 缺失、未绑定或未 ready | 检查 ToolSpec、Endpoint、frame 与 required profile。 |
| Admission | HTTP/contract 失败 | 保留响应中已有 invocation ID，判断 Gateway 是否接纳。 |
| Execution | pending、failed、cancelled 或 unknown | 使用相同 invocation ID 核对；不确定时检查现场。 |
| Evidence | before/after source 缺失 | 检查 source readiness 与 bundle errors，ToolResult 仍为权威。 |
| Verification | invalid/inconclusive/service error | 检查任务契约、evidence、provider 与 mode。 |
| Evolution | reflection 或 promotion blocked | 检查 evolution events；执行不受影响。 |

## 10. 运行验收清单

- [ ] Package 与 runtime version 均为 0.2.2；
- [ ] 通用 Agent tools 与动态 MCP tools 仍注册；
- [ ] 所需 Skill Bundle 与全部 Node artifact 校验通过；
- [ ] 托管 Runtime ready，所有 Tool contexts 健康；
- [ ] 绑定与无任务 Query/Action 使用同一 Gateway Tool API；
- [ ] 已覆盖 Action admission、pending、terminal、cancel、timeout 与 unknown；
- [ ] 已覆盖单活动 AgentTask 与 PlanRevision recovery；
- [ ] 绑定工作流完成 evidence 与任务级 verification；
- [ ] Experience 记录 AgentTask、Skill activation、verification 与 invocation references；
- [ ] 备份包含 AgentTask 与 evolution 持久化；
- [ ] 仅在匹配 assets、nodes 与 Dora 可用时记录真实 MuJoCo 验收。

## 后续阅读

- [用户手册](../zh/02-user-manual.md)
- [通信架构](../user_development_guide/COMMUNICATION.md)
- [Forge Tool API 契约](../forge/README_zh.md)
