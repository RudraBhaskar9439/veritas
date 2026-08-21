import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import create_async_engine

from execution_support import (
    NOW,
    MemoryWorkspaceGateway,
    RecordingBaselineCapture,
    StaticWorkspaceSessions,
)
from repair_support import MemoryRepairRepository
from veritas_runtime.auth.database import metadata
from veritas_runtime.execution.database import (
    SqlExecutionRepository,
    repair_run_step_events,
    repair_run_steps,
)
from veritas_runtime.execution.models import RepairRunStatus
from veritas_runtime.execution.routes import create_execution_router
from veritas_runtime.execution.service import RepairExecutionService
from veritas_runtime.repairs.database import repair_approvals, repair_plans
from veritas_runtime.repairs.models import (
    ApprovalActor,
    ApprovalActorKind,
    ApprovalDecision,
)
from veritas_runtime.repairs.service import RepairPlanningService, repair_plan_checksum


def test_sql_execution_journal_is_resumable_checksummed_and_append_only() -> None:
    async def scenario() -> None:
        repairs = MemoryRepairRepository()
        planning = RepairPlanningService(repairs)
        planned = await planning.create_plan(
            "subject-1",
            repairs.context.manifest.packet_id,
            "repair-request-1",
            repairs.context.impact.report_id,
            NOW,
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
        persisted = next(iter(repairs.plans.values()))
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
            await connection.execute(
                insert(repair_plans).values(
                    plan_id=persisted.plan.plan_id,
                    subject="subject-1",
                    packet_id=persisted.plan.packet_id,
                    impact_report_id=persisted.plan.impact_report_id,
                    version=persisted.plan.version,
                    idempotency_key="stored-plan-key",
                    input_digest="a" * 64,
                    checksum=repair_plan_checksum(persisted.plan),
                    plan_json=persisted.plan.model_dump_json(by_alias=True),
                    created_at=persisted.plan.created_at,
                )
            )
            for approval in persisted.approvals:
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
        repository = SqlExecutionRepository(engine)
        gateway = MemoryWorkspaceGateway(planned.plan.steps)
        service = RepairExecutionService(
            repository,
            StaticWorkspaceSessions(),
            gateway,
            RecordingBaselineCapture(),
        )
        completed = await service.execute(
            "subject-1", planned.plan.plan_id, "execution-request-1", NOW
        )
        replay = await service.execute(
            "subject-1", planned.plan.plan_id, "execution-request-1", NOW
        )
        assert completed.status == RepairRunStatus.COMPLETED
        assert replay.reused is True
        assert len(gateway.apply_calls) == 9
        async with engine.connect() as connection:
            events = await connection.scalar(
                select(func.count()).select_from(repair_run_step_events)
            )
        assert events == 9

        async with engine.begin() as connection:
            await connection.execute(
                update(repair_run_steps)
                .where(repair_run_steps.c.run_id == completed.run_id)
                .values(checksum="0" * 64)
            )
        with pytest.raises(ValueError, match="execution step checksum mismatch"):
            await repository.get_by_idempotency_key(
                f"subject-1:{planned.plan.plan_id}:execution-request-1"
            )
        await engine.dispose()

    asyncio.run(scenario())


def test_execution_route_is_fail_closed_without_a_workspace_session() -> None:
    app = FastAPI()
    app.include_router(create_execution_router(None, None))
    client = TestClient(app)
    assert client.get("/api/v1/execution/capabilities").json() == {"workspaceExecution": False}
    response = client.post(
        "/api/v1/repair-plans/plan-1/execute",
        json={"requestId": "execution-request-1"},
    )
    assert response.status_code == 503
