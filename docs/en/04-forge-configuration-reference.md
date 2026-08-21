# Forge Configuration Reference

> Applies to PhyAgentOS 0.2.2 and the unified Forge Gateway Tool API.

## 1. Location and naming

The default file is `~/.PhyAgentOS/config.json`. `paos onboard` creates or refreshes it. `paos agent` and `paos gateway` accept `--config` and `--workspace` for the active instance.

Pydantic models accept camelCase and snake_case; onboarding writes camelCase. A root-level `runtime` field is explicitly rejected:

```text
legacy `runtime` configuration is unsupported; remove it and configure `forge`
```

## 2. `forge`

| JSON field | Type | Default | Constraint and meaning |
|:-----------|:-----|:--------|:-----------------------|
| `enabled` | boolean | `false` | When false, no configured Tool API client or AgentTask tools are registered. An explicitly active Skill Runtime still enables them. |
| `baseUrl` | string | `http://127.0.0.1:9001` | Fallback Gateway Tool API URL. An active Skill manifest's `gateway_url` takes precedence. |
| `apiVersion` | literal | `forge-tool-api.v1` | The only PAOS Tool API integration version. |
| `requestTimeoutS` | number | `10.0` | HTTP request timeout, greater than zero. |
| `pollIntervalS` | number | `0.5` | Recommended Action status/result reconciliation interval in `[0.1, 5.0]` seconds. |
| `executionTimeoutS` | number | `300.0` | Default Agent-side task deadline guidance. It does not prove that a timed-out Action stopped. |
| `evidence` | object | below | AgentTask best-effort before/after capture settings. |

PAOS invokes only `/tools` and `/invocations`. It does not call `/agent/sessions` or
`/policy/command`; Query and Action concurrency is decided by the selected endpoint operation's
`max_concurrency`.

## 2.1 `resourceRegistry`

| JSON field | Type | Default | Constraint and meaning |
|:-----------|:-----|:--------|:-----------------------|
| `url` | string | `""` | Optional HTTP(S) Resource Registry. `PAOS_RESOURCE_REGISTRY_URL` overrides it. Empty means no implicit download. |

## 3. `forge.evidence`

| JSON field | Type | Default | Constraint and meaning |
|:-----------|:-----|:--------|:-----------------------|
| `requiredImageSources` | string[] | `[]` | Global image sources. Non-empty task sources take precedence; when both are empty, discover runtime-context readiness. |
| `captureTimeoutS` | number | `5.0` | Maximum pre-POST wait for a before snapshot. |
| `postCaptureTimeoutS` | number | `5.0` | Maximum wait for higher sequences after observed Gateway terminal state. |
| `connectionTimeoutS` | number | `2.0` | Timeout for each WebSocket connection attempt. |
| `maxArtifactBytes` | integer | `8388608` | Maximum decoded image or state-message entity size. |
| `associationQuality` | literal | `best_effort` | The implemented PAOS observation-association quality. |

Source precedence:

```text
task.verification.evidence_policy.required_sources (non-empty)
    > forge.evidence.requiredImageSources
```

## 4. `agents.verification`

| JSON field | Type | Default | Constraint and meaning |
|:-----------|:-----|:--------|:-----------------------|
| `serviceEnabled` | boolean | `true` | Starts the independent service. Non-`off` tasks require it to be available. |
| `model` | string/null | `null` | Uses `agents.defaults.model` when null. |
| `provider` | string/null | `null` | Auto-matched from verifier model when null; explicit value must exist in providers. |
| `timeoutS` | number | `180.0` | Per-model-call verification timeout. |
| `evidenceRetention` | enum | `none` | `all | failed | none`. |
| `maxReplansPerEpisode` | integer | `2` | Maximum additional PlanRevisions in one AgentTask; non-negative. |
| `maxVerifierCallsPerRun` | integer | `50` | Verifier-call budget for this PAOS process. Zero disables this code-level budget. |
| `replanTimeoutS` | number | `120.0` | Deadline for beginning a requested PlanRevision. |
| `serviceHost` | string | `127.0.0.1` | Child HTTP-service bind host. |
| `servicePort` | integer | `8100` | Range `1..65535`; use distinct ports for multiple local PAOS instances. |

Verification Service readiness is bounded. A non-`off` AgentTask is rejected when the service is unavailable.

