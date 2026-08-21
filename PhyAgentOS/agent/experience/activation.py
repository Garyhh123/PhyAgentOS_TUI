"""Per-turn Skill activation context and scoped Lesson retrieval."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from PhyAgentOS.agent.experience.contracts import (
    ScopedLesson,
    SkillActivation,
    WorkflowTraceItem,
)
from PhyAgentOS.agent.experience.redaction import redact_text
from PhyAgentOS.agent.experience.store import ExperienceStore
from PhyAgentOS.agent.skills import SkillsLoader


@dataclass
class TurnExperienceContext:
    session_key: str
    task_summary: str
    activations: list[SkillActivation] = field(default_factory=list)
    workflow_trace: list[WorkflowTraceItem] = field(default_factory=list)
    verification_lessons: dict[str, list[dict[str, Any]]] = field(
        default_factory=dict
    )


class SkillActivationManager:
    def __init__(
        self,
        *,
        workspace: str | Path,
        store: ExperienceStore,
        max_lessons_per_skill: int = 8,
        runtime_availability_provider: Callable[[str], bool] | None = None,
    ) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.skills = SkillsLoader(
            self.workspace,
            runtime_availability_provider=runtime_availability_provider,
        )
        self.store = store
        self.max_lessons_per_skill = max(1, int(max_lessons_per_skill))
        self._contexts: dict[str, TurnExperienceContext] = {}
        self._lock = threading.RLock()

    def begin_turn(self, session_key: str, task_summary: str) -> None:
        with self._lock:
            self._contexts[session_key] = TurnExperienceContext(
                session_key=session_key,
                task_summary=redact_text(task_summary.strip()),
            )

    def activate(
        self,
        *,
        session_key: str,
        name: str,
        role: str,
    ) -> tuple[SkillActivation, str, list[ScopedLesson]]:
        skill = self.skills.resolve_skill(name, require_available=True)
        if skill is None:
            raise ValueError(f"Skill {name!r} is not registered or is unavailable")
        if role not in {"primary", "supporting"}:
            raise ValueError("role must be primary or supporting")
        content = Path(skill["path"]).read_text(encoding="utf-8")
        activation = SkillActivation(
            activation_id=f"activation_{uuid4().hex[:16]}",
            skill_name=name,
            role=role,
            source=skill["source"],
            content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )
        with self._lock:
            context = self._contexts.setdefault(
                session_key, TurnExperienceContext(session_key=session_key, task_summary="")
            )
            existing = next(
                (item for item in context.activations if item.skill_name == name), None
            )
            if existing is not None and existing.role != role:
                raise ValueError(
                    f"Skill {name!r} is already activated as {existing.role}"
                )
            if role == "primary":
                primary = next(
                    (item for item in context.activations if item.role == "primary"),
                    None,
                )
                if primary is not None and primary.skill_name != name:
                    raise ValueError(
                        f"primary Skill {primary.skill_name!r} is already activated"
                    )
            if existing is None:
                context.activations.append(activation)
            else:
                activation = existing
            task_summary = context.task_summary
        lessons = self.relevant_lessons(name, task_summary)
        with self._lock:
            context = self._contexts.get(session_key)
            if context is not None:
                context.verification_lessons[name] = [
                    {
                        "skill_name": name,
                        "skill_role": activation.role,
                        "workflow_key": lesson.workflow_key,
                        **self.lesson_payload(lesson),
                    }
                    for lesson in lessons
                ]
        return activation, content, lessons

    def record_tool(self, session_key: str, name: str, arguments: Any) -> None:
        keys = sorted(str(key) for key in arguments) if isinstance(arguments, dict) else []
        with self._lock:
            context = self._contexts.get(session_key)
            if context is None:
                return
            context.workflow_trace.append(WorkflowTraceItem(name=name, input_keys=keys))

    def snapshot(self, session_key: str) -> dict[str, Any]:
        with self._lock:
            context = self._contexts.get(session_key) or TurnExperienceContext(
                session_key=session_key,
                task_summary="",
            )
            return {
                "task_summary": context.task_summary,
                "skill_activations": [
                    item.model_dump(mode="json") for item in context.activations
                ],
                "verification_lessons": [
                    lesson
                    for activation in context.activations
                    for lesson in context.verification_lessons.get(
                        activation.skill_name, []
                    )
                ],
                "workflow_trace": [
                    item.model_dump(mode="json") for item in context.workflow_trace
                ],
            }

    def relevant_lessons(self, skill_name: str, task_summary: str) -> list[ScopedLesson]:
        lessons = self.store.list_lessons(skill_name=skill_name, status="active")
        query_terms = self._terms(task_summary)

        def score(lesson: ScopedLesson) -> tuple[int, int, float] | None:
            applies_overlap = len(
                query_terms & self._terms(" ".join(lesson.applies_when))
            )
            excludes_overlap = len(
                query_terms & self._terms(" ".join(lesson.does_not_apply_when))
            )
            if applies_overlap == 0 or excludes_overlap >= applies_overlap:
                return None
            return (
                applies_overlap - excludes_overlap,
                lesson.observation_count,
                lesson.updated_at.timestamp(),
            )

        ranked = [(item, score(item)) for item in lessons]
        ranked = [(item, value) for item, value in ranked if value is not None]
        ranked.sort(key=lambda item: item[1], reverse=True)
        return [item for item, _ in ranked[: self.max_lessons_per_skill]]

    @staticmethod
    def lesson_payload(lesson: ScopedLesson) -> dict[str, Any]:
        return {
            "lesson_id": lesson.lesson_id,
            "applies_when": lesson.applies_when,
            "does_not_apply_when": lesson.does_not_apply_when,
            "failure_mode": lesson.failure_mode,
            "recommendation": lesson.recommendation,
            "severity": lesson.severity,
            "observations": lesson.observation_count,
        }

    @staticmethod
    def _terms(text: str) -> set[str]:
        terms = {
            token.lower()
            for token in re.findall(r"[A-Za-z0-9_\-]+", text)
            if len(token) > 1
        }
        for phrase in re.findall(r"[\u4e00-\u9fff]+", text):
            if len(phrase) == 1:
                terms.add(phrase)
            else:
                terms.update(phrase[index : index + 2] for index in range(len(phrase) - 1))
        return terms

    def dump_activation_result(
        self,
        activation: SkillActivation,
        content: str,
        lessons: list[ScopedLesson],
    ) -> str:
        return json.dumps(
            {
                "ok": True,
                "activation": activation.model_dump(mode="json"),
                "skill": content,
                "applicable_lessons": [self.lesson_payload(item) for item in lessons],
            },
            ensure_ascii=False,
        )
