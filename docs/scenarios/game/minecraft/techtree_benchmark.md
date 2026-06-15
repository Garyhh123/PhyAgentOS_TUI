# PhyAgentOS x Minecraft - Tech-Tree Benchmark

> Reading Path: Minecraft benchmark integration.
> This page documents the executor-independent Minecraft tech-tree benchmark
> and how it fits into the PhyAgentOS target, skillruntime, session, and
> watchdog model.

---

## Status

| Component | Status | Notes |
|---|---|---|
| Vetted manifest | Ready | 40 obtain-item tasks across six tiers |
| Programmatic evaluator | Ready | Inventory/state checks, no LLM or VLM judge |
| Executor-independent harness | Ready | Agent and world adapter are injected |
| Mineflayer bridge adapter | Example | Optional reference adapter, not core dependency |
| OS session runner integration | External wrapper | Use `TARGETS.md`, `SKILLRUNTIME.md`, `SESSIONS.md`, and watchdog outside the benchmark core |

---

## What This Benchmark Is

The tech-tree benchmark measures whether an agent can obtain standard Minecraft
items along a progression path:

```
Wooden -> Stone -> Iron -> Gold/Redstone -> Diamond -> Armor
```

Each task has:

- a stable task id, such as `wooden.obtain_oak_log`;
- a tier and family;
- a deterministic setup description;
- a `target_item`;
- a programmatic success criterion.

The task set is derived from and vetted against MineStudio-style task configs
and common Minecraft tech-tree milestones, but it is a standalone PhyAgentOS
reimplementation.  It is not the official MineStudio, MCU, MineEvolve,
TeamCraft, or VPT benchmark protocol.

The benchmark is intentionally narrow.  It is an execution-layer benchmark:
reference-adapter tasks run in an isolated arena, place required materials or
target blocks near the agent, expose target coordinates through setup, and give
prerequisite tools declared by the task.  It measures whether an agent can carry
out low-level Minecraft actions, including local navigation, digging, pickup,
crafting, placing, and smelting, once the target is localized and prerequisites
are staged.

It does not measure open-world exploration, resource search, visual target
localization, high-level planning, long-horizon reasoning, multi-agent
coordination, or true tech-tree dependency climbing.  The tiers are difficulty
and category labels, not a dependency chain that the agent must discover or
execute across tasks.

---

## Architecture

```
manifest.json
  -> loader.py
      -> TechTreeTask
          -> world_adapter.reset(task.setup)
          -> injected agent_fn(task, world_adapter)
          -> world_adapter.observe()
          -> evaluator.py
              -> BenchmarkResult
```

The benchmark core does not import PhyAgentOS session or agent machinery.  It
can be wrapped by OS sessions, a direct script, a policy runner, or another
project's Minecraft controller.

---

## Relation To PhyAgentOS Runtime Files

The benchmark itself is lower-level than `SESSIONS.md`.

| Layer | Responsibility |
|---|---|
| `TARGETS.md` | Declares the Minecraft target and bridge endpoint |
| `SKILLRUNTIME.md` | Declares which runtime can execute sessions |
| `SESSIONS.md` | Queues a concrete benchmark episode for watchdog execution |
| WatchdogSupervisor | Claims the session and runs the selected runtime |
| `minecraft_techtree` benchmark | Defines setup, task metadata, and deterministic scoring |

An OS-native benchmark wrapper should create sessions that reference this
benchmark in `runtime_hints`, but the `minecraft_techtree` package itself should
remain independent of watchdog and session schemas.

---

## Public API

```python
from PhyAgentOS.benchmarks.minecraft.techtree import (
    evaluate_task,
    list_tasks,
    load_task,
    run_task,
)

task = load_task("stone.craft_furnace")
print(task.target_item)

verdict = evaluate_task(task, {"inventory": {"furnace": 1}})
print(verdict.success)
```

To run with an arbitrary agent:

```python
def agent_fn(task, world):
    # Any implementation is allowed here: LLM, scripted agent, policy, etc.
    return {"ok": True}


result = run_task("wooden.obtain_oak_log", agent_fn, world_adapter)
print(result.success, result.reward)
```

The world adapter interface is deliberately small:

```python
class WorldAdapter:
    def reset(self, setup):
        ...

    def observe(self):
        ...
```

---

## Optional Mineflayer Bridge Adapter

The package includes an example adapter:

```python
from PhyAgentOS.benchmarks.minecraft.techtree.adapters.mineflayer_bridge import (
    MineflayerBridgeAdapter,
)

world = MineflayerBridgeAdapter("http://127.0.0.1:3000")
```

It uses the bridge `/phase`, `/action`, and `/state` endpoints to perform setup
and observation.  It is not imported by `loader.py`, `evaluator.py`, or
`harness.py`.

The reference adapter also provides bounded scene isolation.  During reset it
teleports the bot to a fixed arena origin, clears a bounded box, lays a fixed
floor, marks the boundary, and places task blocks at coordinates relative to the
arena origin.  This avoids reusing arbitrary old terrain near the bot while
keeping the core benchmark adapter-agnostic.

---

## Task Tiers

| Tier | Count | Examples |
|---|---:|---|
| Wooden | 10 | `wooden.obtain_oak_log`, `wooden.craft_crafting_table` |
| Stone | 8 | `stone.obtain_cobblestone`, `stone.craft_furnace` |
| Iron | 9 | `iron.obtain_raw_iron`, `iron.smelt_iron_ingot` |
| Gold-Redstone | 5 | `gold_redstone.obtain_redstone`, `gold_redstone.craft_clock` |
| Diamond | 4 | `diamond.obtain_diamond`, `diamond.craft_enchanting_table` |
| Armor | 4 | `armor.craft_iron_chestplate`, `armor.craft_diamond_chestplate` |

Task families:

| Family | Count | Scoring |
|---|---:|---|
| `dig_pickup` | 10 | Inventory contains the dropped target item |
| `crafting_inventory` | 5 | Inventory contains crafted item |
| `crafting_table` | 23 | Inventory contains crafted item |
| `smelting` | 2 | Inventory contains smelted item |

The complete task list lives in:

```text
PhyAgentOS/benchmarks/minecraft/techtree/manifest.json
```

---

## Task Table

### Wooden

| id | target_item | family |
|---|---|---|
| `wooden.obtain_oak_log` | `oak_log` | `dig_pickup` |
| `wooden.obtain_dirt` | `dirt` | `dig_pickup` |
| `wooden.obtain_grass_block` | `grass_block` | `dig_pickup` |
| `wooden.craft_oak_planks` | `oak_planks` | `crafting_inventory` |
| `wooden.craft_stick` | `stick` | `crafting_inventory` |
| `wooden.craft_crafting_table` | `crafting_table` | `crafting_inventory` |
| `wooden.craft_chest` | `chest` | `crafting_table` |
| `wooden.craft_ladder` | `ladder` | `crafting_table` |
| `wooden.craft_bow` | `bow` | `crafting_table` |
| `wooden.craft_wooden_pickaxe` | `wooden_pickaxe` | `crafting_table` |

### Stone

| id | target_item | family |
|---|---|---|
| `stone.obtain_cobblestone` | `cobblestone` | `dig_pickup` |
| `stone.craft_stone_pickaxe` | `stone_pickaxe` | `crafting_table` |
| `stone.craft_stone_axe` | `stone_axe` | `crafting_table` |
| `stone.craft_stone_shovel` | `stone_shovel` | `crafting_table` |
| `stone.craft_stone_sword` | `stone_sword` | `crafting_table` |
| `stone.craft_furnace` | `furnace` | `crafting_table` |
| `stone.craft_stonecutter` | `stonecutter` | `crafting_table` |
| `stone.craft_torch` | `torch` | `crafting_inventory` |

