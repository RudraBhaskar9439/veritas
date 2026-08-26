import asyncio

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import insert, update
from sqlalchemy.ext.asyncio import create_async_engine

from repair_support import NOW, MemoryRepairRepository
from veritas_runtime.agents.database import agent_reviews
from veritas_runtime.agents.models import AgentDisposition, AgentReview
from veritas_runtime.agents.service import agent_review_checksum
from veritas_runtime.auth.database import metadata
from veritas_runtime.changes.database import evidence_snapshots
from veritas_runtime.command_center.database import SqlCommandCenterRepository
from veritas_runtime.command_center.models import CommandCenterApprovalRequest
from veritas_runtime.command_center.routes import create_command_center_router
from veritas_runtime.command_center.service import CommandCenterRecord, CommandCenterService
from veritas_runtime.execution.database import repair_runs
from veritas_runtime.execution.models import RepairRun, RepairRunStatus
from veritas_runtime.lineage.database import impact_reports
from veritas_runtime.lineage.service import impact_checksum
from veritas_runtime.orchestration import HumanApprovalContinuation
from veritas_runtime.packets.database import claim_manifests
from veritas_runtime.packets.generator import manifest_checksum
from veritas_runtime.repairs.database import repair_approvals, repair_plans
from veritas_runtime.repairs.models import (
    ApprovalActor,
    ApprovalActorKind,
    ApprovalDecision,
    ApprovalDecisionResult,
    ApprovalStatus,
)
from veritas_runtime.repairs.service import RepairPlanningService, repair_plan_checksum


class MemoryCommandCenterRepository:
    def __init__(self, record: CommandCenterRecord) -> None:
        self.record = record

    async def latest(self, subject: str) -> CommandCenterRecord | None:
        return self.record if subject == "subject-1" else None

    async def get(self, subject: str, plan_id: str) -> CommandCenterRecord | None:
        if subject == "subject-1" and plan_id == self.record.plan.plan_id:
            return self.record
        return None


class RecordingRepairDecisions:
    def __init__(self, approval) -> None:  # type: ignore[no-untyped-def]
        self.approval = approval
        self.calls: list[tuple[str, str, str]] = []

    async def decide_approval(
        self,
        subject,
        actor,
        plan_id,
        approval_id,
        request_id,
        decision,
        reason,
    ):  # type: ignore[no-untyped-def]
        assert actor.principal == "human@example.test"
        assert decision == ApprovalDecision.APPROVE
        assert reason
        self.calls.append((subject, plan_id, request_id))
        return ApprovalDecisionResult(
            approval=self.approval.model_copy(
                update={
                    "status": ApprovalStatus.APPROVED,
                    "decided_by": actor.principal,
                    "reason": reason,
                    "decided_at": NOW,
                }
            ),
            reused=False,
        )


class RecordingOrchestrator:
    def __init__(self, run: RepairRun) -> None:
        self.run = run
        self.calls: list[tuple[str, str, str]] = []

    async def resume_and_verify(self, subject: str, run_id: str, request_id: str):
        self.calls.append((subject, run_id, request_id))
        return self.run.model_copy(update={"status": RepairRunStatus.COMPLETED}), None


def _agent_review(plan_id: str, packet_id: str) -> AgentReview:
    return AgentReview(
        review_id="agent-review-command-center",
        operation_id="operation-command-center",
        plan_id=plan_id,
        packet_id=packet_id,
        model="gemini-2.5-flash",
        prompt_version="consequence-safety-review-v1",
        disposition=AgentDisposition.PROCEED,
        rationale="The registered scope and deterministic policy are internally coherent.",
        recognized_claim_ids=(
            "claim-acquisition-recommendation",
            "claim-churn-direction",
            "claim-churn-value",
            "claim-retention-target",
        ),
        risk_flags=("decision claims remain approval gated",),
        input_digest="a" * 64,
        created_at=NOW,
    )


