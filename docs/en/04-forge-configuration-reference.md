# Forge Configuration Reference

> Applies to PhyAgentOS 0.2.1 and Forge Gateway API `paos-forge-gateway-mvp-plus.v1`.

## 1. Location and naming

The default file is `~/.PhyAgentOS/config.json`. `paos onboard` creates or refreshes it. `paos agent` and `paos gateway` accept `--config` and `--workspace` for the active instance.

Pydantic models accept camelCase and snake_case; onboarding writes camelCase. A root-level `runtime` field is explicitly rejected:

```text
legacy `runtime` configuration is unsupported; remove it and configure `forge`
```

## 2. `forge`

| JSON field | Type | Default | Constraint and meaning |
|:-----------|:-----|:--------|:-----------------------|
| `enabled` | boolean | `false` | When false, no Orchestrator is created and Forge tools are not registered. |
| `baseUrl` | string | `http://127.0.0.1:9001` | Starts with `http://` or `https://`; trailing slash is removed. WebSockets map to `ws://`/`wss://`. |
| `apiVersion` | literal | `paos-forge-gateway-mvp-plus.v1` | The only accepted version; no downgrade. |
| `requestTimeoutS` | number | `10.0` | HTTP request timeout, greater than zero. |
| `pollIntervalS` | number | `0.5` | Session GET interval in `[0.1, 5.0]` seconds. |
| `executionTimeoutS` | number | `300.0` | Gateway execution timeout when the task does not override it. |
| `evidence` | object | below | Adapter-side best-effort capture settings. |

## 3. `forge.evidence`

| JSON field | Type | Default | Constraint and meaning |
|:-----------|:-----|:--------|:-----------------------|
| `requiredImageSources` | string[] | `[]` | Global image sources. Non-empty task sources take precedence; when both are empty, discover runtime-context readiness. |
| `captureTimeoutS` | number | `5.0` | Maximum pre-POST wait for a before snapshot. |
| `postCaptureTimeoutS` | number | `5.0` | Maximum wait for higher sequences after observed Gateway terminal state. |
| `connectionTimeoutS` | number | `2.0` | Timeout for each WebSocket connection attempt. |
| `maxArtifactBytes` | integer | `8388608` | Maximum decoded image or state-message entity size. |
| `associationQuality` | literal | `best_effort` | The only value supported by Gateway 1.0.0. |

Source precedence:

```text
task.verification.evidence_policy.required_sources (non-empty)
    > forge.evidence.requiredImageSources (non-empty)
    > /agent/runtime/context readiness.images keys
```

## 4. `agents.verification`

| JSON field | Type | Default | Constraint and meaning |
|:-----------|:-----|:--------|:-----------------------|
| `serviceEnabled` | boolean | `true` | Starts the independent service. Non-`off` tasks require it to be available. |
| `model` | string/null | `null` | Uses `agents.defaults.model` when null. |
| `provider` | string/null | `null` | Auto-matched from verifier model when null; explicit value must exist in providers. |
| `timeoutS` | number | `180.0` | Per-model-call verification timeout. |
| `evidenceRetention` | enum | `none` | `all | failed | none`. |
| `maxReplansPerEpisode` | integer | `2` | Maximum replans in one root lineage; non-negative. |
| `maxVerifierCallsPerRun` | integer | `50` | Verifier-call budget for this PAOS process. Zero disables this code-level budget. |
| `replanTimeoutS` | number | `120.0` | Deadline for Planner child creation. |
| `serviceHost` | string | `127.0.0.1` | Child HTTP-service bind host. |
| `servicePort` | integer | `8100` | Range `1..65535`; use distinct ports for multiple local PAOS instances. |

Verification Service readiness is bounded. Startup failure does not wait forever. Orchestrator records the error and refuses new non-`off` work.

## 5. `agents.evolution`

| JSON field | Type | Default | Constraint and meaning |
|:-----------|:-----|:--------|:-----------------------|
| `enabled` | boolean | `true` | Enables explicit Skill activation, the experience ledger, and background evolution. Failures never block task execution. |
| `scope` | literal | `verified_forge_lineage` | The first release consumes only Forge root lineages with semantic verdicts. |
| `promotionMode` | literal | `guarded_auto` | Allows only validated, guarded automatic promotion. |
| `minSuccessfulEpisodes` | integer | `3` | Independent successful root lineages required for one candidate; at least 1. |
| `minLessonEpisodes` | integer | `3` | Independent workflow-related failure root lineages required before a clustered Lesson can activate; at least 1. |
| `maxLessonsPerSkill` | integer | `8` | Scoped lessons returned by one `activate_skill` call; range `1..50`. |
| `maxEvolutionCallsPerRun` | integer | `20` | Background reflection budget, separate from verifier calls; zero disables the code-level limit. |
| `model` | string/null | `null` | Inherits the verification model, then the Agent default model. |
| `provider` | string/null | `null` | Inherits the verification provider, then auto-matches the selected model. |

When enabled, the legacy root `LESSONS.md` is preserved but is not injected globally or read by Forge verification. Skill-bound lessons are loaded on demand from the ledger and projected to `skills/<name>/references/LESSONS.md`. The applicable active set returned by explicit Skill activation is frozen with the root task and supplied to automatic verification, recovery children, and review only as non-authoritative advice. It cannot establish a criterion or replace evidence; tasks without activated Skills supply no learned Lessons. Failures unrelated to the workflow remain diagnostic-only; related failures are normalized and clustered before activation. Thresholds count distinct Forge root lineages, not recovery children, reviews, duplicate events, or replays.

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

## 6. `ForgeTaskRequest`

The `forge_execute_task` Agent tool accepts these business fields; `version` and `source` use model defaults:

| Field | Type | Required | Meaning |
|:------|:-----|:---------|:--------|
| `task_description` | string | Yes | Non-empty high-level instruction sent as Gateway `instruction`. |
| `action_type` | string | Yes | Present in cached `capabilities.actions`. |
| `inputs` | JSON object | Yes | Strictly serializable and contains no NaN or Infinity. |
| `verification` | object | Yes | Described below. |
| `execution_timeout_s` | number | No | Greater than zero; defaults to `forge.executionTimeoutS`. |

There are no caller fields for `session_id` or `command_id`. PAOS generates `forge_<uuid>` and `command_<uuid>`.

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
| `minimum_association` | enum | `best_effort` | `best_effort | authoritative`; authoritative currently fails before execution. |

## 8. Mode behavior matrix

| Condition | `off` | `audit` | `enforce` | `recovery` |
|:----------|:------|:--------|:----------|:-----------|
| Goal/criteria required | No | Yes | Yes | Yes |
| Evidence Bundle | No | Yes | Yes | Yes |
| Missing before blocks POST | N/A | No | Yes | Yes |
| Verifier error | N/A | Record; preserve execution terminal | Failed | Failed |
| `inconclusive` | N/A | Record; preserve execution terminal | Failed | Failed |
| `replan_required` | N/A | No recovery | Failed | `awaiting_replan` |

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
    "apiVersion": "paos-forge-gateway-mvp-plus.v1",
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
paos agent -m "Call forge_get_context and report only API version, supports, actions, and readiness. Do not execute an action."
```

`paos status` checks local config, workspace, model, and provider. It does not replace the live Gateway inspection from `forge_get_context`.

## Next reading

- [User Manual](02-user-manual.md)
- [Developer Manual](03-developer-manual.md)
- [Agent Experience and Skill Evolution](05-agent-experience-and-skill-evolution.md)
- [Operations Manual](../user_manual/README_en.md)
- [Forge Integration Contract](../forge/README.md)
