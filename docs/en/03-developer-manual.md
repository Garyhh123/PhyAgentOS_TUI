# PhyAgentOS Developer Manual

[中文](../zh/03-developer-manual.md) · [Documentation index](../README.md)

> Documentation version: 0.2.2.

## 1. Development invariants

1. Robot execution has one physical path: `ForgeToolClient → Gateway Tool API → ToolEndpoint`.
2. AgentTask aggregates planning, evidence, and verdicts; it never executes the robot.
3. `task_id`, `revision_id`, Query record ID, `invocation_id`, and `attempt_id` are distinct.
4. Forge ToolResult and invocation events are authoritative execution facts.
5. Action admission, cancellation acceptance, timeout, and `unknown` do not prove physical stop.
6. General Agent tools, verification, experience, evolution, and dynamic MCP remain independent.
7. Runtime artifacts are installed only after bounded archive and digest verification.

## 2. Module map

| Module | Responsibility |
|:-------|:---------------|
| `agent/loop.py` | Existing Agent loop, general tools, dynamic MCP, Forge tool registration, context, and lifecycle |
| `agent/tools/forge_tool_api.py` | Six Agent wrappers over Query/Action Tool API |
| `agent/tools/forge_task.py` | Five AgentTask lifecycle tools |
| `forge/tool_client.py` | Strict asynchronous HTTP client and response validation |
| `forge/task.py` | AgentTask models, SQLite store, Tool binding, evidence capture, verification, and recovery |
| `forge/observation.py`, `forge/evidence.py` | Best-effort image/state collection and artifact writing |
| `skill_runtime/` | Manifest, catalog, safe archive, installer, Registry, state, Runtime manager, and availability |
| `agent/experience/` | Activation, episodes, assessment, Lessons, Skill candidates, and evolution |
| `verification/` | Public task, evidence, request, and verdict contracts plus verification service |

## 3. Forge Tool API client

`ForgeToolClient` accepts only JSON object envelopes with `ok=true` and object-valued `data`.
Errors preserve HTTP status, error code, retryability, and any returned invocation identity.

| Operation | HTTP contract |
|:----------|:--------------|
| List Tools | `GET /tools` → 200 |
| Read ToolSpec | `GET /tools/{tool_id}` → 200 |
| Read context | `GET /tools/{tool_id}/context` → 200 |
| Invoke Query | resolve ToolSpec, then `POST /tools/{endpoint_id}/{operation}:invoke` → 200 |
| Admit Action | `POST /tools/{tool_id}:invoke` → 202 |
| Action status | `GET /invocations/{invocation_id}` → 200 |
| Action result | `GET /invocations/{invocation_id}/result` → 200 or pending 202 |
| Request cancel | `POST /invocations/{invocation_id}/cancel` → 200 or accepted 202 |

Path components are percent-encoded. Invocation input is `{arguments, caller_id?, timeout_ms?}`.
An Action admission must contain non-empty `invocation_id` and `attempt_id`. If PAOS local tracking
fails after Gateway acceptance, the authoritative response is retained with a `paos_warnings`
entry rather than replaced by a false transport failure.

## 4. Agent-facing tools

Task lifecycle:

- `forge_task_create(task_description, verification)`;
- `forge_task_get(task_id)`;
- `forge_task_begin_revision(task_id, reason)`;
- `forge_task_finalize(task_id)`;
- `forge_task_cancel(task_id, reason?)`.

Tool transport:

- `forge_tool_context(tool_id)`;
- `forge_tool_query(tool_id, arguments, task_id?, caller_id?, timeout_ms?)`;
- `forge_tool_start_action(tool_id, arguments, task_id?, caller_id?, timeout_ms?)`;
- `forge_tool_action_status(invocation_id)`;
- `forge_tool_action_result(invocation_id)`;
- `forge_tool_cancel_action(invocation_id)`.

Bound and unbound calls invoke the same HTTP methods. Bound calls additionally create or update a
ToolExecutionRecord in the active revision. Tool wrappers must never invent a Gateway result.

## 5. AgentTask contracts and transactions

`AgentTaskRecord` contains a stable ID, task description, `TaskVerificationContract`, status,
append-only PlanRevisions, evidence references, verification attempts, cancellation state, and
timestamps. Each `PlanRevision` contains its own Tool records, verdict, and verification attempts.

`AgentTaskStore` uses SQLite WAL and `BEGIN IMMEDIATE`. Creation queries for any non-terminal task
inside the same transaction, enforcing one global active slot across processes. Updates write the
complete validated record and an append-only event. Callers do not modify tables directly.

Terminal task states are `succeeded`, `failed`, and `cancelled`. Non-terminal states are
`executing`, `cancelling`, and `awaiting_replan`. Tool status `unknown` is terminal for aggregate
accounting but is a failure, not evidence of stop.

## 6. Bound execution lifecycle

