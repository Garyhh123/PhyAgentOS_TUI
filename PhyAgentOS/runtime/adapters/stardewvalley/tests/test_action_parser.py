import pytest

from PhyAgentOS.runtime.adapters.stardewvalley.bridge.action_parser import ActionParseError, execute_skill_expression


class FakeExecutor:
    def __init__(self):
        self.calls = []

    def move(self, x, y):
        self.calls.append(("move", (x, y), {}))
        return "moved"

    def use(self, direction):
        self.calls.append(("use", (direction,), {}))
        return "used"

    def choose_option(self, option_index, quantity=None, direction=None):
        self.calls.append(
            (
                "choose_option",
                (option_index, quantity, direction),
                {},
            )
        )
        return "chosen"

    def unattach_item(self):
        self.calls.append(("unattach_item", (), {}))
        return "unattached"

    def menu(self, option, menu_name):
        self.calls.append(("menu", (option, menu_name), {}))
        return "menu"

    def choose_item(self, slot_index):
        self.calls.append(("choose_item", (slot_index,), {}))


def test_allowed_action_calls_executor():
    executor = FakeExecutor()

    result = execute_skill_expression(executor, "move(1, 0)")

    assert result == "moved"
    assert executor.calls == [("move", (1, 0), {})]


@pytest.mark.parametrize(
    "expression,expected_call",
    [
        ('use("down")', ("use", ("down",), {})),
        ('choose_option(1, 1, "in")', ("choose_option", (1, 1, "in"), {})),
        ("unattach_item()", ("unattach_item", (), {})),
        ('menu("open", "map")', ("menu", ("open", "map"), {})),
        ('menu("close", "current_menu")', ("menu", ("close", "current_menu"), {})),
    ],
)
def test_protocol_examples(expression, expected_call):
    executor = FakeExecutor()

    execute_skill_expression(executor, expression)

    assert executor.calls == [expected_call]


@pytest.mark.parametrize(
    "expression",
    [
        "open_map()",
        "executor.move(1, 0)",
        "1 + 2",
        "move(get_x(), 0)",
        "use(down)",
        "move(*[1, 0])",
        "",
    ],
)
def test_rejects_unsafe_or_invalid_expressions(expression):
    with pytest.raises(ActionParseError):
        execute_skill_expression(FakeExecutor(), expression)


def test_rejects_missing_executor_skill_even_if_allowed():
    class MissingExecutor:
        pass

    with pytest.raises(ActionParseError, match="Skill not found"):
        execute_skill_expression(MissingExecutor(), "move(1, 0)")