## 5. `agents.evolution`

| JSON field | Type | Default | Constraint and meaning |
|:-----------|:-----|:--------|:-----------------------|
| `enabled` | boolean | `true` | Enables explicit Skill activation, the experience ledger, and background evolution. Failures never block task execution. |
| `scope` | literal | `verified_forge_lineage` | Consumes AgentTask lineages with semantic verdicts; the persisted literal remains stable for compatibility. |
| `promotionMode` | literal | `guarded_auto` | Allows only validated, guarded automatic promotion. |
| `minSuccessfulEpisodes` | integer | `3` | Independent successful AgentTasks required for one candidate; at least 1. |
| `minLessonEpisodes` | integer | `3` | Independent workflow-related failed AgentTasks required before a clustered Lesson can activate; at least 1. |
| `maxLessonsPerSkill` | integer | `8` | Scoped lessons returned by one `activate_skill` call; range `1..50`. |
| `maxEvolutionCallsPerRun` | integer | `20` | Background reflection budget, separate from verifier calls; zero disables the code-level limit. |
| `model` | string/null | `null` | Inherits the verification model, then the Agent default model. |
| `provider` | string/null | `null` | Inherits the verification provider, then auto-matches the selected model. |

When enabled, the legacy root `LESSONS.md` is preserved but is not injected globally or read by Forge verification. Skill-bound lessons are loaded on demand from the ledger and projected to `skills/<name>/references/LESSONS.md`. The applicable active set returned by explicit Skill activation is frozen with the AgentTask and supplied to automatic verification, later PlanRevisions, and review only as non-authoritative advice. It cannot establish a criterion or replace evidence; tasks without activated Skills supply no learned Lessons. Failures unrelated to the workflow remain diagnostic-only; related failures are normalized and clustered before activation. Thresholds count distinct AgentTasks, not PlanRevisions, reviews, duplicate events, or replays.

The evolution model/provider is resolved independently of the verifier call budget:

```text
agents.evolution.model
  → agents.verification.model
  → agents.defaults.model

agents.evolution.provider
  → agents.verification.provider
  → provider inferred from the selected model
```

`enabled=false` removes `activate_skill`, restores root `LESSONS.md` to normal Agent and verifier context, and allows the verifier's legacy Lesson append behavior. It does not modify or delete the experience database, Skill sidecars, or revision archive.

## 6. AgentTask and Tool API tools

`forge_task_create` accepts `task_description` and the verification contract below. It returns a
PAOS `task_id` and an initial immutable PlanRevision. Pass this `task_id` optionally to
`forge_tool_query` and `forge_tool_start_action`; calls without it use the same Gateway Tool API
but do not occupy the global AgentTask slot or contribute to task verification.

Task lifecycle tools are `forge_task_create`, `forge_task_get`, `forge_task_begin_revision`,
`forge_task_finalize`, and `forge_task_cancel`. Tool transport tools are `forge_tool_context`,
`forge_tool_query`, `forge_tool_start_action`, `forge_tool_action_status`,
`forge_tool_action_result`, and `forge_tool_cancel_action`.

`task_id`, `revision_id`, Query record ID, Gateway `invocation_id`, and Gateway `attempt_id` are
distinct identities. Only one AgentTask may be non-terminal globally. A recovery revision keeps
the same task ID and is limited by `maxReplansPerEpisode` and `replanTimeoutS`.

## 7. `TaskVerificationContract`

| Field | Type | Default | Meaning |
|:------|:-----|:--------|:--------|
| `mode` | enum | `off` | `off | audit | enforce | recovery`. |
| `goal` | string | `""` | Required and trimmed for non-`off`. |
| `success_criteria` | string[] | `[]` | At least one non-blank item for non-`off`. |
| `constraints` | string[] | `[]` | Restrictions preserved during verification and recovery. |
| `evidence_policy` | object | semantic default | Evidence requirements. |

### `evidence_policy`

| Field | Type | Default | Meaning |
|:------|:-----|:--------|:--------|
| `profile` | string | `semantic_default` | Generic label; does not select action-specific code. |
| `required_kinds` | string[] | `["rgb_image"]` | Each kind must exist in before and after. `robot_state` requires `/ws/state`. |
| `required_sources` | string[] | `[]` | Every source must exist for image kinds in both phases. |
| `minimum_association` | enum | `best_effort` | `best_effort | authoritative`; current PAOS collection supplies best-effort evidence. |

