"""Demo 04 runner for the TUI.

Demo 04 is about experience-driven skill evolution: independent successes can
promote a SkillCandidate, repeated workflow-related failures can activate a
scoped lesson, and unrelated failures stay diagnostic. This TUI runner keeps
that story as persisted runtime/evolution artifacts instead of replaying a
single terminal dump.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from phyagentos_tui.demo01_runner import EventSink
from PhyAgentOS.utils.atomic_file import atomic_write_text


SKILL_NAME = "grasp-tabletop-object"
PROFILE = "mujoco-evolution"
MIN_EPISODES = 3
DEMO04_TOOLS = (
    "motion.resolve_relative_pose",
    "motion.move_pose",
    "gripper.set_opening",
)


@dataclass
class Demo04EvolutionRecord:
    run_id: str
    status: str = "running"
    skill_name: str = SKILL_NAME
    profile: str = PROFILE
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    bundle: dict[str, Any] = field(default_factory=dict)
    install: dict[str, Any] = field(default_factory=dict)
    nodes: list[dict[str, Any]] = field(default_factory=list)
    environment: dict[str, Any] = field(default_factory=dict)
    runtime: dict[str, Any] = field(default_factory=dict)
    tools: list[dict[str, Any]] = field(default_factory=list)
    evolution: dict[str, Any] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)

    def event(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        self.updated_at = time.time()
        self.events.append(
            {
                "event_type": event_type,
                "created_at": self.updated_at,
                "payload": payload or {},
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": "paos_skill_evolution_demo_run_v1",
            "run_id": self.run_id,
            "status": self.status,
            "skill_name": self.skill_name,
            "profile": self.profile,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "bundle": self.bundle,
            "install": self.install,
            "nodes": self.nodes,
            "environment": self.environment,
            "runtime": self.runtime,
            "tools": self.tools,
            "evolution": self.evolution,
            "artifacts": self.artifacts,
            "events": self.events,
        }


class Demo04Runner:
    """Run Demo 04 and emit slow staged updates for Chat."""

    progress_delays_s = (2.4, 3.0, 3.5, 3.8, 3.4, 3.8, 3.2, 3.8, 3.8)
    final_delay_s = 3.8

    STAGES = (
        "点亮阈值与失败种子",
        "第 1 次独立成功",
        "第 2 次独立成功",
        "第 3 次成功并晋升 SkillCandidate",
        "第 3 次同类失败并激活 Scoped Lesson",
        "护栏:单次失败仍在 collecting",
        "护栏:外部失败仅保留诊断",
        "回看 Evolution Ledger 与边界",
    )

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.run_id = f"skillrun_{uuid4().hex[:16]}"
        self.run_root = self.workspace / "artifacts" / "skill_runtime" / self.run_id
        self.state_path = self.workspace / ".paos" / "skill_runtime" / "runs" / f"{self.run_id}.json"
        self.record = Demo04EvolutionRecord(run_id=self.run_id)
        self._candidate_id = f"candidate_{uuid4().hex[:10]}"
        self._lesson_id = f"lesson_{uuid4().hex[:10]}"
        self._cluster_id = f"cluster_{uuid4().hex[:10]}"
        self._single_cluster_id = f"cluster_{uuid4().hex[:10]}"
        self._stopped = False

    async def run(self, sink: EventSink) -> Demo04EvolutionRecord:
        await self._emit(
            sink,
            {
                "kind": "reset",
                "title": "Demo 04 · Experience evolution ledger",
                "description": "先点亮阈值与边界，再回放三次独立成功如何晋升候选技能、三次同类失败如何激活 Scoped Lesson，其余失败只保留诊断。",
                "stages": list(self.STAGES),
                "dashboard": self._dashboard(
                    threshold=f"{MIN_EPISODES} successful episodes / {MIN_EPISODES} related failures",
                    candidate="collecting 0/3",
                    cluster="collecting 2/3",
                    lesson="inactive",
                    guard="armed",
                    diagnostics="0 retained",
                    ledger="draft",
                ),
            },
        )
        self._prepare_workspace()
        try:
            await self._stage_preset_failures(sink)
            await self._stage_success(sink, 1)
            await self._stage_success(sink, 2)
            await self._stage_promotion(sink)
            await self._stage_lesson_activation(sink)
            await self._stage_single_failure_guard(sink)
            await self._stage_external_failure_guard(sink)
            await self._stage_ledger_review(sink)
            self.record.status = "succeeded"
            self.record.event("run_succeeded", {"promoted": True, "active_lessons": 1})
            self._persist()
            await self._emit_done(sink)
            return self.record
        except asyncio.CancelledError:
            await self.stop()
            raise
        except Exception as exc:
            self.record.status = "failed"
            self.record.event("run_failed", {"error": f"{type(exc).__name__}: {exc}"})
            self._persist()
            raise

    async def stop(self) -> None:
        self._stopped = True
        self.record.status = "cancelled"
        self.record.runtime["status"] = "stopped"
        self.record.event("runtime_stopped", {"reason": "demo04_stopped_from_tui"})
        self._persist()

    async def _stage_preset_failures(self, sink: EventSink) -> None:
        ledger = self._ledger_root()
        failures = [
            self._failure_observation("task_preset_fail_001", preset=True),
            self._failure_observation("task_preset_fail_002", preset=True),
        ]
        atomic_write_text(
            ledger / "preset_failure_observations.json",
            json.dumps({"observations": failures}, ensure_ascii=False, indent=2) + "\n",
        )
        self.record.evolution = {
            "thresholds": {
                "min_successful_episodes": MIN_EPISODES,
                "min_lesson_episodes": MIN_EPISODES,
            },
            "candidate": {
                "candidate_id": self._candidate_id,
                "skill_name": SKILL_NAME,
                "workflow_key": "grasp-tabletop-object",
                "status": "collecting",
                "supporting_episode_ids": [],
                "support_count": 0,
                "required_support": MIN_EPISODES,
                "blocked_by_lesson_ids": [],
            },
            "clusters": [
                {
                    "cluster_id": self._cluster_id,
                    "pattern_key": "grasp-height-misestimate",
                    "status": "collecting",
                    "supporting_root_task_ids": [item["root_task_id"] for item in failures],
                    "support_count": 2,
                    "required_support": MIN_EPISODES,
                }
            ],
            "lessons": [],
            "diagnostics": [],
        }
        self.record.artifacts.append(str(ledger / "preset_failure_observations.json"))
        self.record.event("preset_failures_recorded", {"support_count": 2, "pattern_key": "grasp-height-misestimate"})
        self._persist()
        await self._emit(
            sink,
            {
                "kind": "stage",
                "stage": 0,
                "status": "success",
                "message": "阈值已点亮：两次同类失败进入 collecting cluster，等待第三次观察",
                "artifacts": [str(ledger / "preset_failure_observations.json")],
                "dashboard": self._dashboard(
                    threshold=f"{MIN_EPISODES} successful episodes / {MIN_EPISODES} related failures",
                    candidate="collecting 0/3",
                    cluster="collecting 2/3",
                    lesson="inactive",
                    guard="armed",
                    diagnostics="0 retained",
                    ledger="draft",
                ),
            },
        )

    async def _stage_success(self, sink: EventSink, index: int) -> None:
        episode = self._success_episode(index)
        path = self._ledger_root() / f"success_episode_{index}.json"
        atomic_write_text(path, json.dumps(episode, ensure_ascii=False, indent=2) + "\n")
        candidate = self.record.evolution["candidate"]
        candidate["supporting_episode_ids"].append(episode["episode_id"])
        candidate["support_count"] = len(candidate["supporting_episode_ids"])
        candidate["status"] = "collecting"
        self.record.artifacts.append(str(path))
        self.record.event("success_episode_recorded", {"episode_id": episode["episode_id"], "support_count": candidate["support_count"]})
        self._persist()
        await self._emit(
            sink,
            {
                "kind": "stage",
                "stage": index,
                "status": "success",
                "message": f"成功 episode 入账 | SkillCandidate 支持 {candidate['support_count']}/{MIN_EPISODES}",
                "artifacts": [str(path)],
                "dashboard": self._dashboard(
                    threshold=f"{MIN_EPISODES} successful episodes / {MIN_EPISODES} related failures",
                    candidate=f"collecting {candidate['support_count']}/{MIN_EPISODES}",
                    cluster="collecting 2/3",
                    lesson="inactive",
                    guard="armed",
                    diagnostics=f"{len(self.record.evolution.get('diagnostics', []))} retained",
                    ledger="draft",
                ),
            },
        )

    async def _stage_promotion(self, sink: EventSink) -> None:
        episode = self._success_episode(3)
        path = self._ledger_root() / "success_episode_3.json"
        atomic_write_text(path, json.dumps(episode, ensure_ascii=False, indent=2) + "\n")
        candidate = self.record.evolution["candidate"]
        candidate["supporting_episode_ids"].append(episode["episode_id"])
        candidate["support_count"] = len(candidate["supporting_episode_ids"])
        candidate["status"] = "promoted"
        candidate["promoted_at"] = time.time()
        skill_dir = self.run_root / "skills" / SKILL_NAME
        references = skill_dir / "references"
        skill_dir.mkdir(parents=True, exist_ok=True)
        references.mkdir(parents=True, exist_ok=True)
        skill_path = skill_dir / "SKILL.md"
        atomic_write_text(skill_path, self._skill_markdown())
        revision_path = self._ledger_root() / "revisions" / SKILL_NAME / f"{self._candidate_id}.json"
        atomic_write_text(
            revision_path,
            json.dumps(
                {
                    "candidate_id": self._candidate_id,
                    "operation": "promote",
                    "skill_path": str(skill_path),
                    "supporting_episode_ids": candidate["supporting_episode_ids"],
                    "managed_block_sha256": self._sha256_text(self._skill_markdown()),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )
        self.record.bundle = {
            "name": f"{SKILL_NAME}-candidate-promoted",
            "path": str(skill_path),
            "sha256": self._sha256(skill_path),
            "files": 1,
        }
        self.record.install = {
            "workspace_override": str(skill_path),
            "transaction": "committed",
            "revision": str(revision_path),
        }
        self.record.artifacts.extend([str(path), str(skill_path), str(revision_path)])
        self.record.event("skill_candidate_promoted", {"candidate_id": self._candidate_id, "support_count": candidate["support_count"]})
        self._persist()
        await self._emit(
            sink,
            {
                "kind": "stage",
                "stage": 3,
                "status": "success",
                "message": f"第 3 次成功触发晋升 | {self._candidate_id} -> promoted | workspace override 写入",
                "artifacts": [str(skill_path), str(revision_path)],
                "dashboard": self._dashboard(
                    threshold=f"{MIN_EPISODES} successful episodes / {MIN_EPISODES} related failures",
                    candidate="promoted",
                    cluster="collecting 2/3",
                    lesson="inactive",
                    guard="armed",
                    diagnostics=f"{len(self.record.evolution.get('diagnostics', []))} retained",
                    ledger="promotion sealed",
                ),
            },
        )

    async def _stage_lesson_activation(self, sink: EventSink) -> None:
        failure = self._failure_observation("task_failure_003", preset=False)
        failure_path = self._ledger_root() / "failure_episode_3.json"
        atomic_write_text(failure_path, json.dumps(failure, ensure_ascii=False, indent=2) + "\n")
        cluster = self.record.evolution["clusters"][0]
        cluster["supporting_root_task_ids"].append(failure["root_task_id"])
        cluster["support_count"] = len(cluster["supporting_root_task_ids"])
        cluster["status"] = "activated"
        lesson = {
            "lesson_id": self._lesson_id,
            "status": "active",
            "skill_name": SKILL_NAME,
            "workflow_key": "grasp-tabletop-object",
            "failure_mode": "抓取位姿高于物体实际高度,闭合时未接触物体",
            "recommendation": "闭合夹爪前以动作后观测核对 TCP 高度与保持状态;偏差时修正高度重试",
            "observation_count": cluster["support_count"],
            "abstraction_validation": {
                "reusable": True,
                "contains_specific_answer": False,
                "confidence": 0.92,
            },
        }
        self.record.evolution["lessons"].append(lesson)
        lessons_md = self.run_root / "skills" / SKILL_NAME / "references" / "LESSONS.md"
        atomic_write_text(lessons_md, self._lessons_markdown(lesson))
        self.record.artifacts.extend([str(failure_path), str(lessons_md)])
        self.record.event("scoped_lesson_activated", {"lesson_id": self._lesson_id, "support_count": cluster["support_count"]})
        self._persist()
        await self._emit(
            sink,
            {
                "kind": "stage",
                "stage": 4,
                "status": "success",
                "message": f"同类失败达到 3/3 | Scoped Lesson active | {self._lesson_id}",
                "artifacts": [str(failure_path), str(lessons_md)],
                "dashboard": self._dashboard(
                    threshold=f"{MIN_EPISODES} successful episodes / {MIN_EPISODES} related failures",
                    candidate="promoted",
                    cluster="activated 3/3",
                    lesson="active",
                    guard="armed",
                    diagnostics=f"{len(self.record.evolution.get('diagnostics', []))} retained",
                    ledger="lesson sealed",
                ),
            },
        )

    async def _stage_single_failure_guard(self, sink: EventSink) -> None:
        guard = {
            "cluster_id": self._single_cluster_id,
            "pattern_key": "grasp-timeout",
            "status": "collecting",
            "supporting_root_task_ids": ["task_failure_single"],
            "support_count": 1,
            "required_support": MIN_EPISODES,
            "guard_result": "not_activated",
        }
        self.record.evolution["clusters"].append(guard)
        path = self._ledger_root() / "guard_single_failure.json"
        atomic_write_text(path, json.dumps(guard, ensure_ascii=False, indent=2) + "\n")
        self.record.artifacts.append(str(path))
        self.record.event("lesson_guard_single_failure", {"cluster_id": self._single_cluster_id, "support_count": 1})
        self._persist()
        await self._emit(
            sink,
            {
                "kind": "stage",
                "stage": 5,
                "status": "success",
                "message": "单次失败只保留 collecting cluster | support 1/3,不会激活 Lesson",
                "artifacts": [str(path)],
                "dashboard": self._dashboard(
                    threshold=f"{MIN_EPISODES} successful episodes / {MIN_EPISODES} related failures",
                    candidate="promoted",
                    cluster="collecting 1/3",
                    lesson="active",
                    guard="holding",
                    diagnostics=f"{len(self.record.evolution.get('diagnostics', []))} retained",
                    ledger="guard intact",
                ),
            },
        )

    async def _stage_external_failure_guard(self, sink: EventSink) -> None:
        diagnostic = {
            "event_type": "lesson_eligibility_rejected",
            "root_task_id": "task_diagnostic_only",
            "decision": "unrelated",
            "reason": "external_or_infrastructure",
            "confidence": 0.95,
            "effect": "diagnostic_only",
        }
        self.record.evolution["diagnostics"].append(diagnostic)
        path = self._ledger_root() / "diagnostic_external_failure.json"
        atomic_write_text(path, json.dumps(diagnostic, ensure_ascii=False, indent=2) + "\n")
        self.record.artifacts.append(str(path))
        self.record.event("lesson_eligibility_rejected", diagnostic)
        self._persist()
        await self._emit(
            sink,
            {
                "kind": "stage",
                "stage": 6,
                "status": "success",
                "message": "external_or_infrastructure 被拒绝进入经验聚类 | 仅保留诊断事件",
                "artifacts": [str(path)],
                "dashboard": self._dashboard(
                    threshold=f"{MIN_EPISODES} successful episodes / {MIN_EPISODES} related failures",
                    candidate="promoted",
                    cluster="collecting 1/3",
                    lesson="active",
                    guard="diagnostic only",
                    diagnostics=f"{len(self.record.evolution.get('diagnostics', []))} retained",
                    ledger="guard intact",
                ),
            },
        )

    async def _stage_ledger_review(self, sink: EventSink) -> None:
        self.record.nodes = [
            {
                "node_id": "experience.coordinator",
                "version": "current-worktree",
                "ready": True,
                "role": "episode capture + threshold routing",
            },
            {
                "node_id": "skill.evolution.manager",
                "version": "current-worktree",
                "ready": True,
                "role": "candidate promotion + revision retention",
            },
            {
                "node_id": "skill.activation.manager",
                "version": "current-worktree",
                "ready": True,
                "role": "workspace override projection",
            },
        ]
        self.record.environment = {
            "path": str(self.run_root / "skills" / SKILL_NAME),
            "ledger": str(self._ledger_root()),
            "immutable_snapshot": True,
        }
        self.record.runtime = {
            "status": "stopped",
            "flow_name": f"paos-{SKILL_NAME}-{PROFILE}",
            "experience_store": str(self._ledger_root() / "experience-ledger.json"),
            "health": {
                "candidate_promoted": self.record.evolution["candidate"]["status"] == "promoted",
                "active_lessons": len(self.record.evolution["lessons"]),
                "diagnostics_retained": len(self.record.evolution["diagnostics"]),
            },
        }
        self.record.tools = [
            {"tool_id": tool_id, "ready": True, "semantics": "query" if "resolve" in tool_id else "action"}
            for tool_id in DEMO04_TOOLS
        ]
        ledger_path = self._ledger_root() / "experience-ledger.json"
        atomic_write_text(
            ledger_path,
            json.dumps(self.record.evolution, ensure_ascii=False, indent=2) + "\n",
        )
        report = self.run_root / "evolution-report.json"
        atomic_write_text(
            report,
            json.dumps(self.record.to_dict(), ensure_ascii=False, indent=2) + "\n",
        )
        bundle = self.run_root / f"{SKILL_NAME}-evolution-snapshot.tar.gz"
        self._write_tar(bundle, self.run_root / "skills" / SKILL_NAME)
        self.record.bundle.update(
            {
                "snapshot": str(bundle),
                "snapshot_sha256": self._sha256(bundle),
                "snapshot_bytes": bundle.stat().st_size,
            }
        )
        self.record.artifacts.extend([str(ledger_path), str(report), str(bundle)])
        self.record.event("evolution_ledger_reviewed", {"report": str(report), "snapshot": str(bundle)})
        self._persist()
        await self._emit(
            sink,
            {
                "kind": "stage",
                "stage": 7,
                "status": "success",
                "message": "账本封存: promoted candidate + active lesson + guard decisions all retained",
                "artifacts": [str(ledger_path), str(report), str(bundle)],
                "dashboard": self._dashboard(
                    threshold=f"{MIN_EPISODES} successful episodes / {MIN_EPISODES} related failures",
                    candidate="promoted",
                    cluster="activated 3/3",
                    lesson="active",
                    guard="diagnostic only",
                    diagnostics=f"{len(self.record.evolution.get('diagnostics', []))} retained",
                    ledger="sealed",
                ),
            },
        )

    async def _emit_done(self, sink: EventSink) -> None:
        await self._emit(
            sink,
            {
                "kind": "done",
                "status": self.record.status,
                "record": self.record.to_dict(),
                "artifacts": self._artifact_summary(),
                "summary": [
                    f"Thresholds: `{MIN_EPISODES}` successes / `{MIN_EPISODES}` related failures",
                    f"SkillCandidate: `{self._candidate_id}` -> `promoted` after `3/3` successes",
                    f"Scoped Lesson: `{self._lesson_id}` -> `active` after `3/3` related failures",
                    "Guards: single failure stayed `collecting`; unrelated failure stayed `diagnostic_only`",
                ],
            },
        )

    def _prepare_workspace(self) -> None:
        (self.workspace / ".paos" / "skill_runtime" / "runs").mkdir(parents=True, exist_ok=True)
        (self.workspace / "artifacts" / "skill_runtime").mkdir(parents=True, exist_ok=True)
        self.run_root.mkdir(parents=True, exist_ok=True)
        self.record.event("run_created", {"run_id": self.run_id})
        self._persist()

    def _persist(self) -> None:
        atomic_write_text(
            self.state_path,
            json.dumps(self.record.to_dict(), ensure_ascii=False, indent=2) + "\n",
        )

    def _ledger_root(self) -> Path:
        root = self.run_root / ".paos" / "evolution"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _artifact_summary(self) -> list[str]:
        preferred = [
            self.run_root / "skills" / SKILL_NAME / "SKILL.md",
            self.run_root / "skills" / SKILL_NAME / "references" / "LESSONS.md",
            self._ledger_root() / "experience-ledger.json",
            self.run_root / "evolution-report.json",
            self.state_path,
        ]
        return [str(path) for path in preferred if path.exists()]

    @staticmethod
    def _dashboard(
        *,
        threshold: str,
        candidate: str,
        cluster: str,
        lesson: str,
        guard: str,
        diagnostics: str,
        ledger: str,
    ) -> dict[str, str]:
        return {
            "Threshold": threshold,
            "Candidate": candidate,
            "Cluster": cluster,
            "Lesson": lesson,
            "Guard": guard,
            "Diagnostics": diagnostics,
            "Ledger": ledger,
        }

    @staticmethod
    async def _emit(sink: EventSink, event: dict[str, Any]) -> None:
        result = sink(event)
        if inspect.isawaitable(result):
            await result

    @staticmethod
    def _success_episode(index: int) -> dict[str, Any]:
        return {
            "episode_id": f"episode_success_{index}",
            "root_task_id": f"task_success_{index}",
            "goal": f"把桌面上的杯子抓起来(success-{index})",
            "outcome": {
                "successful": True,
                "final_verdict": "success",
                "has_failed_attempt": False,
                "criteria_statuses": {
                    "TCP 到达抓取位姿": "satisfied",
                    "夹爪 reached_goal": "satisfied",
                    "物体被夹爪保持": "satisfied",
                },
            },
            "workflow_trace": [
                "motion.resolve_relative_pose",
                "motion.move_pose",
                "gripper.set_opening",
            ],
            "assessment": {
                "outcome": "success",
                "reusable": True,
                "confidence": 0.93,
                "proposal": "create" if index == 1 else "update",
            },
        }

    @staticmethod
    def _failure_observation(root_task_id: str, *, preset: bool) -> dict[str, Any]:
        return {
            "root_task_id": root_task_id,
            "preset": preset,
            "final_verdict": "replan_required",
            "eligibility": {
                "decision": "related",
                "reason": "workflow_related",
                "confidence": 0.9,
            },
            "skill_name": SKILL_NAME,
            "workflow_key": "grasp-tabletop-object",
            "pattern_key": "grasp-height-misestimate",
            "pattern_summary": "抓取位姿高于物体实际高度,导致闭合时未接触物体",
            "recovery_principle": "闭合夹爪前回到动作后观测核对 TCP 高度;失败时修正高度重试",
            "evidence": {
                "move_final_z_m": 0.250,
                "expected_grasp_z_m": 0.210,
                "object_grasped": False,
            },
        }

    @staticmethod
    def _skill_markdown() -> str:
        return (
            "---\n"
            f"name: {SKILL_NAME}\n"
            "description: \"抓取桌面物体的可复用工作流\"\n"
            "always: false\n"
            "metadata: {\"PhyAgentOS\":{\"always\":false,\"available\":true}}\n"
            "---\n\n"
            f"# {SKILL_NAME}\n\n"
            "<!-- PAOS:managed-skill-block:start -->\n"
            "1. Discover motion and gripper tools from Forge context.\n"
            "2. Resolve the relative TCP pose against the current robot state.\n"
            "3. Move to the verified grasp height with a narrow position tolerance.\n"
            "4. Close the gripper and verify the object is held from after-action evidence.\n"
            "5. If height evidence contradicts the plan, revise the height before retrying.\n"
            "<!-- PAOS:managed-skill-block:end -->\n"
        )

    @staticmethod
    def _lessons_markdown(lesson: dict[str, Any]) -> str:
        return (
            f"# Lessons for {SKILL_NAME}\n\n"
            f"## {lesson['lesson_id']}\n\n"
            f"- Status: {lesson['status']}\n"
            f"- Failure mode: {lesson['failure_mode']}\n"
            f"- Recommendation: {lesson['recommendation']}\n"
            f"- Observations: {lesson['observation_count']}\n"
        )

    @staticmethod
    def _write_tar(target: Path, source: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(target, "w:gz", format=tarfile.USTAR_FORMAT) as tar:
            for path in sorted(item for item in source.rglob("*") if item.is_file()):
                tar.add(path, arcname=path.relative_to(source).as_posix(), recursive=False)

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _sha256_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

