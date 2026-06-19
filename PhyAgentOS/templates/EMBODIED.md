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

## Target: minecraft_java_env

### Identity

- **Name**: paos (minecraft_java_env)
- **Type**: game target (Minecraft Java Edition bot)
- **Target Class**: local
- **Target Kind**: game
- **Runtime**: MinecraftTargetRuntime
- **Workspace**: workspaces/minecraft

### Supported Skills

| Skill | Runtime Kind | Description |
|---|---|---|
| `minecraft_navigate` | builtin | Navigate through the Minecraft world using the target runtime. |
| `minecraft_mine` | builtin | Mine or collect blocks through the target runtime. |
| `minecraft_build` | builtin | Place blocks and build simple structures through the target runtime. |

### Supported Actions

| Action | Parameters | Description |
|---|---|---|
| `move` | `dx, dy, dz, absolute` | Move bot by delta or to world coordinates. Also supports `target` for entity tracking. |
| `look` | `yaw, pitch` | Set bot head rotation in degrees. 0=south, 90=west, 180=north, -90=east. |
| `jump` | none | Make bot jump. |
| `sneak` | `sneaking` | Toggle sneaking. |
| `sprint` | none | Toggle sprinting. |
| `attack` | none | Attack the entity the bot is looking at. |
| `interact` | `x, y, z` | Right-click a block at coordinates. |
| `place` | `x, y, z, face` | Place a block against the specified face. |
| `dig` | `x, y, z` | Break a block at coordinates. |
| `use` | `x, y, z` | Use or activate a block, such as a chest or crafting table. |
| `select_slot` | `slot` | Switch hotbar to the given 0-8 slot index. |
| `drop` | `slot` | Drop an item from the hotbar. |
| `chat` | `message` | Send a chat message. |
| `collect` | `block_type, count` | Locate and collect blocks of the given type. |
| `equip` | `type, dest` | Equip an item. |
| `craft` | `item, count` | Craft items. |

### Runtime Connection

- **Transport**: HTTP REST API through the Minecraft bridge server.
- **Target Endpoint**: `targetws://local/minecraft_java_env`
- **Target Adapter**: `target_adapter://minecraft_adapter`
- **Bridge URL**: configured by `TARGETS.md` `config.bridge_url`
- **Health Check**: `GET /health`, including `bot_spawned`
- **State**: `GET /state`, including bot position, health, nearby entities, and inventory
- **Action**: `POST /action`, body `{"type": "...", "params": {...}}`

### Constraints

- **Pathfinder**: mineflayer pathfinder powers `move`; complex terrain or unreachable coordinates can fail.
- **Render Distance**: limited by server settings, usually 8-12 chunks.
- **Action Latency**: governed by target config `step_delay`, default 0.1s; move actions can take several seconds.

## Target: stardewvalley_smapi

### Identity

- **Name**: stardewvalley_smapi
- **Type**: game target (Stardew Valley via SMAPI + StardojoMod)
- **Target Class**: local
- **Target Kind**: game
- **Runtime**: StardewValleyTargetRuntime
- **Workspace**: workspaces/stardewvalley

### Supported Skills

| Skill | Runtime Kind | Description |
|---|---|---|
| `stardewvalley_navigate` | builtin | Navigate and interact with the Stardew Valley world. |

### Supported Actions

| Action | Parameters | Description |
|---|---|---|
| `move` | `dx, dy` | Relative movement by tile offset. |
| `use` | `direction` | Use tool toward up/down/left/right. |
| `interact` | `direction` | Interact/harvest/talk toward a direction. |
| `choose_item` | `slot_index` | Switch to inventory slot 0-11. |
| `craft` | `item_name` | Craft an item by name. |

### Observation Fields

- `position`: [x, y] tile coordinates
- `location`: current map name
- `facing_direction`: up/down/left/right
- `health`, `energy`, `money`: player stats
- `inventory`: list of {Name, Quantity} items
- `surroundings`: list of nearby tiles with terrain/objects
- `buildings`: farm buildings with door positions

### Constraints

- **Interaction Range**: 1 tile for use/interact.
- **Time Progression**: game time advances during and between actions.
- **Block Reach**: about 4.5 blocks for dig, place, and interact.

### Observer

prismarine-viewer on port 3007 provides a browser-based 3D first-person view as an independent side channel.
