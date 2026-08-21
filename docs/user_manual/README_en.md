# PhyAgentOS Operations Manual

[中文](README.md) · [Documentation index](../README.md)

> Version: 0.2.2

## 1. Runtime model

```text
User/Channel → AgentLoop → Forge task and Tool API tools
                                  │
                     bound or unbound Tool call
                                  ▼
                         ForgeToolClient
                                  ▼
Gateway /tools → ToolInvocation → ToolEndpoint → Dora → robot/simulator

bound calls → AgentTask SQLite → evidence → verification → experience/evolution
```

Gateway owns execution. PAOS owns user-task aggregation and semantic verdicts. Skill Runtime owns
the explicit lifecycle of installed Bundle profiles; it does not replace Gateway execution truth.

## 2. Pre-deployment checks

### PAOS host

- Python 3.11 or 3.12 and the intended v0.2.2 environment are installed.
- `paos status` resolves the expected config, workspace, model, and provider.
- Workspace, PAOS data paths, and artifact paths have sufficient permissions and disk space.
- Verification provider credentials are available when non-`off` tasks are allowed.

### Skill Runtime

- Registry/index metadata includes artifact size and SHA-256; locked node digests resolve.
- Required binaries are executable, required assets exist, and required environment variables are set.
- Dora is installed and on `PATH`.
- The profile Gateway address is not occupied by an unmanaged process.

### Forge Gateway

- `GET /tools` returns a successful object envelope.
- Required ToolSpecs and `/tools/{tool_id}/context` are present and ready.
- Endpoint operation `max_concurrency` matches the robot's safe concurrency.
- The move-arm profile has `agent.enabled: false`.

### Persistence

- `.paos/agent_tasks`, `.paos/evolution`, Agent conversation history, and Skill Runtime state are on durable storage.
- Backup and retention procedures do not delete evolution data when rotating robot evidence.

## 3. Startup and health

For a managed Skill profile:

```bash
paos skill inspect move-arm-by-ee
paos skill start move-arm-by-ee --profile mujoco
paos skill status move-arm-by-ee
paos agent
# or: paos gateway
```

Healthy Runtime status requires persisted `running`, a live named Dora flow, Gateway `/tools`, and
ready context for every manifest `required_tool`. Use `paos skill logs <name>` for lifecycle and
Dora launch logs.

For an externally managed Gateway, start it independently and verify Tool context through the
Agent with `forge_tool_context`; `paos status` checks local configuration only.

## 4. Task monitoring

Record these identities separately:

| Identity | Owner | Use |
|:---------|:------|:----|
| `task_id` | PAOS | User-visible aggregate and verification |
| `revision_id` | PAOS | Append-only planning generation |
| Query `record_id` | PAOS | One bound synchronous Query |
| `invocation_id` | Gateway | One asynchronous Action lifecycle |
| `attempt_id` | Gateway | One execution attempt |

Use `forge_task_get(task_id)` for aggregate state and Tool records. Use
`forge_tool_action_status(invocation_id)` and `forge_tool_action_result(invocation_id)` for execution
truth. A result endpoint may return HTTP 202 while pending.

Expected task states:

| State | Operator meaning |
|:------|:-----------------|
| `executing` | Planning or bound Tool calls continue. |
| `cancelling` | Cancellation was requested; physical stop is not yet proven. |
| `awaiting_replan` | Verification permits a bounded new PlanRevision before its deadline. |
| `succeeded` / `failed` / `cancelled` | PAOS aggregate is terminal. Inspect invocation facts separately when needed. |

## 5. Cancellation and stop

For one Action, call `forge_tool_cancel_action(invocation_id)`, then continue status/result
reconciliation. For all Actions bound to a task, call `forge_task_cancel(task_id, reason)`, reconcile
each invocation, inspect physical state when effects are uncertain, then finalize the task.

Never report `requested`, `accepted`, a timeout, or `unknown` as proof of physical stop. Do not
retry the motion until effect reconciliation is complete.

Stop a managed Runtime only after its tracked invocations are terminal:

```bash
paos skill stop move-arm-by-ee
```

`--force` is reserved for an operator who has independently assessed the physical system. It stops
the managed Dora flow but does not rewrite Gateway invocation results.

## 6. Graceful shutdown

1. Stop admitting new user tasks.
2. Read the active AgentTask and reconcile every Action invocation.
3. Finalize or cancel/finalize the AgentTask.
4. Stop PAOS channels or Agent.
5. Stop the Skill Runtime profile.
6. Stop shared infrastructure only if no other profile uses it.

## 7. Crash restart

After a PAOS restart, open the persisted AgentTask with its known `task_id`. Do not recreate or
resubmit an Action from local intent. Query every persisted `invocation_id` and update the record
from Gateway status/result. If Gateway can no longer resolve an invocation, treat the effect as
unknown and escalate to physical-state inspection.

`paos skill status <name>` reconciles Runtime state against Dora and Gateway health. It can move a
persisted starting/running state to failed when the flow or Tool contexts are unavailable; restart
only after diagnosing the previous flow.

## 8. Backup and disk management

With PAOS stopped, back up the database together with WAL/SHM files and the referenced trees:

```text
<workspace>/.paos/agent_tasks/tasks.sqlite3*
<workspace>/.paos/evolution/experience.sqlite3*
<workspace>/.paos/evolution/revisions/
<workspace>/artifacts/agent_tasks/
<workspace>/skills/
```

Also retain installed Bundle/Node manifests, Runtime state, and lifecycle logs according to the
deployment's PAOS data-path policy. Evidence retention may prune entity files after verification;
it must not remove task records, invocation references, or evolution history.

## 9. Failure layers

| Layer | Typical symptom | First action |
|:------|:----------------|:-------------|
| Registry/install | Digest, size, manifest, or lock failure | Correct the signed metadata or artifact; do not bypass validation. |
| Runtime | Dora flow or Gateway health unavailable | Inspect `paos skill status` and `logs`. |
| Tool context | Tool missing, unbound, or not ready | Inspect ToolSpec, Endpoint, frame, and required profile. |
| Admission | HTTP/contract failure | Preserve any returned invocation ID; determine whether Gateway accepted work. |
| Execution | pending, failed, cancelled, or unknown | Reconcile using the same invocation ID and inspect physical state when uncertain. |
| Evidence | before/after source missing | Inspect source readiness and bundle errors; keep ToolResult authoritative. |
| Verification | invalid/inconclusive/service error | Inspect task contract, evidence, provider, and mode semantics. |
| Evolution | reflection or promotion blocked | Inspect evolution events; execution remains unaffected. |

## 10. Operational acceptance checklist

- [ ] Package and runtime version report 0.2.2.
- [ ] General Agent tools and dynamic MCP tools remain registered.
- [ ] Required Skill Bundle and all node artifacts verify.
- [ ] Managed Runtime reaches ready and all Tool contexts are healthy.
- [ ] Bound and unbound Query/Action calls use the same Gateway Tool API.
- [ ] Action admission, pending, terminal, cancel, timeout, and unknown behavior are exercised.
- [ ] One-active-AgentTask enforcement and PlanRevision recovery are exercised.
- [ ] Evidence and task-level verification complete for a bound workflow.
- [ ] Experience records AgentTask, Skill activation, verification, and invocation references.
- [ ] Backups include AgentTask and evolution persistence.
- [ ] Real MuJoCo acceptance is recorded only when matching assets, nodes, and Dora are available.

## Next reading

- [User Manual](../en/02-user-manual.md)
- [Communication Architecture](../user_development_guide/COMMUNICATION_en.md)
- [Forge Tool API Contract](../forge/README.md)