### Iron

| id | target_item | family |
|---|---|---|
| `iron.obtain_coal` | `coal` | `dig_pickup` |
| `iron.obtain_raw_iron` | `raw_iron` | `dig_pickup` |
| `iron.smelt_iron_ingot` | `iron_ingot` | `smelting` |
| `iron.craft_iron_pickaxe` | `iron_pickaxe` | `crafting_table` |
| `iron.craft_iron_axe` | `iron_axe` | `crafting_table` |
| `iron.craft_iron_shovel` | `iron_shovel` | `crafting_table` |
| `iron.craft_iron_sword` | `iron_sword` | `crafting_table` |
| `iron.craft_bucket` | `bucket` | `crafting_table` |
| `iron.craft_shears` | `shears` | `crafting_inventory` |

### Gold-Redstone

| id | target_item | family |
|---|---|---|
| `gold_redstone.obtain_raw_gold` | `raw_gold` | `dig_pickup` |
| `gold_redstone.smelt_gold_ingot` | `gold_ingot` | `smelting` |
| `gold_redstone.obtain_redstone` | `redstone` | `dig_pickup` |
| `gold_redstone.craft_clock` | `clock` | `crafting_table` |
| `gold_redstone.craft_compass` | `compass` | `crafting_table` |

### Diamond

| id | target_item | family |
|---|---|---|
| `diamond.obtain_diamond` | `diamond` | `dig_pickup` |
| `diamond.obtain_obsidian` | `obsidian` | `dig_pickup` |
| `diamond.craft_diamond_pickaxe` | `diamond_pickaxe` | `crafting_table` |
| `diamond.craft_enchanting_table` | `enchanting_table` | `crafting_table` |

### Armor

| id | target_item | family |
|---|---|---|
| `armor.craft_iron_helmet` | `iron_helmet` | `crafting_table` |
| `armor.craft_iron_chestplate` | `iron_chestplate` | `crafting_table` |
| `armor.craft_diamond_helmet` | `diamond_helmet` | `crafting_table` |
| `armor.craft_diamond_chestplate` | `diamond_chestplate` | `crafting_table` |

---

## Reporting Guidance

Reports should include:

- benchmark name and manifest version;
- task ids and tier split;
- agent or runtime used;
- world adapter used;
- number of repetitions per task;
- success rate and mean reward;
- failure categories when available;
- reproducibility notes, including Minecraft version, bridge version, and setup.

Do not compare these numbers directly to MineStudio, MCU, MineEvolve, TeamCraft,
or VPT leaderboards.  This benchmark is a vetted, executor-independent,
standalone obtain-item reimplementation designed for OS integration and
repeatable programmatic scoring.

---

## Limitations

| Limitation | Impact |
|---|---|
| Standalone vetted subset | Derived from MineStudio-style configs and tech-tree tiers, then reimplemented as a standalone programmatic mineflayer benchmark; not an official MineStudio, MCU, MineEvolve, TeamCraft, or VPT protocol, so scores are not comparable to their public numbers |
| Execution-layer scope | Materials or target blocks are placed near the agent, target coordinates are available through setup, and prerequisite tools are provided; scores measure low-level physical execution after setup |
| Not an exploration or planning benchmark | Does not measure resource search, visual target localization, high-level planning, long-horizon reasoning, or true tech-tree dependency climbing |
| Tech-tree tiers are labels | Tiers describe task category and difficulty; tasks are isolated and do not require the agent to traverse a dependency chain across tasks |
| Programmatic inventory/state scoring | Avoids VLM judgment but misses visual or semantic nuance |
| Arena-only scene isolation | Reference adapter uses a fixed cleaned arena and relative task placement; it does not regenerate full world seeds or natural terrain |
| Execution non-determinism | Use repeated trials when reporting results |
| Reference adapter is mineflayer-specific | Core benchmark remains adapter-agnostic |
