import json
from collections import deque
from pathlib import Path

from PhyAgentOS.runtime.adapters.stardewvalley.bridge.obs_compact import COMPACT_OBS_KEYS, compact_obs, image_paths_from_obs, to_jsonable


def test_compact_obs_keeps_stable_field_set_and_omits_raw_screenshot():
    obs = {key: f"value:{key}" for key in COMPACT_OBS_KEYS}
    obs["ScreenShot"] = object()
    obs["screenshot"] = object()

    compact = compact_obs(obs)

    assert tuple(compact.keys()) == COMPACT_OBS_KEYS
    assert "ScreenShot" not in compact
    assert "screenshot" not in compact


def test_compact_obs_uses_single_public_image_field():
    obs = {key: None for key in COMPACT_OBS_KEYS}
    obs["image_paths"] = deque([Path("screen_shot_buffer/a.jpeg"), "b.jpeg"])

    compact = compact_obs(obs)

    assert "image_paths" not in compact
    assert compact["latest_image_url"] is None
    json.dumps(compact)


def test_to_jsonable_supports_numpy_like_values():
    class Scalar:
        def item(self):
            return 3

    class Array:
        def tolist(self):
            return [Scalar(), Path("x")]

    assert to_jsonable({"value": Array()}) == {"value": [3, "x"]}


def test_image_paths_from_obs_returns_string_paths():
    obs = {"image_paths": deque([Path("a.jpeg"), "b.jpeg"])}

    assert image_paths_from_obs(obs) == ["a.jpeg", "b.jpeg"]