async def _fixture():  # type: ignore[no-untyped-def]
    repairs = MemoryRepairRepository()
    planned = await RepairPlanningService(repairs).create_plan(
        "subject-1",
        repairs.context.manifest.packet_id,
        "command-center-plan",
        repairs.context.impact.report_id,
        NOW,
    )
    run = RepairRun(
        run_id="run-command-center",
        plan_id=planned.plan.plan_id,
        packet_id=planned.plan.packet_id,
        status=RepairRunStatus.AWAITING_APPROVAL,
        created_at=NOW,
        updated_at=NOW,
        steps=(),
    )
    record = CommandCenterRecord(
        plan=planned.plan,
        manifest=repairs.context.manifest,
        impact=repairs.context.impact,
        approvals=planned.approvals,
        run=run,
        verification=None,
        certificate=None,
        snapshots=repairs.context.snapshot_metadata,
        agent_review=_agent_review(planned.plan.plan_id, planned.plan.packet_id),
    )
    service = CommandCenterService(MemoryCommandCenterRepository(record))
    return service, planned, run


def test_live_read_model_is_derived_from_the_integrity_chain() -> None:
    async def scenario() -> None:
        service, planned, run = await _fixture()
        incident = await service.latest("subject-1")
        assert incident is not None
        assert incident.id == planned.plan.plan_id
        assert incident.run_id == run.run_id
        assert incident.status.value == "awaiting_approval"
        assert incident.source == "live"
        assert len(incident.claims) == 4
        assert len(incident.artifacts) == 5
        assert incident.coverage.targets == 13
        assert incident.certificate is None
        assert incident.agent_review is not None
        assert incident.agent_review.model == "gemini-2.5-flash"
        assert incident.approvals[0].run_id == run.run_id
        assert await service.latest("another-subject") is None
        with pytest.raises(LookupError, match="not found"):
            await service.get("subject-1", "missing-plan")

    asyncio.run(scenario())


def test_live_read_model_omits_semantically_unchanged_impacted_claims() -> None:
    async def scenario() -> None:
        service, planned, run = await _fixture()
        record = await service._repository.get(  # type: ignore[attr-defined]
            "subject-1", planned.plan.plan_id
        )
        assert record is not None
        unchanged_claim_id = record.plan.steps[0].claim_id
        remaining_steps = tuple(
            step for step in record.plan.steps if step.claim_id != unchanged_claim_id
        )
        assert remaining_steps
        remaining_artifact_ids = {step.artifact_id for step in remaining_steps}
        plan = record.plan.model_copy(
            update={
                "steps": remaining_steps,
                "unchanged_impacted_claim_ids": (
                    *record.plan.unchanged_impacted_claim_ids,
                    unchanged_claim_id,
                ),
                "approvals": tuple(
                    approval
                    for approval in record.plan.approvals
                    if approval.claim_id != unchanged_claim_id
                ),
            }
        )
        pruned_record = CommandCenterRecord(
            plan=plan,
            manifest=record.manifest,
            impact=record.impact,
            approvals=tuple(
                approval
                for approval in record.approvals
                if approval.claim_id != unchanged_claim_id
            ),
            run=run,
            verification=record.verification,
            certificate=record.certificate,
            snapshots=record.snapshots,
            agent_review=record.agent_review,
        )

        incident = await CommandCenterService(
            MemoryCommandCenterRepository(pruned_record)
        ).latest("subject-1")

        assert incident is not None
        assert unchanged_claim_id not in {claim.id for claim in incident.claims}
        assert {artifact.id for artifact in incident.artifacts} == remaining_artifact_ids
        assert incident.coverage.affected_claims == len({step.claim_id for step in remaining_steps})

    asyncio.run(scenario())


