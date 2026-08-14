"""Task outcome source adapters for the experience subsystem."""

from __future__ import annotations

from typing import Protocol

from PhyAgentOS.agent.experience.contracts import LineageOutcome, TaskOutcomeEnvelope
from PhyAgentOS.agent.experience.redaction import opaque_ref, redact_text


class TaskOutcomeSource(Protocol):
    def build(self, task_ref: str) -> TaskOutcomeEnvelope: ...


class ForgeTaskOutcomeSource:
    """Build a redacted task-level outcome from one persisted Forge lineage."""

    def __init__(self, orchestrator) -> None:
        self.orchestrator = orchestrator

    def build(self, task_ref: str) -> TaskOutcomeEnvelope:
        terminal = self.orchestrator.get_session(task_ref)
        lineage = self.orchestrator.store.lineage(terminal.root_session_id)
        final = lineage[-1]
        final_verdict = final.verification.verdict
        criteria_statuses = (
            {item.criterion: item.status for item in final_verdict.criteria}
            if final_verdict is not None
            else {}
        )
        items: list[LineageOutcome] = []
        for record in lineage:
            verdict = record.verification.verdict
            refs: list[str] = []
            if verdict is not None:
                refs.extend(verdict.evidence_refs)
                for criterion in verdict.criteria:
                    refs.extend(criterion.evidence_refs)
            items.append(
                LineageOutcome(
                    session_ref=record.session_id,
                    action_semantics=record.request.action_type,
                    input_keys=sorted(record.request.inputs.keys()),
                    execution_status=(
                        record.execution.status if record.execution is not None else None
                    ),
                    semantic_verdict=verdict.verdict if verdict is not None else None,
                    reason=redact_text(verdict.reason) if verdict is not None else "",
                    verifier_lesson=(
                        redact_text(verdict.lesson) if verdict is not None else ""
                    ),
                    evidence_refs=list(
                        dict.fromkeys(opaque_ref(item) for item in refs)
                    ),
                )
            )
        contract = final.request.verification
        return TaskOutcomeEnvelope(
            task_id=final.session_id,
            root_task_id=final.root_session_id,
            goal=redact_text(contract.goal or final.request.task_description),
            success_criteria=[redact_text(item) for item in contract.success_criteria],
            final_verdict=final_verdict.verdict if final_verdict is not None else None,
            criteria_statuses={
                redact_text(criterion): status
                for criterion, status in criteria_statuses.items()
            },
            lineage=items,
            record_refs=[f"forge:{item.session_ref}" for item in items],
            completed_at=final.terminal_at or final.updated_at,
        )
