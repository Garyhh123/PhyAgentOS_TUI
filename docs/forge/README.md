# Forge Tool API Integration Contract

[中文](README_zh.md) · [Documentation index](../README.md)

> Applies to PhyAgentOS 0.2.2.

## 1. Execution boundary

```text
AgentTask-bound call / unbound call
        → ForgeToolClient
        → Gateway /tools → ToolInvocation → ToolEndpoint
        → Dora and robot nodes
```

PAOS supports Query and Action. AgentTask aggregates a user goal, but Gateway remains the physical
execution owner. Both bound and unbound calls use the same routes. The selected Endpoint operation
enforces `max_concurrency`; PAOS does not introduce a cross-Tool Resource/Control lease.

## 2. Tool discovery and context

```text
GET /tools
GET /tools/{tool_id}
GET /tools/{tool_id}/context
```

A ToolSpec declares stable identity, implementation/Endpoint binding, operation, `query|action`
semantics, strict input/output schema, readiness, and robot frame profile. Context is read live
before invocation; callers do not infer frame, unit, readiness, or binding.

## 3. Query contract

`forge_tool_query` reads the configured ToolSpec, verifies `semantics=query`, then invokes:

```text
POST /tools/{endpoint_id}/{operation}:invoke
Content-Type: application/json

{
  "arguments": {},
  "caller_id": "optional",
  "timeout_ms": 10000
}
```

Success is HTTP 200 with `{ "ok": true, "data": { ... } }`. A bound Query creates a terminal PAOS
ToolExecutionRecord under the active PlanRevision. An unbound Query returns the same Gateway data
without task attribution.

## 4. Action contract

Admission:

```text
POST /tools/{tool_id}:invoke
→ HTTP 202
→ data.invocation_id + data.attempt_id
```

Reconciliation:

```text
GET  /invocations/{invocation_id}
GET  /invocations/{invocation_id}/result
POST /invocations/{invocation_id}/cancel
```

Result HTTP 202 means pending. Cancel HTTP 200/202 means the cancellation request was processed or
accepted; it does not prove stop. A timeout means the remote state is unknown. An explicit
`unknown` terminal outcome closes PAOS accounting as a failure but remains physically uncertain and
must not trigger a blind retry.

Every accepted invocation identity is retained. If local tracking fails after acceptance, PAOS
returns the authoritative Gateway response with a local warning so an operator can reconcile it.

## 5. Agent tools

| Tool | Contract |
|:-----|:---------|
| `forge_tool_context` | Read ToolSpec and live context. |
| `forge_tool_query` | Invoke synchronous Query; optional `task_id`. |
| `forge_tool_start_action` | Admit asynchronous Action; optional `task_id`. |
| `forge_tool_action_status` | Read invocation phase/status. |
| `forge_tool_action_result` | Read pending or terminal result. |
| `forge_tool_cancel_action` | Request cancellation without asserting stop. |
| `forge_task_create` | Create the one active AgentTask and revision 1. |
| `forge_task_get` | Read task, revisions, Tool records, evidence, and verdict. |
| `forge_task_begin_revision` | Append a revision after an allowed recovery verdict. |
| `forge_task_finalize` | Capture after evidence and apply aggregate task verification. |
| `forge_task_cancel` | Request cancellation for all non-terminal bound Actions. |

Tools are registered when Forge is enabled or one healthy Skill Runtime is active. Existing general
Agent tools and dynamic MCP tools remain registered independently.

## 6. Identity and correlation

| Identity | Owner | Meaning |
|:---------|:------|:--------|
| `task_id` | PAOS | Stable task aggregate |
| `revision_id` | PAOS | Immutable planning generation |
| `record_id` | PAOS | Bound Query result or Action reference |
| `invocation_id` | Gateway | Asynchronous Action lifecycle |
| `attempt_id` | Gateway | Execution attempt |

Correlation is explicit. IDs are not aliases and are not derived from one another.

## 7. AgentTask model

Only one AgentTask may be non-terminal globally; unbound calls do not occupy the slot. Creation and
updates use SQLite WAL and immediate transactions. A task contains an append-only list of
PlanRevisions. Each revision contains Tool records, a semantic verdict, and verification attempts.

```text
executing
  ├─ finalize → succeeded | failed
  ├─ recovery verdict → awaiting_replan → begin_revision → executing
  └─ cancel → cancelling → reconcile → finalize → cancelled | failed
```

Once a Tool record is terminal, later observations do not rewrite its execution fact. A recovery
revision keeps the same task ID and is bounded by replan count and deadline.

## 8. Evidence and verification

PAOS performs best-effort capture before the first bound Action and after every bound Action reaches
terminal accounting state. Evidence artifacts include source, phase, sequence, timestamps, media
metadata, size, SHA-256, and workspace-relative references. Capture errors are recorded rather than
hidden.

`forge_task_finalize` aggregates all bound Tool facts and applies the task contract:

- `off`: execution-derived result;
- `audit`: record semantic verdict, preserve execution-derived result;
- `enforce`: semantic verdict controls success and fails closed;
- `recovery`: enforce semantics plus bounded `replan_required`.

Forge ToolResult and events are authoritative for execution. The PAOS verifier decides only whether
the user-level task is complete.

## 9. Experience and evolution

The terminal AgentTask is adapted into one redacted episode. It can reference explicit Skill
activation, PlanRevision verdicts, ToolInvocation/attempt fingerprints, and evidence without
persisting raw outputs, credentials, endpoints, or physical parameters in learned content.

Existing experience formats remain readable because the new references are optional. Evolution is
fail-open and never alters Gateway facts, AgentTask terminal state, or verification attempts.

## 10. Skill Runtime

Skill Runtime installs and manages manifest-v2 Bundles. Installation requires safe contained
paths, bounded extraction, SHA-256 file inventory, strict manifest validation, immutable Node locks,
staging, atomic replacement, and rollback. Registry/static-index downloads require artifact size
and digest and occur only with explicit configuration.

RuntimeManager starts a named Dora profile, checks required binaries/assets/environment, waits for
Gateway `/tools` and all manifest required Tool contexts, and persists status/logs. A healthy active
Runtime contributes Skill availability and its manifest `gateway_url` overrides `forge.baseUrl`.

Normal stop is rejected while tracked non-terminal invocations exist. Force stop is an explicit
operator decision and does not change execution truth.

## 11. move-arm-by-ee profile

The built-in `move-arm-by-ee` v0.2 Skill provides:

- `motion.resolve_relative_pose` Query;
- `motion.move_pose` Action;
- `gripper.set_opening` Action;
- MuJoCo Dora dataflow and independently locked node artifacts;
- Gateway Tool API enabled with `agent.enabled: false`.

The workflow reads context, resolves a relative target, passes the absolute pose into the motion
Action, reconciles the invocation, and finalizes task-level verification. Real MuJoCo execution
requires the matching Bundle assets and locked Runtime artifacts.

## 12. Conformance

An integration is conformant when it covers Tool discovery/context, Query response, Action
admission, pending and terminal result, cancellation, timeout/unknown, endpoint concurrency,
AgentTask binding/revisions, evidence, aggregate verification, experience attribution, Bundle
security, transactional installation, Runtime health, and availability propagation.

Mock Gateway tests are sufficient for code and contract acceptance. Hardware/MuJoCo acceptance is
recorded separately with exact artifact digests and environment.

## Related documentation

- [Framework Introduction](../en/01-framework-introduction.md)
- [Configuration Reference](../en/04-forge-configuration-reference.md)
- [Integration Development Guide](../user_development_guide/README_en.md)
- [Operations Manual](../user_manual/README_en.md)
