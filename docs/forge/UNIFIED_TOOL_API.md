# Unified Forge Tool API Integration

> Applies to PhyAgentOS 0.2.2. See [Forge Tool API Integration Contract](README.md) for the full
> operational and development contract.

## One physical execution plane

```text
AgentTask-bound call / unbound call
        → ForgeToolClient
        → Gateway /tools → ToolInvocation → ToolEndpoint
        → Dora and robot nodes
```

PAOS supports Query and Action only. It does not call `/agent/sessions` or `/policy/command`, does
not implement Session semantics, and does not add a cross-Tool resource lease. The Gateway routes
to the selected Endpoint operation and enforces that operation's `max_concurrency`.

## Agent tools

- Task lifecycle: `forge_task_create`, `forge_task_get`, `forge_task_begin_revision`,
  `forge_task_finalize`, and `forge_task_cancel`.
- Tool API: `forge_tool_context`, `forge_tool_query`, `forge_tool_start_action`,
  `forge_tool_action_status`, `forge_tool_action_result`, and `forge_tool_cancel_action`.

`forge_tool_query` and `forge_tool_start_action` accept an optional `task_id`. Bound calls are
aggregated for PAOS task verification; unbound calls use the same Gateway endpoints but do not
occupy the single global AgentTask slot.

Action admission is not completion. `cancel_status=requested|accepted`, a local timeout, or an
`unknown` terminal outcome never proves that the physical effect stopped and must not trigger a
blind retry.

## AgentTask and verification

An AgentTask stores append-only PlanRevisions, Query records, Action invocation references,
evidence, and verification attempts. The following identities are deliberately different:

- PAOS `task_id`;
- PAOS `revision_id`;
- PAOS Query/execution record ID;
- Gateway `invocation_id`;
- Gateway `attempt_id`.

Forge owns each Tool execution fact. PAOS captures best-effort evidence before the first bound
Action and after all bound Actions are terminal, then `forge_task_finalize` applies the existing
`off`, `audit`, `enforce`, or `recovery` task semantics. A recoverable verdict appends a bounded
PlanRevision to the same task; it does not create another execution plane.

## Skill Runtime

`paos skill` discovers and installs manifest-v2 bundles, verifies SHA-256 inventories, and manages
an explicit named Dora profile. Installation uses safe extraction and atomic replacement. Node
artifacts are independently locked and installed under the Forge Runtime root. Downloads require
either `resourceRegistry.url`, `PAOS_RESOURCE_REGISTRY_URL`, or an explicit static index.

When one healthy Skill Runtime is active, its manifest `gateway_url` overrides `forge.baseUrl` and
its Skill becomes available to the Agent loader and activation/evolution pipeline.

The built-in `move-arm-by-ee` v0.2 profile provides:

- Query `motion.resolve_relative_pose`;
- Action `motion.move_pose`;
- Action `gripper.set_opening`;
- a MuJoCo Dora profile with `agent.enabled: false` in Gateway configuration.

Actual MuJoCo acceptance additionally requires the matching locked node artifacts and Bundle
assets from a configured Registry or release index.

---

# Forge Tool API 统一接入

当前 PAOS 只有一条物理执行链：绑定 AgentTask 的调用与无任务调用都经过
`ForgeToolClient → Gateway /tools → ToolInvocation → ToolEndpoint → Dora/机器人节点`。
PAOS 只支持 Query/Action，不调用 `/agent/sessions`、`/policy/command`，不实现 Session，
也不新增跨 Tool 资源租约；并发由 Endpoint operation 的 `max_concurrency` 裁决。

AgentTask 负责聚合 PlanRevision、Query record、Action invocation 引用、证据与验证结论，
但不执行机器人。Action 接受、取消接受、timeout 或 `unknown` 都不能解释为物理动作已经
停止，也不能触发盲目重试。恢复验证在同一个 `task_id` 上追加有预算和 deadline 的
PlanRevision。

Skill Runtime 使用 manifest v2、SHA-256 清单、安全解包、原子安装和持久化状态。活动
Runtime 的 `gateway_url` 优先于 `forge.baseUrl`；未配置 Registry 或显式静态 index 时不会
隐式下载。内置 `move-arm-by-ee` v0.2 支持相对末端位姿 Query、末端移动 Action 与夹爪
开度 Action，Gateway profile 已设置 `agent.enabled: false`。
