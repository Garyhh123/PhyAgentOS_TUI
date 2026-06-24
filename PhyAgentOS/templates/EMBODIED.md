# Embodied Targets

This file is the human-readable counterpart of `TARGETS.md`.
Each section uses `## Target: <target_id>` so the agent can load only enabled targets from `TARGETS.md`, after applying `runtime.targetEnabled` config overrides.

## Target: libero_real_remote

### Identity

- **Name**: libero_real_remote
- **Type**: remote simulation target
- **Target Class**: remote
- **Target Kind**: simulation
- **Runtime**: LiberoRemoteTargetProxy
- **Workspace**: workspaces/libero_real

### Supported Skills

| Skill | Runtime Kind | Description |
|---|---|---|
| `pi05_libero_remote` | policy | Closed-loop PI0.5 / OpenPI policy execution through the runtime session protocol. |

### Observation Contract

- **Observation Type**: multimodal
- **Empty Observation Allowed**: false
- **Image Channels**: `observation/image`, `observation/wrist_image`
- **State Channel**: `observation/state`
- **Prompt Channel**: `prompt`
- **Camera Resolution**: 256 x 256

### Action Contract

- **Action Representation**: delta_eef_pose_gripper
- **Action Dimension**: 7
- **Frame**: base
- **Chunk Mode**: variable-length chunks, default up to 50 actions
- **Policy Hz**: 20
- **Max Steps**: 280
- **Warmup Wait Steps**: 10

### Runtime Connection

- **Target Endpoint**: `targetws://libero-host:9002`
- **Target Adapter**: `target_adapter://libero_adapter`
- **Runtime Contract**: `configs/runtime/contracts/libero_real.runtime.yaml`
- **Policy Skill**: `pi05_libero_remote`

### Perception

- **Enabled**: false
- **Strict Preflight**: true
- **Sensor Config**: none
- **Perception Config**: none
- **Artifact Directory**: none

### Safety and Constraints

- Runtime sessions must be appended to `SESSIONS.md`; direct action queues are not supported.
- Preflight must verify target enablement, adapter compatibility, observation schema, policy adapter, and action contract before execution.
- Do not invent endpoints or adapter URIs. Use values from `TARGETS.md` unless the user explicitly overrides them.
