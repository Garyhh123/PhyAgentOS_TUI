# Minecraft Tech-Tree Benchmark

The Minecraft tech-tree benchmark is an executor-independent, standalone
obtain-item benchmark for standard Minecraft item progression.  Its tasks are
derived from and vetted against MineStudio-style task configs plus a standard
Minecraft tech-tree taxonomy, then reimplemented as PhyAgentOS-owned task
definitions with programmatic scoring.

This is not an official MineStudio, MCU, MineEvolve, TeamCraft, or VPT
benchmark protocol, and its numbers should not be compared to those public
leaderboards.

## Scope

This is an execution-layer benchmark.  The reference adapter resets each task
into an isolated arena, places required materials or target blocks near the
agent, provides target coordinates through the task setup, and gives the
prerequisite tools declared by the task.  It measures whether an injected agent
can execute low-level Minecraft actions, including local navigation, digging,
pickup, crafting, placing, and smelting, once materials are staged, targets are
localized, and prerequisites are available.

It does not measure open-world exploration, resource search, visual target
localization, high-level planning, long-horizon reasoning, or climbing the real
Minecraft dependency chain.  The tech-tree tiers are difficulty and category
labels; they are not a dependency chain that the agent must discover or execute
across tasks.

The benchmark core does not run an agent by itself.  It exposes a small API:

1. load a task from `manifest.json`;
2. set up the world through an injected `WorldAdapter`;
3. call an injected `agent_fn`;
4. evaluate the final observation with deterministic inventory/state checks.

No LLM, VLM, watchdog, session runner, governance, skill induction, or workspace
state is required by the core package.

## Package Layout

| File | Purpose |
|---|---|
| `manifest.json` | Vetted 40-task tech-tree manifest |
| `schema.py` | Dataclasses for tasks, arena setup, and success criteria |
| `loader.py` | `load_manifest`, `list_tasks`, `load_task` |
| `evaluator.py` | Programmatic inventory evaluator |
| `harness.py` | Executor-independent `run_task` harness |
| `adapters/mineflayer_bridge.py` | Optional reference adapter for a mineflayer HTTP bridge |

## Public API

```python
from PhyAgentOS.benchmarks.minecraft.techtree import (
    evaluate_task,
    list_tasks,
    load_task,
    run_task,
)

task = load_task("wooden.obtain_oak_log")
verdict = evaluate_task(task, {"inventory": {"oak_log": 1}})
print(verdict.success)
```

To run an agent, inject your own world adapter and agent function:

```python
from PhyAgentOS.benchmarks.minecraft.techtree import run_task


def my_agent(task, world):
    # The benchmark does not care how this agent works.
    # It may be scripted, LLM-driven, policy-driven, or another system.
    return {"ok": True}


result = run_task("wooden.obtain_oak_log", my_agent, my_world_adapter)
print(result.success, result.reward)
```

`my_world_adapter` only needs two methods:

```python
class WorldAdapter:
    def reset(self, setup):
        ...

    def observe(self):
        ...
```

The optional `MineflayerBridgeAdapter` demonstrates how a mineflayer HTTP bridge
can implement that interface.  It is deliberately isolated under `adapters/` so
the benchmark core remains executor-independent.

## Reset And Arena Isolation

Task setup describes a fixed local arena in addition to inventory and task
blocks.  The default arena origin is `[-2000, 80, -2000]`; the reference
mineflayer adapter teleports the bot there, clears a bounded box, lays a fixed
floor, marks the boundary, then places task blocks at fixed coordinates relative
to the arena origin.

This makes reference-adapter runs reproducible inside the arena and avoids
accidentally using old world terrain around the bot.  The benchmark does not
claim to recreate a full Minecraft world seed or terrain distribution.

## Scoring

Version 1 uses deterministic programmatic criteria.  Most tasks use:

```json
{"type": "inventory_contains", "item": "<target_item>", "count": 1}
```

The evaluator accepts common Minecraft observation shapes:

- `{"inventory": {"oak_log": 1}}`
- `{"inventory": {"counts": {"oak_log": 1}}}`
- `{"inventory_items": [{"name": "minecraft:oak_log", "count": 1}]}`
- `{"info": {"inventory_items": [...]}}`

Reward is `1.0` for success and `0.0` otherwise.  Repeated trials are
recommended because Minecraft execution loops can be non-deterministic even
when the initial task definition is fixed.

## Task List

### Wooden

| id | target_item | family | source |
|---|---|---|---|
| `wooden.obtain_oak_log` | `oak_log` | `dig_pickup` | collect_wood |
| `wooden.obtain_dirt` | `dirt` | `dig_pickup` | mine_dirt |
| `wooden.obtain_grass_block` | `grass_block` | `dig_pickup` | collect_grass |
| `wooden.craft_oak_planks` | `oak_planks` | `crafting_inventory` | craft_the_crafting_table |
| `wooden.craft_stick` | `stick` | `crafting_inventory` | tool_bow |
| `wooden.craft_crafting_table` | `crafting_table` | `crafting_inventory` | craft_table |
| `wooden.craft_chest` | `chest` | `crafting_table` | prepare_a_birthday_present_for_your_neighbor |
| `wooden.craft_ladder` | `ladder` | `crafting_table` | craft_ladder, craft_to_ladder |
| `wooden.craft_bow` | `bow` | `crafting_table` | tool_bow |
| `wooden.craft_wooden_pickaxe` | `wooden_pickaxe` | `crafting_table` | survive_plant |

