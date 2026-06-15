# Rollout Service (Step A)

External Isaac Sim rollout process for PhyAgentOS runtime. Communicates over **WebSocket + msgpack** and is independent of `WatchdogSupervisor` / `SESSIONS.md`.

Bundled like **PhyAgentOS3** (no external `InternUtopia` checkout):

```text
rollout/
  vendor/          # internutopia + bridge + PiperGo2ManipulationAPI
  simulation/      # isaac_bootstrap, vla_pick, scene bootstrap
  configs/         # pipergo2_manipulation.json (paths -> <repo>/asserts/...)
  bootstrap.py
```

Large assets live at **`<repo>/asserts/`** (not inside `rollout/`). PiperGo2 reuses the **Aliengo locomotion policy** at:

`asserts/robots/aliengo/policy/move_by_speed/aliengo_loco_model_4000.pt`

(configured in `rollout/vendor/internutopia_extension/configs/robots/pipergo2.py` via `gm.ASSET_PATH`). Do **not** point `INTERNUTOPIA_ASSETS_PATH` at `/data/datasets/GRScenes` unless that tree actually contains `robots/aliengo/...` on your machine.

If missing, symlink or unzip per PhyAgentOS3 docs:

```bash
ln -sf /path/to/PhyAgentOS3/asserts /home/zyserver/work/my_project/PhyAgentOS/asserts
# or download asserts.zip into repo root (see PhyAgentOS3 docs/README_paos_env.md §3b)
```

Refresh vendor from OS3 after upstream changes:

```bash
bash scripts/sync_rollout_from_os3.sh /home/zyserver/work/my_project/PhyAgentOS3
```

## PiperGo2 manipulation

Migrated from `hal/drivers/pipergo2_manipulation_driver.py` into `rollout/pipergo2_runner.py`.

### Start server (GUI / VNC)

From repo root, with `paos` conda env and Isaac Sim paths configured in the JSON `isaac_env` block:

```bash
cd /home/zyserver/work/my_project/PhyAgentOS
conda activate paos
python -m rollout --config PhyAgentOS/rollout/configs/pipergo2_manipulation.json --gui --port 8765
```

Headless:

```bash
python -m rollout --config PhyAgentOS/rollout/configs/pipergo2_manipulation.json --headless --port 8765
```

On first GUI start, Isaac bootstrap may **re-exec** the process once (`[isaac-bootstrap] LD_LIBRARY_PATH changed`).

The rollout server uses a **sync websockets** listener on a side thread and runs all Isaac/reset/step work on the **process main thread** (required for Kit signals). Runtime watchdog disconnects without shutting down the sim between sessions.

### WebSocket protocol

Binary frames: msgpack dict envelope.

**Request**

```yaml
type: health | reset | observe | step | close
session_id: optional
episode_id: optional
seq: int
payload: dict
```

**Response**

```yaml
type: <same as request>
ok: bool
payload: dict
error: str | null
```

### `step` payload modes

| mode | fields | use |
|------|--------|-----|
| `control` | `action: { ... }` | InternUtopia env step (VLA low-level) |
| `command` | `command`, `params` | Legacy actions: `navigate_to_named`, `run_pick_place`, `run_vla_pick_and_return`, `api_call`, ... |
| `language` | `text` | Short NL routing (pick / desk / home / describe) |

### Example (Python client)

```python
import asyncio
import websockets
from rollout.protocol import decode_message, encode_message

async def demo():
    async with websockets.connect("ws://127.0.0.1:8765", max_size=None) as ws:
        await ws.send(encode_message({"type": "reset", "seq": 1, "payload": {}}))
        print(decode_message(await ws.recv()))
        await ws.send(encode_message({
            "type": "step", "seq": 2,
            "payload": {"mode": "command", "command": "navigate_to_named", "params": {"waypoint_key": "desk"}},
        }))
        print(decode_message(await ws.recv()))

asyncio.run(demo())
```

### Observation shape (`reset` / `observe` / `step`)

```yaml
obs:
  raw: ...          # internutopia builtin obs
  robot: ...        # pipergo2 slice
  robot_xy: [x, y]
  runtime: ...      # manipulation snapshot
  scene_description_cn: str
  images:           # optional VLA cameras (camera1/2/3)
  state:            # optional 7-d joint+gripper vector
```

## Runtime integration (Step B)

`PhyAgentOS/runtime/targets/sim/isaacsim_ws_target.py` connects here as a WS client.
Register in workspace `TARGETS.md` with `backend: isaacsim_ws` and `config.rollout_ws_url`.

Start rollout server first, then runtime watchdog with `pipergo2_isaac_sim` target.

## Adapter (Step C)

- Adapter id: `pipergo2_isaac_openpi_adapter`
- Skill id: `openpi_pipergo2_isaac_vla`
- Maps `camera1`/`camera2` (+ optional `camera3`) and 7-D actions; `encode_step_input` accepts
  vectors, `command` dicts, or natural language strings for rollout high-level steps.
