import asyncio

import pytest

from repair_support import MemoryRepairRepository, canonical_repair_context
from veritas_runtime.repairs.models import (
    ApprovalActor,
    ApprovalActorKind,
    ApprovalDecision,
    ApprovalStatus,
    PolicyDisposition,
    RepairOperation,
    RepairPlanState,
)
from veritas_runtime.repairs.planner import RepairPlanningIntegrityError, TypedRepairPlanner
from veritas_runtime.repairs.service import (
    ApprovalConflict,
    RepairPlanIdempotencyConflict,
    RepairPlanningService,
)


def test_canonical_plan_is_minimal_typed_and_policy_checked() -> None:
    context = canonical_repair_context()
    draft = TypedRepairPlanner().plan(
        "subject-1",
        context.manifest,
        context.impact,
        context.impact_checksum,
        context.sources,
        context.snapshot_metadata,
    )
    assert len(draft.steps) == 9
    assert draft.state == RepairPlanState.AWAITING_APPROVAL
    assert draft.policy_summary.auto_execute_steps == 3
    assert draft.policy_summary.approval_required_steps == 4
    assert draft.policy_summary.draft_only_steps == 2
    assert draft.policy_summary.blocked_steps == 0
    assert {approval.claim_id for approval in draft.approvals} == {
        "claim-retention-target",
        "claim-scale-acquisition",
    }
    assert len(draft.approvals) == 2
    assert all(
        step.approval_id is not None
        for step in draft.steps
        if step.disposition == PolicyDisposition.REQUIRES_APPROVAL
    )
    correction_steps = [
        step for step in draft.steps if step.operation == RepairOperation.CREATE_CORRECTION_DRAFT
    ]
    assert len(correction_steps) == 2
    statements = {step.claim_id: step.proposed_statement for step in draft.steps}
    assert statements["claim-churn-value"] == "Q3 customer churn is 9%."
    assert statements["claim-churn-improved"] == "Customer churn worsened during Q3."
    assert statements["claim-retention-target"] == ("The retention target has not been achieved.")
    assert statements["claim-scale-acquisition"] == (
        "The company should pause the planned increase in acquisition spend."
    )
    assert all(step.base_revision_id for step in draft.steps)
    assert len({step.execution_key for step in draft.steps}) == 9


def test_planner_fails_closed_for_missing_snapshot_and_manifest_mismatch() -> None:
    context = canonical_repair_context()
    planner = TypedRepairPlanner()
    with pytest.raises(RepairPlanningIntegrityError, match="No immutable current snapshot"):
        planner.plan(
            "subject-1",
            context.manifest,
            context.impact,
            context.impact_checksum,
            context.sources[:1],
            context.snapshot_metadata[:1],
        )
    bad_impact = context.impact.model_copy(update={"manifest_id": "other-manifest"})
    with pytest.raises(RepairPlanningIntegrityError, match="does not bind"):
        planner.plan(
            "subject-1",
            context.manifest,
            bad_impact,
            context.impact_checksum,
            context.sources,
            context.snapshot_metadata,
        )


def test_plan_replay_and_human_approval_are_idempotent_and_separate() -> None:
    repository = MemoryRepairRepository()
    service = RepairPlanningService(repository)

    async def scenario() -> None:
        created = await service.create_plan(
            "subject-1",
            repository.context.manifest.packet_id,
            "repair-request-1",
            repository.context.impact.report_id,
        )
        replay = await service.create_plan(
            "subject-1",
            repository.context.manifest.packet_id,
            "repair-request-1",
            repository.context.impact.report_id,
        )
        assert created.reused is False
        assert replay.reused is True
        approval = created.approvals[0]
        with pytest.raises(PermissionError, match="authenticated human"):
            await service.decide_approval(
                "subject-1",
                ApprovalActor(principal="veritas-agent", kind=ApprovalActorKind.SERVICE),
                created.plan.plan_id,
                approval.approval_id,
                "approval-request-1",
                ApprovalDecision.APPROVE,
                "I reviewed the business consequence.",
            )
        decided = await service.decide_approval(
            "subject-1",
            ApprovalActor(principal="human@example.test", kind=ApprovalActorKind.HUMAN),
            created.plan.plan_id,
            approval.approval_id,
            "approval-request-1",
            ApprovalDecision.APPROVE,
            "I reviewed the business consequence.",
        )
        repeated = await service.decide_approval(
            "subject-1",
            ApprovalActor(principal="human@example.test", kind=ApprovalActorKind.HUMAN),
            created.plan.plan_id,
            approval.approval_id,
            "approval-request-1",
            ApprovalDecision.APPROVE,
            "I reviewed the business consequence.",
        )
        assert decided.approval.status == ApprovalStatus.APPROVED
        assert repeated.reused is True
        with pytest.raises(ApprovalConflict, match="different decision"):
            await service.decide_approval(
                "subject-1",
                ApprovalActor(principal="human@example.test", kind=ApprovalActorKind.HUMAN),
                created.plan.plan_id,
                approval.approval_id,
                "approval-request-1",
                ApprovalDecision.REJECT,
                "I reviewed the business consequence.",
            )

        source = repository.context.sources[0]
        repository.context = repository.context.__class__(
            manifest=repository.context.manifest,
            manifest_checksum=repository.context.manifest_checksum,
            impact=repository.context.impact,
            impact_checksum=repository.context.impact_checksum,
            sources=(source.model_copy(update={"value": 0.1}), *repository.context.sources[1:]),
            snapshot_metadata=repository.context.snapshot_metadata,
        )
        with pytest.raises(RepairPlanIdempotencyConflict, match="different immutable inputs"):
            await service.create_plan(
                "subject-1",
                repository.context.manifest.packet_id,
                "repair-request-1",
                repository.context.impact.report_id,
            )

    asyncio.run(scenario())
