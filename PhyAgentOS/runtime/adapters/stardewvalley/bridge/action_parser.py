"""Safe parser for Stardew skill-call expressions."""

from __future__ import annotations

import ast
from collections.abc import Callable
from typing import Any

ALLOWED_SKILLS = frozenset(
    {
        "move",
        "use",
        "interact",
        "choose_item",
        "craft",
        "choose_option",
        "attach_item",
        "unattach_item",
        "menu",
    }
)


class ActionParseError(ValueError):
    """Raised when a Track A action string is not a safe skill call."""


def parse_skill_expression(expression: str) -> tuple[str, list[Any], dict[str, Any]]:
    """Parse a safe skill-call expression into name, args, and kwargs.

    Only direct calls such as ``move(1, 0)`` or ``use("down")`` are accepted.
    Arguments must be Python literals so Track A cannot smuggle arbitrary code
    through the bridge.
    """

    if not isinstance(expression, str):
        raise ActionParseError("Action must be a string.")

    expression = expression.strip()
    if not expression:
        raise ActionParseError("Action must not be empty.")

    try:
        parsed = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ActionParseError(f"Invalid action syntax: {exc.msg}") from exc

    call = parsed.body
    if not isinstance(call, ast.Call):
        raise ActionParseError("Action must be a function call expression.")

    if not isinstance(call.func, ast.Name):
        raise ActionParseError("Only direct skill calls are allowed.")

    skill_name = call.func.id
    if skill_name not in ALLOWED_SKILLS:
        raise ActionParseError(f"Skill not allowed: {skill_name}")

    args = [_literal_eval(arg) for arg in call.args]
    kwargs: dict[str, Any] = {}
    for keyword in call.keywords:
        if keyword.arg is None:
            raise ActionParseError("Star arguments are not allowed.")
        kwargs[keyword.arg] = _literal_eval(keyword.value)

    return skill_name, args, kwargs


def execute_skill_expression(skill_executor: Any, expression: str) -> Any:
    """Parse and execute a safe skill-call expression on ``skill_executor``."""

    skill_name, args, kwargs = parse_skill_expression(expression)
    skill = getattr(skill_executor, skill_name, None)
    if not callable(skill):
        raise ActionParseError(f"Skill not found on executor: {skill_name}")
    return skill(*args, **kwargs)


def _literal_eval(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except (SyntaxError, ValueError) as exc:
        raise ActionParseError("Action arguments must be literal values.") from exc


def allowed_skill_names() -> tuple[str, ...]:
    """Return the allowed skill names in a stable order for documentation."""

    return tuple(sorted(ALLOWED_SKILLS))


def make_executor(skills: dict[str, Callable[..., Any]]) -> Any:
    """Build a tiny attribute executor, useful for tests and examples."""

    return type("SkillExecutor", (), dict(skills))()