## 8. Mode behavior matrix

| Condition | `off` | `audit` | `enforce` | `recovery` |
|:----------|:------|:--------|:----------|:-----------|
| Goal/criteria required | No | Yes | Yes | Yes |
| Best-effort Evidence Bundle | Yes for bound Actions | Yes | Yes | Yes |
| Missing before blocks Tool API Action | No | No | No | No |
| Verifier error | N/A | Record; preserve execution terminal | Failed | Failed |
| `inconclusive` | N/A | Record; preserve execution terminal | Failed | Failed |
| `replan_required` | N/A | No recovery | Failed | `awaiting_replan` |

## 8.1 Skill Runtime controls

Skill Runtime paths are managed by PAOS data-path helpers rather than additional config fields.
Use `paos skill search/install/update/remove/list/inspect/start/status/logs/stop` for Bundle and
Runtime lifecycle and `paos forge-node install/verify` for independently locked nodes. Starting a
profile validates required binaries, assets, environment variables, Dora, Gateway `/tools`, and
all manifest `required_tools`. An active Runtime's manifest `gateway_url` is the Tool API URL used
by the Agent.

## 9. `embodiments`

Embodiment config describes knowledge topology, not execution adapters:

| Field | Default | Meaning |
|:------|:--------|:--------|
| `mode` | `single` | `single | fleet`. |
| `sharedWorkspace` | `~/.PhyAgentOS/workspaces/shared` | Agent shared workspace in fleet mode. |
| `instances` | `[]` | Robot knowledge profiles. |

Instance fields: `robotId` and `workspace` are required; `enabled=true`; `profileName` and `sharedEnvironment` are optional. Extra fields are forbidden, so legacy `driver` fields must be removed.

## 10. Recommended configurations

### 10.1 Execution-chain smoke use

```json
{
  "forge": {
    "enabled": true,
    "baseUrl": "http://127.0.0.1:9001"
  },
  "agents": {
    "verification": {
      "serviceEnabled": false
    },
    "evolution": {
      "enabled": false
    }
  }
}
```

This configuration permits only tasks with `verification.mode=off`.

### 10.2 Long-running verified use

```json
{
  "agents": {
    "verification": {
      "serviceEnabled": true,
      "model": "openrouter/openai/gpt-4o-mini",
      "provider": "openrouter",
      "timeoutS": 180,
      "evidenceRetention": "failed",
      "maxReplansPerEpisode": 2,
      "maxVerifierCallsPerRun": 50,
      "replanTimeoutS": 120,
      "serviceHost": "127.0.0.1",
      "servicePort": 8100
    },
    "evolution": {
      "enabled": true,
      "scope": "verified_forge_lineage",
      "promotionMode": "guarded_auto",
      "minSuccessfulEpisodes": 3,
      "minLessonEpisodes": 3,
      "maxLessonsPerSkill": 8,
      "maxEvolutionCallsPerRun": 20,
      "model": null,
      "provider": null
    }
  },
  "forge": {
    "enabled": true,
    "baseUrl": "http://127.0.0.1:9001",
    "apiVersion": "forge-tool-api.v1",
    "requestTimeoutS": 10,
    "pollIntervalS": 0.5,
    "executionTimeoutS": 300,
    "evidence": {
      "requiredImageSources": ["front"],
      "captureTimeoutS": 5,
      "postCaptureTimeoutS": 5,
      "connectionTimeoutS": 2,
      "maxArtifactBytes": 8388608,
      "associationQuality": "best_effort"
    }
  }
}
```

## 11. Configuration checks

```bash
paos status
paos agent -m "Call forge_tool_context for the requested Tool and report its schema, binding, readiness, and frame profile. Do not execute an Action."
```

`paos status` checks local config, workspace, model, and provider. It does not replace live Tool inspection through `forge_tool_context`.

## Next reading

- [User Manual](02-user-manual.md)
- [Developer Manual](03-developer-manual.md)
- [Agent Experience and Skill Evolution](05-agent-experience-and-skill-evolution.md)
- [Operations Manual](../user_manual/README_en.md)
- [Unified Forge Tool API Contract](../forge/UNIFIED_TOOL_API.md)
