from PhyAgentOS.cli.stardew_commands import _extract_action


def test_extract_action_accepts_raw_action():
    assert _extract_action('use("down")') == 'use("down")'


def test_extract_action_recovers_action_from_text():
    assert _extract_action('Next action: move(1, 0)') == "move(1, 0)"


def test_extract_action_recovers_action_from_json():
    assert _extract_action('{"action": "interact(\\"up\\")"}') == 'interact("up")'


def test_extract_action_prefers_final_action_line():
    raw = "I should move toward the weeds.\nACTION: move(2, 0)"
    assert _extract_action(raw) == "move(2, 0)"


def test_extract_action_ignores_think_blocks():
    raw = "<think>try several options</think>\nACTION: choose_item(4)"
    assert _extract_action(raw) == "choose_item(4)"
