# PhyAgentOS Developer Manual

> Documentation version: 0.2.1. This manual is for PAOS, Forge Gateway, evidence, verifier, Agent-tool, and experience-evolution developers.

## 1. Development principles

Changes touching embodied execution must preserve these invariants:

1. Forge Gateway is the only robot execution entry point.
2. Gateway terminal state is execution fact; task success follows verification policy.
3. Only PAOS generates session and command IDs; callers cannot provide or reuse them.
4. A session with recorded dispatch intent is never automatically POSTed again.
5. Gateway session, command, request, action, command identity, and policy identity all match.
6. A written Execution Record cannot be overwritten by verification, review, or retention.
7. Evidence preserves real source, sequence, source time when present, and PAOS receive time; it never fabricates authoritative association.
8. Verifier prompts, public verdicts, and Recovery Requests are independent of `action_type`.
9. Parent `replanned` and child creation occur in one SQLite transaction.
10. Execution, evidence, verification, recovery, and persistence changes include failure and restart tests.
11. Experience is counted once per root lineage, stores redacted workflow structure rather than raw tool data, and never runs on the Forge critical path.
12. Evolution is fail-open, never rewrites operator safety files, and modifies only validated workspace Skill managed blocks or generated Lesson projections.

## 2. Module map

| Area | Path | Responsibility |
|:-----|:-----|:---------------|
| Agent integration | `PhyAgentOS/agent/loop.py` | Register tools, inject capability summary, handle system events |
| Agent tools | `PhyAgentOS/agent/tools/forge.py` | JSON schemas, call context, Orchestrator facade |
| Public contracts | `PhyAgentOS/verification/contracts.py` | Task, Session, Execution, Evidence, Verdict, Recovery, state machine |
| Verification request | `PhyAgentOS/verification/request_builder.py` | Resolve bundle, validate digest/window/requirements, build multimodal request |
| Verification engine | `PhyAgentOS/verification/engine.py` | Stateless model call and timeout |
| Verification service | `PhyAgentOS/verification/service.py` | Child process, readiness, authentication, strict JSON output |
| Verifier facade | `PhyAgentOS/agent/session_verifier.py` | Budgets, attempts, retention, optional legacy Lesson writes, review |
| Skill activation | `PhyAgentOS/agent/experience/activation.py` | Per-turn primary/supporting binding, trace field names, scoped Lesson retrieval |
| Experience contracts | `PhyAgentOS/agent/experience/contracts.py` | Outcome, episode, assessment, observation, cluster, Lesson, and candidate models |
| Outcome adapters | `PhyAgentOS/agent/experience/source.py` | Generic `TaskOutcomeSource` and Forge root-lineage envelope |
| Experience coordinator/store | `PhyAgentOS/agent/experience/coordinator.py`, `store.py` | Async jobs, root idempotency, SQLite WAL ledger, restart recovery |
| Reflection and evolution | `PhyAgentOS/agent/experience/analyzer.py`, `evolution.py` | Structured model calls, Lesson lifecycle, Skill validation/promotion/rollback |
| Gateway client | `PhyAgentOS/forge/client.py` | `httpx.AsyncClient` wrapper for Agent API |
| Observation | `PhyAgentOS/forge/observation.py` | Async WebSockets, bounded per-source latest frames, validation |
| Evidence writer | `PhyAgentOS/forge/evidence.py` | Safe paths, atomic writes, SHA-256, snapshots, bundles |
| Adapter | `PhyAgentOS/forge/adapter.py` | One-action execution, identity, polling, timeout, cancellation, mapping |
| Store | `PhyAgentOS/forge/store.py` | SQLite WAL, transactions, state, events, atomic replan |
| Orchestrator | `PhyAgentOS/forge/orchestrator.py` | Async tasks, modes, restart, recovery, notification |
| Configuration | `PhyAgentOS/config/schema.py` | Forge, evidence, verification, and embodiment schemas |

## 3. Public models

### 3.1 `ForgeTaskRequest`

```python
ForgeTaskRequest(
    task_description="Place the red object in the tray",
    action_type="<gateway-advertised-action>",
    inputs={...},
    verification=TaskVerificationContract(...),
    execution_timeout_s=300.0,
)
```