### Stone

| id | target_item | family | source |
|---|---|---|---|
| `stone.obtain_cobblestone` | `cobblestone` | `dig_pickup` | cut_stone |
| `stone.craft_stone_pickaxe` | `stone_pickaxe` | `crafting_table` | cut_stone |
| `stone.craft_stone_axe` | `stone_axe` | `crafting_table` | collect_wood |
| `stone.craft_stone_shovel` | `stone_shovel` | `crafting_table` | mine_dirt |
| `stone.craft_stone_sword` | `stone_sword` | `crafting_table` | survive_combat |
| `stone.craft_furnace` | `furnace` | `crafting_table` | craft_smelting |
| `stone.craft_stonecutter` | `stonecutter` | `crafting_table` | craft_stonecut |
| `stone.craft_torch` | `torch` | `crafting_inventory` | find_diamond |

### Iron

| id | target_item | family | source |
|---|---|---|---|
| `iron.obtain_coal` | `coal` | `dig_pickup` | mine_iron_ore |
| `iron.obtain_raw_iron` | `raw_iron` | `dig_pickup` | mine_iron_ore |
| `iron.smelt_iron_ingot` | `iron_ingot` | `smelting` | craft_smelting |
| `iron.craft_iron_pickaxe` | `iron_pickaxe` | `crafting_table` | mine_obsidian |
| `iron.craft_iron_axe` | `iron_axe` | `crafting_table` | clean_up |
| `iron.craft_iron_shovel` | `iron_shovel` | `crafting_table` | dig_three_down_and_fill_one_up |
| `iron.craft_iron_sword` | `iron_sword` | `crafting_table` | enchant_sword |
| `iron.craft_bucket` | `bucket` | `crafting_table` | craft_to_cake |
| `iron.craft_shears` | `shears` | `crafting_inventory` | collect_wool |

### Gold-Redstone

| id | target_item | family | source |
|---|---|---|---|
| `gold_redstone.obtain_raw_gold` | `raw_gold` | `dig_pickup` | craft_to_clock |
| `gold_redstone.smelt_gold_ingot` | `gold_ingot` | `smelting` | craft_to_clock |
| `gold_redstone.obtain_redstone` | `redstone` | `dig_pickup` | craft_to_clock |
| `gold_redstone.craft_clock` | `clock` | `crafting_table` | craft_to_clock |
| `gold_redstone.craft_compass` | `compass` | `crafting_table` | find_village |

### Diamond

| id | target_item | family | source |
|---|---|---|---|
| `diamond.obtain_diamond` | `diamond` | `dig_pickup` | find_diamond, mine_diamond_ore |
| `diamond.obtain_obsidian` | `obsidian` | `dig_pickup` | mine_obsidian |
| `diamond.craft_diamond_pickaxe` | `diamond_pickaxe` | `crafting_table` | mine_obsidian |
| `diamond.craft_enchanting_table` | `enchanting_table` | `crafting_table` | craft_enchantment |

### Armor

| id | target_item | family | source |
|---|---|---|---|
| `armor.craft_iron_helmet` | `iron_helmet` | `crafting_table` | survive_combat |
| `armor.craft_iron_chestplate` | `iron_chestplate` | `crafting_table` | survive_combat |
| `armor.craft_diamond_helmet` | `diamond_helmet` | `crafting_table` | enchant_diamond_sword |
| `armor.craft_diamond_chestplate` | `diamond_chestplate` | `crafting_table` | enchant_diamond_sword |

## Limitations

- This is a vetted, standalone reimplementation derived from MineStudio-style
  task configs and Minecraft tech-tree tiers.  It is not the official
  MineStudio, MCU, MineEvolve, TeamCraft, or VPT benchmark protocol, and scores
  are not directly comparable to external leaderboard numbers.
- This is an execution-layer obtain-item benchmark.  Each task runs in an
  isolated arena with materials or target blocks placed near the agent, target
  coordinates available through setup, and prerequisite tools provided.  Scores
  measure whether the agent can execute low-level Minecraft actions after setup,
  not whether it can discover resources or plan the dependency chain.
- It does not measure open-world exploration, resource search, visual target
  localization, high-level planning, long-horizon reasoning, or true tech-tree
  climbing.  The tech-tree tiers are difficulty and category labels, not a
  dependency chain that the agent must execute across tasks.
- It uses programmatic inventory/state checks, not visual judgment.
- The reference adapter isolates each task inside a fixed, cleaned arena with
  relative task placement.  It does not regenerate a full world seed or natural
  terrain distribution.
- A task definition can be deterministic while a Minecraft execution loop is
  still non-deterministic.  Use multiple repetitions when reporting scores.
- The core harness is single-agent by default.  Multi-agent or OS session
  execution should wrap this package rather than modifying the core benchmark.