1. Create an AgentTask and revision 1.
2. On the first bound Action, perform best-effort before-capture.
3. Invoke Query or admit Action through ForgeToolClient.
4. Persist Query response or Action invocation/attempt references.
5. Update Action record only from authoritative status/result responses.
6. After every bound Action is terminal, perform after-capture on finalize.
7. Aggregate Tool records, evidence, and the task contract for verification.
8. Persist task and revision verdicts; schedule one terminal experience episode.

Once a record is terminal, later observations do not rewrite it. Cancellation responses are
stored, but `requested` or `accepted` leaves the task in `cancelling` until reconciliation and
explicit finalization.

## 7. Verification and recovery

`TaskVerificationContract` remains the public user-level contract. The verifier receives goal,
criteria, constraints, all bound execution facts, validated evidence, prior attempts, and frozen
Skill-scoped advisory Lessons.

In recovery mode, a valid `replan_required` verdict moves the task to `awaiting_replan` with a
deadline. `begin_revision` checks the same `task_id`, replan budget, deadline, and task state, then
appends a revision. Earlier attempts remain visible to experience analysis. Verifier exceptions are
persisted as failed attempts; audit preserves execution semantics, while enforce/recovery fail.

## 8. Evidence and retention

Evidence paths are workspace-relative and written atomically. Images are validated for media type,
decoded size, sequence, timestamps, phase, source, and SHA-256. The evidence bundle records capture
quality and errors rather than presenting best-effort collection as authoritative.

Retention can remove entity bytes according to policy, but it must preserve the task record,
execution references, bundle metadata, and tombstone information required for audit.

## 9. Skill Runtime contracts

A `skill.yaml` manifest must use `manifest_version: 2`, a directory-safe name/version, a relative
Skill document, an HTTP(S) `gateway_url`, non-empty required Tools, at least one profile, and strict
known fields. Registry-resolved nodes require artifact identity, version, platform, architecture,
and SHA-256 digest.

Archive validation rejects absolute/traversing paths, links, duplicate/colliding paths, oversized
files, expansion-limit violations, missing inventory entries, and digest mismatches. Skill and Node
installers stage content, validate it, then atomically replace the target with rollback support.

RuntimeManager:

1. resolves the installed Skill and profile;
2. materializes the locked environment without mutating installed nodes;
3. checks Dora, dataflow, required files, and environment;
4. refuses to adopt an unmanaged Gateway already using the address;
5. starts the named Dora flow;
6. waits for flow, `GET /tools`, and all required Tool contexts;
7. persists running/failed/stopped state and lifecycle logs.

A normal stop is rejected while non-terminal invocations remain tracked. Force stop is an explicit
operator action and does not change invocation truth.

## 10. Registry and availability

Registry and static-index artifacts require expected size and SHA-256 before entering the cache.
Resumed downloads are verified again before installation. No Registry URL means no Registry
download. `PAOS_RESOURCE_REGISTRY_URL` overrides `resourceRegistry.url`.

`discover_active_runtime` reconciles persisted state, Dora flow, Gateway health, and required Tool
contexts. Its availability provider flows through SkillsLoader, ExperienceCoordinator, and
SkillActivationManager. Skill discovery order is workspace, installed, built-in.

## 11. Experience and evolution integration

All Agent tool calls remain recorded. Optional opaque fields attach AgentTask, revision,
invocation, and attempt references without breaking older persisted models. The outcome source
maps each revision verdict to its last execution record so a recovered task preserves both failed
and successful semantic attempts.

Generated Lessons and Skill updates remain subject to redaction, scope, support thresholds,
abstraction checks, managed-block replacement, atomic writes, reload validation, and rollback.
Evolution failures remain fail-open.

## 12. Extension workflows

To add a robot capability:

1. implement or package the ToolEndpoint operation;
2. publish a Query or Action ToolSpec with exact schemas and binding;
3. define operation `max_concurrency` in Gateway;
4. add the locked node and profile references to a manifest-v2 Bundle;
5. test context, invocation, pending, terminal, cancellation, and unknown outcomes;
6. add workflow guidance to a Skill without embedding task-specific coordinates or secrets.

Do not create a second PAOS execution protocol, direct Agent-to-Dora calls, or a cross-Tool lease.
A new Agent tool is justified only when the generic task and Tool API tools cannot express the
capability.

## 13. Test gates

```bash
ruff check PhyAgentOS tests
python -m compileall -q PhyAgentOS tests
pytest -q
```

Tests should cover response contracts, pending/cancel/timeout/unknown semantics, one active task,
unbound calls, revision recovery, evidence, episode attribution, archive attacks, transactional
rollback, Registry verification, Runtime health, and mocked Query→Action workflows. Real MuJoCo
tests are conditional on matching artifacts and Dora availability.

## Next reading

- [Forge Tool API Integration Contract](../forge/README.md)
- [Integration Development Guide](../user_development_guide/README_en.md)
- [Agent Experience and Skill Evolution](05-agent-experience-and-skill-evolution.md)
