# Forge Tool API 接入契约

[English](README.md) · [文档索引](../README.md)

> 适用于 PhyAgentOS 0.2.2。

## 1. 执行边界

```text
绑定 AgentTask 的调用 / 无任务调用
        → ForgeToolClient
        → Gateway /tools → ToolInvocation → ToolEndpoint
        → Dora 与机器人节点
```

PAOS 支持 Query 与 Action。AgentTask 聚合用户目标，但 Gateway 仍是物理执行所有者。绑定与
无任务调用使用相同 routes。所选 Endpoint operation 执行 `max_concurrency`；PAOS 不增加跨
Tool Resource/Control lease。

## 2. Tool 发现与 context

```text
GET /tools
GET /tools/{tool_id}
GET /tools/{tool_id}/context
```

ToolSpec 声明稳定 identity、implementation/Endpoint binding、operation、`query|action`
semantics、严格 input/output schema、readiness 与 robot frame profile。调用前实时读取 context，
调用方不能猜测 frame、unit、readiness 或 binding。

## 3. Query 契约

`forge_tool_query` 读取配置 ToolSpec，确认 `semantics=query`，再调用：

```text
POST /tools/{endpoint_id}/{operation}:invoke
Content-Type: application/json

{
  "arguments": {},
  "caller_id": "optional",
  "timeout_ms": 10000
}
```

成功响应为 HTTP 200 和 `{ "ok": true, "data": { ... } }`。绑定 Query 在 active
PlanRevision 下创建终态 PAOS ToolExecutionRecord；无任务 Query 返回相同 Gateway data，但不
进行任务归因。

## 4. Action 契约

Admission：

```text
POST /tools/{tool_id}:invoke
→ HTTP 202
→ data.invocation_id + data.attempt_id
```

Reconciliation：

```text
GET  /invocations/{invocation_id}
GET  /invocations/{invocation_id}/result
POST /invocations/{invocation_id}/cancel
```

Result HTTP 202 表示 pending。Cancel HTTP 200/202 表示取消请求已处理或接受，不证明停止。
Timeout 表示远端状态未知。显式 `unknown` 终态会以失败关闭 PAOS 记账，但物理效果仍不确定，
不能触发盲目重试。

任何已接纳 invocation identity 都必须保留。若接纳后本地追踪失败，PAOS 返回权威 Gateway
response 并附加本地 warning，便于运维核对。

## 5. Agent tools

| Tool | 契约 |
|:-----|:-----|
| `forge_tool_context` | 读取 ToolSpec 与实时 context。 |
| `forge_tool_query` | 调用同步 Query，可选 `task_id`。 |
| `forge_tool_start_action` | 接纳异步 Action，可选 `task_id`。 |
| `forge_tool_action_status` | 读取 invocation phase/status。 |
| `forge_tool_action_result` | 读取 pending 或终态 result。 |
| `forge_tool_cancel_action` | 请求取消，不宣称停止。 |
| `forge_task_create` | 创建唯一活动 AgentTask 与 revision 1。 |
| `forge_task_get` | 读取 task、revisions、Tool records、evidence 与 verdict。 |
| `forge_task_begin_revision` | 在允许 recovery verdict 后追加 revision。 |
| `forge_task_finalize` | 后置采集并执行聚合任务验证。 |
| `forge_task_cancel` | 为全部非终态绑定 Action 请求取消。 |

Forge 启用或存在健康活动 Skill Runtime 时注册这些 tools。现有通用 Agent tools 与动态 MCP
tools 独立保持注册。

## 6. Identity 与关联

| Identity | 所有者 | 含义 |
|:---------|:-------|:-----|
| `task_id` | PAOS | 稳定任务聚合 |
| `revision_id` | PAOS | 不可变规划世代 |
| `record_id` | PAOS | 绑定 Query result 或 Action reference |
| `invocation_id` | Gateway | 异步 Action 生命周期 |
| `attempt_id` | Gateway | 执行 attempt |

