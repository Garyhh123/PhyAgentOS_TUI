# PhyAgentOS Integration Development Guide

[中文](README.md) · [Documentation index](../README.md)

> Version: 0.2.3

## 1. Choose the integration point

| Capability | Integration point |
|:-----------|:------------------|
| Robot read or calculation | Gateway Query ToolSpec + ToolEndpoint operation |
| Robot effect | Gateway Action ToolSpec + ToolEndpoint operation |
| Stateful capability lifecycle | Gateway Session ToolSpec + ToolEndpoint operation |
| Dora nodes and deployment assets | Manifest-v2 Skill Bundle and locked Node artifacts |
| Workflow instructions | `SKILL.md` discovered by SkillsLoader |
| User-task success | Generic `TaskVerificationContract` and AgentTask finalize |
| New model provider | Existing provider registry/configuration |
| Non-robot Agent capability | Existing Agent ToolRegistry or dynamic MCP |

Do not connect Agent code directly to robot SDKs, Dora nodes, simulators, or legacy Gateway
Session/Policy routes outside the governed Tool API.

## 2. Define a ToolSpec

Every ToolSpec has a stable `tool_id`, implementation and endpoint binding, operation,
`semantics: query|action|session`, description, strict input/output JSON schemas, readiness requirements,
and a robot frame profile when spatial inputs are involved.

```yaml
tool_id: motion.resolve_relative_pose
implementation_id: motion.integration
endpoint_id: motion.relative_pose
operation: resolve
semantics: query
description: Resolve a relative end-effector delta into an absolute target pose.
input_schema:
  type: object
  additionalProperties: false
  required: [translation_frame, translation_m]
  properties:
    translation_frame: {enum: [tcp, base]}
    translation_m:
      type: object
      additionalProperties: false
      required: [x, y, z]
      properties:
        x: {type: number}
        y: {type: number}
        z: {type: number}
output_schema:
  type: object
robot_frame_profile:
  base_frame: arm_base
  tool_frame: tcp
```

Use Query for synchronous reads or deterministic resolution without a robot effect. Use Action for
bounded physical effects and Session for explicitly owned, stateful lifecycles. Define Endpoint operation `max_concurrency` at
the execution owner; PAOS does not create a cross-Tool lease.

## 3. Implement Query, Action, and Session behavior

Query calls are resolved from ToolSpec and invoked at:

```text
POST /tools/{endpoint_id}/{operation}:invoke → HTTP 200
```

Action admission uses:

```text
POST /tools/{tool_id}:invoke → HTTP 202 + invocation_id + attempt_id
GET  /invocations/{invocation_id}
GET  /invocations/{invocation_id}/result
POST /invocations/{invocation_id}/cancel
```

Session admission uses the same `POST /tools/{tool_id}:invoke` contract. Reconcile it through the
common invocation routes and stop it with `POST /invocations/{invocation_id}/stop`. Declare whether
the Session is task-owned, shared, or runtime-owned; do not let one owner stop another owner's
Session.

Action status/result must expose an explicit lifecycle. Result may remain pending with HTTP 202.
Cancellation acceptance reports control handling only. When execution truth cannot be recovered,
return an explicit unknown outcome rather than fabricating cancellation or success.

Inputs and outputs must be finite JSON and satisfy ToolSpec. Spatial Tools must state frames,
units, tolerances, and orientation behavior. Avoid hidden defaults that the Agent cannot inspect
through `forge_tool_context`.

## 4. Build a manifest-v2 Skill Bundle

An installed Skill Bundle contains:

```text
<skill>/
├── skill.yaml
├── SKILL.md
├── profiles/<profile>/dataflow.yaml
├── profiles/<profile>/...
└── assets/...
```

Minimal manifest structure:

```yaml
manifest_version: 2
name: example-skill
version: "1.0.0"
description: Example robot workflow.
skill_document: SKILL.md
gateway_url: http://127.0.0.1:19002
required_tools: [example.query, example.action]
profiles:
  sim:
    dataflow: profiles/sim/dataflow.yaml
    required_binaries: [gateway, example_node]
    required_assets: [assets/scene.xml]
    required_environment: []
    environment: {}
artifacts:
  resolver: registry
  nodes:
    gateway:
      artifact_id: gateway-1.0.0-linux-x86_64
      version: "1.0.0"
      platform: linux
      arch: x86_64
      artifact_type: executable_tar_gz
      entrypoint: gateway
      sha256: <64-character-sha256>
```

