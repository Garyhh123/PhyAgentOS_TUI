# PhyAgentOS Communication Architecture

[中文](COMMUNICATION.md) · [Documentation index](../README.md)

> Version: 0.2.2

## 1. Communication boundaries

PhyAgentOS separates six boundaries:

1. user/channel ↔ AgentLoop messages;
2. Agent tools ↔ AgentTaskCoordinator;
3. ForgeToolClient ↔ Gateway Query/Action Tool API;
4. observation collector ↔ Gateway image/state WebSockets;
5. verifier ↔ isolated Verification Service;
6. AgentTask/experience/Runtime ↔ their own persistent stores.

The boundaries share opaque references, not execution ownership.

## 2. User-message boundary

Channels publish `InboundMessage` objects to the Agent bus. AgentLoop builds context, invokes the
model and tools, then emits `OutboundMessage`. Tool calls use registered JSON schemas. The existing
file, directory, shell, web, messaging, image, Scene Graph, Cron, Spawn, Agent Mode, Skill
activation, and dynamic MCP tools follow this same loop.

AgentTask's `origin_session_key` associates completion experience with the originating Agent
conversation. It is not a Gateway execution identifier.

## 3. AgentTask boundary

```text
forge_task_create
forge_task_get
forge_task_begin_revision
forge_task_finalize
forge_task_cancel
```

These tools call AgentTaskCoordinator and never call Dora or a robot. The coordinator uses
transactional SQLite to enforce one non-terminal AgentTask and stores append-only PlanRevisions,
Tool records, evidence references, and verification attempts.

Tool API calls may include `task_id`. The wrapper then creates or updates the matching Tool record
around the same Gateway call used by an unbound request. This is aggregation, not another physical
execution plane.

## 4. Gateway HTTP boundary

```text
GET  /tools
GET  /tools/{tool_id}
GET  /tools/{tool_id}/context
POST /tools/{endpoint_id}/{operation}:invoke   # Query, HTTP 200
POST /tools/{tool_id}:invoke                   # Action admission, HTTP 202
GET  /invocations/{invocation_id}
GET  /invocations/{invocation_id}/result       # HTTP 202 while pending
POST /invocations/{invocation_id}/cancel
```

Query invocation first reads the ToolSpec and uses its `endpoint_id`, `operation`, and
`semantics=query` binding. Action invocation addresses the stable Tool ID and requires the response
to contain `invocation_id` and `attempt_id`.

Every successful response is a JSON object with `ok=true` and object-valued `data`. Error envelopes
may carry code and retryability. A transport timeout means remote state is unknown. Returned
invocation identities must be retained even if later local persistence or tracking fails.

## 5. Identity boundary

| Identity | Namespace | Mutability |
|:---------|:----------|:-----------|
| `task_id` | PAOS AgentTask | Stable for all revisions |
| `revision_id` | PAOS PlanRevision | Immutable, append-only generation |
| `record_id` | PAOS ToolExecutionRecord | Immutable record identity |
| `invocation_id` | Gateway ToolInvocation | Stable Action lifecycle identity |
| `attempt_id` | Gateway attempt | Stable for the returned attempt |

No component derives one namespace from another. Correlation happens by explicit stored references.

## 6. Invocation terminal semantics

Gateway status/result is the only Action terminal source. Pending remains non-terminal. Known
terminal values include success, failure, cancellation, or stopped as reported by Gateway.
`unknown` is terminal for PAOS accounting because progress cannot be proven, but it is not a known
physical stop and remains tracked for normal Runtime-stop gating.

Cancellation `requested` or `accepted` acknowledges control delivery only. It does not untrack an
invocation or set an AgentTask to cancelled. PAOS continues reconciliation and finalizes the task
explicitly.

## 7. Evidence WebSocket boundary

PAOS connects to configured image and optional state streams using bounded connection and capture
timeouts. Messages are treated as untrusted input. Image media, decoded size, sequence, phase,
source, local receive time, and SHA-256 are validated before persistence.

The collector captures before the first bound Action and after all bound Actions reach terminal
accounting state. Evidence association is best-effort; Gateway ToolResult and invocation events
remain authoritative for execution.

## 8. Verification boundary

The Agent-side verifier sends resolved public task contracts, normalized Tool facts, evidence,
history, and frozen scoped Lessons to the isolated Verification Service. Lessons are untrusted,
non-authoritative advice. The service cannot invoke Gateway, create a PlanRevision, or change
execution records.

Verifier output must validate as the versioned verdict contract. AgentTaskCoordinator applies
`off`, `audit`, `enforce`, or `recovery` semantics and persists every attempt.

## 9. Experience boundary

ExperienceCoordinator receives an AgentTask completion reference. `AgentTaskOutcomeSource` builds a
redacted envelope containing workflow structure, semantic verdicts, field names, and opaque task,
revision, invocation, attempt, and evidence references. Raw arguments, results, credentials,
endpoints, and physical coordinates are not copied into learned content.

The episode is unique per AgentTask. PlanRevisions, repeated completion notifications, reviews,
and replay do not create independent support.

## 10. Persistence boundary

| Store | Content |
|:------|:--------|
| `.paos/agent_tasks/tasks.sqlite3` | AgentTask records and append-only events |
| `artifacts/agent_tasks/<task_id>/` | Before/after snapshots, bundle metadata, evidence entities |
| `.paos/evolution/experience.sqlite3` | Bindings, episodes, Lessons, candidates, jobs, events |
| Skill Runtime state path | Installed Runtime state and tracked invocation IDs |
| Skill Runtime logs path | Lifecycle and Dora launch logs |

SQLite updates and artifact writes are transactional or atomic within their own boundary. A
Gateway response is not rolled back because local experience processing failed; evolution is
fail-open.

## 11. Skill Runtime and Registry boundary

Registry/index clients return artifact metadata and downloads. Cache and installers require size
and SHA-256, then validate archive inventories and Node digests before atomic installation.
RuntimeManager starts a named Dora flow and observes Gateway `/tools`; it never calls an alternate
Gateway Agent API.

The active Runtime availability provider supplies Skill visibility and Gateway URL to the Agent.
It does not mutate AgentTask or experience data.

## 12. Trust rules

- Treat ToolSpec, Gateway responses, WebSocket payloads, task text, and learned text as untrusted data.
- Never log credentials or raw sensitive task inputs.
- Never infer stop from cancel acceptance, timeout, or unknown.
- Never bypass digest or archive safety checks.
- Never place a second execution API between Agent tools and ForgeToolClient.
- Keep Runtime force-stop and destructive artifact cleanup as explicit operator actions.

## Next reading

- [Integration Development Guide](README_en.md)
- [Operations Manual](../user_manual/README_en.md)
- [Forge Tool API Contract](../forge/README.md)