def test_approval_continuation_validates_binding_before_advancing() -> None:
    async def scenario() -> None:
        service, planned, run = await _fixture()
        approval = planned.approvals[0]
        repairs = RecordingRepairDecisions(approval)
        orchestrator = RecordingOrchestrator(run)
        continuation = HumanApprovalContinuation(service, repairs, orchestrator)  # type: ignore[arg-type]
        request = CommandCenterApprovalRequest(
            request_id="approve-and-continue",
            decision=ApprovalDecision.APPROVE,
            reason="I reviewed the complete registered blast radius.",
        )

        with pytest.raises(LookupError, match="not bound"):
            await continuation.decide(
                "subject-1",
                ApprovalActor(
                    principal="human@example.test",
                    kind=ApprovalActorKind.HUMAN,
                ),
                planned.plan.plan_id,
                "wrong-run",
                approval.approval_id,
                request,
            )
        assert repairs.calls == []

        result = await continuation.decide(
            "subject-1",
            ApprovalActor(
                principal="human@example.test",
                kind=ApprovalActorKind.HUMAN,
            ),
            planned.plan.plan_id,
            run.run_id,
            approval.approval_id,
            request,
        )
        assert result.approval.approval.status == ApprovalStatus.APPROVED
        assert result.run.status == RepairRunStatus.COMPLETED
        assert repairs.calls == [("subject-1", planned.plan.plan_id, "approve-and-continue")]
        assert orchestrator.calls == [("subject-1", run.run_id, "approve-and-continue:resume")]

    asyncio.run(scenario())


def test_command_center_routes_fail_closed_and_expose_atomic_approval_action() -> None:
    closed = FastAPI()
    closed.include_router(create_command_center_router(None, None))
    closed_client = TestClient(closed)
    assert closed_client.get("/api/v1/command-center/capabilities").json() == {
        "liveReadModel": False,
        "approvalContinuation": False,
    }
    assert (
        closed_client.post(
            "/api/v1/command-center/incidents/p/runs/r/approvals/a",
            json={
                "requestId": "request",
                "decision": "approve",
                "reason": "A sufficiently detailed approval reason.",
            },
        ).status_code
        == 503
    )

    async def subject_resolver(_request: Request) -> str:
        return "subject-1"

    async def actor_resolver(_request: Request) -> ApprovalActor:
        return ApprovalActor(
            principal="human@example.test",
            kind=ApprovalActorKind.HUMAN,
        )

    service, planned, run = asyncio.run(_fixture())
    repairs = RecordingRepairDecisions(planned.approvals[0])
    continuation = HumanApprovalContinuation(  # type: ignore[arg-type]
        service,
        repairs,
        RecordingOrchestrator(run),
    )
    app = FastAPI()
    app.include_router(
        create_command_center_router(
            service,
            subject_resolver,
            continuation,
            actor_resolver,
        )
    )
    client = TestClient(app)
    latest = client.get("/api/v1/command-center/incidents/latest")
    assert latest.status_code == 200
    approval = planned.approvals[0]
    response = client.post(
        f"/api/v1/command-center/incidents/{planned.plan.plan_id}"
        f"/runs/{run.run_id}/approvals/{approval.approval_id}",
        json={
            "requestId": "route-approval",
            "decision": "approve",
            "reason": "I reviewed the complete registered blast radius.",
        },
    )
    assert response.status_code == 200
    assert response.json()["run"]["status"] == "completed"