All paths are relative and contained by the Bundle. Each Node archive has the locked SHA-256 and
contains exactly one root-level executable with the locked filename; the installer records the
extracted binary hash in its receipt. The Bundle archive inventory must
cover every file with SHA-256. Links, path traversal, collisions, oversized expansion, and unlisted
content are rejected.

## 5. Publish artifacts

A Resource Registry or schema-v3 static index must provide artifact identity, URL, exact size, and
SHA-256. Node metadata additionally provides the identity fields required by the
Skill lock. Do not publish mutable content at the same artifact identity.

Test installation through the same public commands users run:

```bash
python scripts/package_skill.py /path/to/example-skill --output-dir /tmp/packages
paos skill install example-skill --version 1.0.0
paos forge-node verify example-skill gateway
paos skill inspect example-skill
```

Installers stage, validate, atomically replace, and roll back on failure. Never require callers to
disable digest verification.

## 6. Design the Dora profile

The dataflow should give each node explicit inputs/outputs and use the Gateway Tool request/response
ports declared in its profile. Required executables are resolved from the immutable Runtime
environment. Assets remain in the Skill Bundle and are referenced with relocatable paths.

RuntimeManager creates a deterministic flow name, verifies Dora and required files, starts the
flow, then waits for Gateway `/tools` and every required Tool context. A Gateway already listening
at the manifest URL is not silently adopted.

When Tool API is the physical execution plane, disable the Gateway Agent API in the profile:

```yaml
agent:
  enabled: false
tools:
  enabled: true
```

## 7. Write workflow guidance

`SKILL.md` should tell the Agent when to activate the Skill, which contexts to inspect, the Query →
Action/Session ordering, task binding, ownership, terminal reconciliation, verification checkpoints, and safe recovery
rules. It must not embed secrets, Registry URLs, task-specific coordinates, or instructions to
bypass Gateway/verification.

For a verified workflow, activate the primary Skill in the current turn, create one AgentTask from
that activation, bind every contributing Query/Action/Session to the same task, finalize after all
task-owned executions terminate, and append a PlanRevision only when recovery verdict
allows it.

## 8. Evidence and verification

Robot capability integration should expose Tool execution facts, not action-specific verifier code.
PAOS captures configured image/state sources and applies the generic verification contract at
AgentTask finalize. Tool output schemas should contain useful terminal result semantics, final
state/error data, and tolerances where relevant.

If authoritative evidence is introduced later, version the evidence contract explicitly. Do not
upgrade best-effort WebSocket association by convention.

## 9. Fake Gateway and conformance tests

Before real hardware or simulation, use a mock HTTP transport to test:

- Tool list/spec/context and Query binding resolution;
- activation candidate revalidation and ToolSpec/runtime drift rejection;
- Action HTTP 202 admission with invocation and attempt identities;
- Session admission, ownership, status/result, and stop;
- pending status/result and known terminal results;
- cancellation requested/accepted without false stop;
- timeout and unknown without blind retry;
- endpoint concurrency rejection behavior;
- diagnostic Query and bound calls through identical routes;
- AgentTask one-active constraint, revisions, evidence, and aggregate verification;
- archive traversal/link/collision/digest attacks and transactional rollback;
- Runtime start/status/log/stop and availability propagation.

Then run a complete simulated workflow. Real robot or MuJoCo acceptance must identify the exact
Bundle, node digests, profile, and environment used.

## 10. Integration acceptance checklist

- [ ] Tool semantics and schemas are explicit and strict.
- [ ] Frame, unit, tolerance, and readiness conventions are inspectable.
- [ ] Gateway operation owns `max_concurrency`.
- [ ] Query, Action, and Session use the documented HTTP contracts.
- [ ] Skill/Runtime/ToolSpec binding is frozen and revalidated for every governed execution.
- [ ] Invocation and attempt IDs remain separate from PAOS task IDs.
- [ ] Cancel, stop, timeout, and unknown do not imply physical stop or trigger a blind POST retry.
- [ ] Bundle and Node artifacts have immutable size/digest metadata.
- [ ] Runtime profile starts from a clean environment and reaches all Tool contexts.
- [ ] Gateway Agent API is disabled for the Tool-only profile.
- [ ] General Agent tools, verification, experience, and evolution require no capability-specific fork.

## Next reading

- [Developer Manual](../en/03-developer-manual.md)
- [Communication Architecture](COMMUNICATION_en.md)
- [Forge Tool API Contract](../forge/README.md)
