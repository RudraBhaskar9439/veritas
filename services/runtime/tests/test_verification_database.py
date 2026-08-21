import asyncio
import hashlib
import json

import pytest
from sqlalchemy import insert, update
from sqlalchemy.ext.asyncio import create_async_engine

from change_support import MemorySnapshotObjects
from execution_support import StaticWorkspaceSessions
from repair_support import MemorySnapshotReader
from verification_support import (
    NOW,
    MemoryIndependentVerifier,
    MemoryVerificationRepository,
    canonical_verification_context,
)
from veritas_runtime.auth.database import metadata
from veritas_runtime.changes.database import evidence_snapshots
from veritas_runtime.changes.models import EvidenceCapture
from veritas_runtime.changes.snapshots import ImmutableSnapshotService
from veritas_runtime.execution.database import repair_run_steps, repair_runs
from veritas_runtime.packets.database import claim_manifests
from veritas_runtime.packets.generator import manifest_checksum
from veritas_runtime.repairs.database import repair_plans
from veritas_runtime.repairs.models import SourceVersionRef
from veritas_runtime.repairs.service import repair_plan_checksum
from veritas_runtime.verification.database import (
    SqlVerificationRepository,
    integrity_certificates,
    verification_reports,
)
from veritas_runtime.verification.service import VerificationService


def test_sql_verification_results_are_checksummed_and_certificate_bound() -> None:
    async def scenario() -> None:
        context = await canonical_verification_context()
        memory = MemoryVerificationRepository(context)
        result = await VerificationService(
            memory,
            StaticWorkspaceSessions(),
            MemoryIndependentVerifier(context),
        ).verify("subject-1", context.run.run_id, "verify-sql", NOW)
        assert result.certificate is not None

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        repository = SqlVerificationRepository(engine, MemorySnapshotReader({}))
        key = f"subject-1:{context.run.run_id}:verify-sql"
        stored = await repository.persist(
            "subject-1",
            result.report,
            result.certificate,
            key,
            "a" * 64,
        )
        replay = await repository.get_by_idempotency_key(key)
        assert replay == stored

        async with engine.begin() as connection:
            await connection.execute(
                update(integrity_certificates)
                .where(integrity_certificates.c.report_id == result.report.report_id)
                .values(checksum="0" * 64)
            )
        with pytest.raises(ValueError, match="certificate checksum mismatch"):
            await repository.get_by_idempotency_key(key)

        async with engine.begin() as connection:
            await connection.execute(
                update(integrity_certificates)
                .where(integrity_certificates.c.report_id == result.report.report_id)
                .values(checksum=stored.certificate_checksum)
            )
            await connection.execute(
                update(verification_reports)
                .where(verification_reports.c.report_id == result.report.report_id)
                .values(checksum="0" * 64)
            )
        with pytest.raises(ValueError, match="report checksum mismatch"):
            await repository.get_by_idempotency_key(key)
        await engine.dispose()

    asyncio.run(scenario())


def test_sql_repository_rebuilds_independent_context_from_immutable_records() -> None:
    async def scenario() -> None:
        original = await canonical_verification_context()
        objects = MemorySnapshotObjects()
        snapshot_service = ImmutableSnapshotService(objects)
        snapshots = []
        for source in original.sources:
            capture = EvidenceCapture(
                subject="subject-1",
                packet_id=original.manifest.packet_id,
                source_id=source.source_id,
                resource_id=source.resource_id,
                workspace_version=source.version,
                mime_type="application/vnd.google-apps.spreadsheet",
                evidence={source.anchor: source.value},
            )
            snapshots.append((await snapshot_service.capture(capture, None, NOW)).snapshot)
        snapshot_index = {snapshot.source_id: snapshot for snapshot in snapshots}
        steps = tuple(
            step.model_copy(
                update={
                    "source_versions": tuple(
                        SourceVersionRef(
                            source_id=source_ref.source_id,
                            snapshot_id=snapshot_index[source_ref.source_id].snapshot_id,
                            workspace_version=snapshot_index[
                                source_ref.source_id
                            ].workspace_version,
                            content_hash=snapshot_index[source_ref.source_id].content_hash,
                        )
                        for source_ref in step.source_versions
                    )
                }
            )
            for step in original.plan.steps
        )
        used_snapshot_ids = tuple(
            sorted({ref.snapshot_id for step in steps for ref in step.source_versions})
        )
        plan = original.plan.model_copy(
            update={"steps": steps, "source_snapshot_ids": used_snapshot_ids}
        )
        run = original.run.model_copy(update={"plan_id": plan.plan_id})

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
            await connection.execute(
                insert(claim_manifests).values(
                    manifest_id=original.manifest.manifest_id,
                    packet_id=original.manifest.packet_id,
                    version=original.manifest.version,
                    idempotency_key="manifest-key",
                    input_digest="1" * 64,
                    checksum=manifest_checksum(original.manifest),
                    manifest_json=original.manifest.model_dump_json(by_alias=True),
                    created_at=original.manifest.created_at,
                )
            )
            await connection.execute(
                insert(repair_plans).values(
                    plan_id=plan.plan_id,
                    subject="subject-1",
                    packet_id=plan.packet_id,
                    impact_report_id=plan.impact_report_id,
                    version=plan.version,
                    idempotency_key="plan-key",
                    input_digest="2" * 64,
                    checksum=repair_plan_checksum(plan),
                    plan_json=plan.model_dump_json(by_alias=True),
                    created_at=plan.created_at,
                )
            )
            await connection.execute(
                insert(repair_runs).values(
                    run_id=run.run_id,
                    subject="subject-1",
                    plan_id=run.plan_id,
                    packet_id=run.packet_id,
                    idempotency_key="run-key",
                    status=run.status.value,
                    created_at=run.created_at,
                    updated_at=run.updated_at,
                )
            )
            for record in run.steps:
                payload = record.model_dump_json(by_alias=True)
                checksum = hashlib.sha256(
                    json.dumps(
                        record.model_dump(mode="json", by_alias=True),
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode()
                ).hexdigest()
                await connection.execute(
                    insert(repair_run_steps).values(
                        run_id=run.run_id,
                        step_id=record.step_id,
                        status=record.status.value,
                        record_json=payload,
                        checksum=checksum,
                        updated_at=run.updated_at,
                    )
                )
            for snapshot in snapshots:
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
        repository = SqlVerificationRepository(engine, MemorySnapshotReader(objects.objects))
        await repository.persist_baselines("subject-1", original.baselines)
        loaded = await repository.load_context("subject-1", run.run_id)
        assert loaded.plan == plan
        assert loaded.run.run_id == run.run_id
        assert loaded.run.status == run.status
        assert {record.step_id for record in loaded.run.steps} == {
            record.step_id for record in run.steps
        }
        assert len(loaded.sources) == 6
        assert len(loaded.baselines) == 5

        result = await VerificationService(
            repository,
            StaticWorkspaceSessions(),
            MemoryIndependentVerifier(loaded),
        ).verify("subject-1", run.run_id, "verify-sql-e2e", NOW)
        assert result.certificate is not None
        replay = await repository.get_by_idempotency_key(f"subject-1:{run.run_id}:verify-sql-e2e")
        assert replay is not None
        assert replay.report_checksum == result.report_checksum
        await engine.dispose()

    asyncio.run(scenario())
