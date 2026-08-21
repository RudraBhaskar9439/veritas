import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import create_async_engine

from change_support import MemorySnapshotObjects
from packet_support import RecordingArtifactWriter, load_generation_request
from repair_support import NOW, MemorySnapshotReader
from veritas_runtime.auth.database import metadata
from veritas_runtime.changes.database import SqlWatchRepository
from veritas_runtime.changes.models import EvidenceCapture
from veritas_runtime.changes.registration import ManifestEvidenceRegistrar
from veritas_runtime.changes.snapshots import ImmutableSnapshotService
from veritas_runtime.lineage.database import SqlImpactRepository
from veritas_runtime.lineage.service import ImpactAnalysisService
from veritas_runtime.packets.database import SqlManifestRepository
from veritas_runtime.packets.generator import DecisionPacketGenerator
from veritas_runtime.repairs.database import SqlRepairRepository, repair_plans
from veritas_runtime.repairs.models import (
    ApprovalActor,
    ApprovalActorKind,
    ApprovalDecision,
    ApprovalStatus,
)
from veritas_runtime.repairs.service import RepairPlanningService


def test_sql_repair_repository_uses_causal_content_and_persists_audited_approvals() -> None:
    request_id, blueprint, sources = load_generation_request()

    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        generated = await DecisionPacketGenerator(
            RecordingArtifactWriter(), SqlManifestRepository(engine)
        ).generate(request_id, blueprint, sources, NOW)
        changes = SqlWatchRepository(engine)
        await ManifestEvidenceRegistrar(changes).register("subject-1", generated.manifest, NOW)
        stream = await changes.get_or_create_stream("subject-1", "page-1", NOW)
        objects = MemorySnapshotObjects()
        snapshots = ImmutableSnapshotService(objects)
        churn_capture = EvidenceCapture(
            subject="subject-1",
            packet_id=blueprint.packet_id,
            source_id="src-churn",
            resource_id="demo-sheet",
            workspace_version="sheet-v1",
            mime_type="application/vnd.google-apps.spreadsheet",
            evidence={"Metrics!B17": 0.04},
        )
        previous_capture = churn_capture.model_copy(
            update={
                "source_id": "src-churn-previous",
                "evidence": {"Metrics!B16": 0.06},
            }
        )
        churn_baseline = (await snapshots.capture(churn_capture, None, NOW)).snapshot
        previous_baseline = (await snapshots.capture(previous_capture, None, NOW)).snapshot
        await changes.commit_snapshots_and_cursor(
            stream.stream_id,
            "page-1",
            "page-2",
            (churn_baseline, previous_baseline),
            NOW,
        )
        changed_capture = churn_capture.model_copy(
            update={"workspace_version": "sheet-v2", "evidence": {"Metrics!B17": 0.09}}
        )
        churn_changed = (
            await snapshots.capture(changed_capture, churn_baseline, NOW + timedelta(minutes=1))
        ).snapshot
        await changes.commit_snapshots_and_cursor(
            stream.stream_id,
            "page-2",
            "page-3",
            (churn_changed,),
            NOW + timedelta(minutes=1),
        )
        impact = await ImpactAnalysisService(SqlImpactRepository(engine)).analyze(
            "subject-1",
            blueprint.packet_id,
            "impact-request-1",
            (churn_changed.snapshot_id,),
            NOW + timedelta(minutes=2),
        )
        repository = SqlRepairRepository(engine, MemorySnapshotReader(objects.objects))
        service = RepairPlanningService(repository)
        created = await service.create_plan(
            "subject-1",
            blueprint.packet_id,
            "repair-request-1",
            impact.report.report_id,
            NOW + timedelta(minutes=3),
        )
        replay = await service.create_plan(
            "subject-1",
            blueprint.packet_id,
            "repair-request-1",
            impact.report.report_id,
            NOW + timedelta(minutes=3),
        )
        assert created.reused is False
        assert replay.reused is True
        assert len(created.plan.steps) == 9
        assert len(created.approvals) == 2

        decision = await service.decide_approval(
            "subject-1",
            ApprovalActor(principal="human@example.test", kind=ApprovalActorKind.HUMAN),
            created.plan.plan_id,
            created.approvals[0].approval_id,
            "approval-request-1",
            ApprovalDecision.APPROVE,
            "Reviewed the changed recommendation and approved the repair.",
            NOW + timedelta(minutes=4),
        )
        decision_replay = await service.decide_approval(
            "subject-1",
            ApprovalActor(principal="human@example.test", kind=ApprovalActorKind.HUMAN),
            created.plan.plan_id,
            created.approvals[0].approval_id,
            "approval-request-1",
            ApprovalDecision.APPROVE,
            "Reviewed the changed recommendation and approved the repair.",
            NOW + timedelta(minutes=4),
        )
        assert decision.approval.status == ApprovalStatus.APPROVED
        assert decision_replay.reused is True

        async with engine.begin() as connection:
            await connection.execute(
                update(repair_plans)
                .where(repair_plans.c.plan_id == created.plan.plan_id)
                .values(checksum="0" * 64)
            )
        with pytest.raises(ValueError, match="repair plan checksum mismatch"):
            await repository.get_by_idempotency_key(
                f"subject-1:{blueprint.packet_id}:repair-request-1"
            )
        await engine.dispose()

    asyncio.run(scenario())
