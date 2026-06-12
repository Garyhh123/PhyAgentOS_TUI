"""Hierarchical task plan schemas for structured agent execution."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ActionSpec(BaseModel):
    """One bridge action with type and params."""
    type: str
    params: dict[str, Any] = Field(default_factory=dict)


class TaskNode(BaseModel):
    """A single task with preconditions, actions, and verification."""
    id: str
    name: str
    preconditions: list[str] = Field(default_factory=list)
    actions: list[ActionSpec] = Field(default_factory=list)
    verify: list[str] = Field(default_factory=list)
    on_fail: Literal["abort", "retry", "skip"] = "retry"
    max_retries: int = 3
    state: Literal["pending", "running", "done", "failed", "skipped"] = "pending"
    attempts: int = 0
    last_error: str | None = None


class SubGoal(BaseModel):
    """A group of related tasks with shared pre/post checks."""
    id: str
    name: str
    precheck: list[str] = Field(default_factory=list)
    postcheck: list[str] = Field(default_factory=list)
    tasks: list[TaskNode] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    state: Literal["pending", "running", "done", "failed"] = "pending"


class TaskPlan(BaseModel):
    """Full hierarchical execution plan."""
    goal: str
    subgoals: list[SubGoal] = Field(default_factory=list)