`inputs` must contain finite JSON values. NaN, Infinity, non-serializable objects, and blank `task_description` or `action_type` values are rejected.

### 3.2 `TaskVerificationContract`

When `mode != off`, goal and at least one criterion are required. Criteria and constraints cannot contain blank items. Evidence policy requires `rgb_image` by default and may override sources per task. Empty task sources fall back to Forge target configuration or readiness discovery.

### 3.3 `ExecutionRecord`

This model is `frozen=True` and contains:

- PAOS/Gateway session and command IDs;
- Gateway API and instance identity;
- action type and policy ID;
- normalized execution status;
- generic capability `result_semantics` and `completion` declarations;
- Gateway timeline, outputs, and error.

Never put a task verdict into this model or change Gateway `succeeded` to `failed` because a verifier rejected the semantic result.

### 3.4 `EvidenceBundle`

Each artifact has phase, kind, source ID, sequence, capture/receive time, media type, byte size, SHA-256, a safe workspace-relative URI, and retention state. `EvidenceQuality` separately records completeness, association, missing requirements, stale artifacts, and errors.

### 3.5 `VerificationVerdict`

The verifier returns exactly one `CriterionVerdict` for each input success criterion and copies the criterion verbatim. `success` requires every criterion to be `satisfied`. `failure` and `replan_required` require at least one unmet or unknown item. `replan_required` also requires action-independent `recovery_context`.

### 3.6 Experience contracts

The experience subsystem has its own versioned boundary:

| Model | Role |
|:------|:-----|
| `TaskOutcomeEnvelope` | Provider-neutral semantic result, criterion statuses, lineage attempts, and opaque record/evidence references |
| `TaskEpisode` | One redacted root task plus Skill activations and workflow trace |
| `ExperienceAssessment` | Structured reflection with reuse decision, Skill proposal, failure observations, contradictions, and conflicts |
| `LessonEligibility` | `related | unrelated | uncertain` attribution with a bounded reason enum and confidence |
| `FailureObservation` | Normalized workflow failure pattern without a concrete answer or raw task values |
| `LessonCluster` | Same-Skill, same-workflow, canonical-pattern support and synthesis state |
| `ScopedLesson` | Applicable/non-applicable boundaries, failure mode, recommendation, source support, and lifecycle state |
| `SkillCandidate` | Create/update proposal, independent support, blockers, revision, and promotion state |

These contracts reject extra fields. Persisted workflow traces contain tool names and input field names only. Endpoints, credentials, absolute paths, command IDs, raw outputs, and evidence locators are removed or replaced with opaque references; lineage session IDs remain only as internal immutable record references and are forbidden in generated Lesson/Skill content.

## 4. State machine and transactions

`ALLOWED_FORGE_TRANSITIONS` defines every legal transition. Every Store update loads the model, applies a mutation, validates the transition, updates time, writes JSON, appends an event, and commits.

SQLite tables:

```text
forge_sessions
  session_id PRIMARY KEY
  command_id UNIQUE
  root_session_id
  parent_session_id UNIQUE
  status
  record_json
  created_at / updated_at

forge_events
  event_id PRIMARY KEY
  session_id FOREIGN KEY
  event_type
  created_at
  payload_json
```

Task creation and replan use `BEGIN IMMEDIATE`, keeping one non-terminal lineage even when multiple Store instances submit concurrently.

Experience state is independent and stored in `.paos/evolution/experience.sqlite3`. Its tables include task bindings, unique-root episodes/jobs, scoped Lessons, failure observations, Lesson clusters, unique `(cluster_id, root_task_id)` support, cluster jobs, Skill candidates, events, and migration metadata. WAL and `BEGIN IMMEDIATE` protect writes; interrupted running jobs return to `pending` at startup. This database does not participate in Forge state transitions.

## 5. Gateway startup contract

`ForgeAdapter.validate_capabilities()` requires:

```json
{
  "api_version": "paos-forge-gateway-mvp-plus.v1",
  "supports": {
    "sessions": true,
    "command_id": true,
    "runtime_context": true,
    "serial_actions_only": true
  },
  "actions": {
    "<action_type>": {
      "policy_id": "...",
      "command": "...",
      "result_semantics": "command_completed",
      "completion": {},
      "required_parameters": [],
      "input_mapping": {}
    }
  }
}
```

