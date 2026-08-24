import asyncio

from execution_support import (
    NOW,
    MemoryExecutionRepository,
    MemoryWorkspaceGateway,
    RecordingBaselineCapture,
    StaticWorkspaceSessions,
    plan_from_memory,
)
from repair_support import MemoryRepairRepository
from veritas_runtime.execution.models import RepairRunStatus, StepExecutionStatus
from veritas_runtime.execution.service import RepairExecutionService
from veritas_runtime.repairs.models import ApprovalActor, ApprovalActorKind, ApprovalDecision
from veritas_runtime.repairs.service import RepairPlanningService


def test_execution_resumes_after_approvals_without_repeating_completed_writes() -> None:
    repairs = MemoryRepairRepository()
    planning = RepairPlanningService(repairs)

    async def scenario() -> None:
        planned = await planning.create_plan(
            "subject-1",
            repairs.context.manifest.packet_id,
            "repair-request-1",
            repairs.context.impact.report_id,
            NOW,
        )
        repository = MemoryExecutionRepository(repairs)
        gateway = MemoryWorkspaceGateway(planned.plan.steps)
        human_paragraph = gateway.human_regions["artifact-board-memo"]
        baselines = RecordingBaselineCapture()
        execution = RepairExecutionService(
            repository, StaticWorkspaceSessions(), gateway, baselines
        )
        first = await execution.execute(
            "subject-1", planned.plan.plan_id, "execution-request-1", NOW
        )
        assert first.status == RepairRunStatus.AWAITING_APPROVAL
        assert len(baselines.calls) == 1
        assert len(gateway.apply_calls) == 5
        assert (
            sum(record.status == StepExecutionStatus.WAITING_APPROVAL for record in first.steps)
            == 4
        )

        actor = ApprovalActor(principal="human@example.test", kind=ApprovalActorKind.HUMAN)
        for index, approval in enumerate(planned.approvals):
            await planning.decide_approval(
                "subject-1",
                actor,
                planned.plan.plan_id,
                approval.approval_id,
                f"approval-request-{index}",
                ApprovalDecision.APPROVE,
                "Reviewed and approved the changed business decision.",
                NOW,
            )
        resumed = await execution.resume("subject-1", first.run_id, "resume-request-1", NOW)
        assert resumed.status == RepairRunStatus.COMPLETED
        assert len(baselines.calls) == 2
        assert resumed.reused is True
        assert len(gateway.apply_calls) == 9
        assert gateway.human_regions["artifact-board-memo"] == human_paragraph
        replay = await execution.execute(
            "subject-1", planned.plan.plan_id, "execution-request-1", NOW
        )
        assert replay.reused is True
        assert len(baselines.calls) == 2
        assert len(gateway.apply_calls) == 9

        plan, approvals = plan_from_memory(repairs)
        assert plan.plan_id == planned.plan.plan_id
        assert all(approval.status.value == "approved" for approval in approvals)

    asyncio.run(scenario())


def test_overlapping_human_edit_becomes_conflict_without_mutation() -> None:
    repairs = MemoryRepairRepository()
    planning = RepairPlanningService(repairs)

    async def scenario() -> None:
        planned = await planning.create_plan(
            "subject-1",
            repairs.context.manifest.packet_id,
            "repair-request-1",
            repairs.context.impact.report_id,
            NOW,
        )
        repository = MemoryExecutionRepository(repairs)
        gateway = MemoryWorkspaceGateway(planned.plan.steps)
        auto_step = next(
            step for step in planned.plan.steps if step.disposition.value == "auto_execute"
        )
        gateway.statements[(auto_step.resource_id, auto_step.anchor)] = (
            "The CFO rewrote this exact registered claim."
        )
        run = await RepairExecutionService(
            repository,
            StaticWorkspaceSessions(),
            gateway,
            RecordingBaselineCapture(),
        ).execute("subject-1", planned.plan.plan_id, "conflict-run", NOW)
        assert run.status == RepairRunStatus.CONFLICT
        conflict = next(record for record in run.steps if record.step_id == auto_step.step_id)
        assert conflict.status == StepExecutionStatus.CONFLICT
        assert auto_step.step_id not in gateway.apply_calls

    asyncio.run(scenario())