def test_sql_command_center_repository_rebuilds_a_subject_scoped_incident() -> None:
    async def scenario() -> None:
        service, planned, run = await _fixture()
        source_record = await service._repository.get(  # type: ignore[attr-defined]
            "subject-1", planned.plan.plan_id
        )
        assert source_record is not None
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
            await connection.execute(
                insert(claim_manifests).values(
                    manifest_id=source_record.manifest.manifest_id,
                    packet_id=source_record.manifest.packet_id,
                    version=source_record.manifest.version,
                    idempotency_key="command-center-manifest",
                    input_digest="1" * 64,
                    checksum=manifest_checksum(source_record.manifest),
                    manifest_json=source_record.manifest.model_dump_json(by_alias=True),
                    created_at=source_record.manifest.created_at,
                )
            )
            await connection.execute(
                insert(impact_reports).values(
                    report_id=source_record.impact.report_id,
                    subject="subject-1",
                    packet_id=source_record.impact.packet_id,
                    version=source_record.impact.version,
                    idempotency_key="command-center-impact",
                    input_digest="2" * 64,
                    checksum=impact_checksum(source_record.impact),
                    report_json=source_record.impact.model_dump_json(by_alias=True),
                    created_at=source_record.impact.created_at,
                )
            )
            await connection.execute(
                insert(repair_plans).values(
                    plan_id=planned.plan.plan_id,
                    subject="subject-1",
                    packet_id=planned.plan.packet_id,
                    impact_report_id=planned.plan.impact_report_id,
                    version=planned.plan.version,
                    idempotency_key="command-center-plan",
                    input_digest="3" * 64,
                    checksum=repair_plan_checksum(planned.plan),
                    plan_json=planned.plan.model_dump_json(by_alias=True),
                    created_at=planned.plan.created_at,
                )
            )
            for approval in planned.approvals:
                await connection.execute(
                    insert(repair_approvals).values(
                        approval_id=approval.approval_id,
                        plan_id=approval.plan_id,
                        claim_id=approval.claim_id,
                        status=approval.status.value,
                        decided_by=approval.decided_by,
                        reason=approval.reason,
                        decided_at=approval.decided_at,
                    )
                )
            await connection.execute(
                insert(repair_runs).values(
                    run_id=run.run_id,
                    subject="subject-1",
                    plan_id=run.plan_id,
                    packet_id=run.packet_id,
                    idempotency_key="command-center-run",
                    status=run.status.value,
                    created_at=run.created_at,
                    updated_at=run.updated_at,
                )
            )
            for snapshot in source_record.snapshots:
                await connection.execute(
                    insert(evidence_snapshots).values(
                        snapshot_id=snapshot.snapshot_id,
                        subject=snapshot.subject,
                        packet_id=snapshot.packet_id,
                        source_id=snapshot.source_id,
                        resource_id=snapshot.resource_id,
                        workspace_version=snapshot.workspace_version,
                        content_hash=snapshot.content_hash,
                        semantic_hash=snapshot.semantic_hash,
                        bucket=snapshot.storage.bucket,
                        object_name=snapshot.storage.object_name,
                        object_generation=snapshot.storage.generation,
                        delta_kind=snapshot.delta_kind.value,
                        created_at=snapshot.created_at,
                    )
                )
            review = source_record.agent_review
            assert review is not None
            await connection.execute(
                insert(agent_reviews).values(
                    review_id=review.review_id,
                    subject="subject-1",
                    operation_id=review.operation_id,
                    plan_id=review.plan_id,
                    packet_id=review.packet_id,
                    model=review.model,
                    prompt_version=review.prompt_version,
                    input_digest=review.input_digest,
                    checksum=agent_review_checksum(review),
                    review_json=review.model_dump_json(by_alias=True),
                    created_at=review.created_at,
                )
            )

        repository = SqlCommandCenterRepository(engine)
        loaded = await repository.latest("subject-1")
        assert loaded is not None
        assert loaded.plan == planned.plan
        assert loaded.run is not None
        assert loaded.run.run_id == run.run_id
        assert len(loaded.approvals) == 2
        assert loaded.agent_review == source_record.agent_review
        assert {snapshot.snapshot_id for snapshot in loaded.snapshots} == set(
            planned.plan.source_snapshot_ids
        )
        assert await repository.latest("another-subject") is None
        assert await repository.get("subject-1", "missing-plan") is None

        async with engine.begin() as connection:
            await connection.execute(
                update(repair_plans)
                .where(repair_plans.c.plan_id == planned.plan.plan_id)
                .values(checksum="0" * 64)
            )
        with pytest.raises(ValueError, match="repair plan checksum mismatch"):
            await repository.get("subject-1", planned.plan.plan_id)
        await engine.dispose()

    asyncio.run(scenario())