Action metadata informs Planner selection and the Execution Record. It never chooses a verifier branch.

## 6. Adapter execution protocol

The ordering for a fresh task is mandatory:

1. Validate action capability.
2. Start image/state collectors for non-`off` work.
3. Await required sources and atomically persist the before snapshot.
4. Let Orchestrator persist `dispatching` and dispatch intent.
5. POST `/agent/sessions`.
6. Validate session, command, and action identity in the create response.
7. Poll `/agent/sessions/{session_id}`.
8. Accept only `succeeded | failed | cancelled`; request cancellation on timeout.
9. After observing terminal state, await higher image sequences and write the after snapshot.
10. Write immutable Execution Record and Evidence Bundle.

Gateway payload:

```json
{
  "session_id": "forge_<generated>",
  "command_id": "command_<generated>",
  "action_type": "...",
  "instruction": "...",
  "source": "paos-agent",
  "inputs": {}
}
```

Terminal acceptance requires all of:

```text
session.session_id == requested session_id
command.command_id == requested command_id
command.session_id == requested session_id
command.request_id == requested command_id
session.action_type == requested action_type
command.action_type/policy_id/command == advertised capability identity
session.status == command.status in succeeded|failed|cancelled
```

## 7. Observation and evidence

The collector retains only the highest legal sequence for each required image source. Duplicate or out-of-order frames do not replace the latest frame. It reconnects after disconnection and keeps a bounded recent-error list.

Accepted entities are:

- `image/jpeg` / `image/jpg`;
- `image/png`;
- `image/webp`;
- JSON robot state.

Beyond Base64 and decoded size limits, image magic bytes are verified. Artifact filenames include a safe source label, source digest, and sequence to avoid collisions after source sanitization. Every URI is workspace-relative and rejects `..`.

Before model invocation, `VerificationRequestBuilder` revalidates:

- bundle/session/command identity;
- completeness and minimum association;
- capture-window ordering;
- required kinds and sources in both phases;
- retained entity existence, byte size, and SHA-256;
- image media type against bytes;
- unique evidence IDs.

## 8. Verification Service

`ForgeTaskVerifier` starts an independent Python child process. It listens on configured host/port, authenticates with a per-process `X-PAOS-Admin-Token`, and exposes:

```text
GET  /healthz
POST /v1/verify-task
```

The request version is `forge_verification_request_v1`. Startup readiness is bounded; model calls are limited by `timeoutS` and `maxVerifierCallsPerRun`.

The prompt contains only:

- task goal, success criteria, and constraints;
- immutable Execution Record;
- Evidence Bundle and entities;
- root-lineage history;
- when evolution is enabled, the active scoped Lessons frozen from the root task's explicit Skill activations;
- otherwise, legacy/human-authored root Lessons when present;
- valid evidence IDs.

Scoped Lessons are untrusted, non-authoritative workflow advice. The service prompt forbids using them to establish criterion status, replace the task contract or evidence, or populate evidence references. Evolution mode never reads root `LESSONS.md` for automatic verification or review; an unbound task receives an empty Lesson set. Malformed service output is normalized to `inconclusive`, then checked again by public models and the exact-criteria validator. `audit` records the error; `enforce` and `recovery` fail closed. The verdict's `lesson` field is reflection input only. With evolution enabled, the verifier no longer appends it directly to root `LESSONS.md`.

## 9. Recovery

The verifier may recommend `replan_required` but cannot output action types, policy parameters, or Gateway inputs. Orchestrator creates a `RecoveryRequest` and sends an `InboundMessage(channel="system")` to the original Agent session.

When Planner calls `create_replanned_forge_session`:

- parent is still `awaiting_replan`;
- deadline is not expired;
- replan budget remains;
- child inherits verification contract, root lineage, origin routing, and source;
- Planner supplies new task description, action type, and inputs;
- PAOS generates fresh session and command IDs;
- parent terminal transition and child creation commit atomically;
- duplicate calls return the existing child.

## 10. Agent task experience and Skill evolution

### 10.1 Activation and attribution

