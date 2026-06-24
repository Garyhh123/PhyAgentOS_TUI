"""Load BEHAVIOR-1K task lists from a local checkout."""

from __future__ import annotations

import json
from pathlib import Path

from b1k_integration.benchmark.schemas import BenchmarkTaskSpec

CHALLENGE50_TASK_NAMES: tuple[str, ...] = (
    "turning_on_radio",
    "picking_up_trash",
    "putting_away_Halloween_decorations",
    "cleaning_up_plates_and_food",
    "can_meat",
    "setting_mousetraps",
    "hiding_Easter_eggs",
    "picking_up_toys",
    "rearranging_kitchen_furniture",
    "putting_up_Christmas_decorations_inside",
    "set_up_a_coffee_station_in_your_kitchen",
    "putting_dishes_away_after_cleaning",
    "preparing_lunch_box",
    "loading_the_car",
    "carrying_in_groceries",
    "bringing_in_wood",
    "moving_boxes_to_storage",
    "bringing_water",
    "tidying_bedroom",
    "outfit_a_basic_toolbox",
    "sorting_vegetables",
    "collecting_childrens_toys",
    "putting_shoes_on_rack",
    "boxing_books_up_for_storage",
    "storing_food",
    "clearing_food_from_table_into_fridge",
    "assembling_gift_baskets",
    "sorting_household_items",
    "getting_organized_for_work",
    "clean_up_your_desk",
    "setting_the_fire",
    "clean_boxing_gloves",
    "wash_a_baseball_cap",
    "wash_dog_toys",
    "hanging_pictures",
    "attach_a_camera_to_a_tripod",
    "clean_a_patio",
    "clean_a_trumpet",
    "spraying_for_bugs",
    "spraying_fruit_trees",
    "make_microwave_popcorn",
    "cook_cabbage",
    "chop_an_onion",
    "slicing_vegetables",
    "chopping_wood",
    "cook_hot_dogs",
    "cook_bacon",
    "freeze_pies",
    "canning_food",
    "make_pizza",
)

TASK_NAME_TO_INDEX = {name: idx for idx, name in enumerate(CHALLENGE50_TASK_NAMES)}


def resolve_behavior1k_root(root: str | Path | None) -> Path:
    if root:
        path = Path(root).expanduser().resolve()
        if path.is_dir():
            return path
    env_root = Path.home() / "work" / "BEHAVIOR-1K"
    if env_root.is_dir():
        return env_root.resolve()
    raise FileNotFoundError(
        "BEHAVIOR-1K root not found. Set behavior1k_root in BENCHMARKS.md or "
        "export BEHAVIOR1K_ROOT=/path/to/BEHAVIOR-1K"
    )


def load_task_instructions(behavior1k_root: Path) -> dict[str, str]:
    path = behavior1k_root / "docs" / "challenge" / "task_data.json"
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    out: dict[str, str] = {}
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and item.get("name"):
                out[str(item["name"])] = str(item.get("instruction") or item.get("description") or "")
    elif isinstance(payload, dict):
        for name, item in payload.items():
            if isinstance(item, dict):
                out[str(name)] = str(item.get("instruction") or item.get("description") or "")
            else:
                out[str(name)] = str(item)
    return out


def list_tasks(
    *,
    task_source: str,
    behavior1k_root: Path,
    task_names: list[str] | None = None,
) -> list[BenchmarkTaskSpec]:
    instructions = load_task_instructions(behavior1k_root)
    source = task_source.strip().lower()
    if source in ("challenge50", "challenge_50", "b50"):
        names = list(CHALLENGE50_TASK_NAMES)
    elif source == "custom":
        names = list(task_names or [])
    elif source == "all_bddl":
        defs_dir = behavior1k_root / "bddl3" / "bddl" / "activity_definitions"
        if not defs_dir.is_dir():
            defs_dir = behavior1k_root / "src" / "omnigibson" / "bddl3" / "bddl" / "activity_definitions"
        names = sorted(p.name for p in defs_dir.iterdir() if p.is_dir()) if defs_dir.is_dir() else []
    else:
        raise ValueError(f"unsupported BEHAVIOR-1K task_source: {task_source!r}")

    if task_names:
        wanted = {n.strip() for n in task_names if n.strip()}
        names = [n for n in names if n in wanted]
        missing = sorted(wanted - set(names))
        if missing:
            raise ValueError(f"unknown task name(s): {missing}")

    tasks: list[BenchmarkTaskSpec] = []
    for name in names:
        tasks.append(
            BenchmarkTaskSpec(
                name=name,
                index=TASK_NAME_TO_INDEX.get(name),
                instruction=instructions.get(name, name.replace("_", " ")),
            )
        )
    return tasks


def default_test_instance_ids(_behavior1k_root: Path, _task_name: str) -> list[int]:
    """Fallback public eval instance ids when metadata is unavailable."""
    return [0]