关联必须显式保存；这些 ID 不是别名，也不能相互派生。

## 7. AgentTask 模型

全局最多一个非终态 AgentTask；无任务调用不占槽位。创建与更新使用 SQLite WAL 和 immediate
transaction。Task 包含只追加 PlanRevision；每个 revision 包含 Tool records、semantic verdict
和 verification attempts。

```text
executing
  ├─ finalize → succeeded | failed
  ├─ recovery verdict → awaiting_replan → begin_revision → executing
  └─ cancel → cancelling → reconcile → finalize → cancelled | failed
```

Tool record 终结后，后续 observation 不改写执行事实。Recovery revision 保持相同 task ID，
并受 replan count 与 deadline 限制。

## 8. Evidence 与 verification

PAOS 在第一次绑定 Action 前和所有绑定 Action 达到记账终态后进行 best-effort 采集。Evidence
artifact 包含 source、phase、sequence、timestamp、media metadata、size、SHA-256 与工作区相对
reference。采集错误会显式记录。

`forge_task_finalize` 聚合全部绑定 Tool facts，并应用任务契约：

- `off`：执行派生结果；
- `audit`：记录 semantic verdict，保留执行派生结果；
- `enforce`：semantic verdict 决定成功并 fail closed；
- `recovery`：enforce 语义加有预算 `replan_required`。

Forge ToolResult 与 events 对执行负责；PAOS verifier 只判断用户任务是否完成。

## 9. Experience 与 evolution

终态 AgentTask 转换为唯一去敏 episode，可引用显式 Skill activation、PlanRevision verdict、
ToolInvocation/attempt fingerprint 和 evidence，但不会把原始 output、凭据、endpoint 或物理参数
写入学习内容。

新增 reference 为可选字段，因此旧 experience 格式保持可读。Evolution fail-open，不改变
Gateway facts、AgentTask terminal state 或 verification attempt。

## 10. Skill Runtime

Skill Runtime 安装并管理 manifest v2 Bundle。安装要求安全 contained path、有界解包、SHA-256
文件清单、严格 manifest、不可变 Node lock、staging、原子替换与 rollback。Registry/静态 index
下载必须有 artifact size 与 digest，并且只在显式配置时发生。

RuntimeManager 启动命名 Dora profile，检查 required binaries/assets/environment，等待 Gateway
`/tools` 与 manifest 全部 required Tool context，并持久化 status/log。健康活动 Runtime 提供
Skill availability，其 manifest `gateway_url` 覆盖 `forge.baseUrl`。

存在被追踪非终态 invocation 时，正常 stop 会被拒绝。Force stop 是显式运维决策，不改变执行
事实。

## 11. move-arm-by-ee profile

内置 `move-arm-by-ee` v0.2 Skill 提供：

- `motion.resolve_relative_pose` Query；
- `motion.move_pose` Action；
- `gripper.set_opening` Action；
- MuJoCo Dora dataflow 与独立锁定 Node artifacts；
- Gateway Tool API 启用并设置 `agent.enabled: false`。

工作流读取 context、解析相对目标、把绝对 pose 传给移动 Action、核对 invocation，并完成任务级
verification。真实 MuJoCo 执行需要匹配的 Bundle assets 与锁定 Runtime artifacts。

## 12. Conformance

接入需要覆盖 Tool discovery/context、Query response、Action admission、pending/terminal result、
cancel、timeout/unknown、endpoint concurrency、AgentTask binding/revisions、evidence、聚合
verification、experience attribution、Bundle security、事务安装、Runtime health 与 availability
传播。

Mock Gateway 测试可完成代码与契约验收；硬件/MuJoCo 验收单独记录确切 artifact digests 与环境。

## 相关文档

- [框架介绍](../zh/01-framework-introduction.md)
- [配置参考](../zh/04-forge-configuration-reference.md)
- [集成开发指南](../user_development_guide/README.md)
- [运行手册](../user_manual/README.md)