`activate_skill` resolves only exact hyphen-case names registered by `SkillsLoader`, honors workspace-over-built-in precedence, and rejects unavailable Skills and arbitrary paths. One turn may activate one primary and multiple supporting Skills. The activation result returns the full Skill, the activation record/digest, and ranked active Lessons. Only the primary may be updated automatically; supporting Skills may receive failure attribution.

AgentLoop records tool order and argument keys during the turn. After `forge_execute_task` accepts a new root session, that activation snapshot is bound to the root ID. A direct `SKILL.md` read is deliberately not an activation. Tasks without an activation remain unbound rather than receiving a guessed association.

### 10.2 Outcome capture and reflection jobs

`ForgeTaskOutcomeSource` converts the complete root lineage into a redacted `TaskOutcomeEnvelope`. The terminal automatic system event creates at most one episode/job for the root. Recovery children, duplicate events, process replay, and manual review cannot create independent support.

Only semantic `success`, `failure`, and `replan_required` outcomes are learnable. A success must have non-empty criterion statuses and all must be `satisfied`. A recovered success is `mixed`: it can support the successful workflow and still expose normalized failed attempts. `off`, `inconclusive`, invalid/service-error, and review-only outcomes are ignored for promotion.

The coordinator persists first, schedules `asyncio` reflection, and retries failures according to the stored job policy. Its call counter is separate from `maxVerifierCallsPerRun`. Exhausted evolution budget defers jobs without changing the task result.

### 10.3 Lesson clustering and lifecycle

The reflection model emits `LessonEligibility` for each failed/replanned workflow pattern. Only `decision=related` with `reason=workflow_related` proceeds. `task_unsatisfiable`, `verifier_limit`, `evidence_limit`, `external_or_infrastructure`, `user_constraint`, and `unknown` remain diagnostic events.

A related failure becomes a normalized `FailureObservation`. The model selects an existing same-Skill/same-workflow cluster when semantically equivalent or proposes a stable `pattern_key`; no embedding or vector database is used. SQLite counts each root once per cluster. Before `minLessonEpisodes`, the cluster remains `collecting`.

At the threshold, synthesis receives normalized observations only, not raw inputs. Static validation rejects credentials, endpoints, paths, action/command/session IDs, Action Manifest material, bypass instructions, prompt injection, fixed coordinates/numbers/options, and answer-like wording. A second structured model validation must return `reusable=true`, `contains_specific_answer=false`, no `unsupported_literals`, and confidence at least `0.8`. Otherwise the cluster becomes `blocked` and is never injected.

An activated `ScopedLesson` can be superseded only by an active replacement in the same Skill/workflow scope. Independent successful counterexamples can retire it and reopen its cluster. `references/LESSONS.md` is an atomic human-readable projection of active and historical Lessons plus collecting/blocked clusters; the SQLite ledger is authoritative. `activate_skill` returns only active, applicability-matched Lessons up to `maxLessonsPerSkill`.

On first startup, root `LESSONS.md` entries are imported as inactive unbound legacy records. Existing pre-cluster active Lessons are deactivated, seeded into clusters from their known episode roots, and must be re-synthesized and revalidated before activation.

### 10.4 Skill candidates and promotion

Reusable semantic success creates or merges a candidate by Skill and workflow key. Update proposals must target the activated primary Skill; without a primary, reflection may propose a new non-duplicate Skill. Independent episode IDs provide support. Promotion requires `minSuccessfulEpisodes` and is blocked by active same-workflow Lessons, reflection conflicts, validation errors, or unsafe content.

Generated content is limited to trigger, preconditions, generalized steps, verification checkpoints, recovery guidance, and applicability boundaries. It cannot contain scripts/assets, endpoints, credentials, fixed Gateway actions/IDs, Action Manifest copies, or instructions to bypass Forge/verification.

New Skills are created under `workspace/skills/<name>/SKILL.md` with `always: false`. Updates replace exactly one `<!-- paos:learned-workflow:start -->` managed block and preserve human-authored content. A built-in baseline is archived and copied to a workspace override; built-in files are never changed. Atomic writes, structural/content validation, workspace reload, revision archives, and rollback guard every promotion. The current turn keeps its activated digest; refreshed summaries apply on a later turn.

## 11. Extension workflows

### 11.1 Add a Gateway action

Action implementation and registration happen in Forge Gateway/Runtime, not PAOS:

1. Publish stable action identity in Gateway capabilities.
2. Declare `required_parameters`, `input_mapping`, `result_semantics`, and `completion`.
3. Return complete, consistent session/command identities from create and get.
4. Keep terminal states within the supported contract.
5. Add only generic contract/fake-Gateway tests in PAOS—never an action-specific verifier flag.

### 11.2 Add an evidence source

Publish a stable `id`, monotonically increasing `seq`, legal `content_type`, and Base64 data on Gateway `/ws/images`. An optional `timestamp` must be real source time. Reference that source from PAOS target configuration or the task evidence policy.

A new evidence kind must extend public contracts, collection/writing, request resolution, retention, and end-to-end tests together. Do not hide private artifact paths in action manifests.

### 11.3 Add an Agent tool

Only add a tool when the seven generic Forge tools cannot represent the capability. A new tool must not accept caller-supplied session/command IDs, POST directly to Gateway, or bypass Store/Orchestrator.

## 12. Errors and observability

Stable error prefixes support operational triage:

| Category | Examples |
|:---------|:---------|
| Gateway contract | `FORGE_GATEWAY_API_UNSUPPORTED`, `FORGE_GATEWAY_CAPABILITY_MISSING` |
| Action/correlation | `FORGE_ACTION_UNSUPPORTED`, `FORGE_EXECUTION_STATE_LOST` |
| Evidence | `FORGE_EVIDENCE_CONFIGURATION_REQUIRED`, `FORGE_EVIDENCE_UNAVAILABLE`, `VERIFICATION_EVIDENCE_UNAVAILABLE` |
| Verification | `VERIFICATION_INVALID_VERDICT`, `VERIFICATION_CALL_BUDGET_EXHAUSTED`, `VERIFICATION_SERVICE_UNAVAILABLE` |
| Recovery | `VERIFICATION_REPLAN_LIMIT_REACHED`, `VERIFICATION_REPLAN_TIMEOUT` |
| Execution | `GATEWAY_EXECUTION_TIMEOUT`, `GATEWAY_SESSION_FAILED`, `FORGE_SESSION_CANCELLED` |

The SQLite event log is the orchestration audit source. Raw Gateway create/last/cancel responses remain in the session record. Public artifacts provide cross-process readable facts.

Evolution has a separate structured event stream including episode/assessment completion, eligibility rejection, observation/cluster support, Lesson activation/supersession/retirement, candidate support/block/promotion, validation rejection, budget deferral, baseline archive, and rollback. Logs expose IDs and bounded summaries rather than sensitive task values.

## 13. Testing

```bash
python -m pip install -e ".[dev]"
pytest
ruff check PhyAgentOS tests
python -m compileall -q PhyAgentOS tests
```

Tests should cover:

- model versions, required fields, illegal states/verdicts/URIs/digests;
- Store concurrency, one active lineage, transitions, atomic replan;
- Gateway API/support/action/identity/terminal/cancel/reset;
- multiple sources, ordering, duplicates, stale frames, disconnects, invalid media, oversize artifacts;
- all four modes, missing evidence, service errors, retention, and review immutability;
- restart before POST, 404 after intent, late capture, interrupted verification, recovery deduplication;
- tool registration, system-event routing, and Forge-disabled behavior;
- repository guard against the removed execution architecture;
- exact Skill activation, workspace precedence, primary uniqueness, supporting Skills, availability, and path rejection;
- learnable-outcome classification, root/replay/recovery/review idempotency, redacted traces, job restart, and fail-open behavior;
- Lesson eligibility, same-pattern clustering, independent-root threshold, static/model abstraction validation, projection, migration, supersession, and retirement;
- first/second/third success promotion, blockers, managed-block protection, built-in override, atomic revision archive, reload, and rollback.

Optional black-box tests connect only through `FORGE_GATEWAY_URL` and never modify Gateway source or configuration.

## Next reading

- [Integration Development Guide](../user_development_guide/README_en.md)
- [Communication Architecture](../user_development_guide/COMMUNICATION_en.md)
- [Forge Integration Contract](../forge/README.md)
- [Configuration Reference](04-forge-configuration-reference.md)
- [Agent Experience and Skill Evolution](05-agent-experience-and-skill-evolution.md)
