from dataclasses import dataclass

from veritas_runtime.agents.models import AgentReview
from veritas_runtime.agents.service import GeminiConsequenceReviewService
from veritas_runtime.changes.models import DeltaKind, EvidenceSnapshot
from veritas_runtime.command_center.models import (
    CommandCenterApprovalRequest,
    CommandCenterApprovalResult,
    CommandCenterConflictRecoveryRequest,
)
from veritas_runtime.command_center.service import CommandCenterService
from veritas_runtime.execution.models import RepairRun, RepairRunStatus
from veritas_runtime.execution.service import RepairExecutionService
from veritas_runtime.lineage.models import ImpactReport
from veritas_runtime.lineage.service import ImpactAnalysisService
from veritas_runtime.operations.models import Operation
from veritas_runtime.repairs.models import ApprovalActor, RepairPlan
from veritas_runtime.repairs.service import RepairPlanningService
from veritas_runtime.verification.models import VerificationResult
from veritas_runtime.verification.service import VerificationService


@dataclass(frozen=True)
class OrchestrationOutcome:
    packet_id: str
    impact: ImpactReport
    plan: RepairPlan
    run: RepairRun
    verification: VerificationResult | None
    agent_review: AgentReview | None = None


class ConsequenceRepairOrchestrator:
    """Advances meaningful evidence changes through the autonomous repair lifecycle."""

    def __init__(
        self,
        impact: ImpactAnalysisService,
        repairs: RepairPlanningService,
        execution: RepairExecutionService,
        verification: VerificationService,
        agent_review: GeminiConsequenceReviewService | None = None,
    ) -> None:
        self._impact = impact
        self._repairs = repairs
        self._execution = execution
        self._verification = verification
        self._agent_review = agent_review

    async def process(
        self,
        operation: Operation,
        snapshots: tuple[EvidenceSnapshot, ...],
    ) -> tuple[OrchestrationOutcome, ...]:
        grouped: dict[str, list[EvidenceSnapshot]] = {}
        for snapshot in snapshots:
            if snapshot.delta_kind == DeltaKind.MEANINGFUL:
                grouped.setdefault(snapshot.packet_id, []).append(snapshot)
        outcomes: list[OrchestrationOutcome] = []
        for packet_id, packet_snapshots in sorted(grouped.items()):
            root = f"{operation.idempotency_key}:{packet_id}"
            impact = await self._impact.analyze(
                operation.subject,
                packet_id,
                f"{root}:impact",
                tuple(snapshot.snapshot_id for snapshot in packet_snapshots),
            )
            plan = await self._repairs.create_plan(
                operation.subject,
                packet_id,
                f"{root}:plan",
                impact.report.report_id,
            )
            review = (
                await self._agent_review.review(
                    operation.subject,
                    operation.operation_id,
                    impact.report,
                    plan.plan,
                )
                if self._agent_review is not None
                else None
            )
            run = await self._execution.execute(
                operation.subject,
                plan.plan.plan_id,
                f"{root}:execute",
            )
            verified = (
                await self._verification.verify(
                    operation.subject,
                    run.run_id,
                    f"{root}:verify",
                )
                if run.status == RepairRunStatus.COMPLETED
                else None
            )
            outcomes.append(
                OrchestrationOutcome(
                    packet_id,
                    impact.report,
                    plan.plan,
                    run,
                    verified,
                    review.review if review is not None else None,
                )
            )
        return tuple(outcomes)

    async def resume_and_verify(
        self,
        subject: str,
        run_id: str,
        request_id: str,
    ) -> tuple[RepairRun, VerificationResult | None]:
        run = await self._execution.resume(subject, run_id, request_id)
        verification = (
            await self._verification.verify(subject, run.run_id, f"{request_id}:verify")
            if run.status == RepairRunStatus.COMPLETED
            else None
        )
        return run, verification


class HumanApprovalContinuation:
    """Validates and advances the complete post-approval workflow idempotently."""

    def __init__(
        self,
        command_center: CommandCenterService,
        repairs: RepairPlanningService,
        orchestrator: ConsequenceRepairOrchestrator,
    ) -> None:
        self._command_center = command_center
        self._repairs = repairs
        self._orchestrator = orchestrator

    async def decide(
        self,
        subject: str,
        actor: ApprovalActor,
        plan_id: str,
        run_id: str,
        approval_id: str,
        request: CommandCenterApprovalRequest,
    ) -> CommandCenterApprovalResult:
        incident = await self._command_center.get(subject, plan_id)
        approval = next(
            (item for item in incident.approvals if item.approval_id == approval_id),
            None,
        )
        if incident.run_id != run_id or approval is None or approval.run_id != run_id:
            raise LookupError("Approval is not bound to this repair run")
        decision = await self._repairs.decide_approval(
            subject,
            actor,
            plan_id,
            approval_id,
            request.request_id,
            request.decision,
            request.reason,
        )
        run, verification = await self._orchestrator.resume_and_verify(
            subject,
            run_id,
            f"{request.request_id}:resume",
        )
        return CommandCenterApprovalResult(
            approval=decision,
            run=run,
            verification=verification,
        )


class ConflictRecoveryContinuation:
    """Starts a version-checked successor to a conflicted repair run."""

    def __init__(
        self,
        command_center: CommandCenterService,
        execution: RepairExecutionService,
    ) -> None:
        self._command_center = command_center
        self._execution = execution

    async def reconcile(
        self,
        subject: str,
        actor: ApprovalActor,
        plan_id: str,
        run_id: str,
        request: CommandCenterConflictRecoveryRequest,
    ) -> RepairRun:
        if actor.kind.value != "human":
            raise PermissionError("Conflict recovery requires an authenticated human")
        incident = await self._command_center.get(subject, plan_id)
        if incident.run_id != run_id:
            raise LookupError("Conflict recovery is not bound to this repair run")
        if incident.status.value != "attention":
            raise ValueError("The repair run does not require conflict recovery")
        return await self._execution.reconcile_conflict(
            subject,
            run_id,
            request.request_id,
            actor.principal,
            request.reason,
        )
