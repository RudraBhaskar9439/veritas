import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import create_async_engine

from change_support import MemorySnapshotObjects
from lineage_support import NOW
from packet_support import RecordingArtifactWriter, load_generation_request
from veritas_runtime.auth.database import metadata
from veritas_runtime.changes.database import SqlWatchRepository
from veritas_runtime.changes.models import EvidenceCapture
from veritas_runtime.changes.registration import ManifestEvidenceRegistrar
from veritas_runtime.changes.snapshots import ImmutableSnapshotService
from veritas_runtime.lineage.database import SqlImpactRepository, impact_reports
from veritas_runtime.lineage.service import (
    ImpactAnalysisService,
    ImpactIdempotencyConflict,
)
from veritas_runtime.packets.database import SqlManifestRepository, claim_manifests
from veritas_runtime.packets.generator import DecisionPacketGenerator


def test_sql_impact_repository_loads_owned_lineage_versions_and_checks_integrity() -> None:
    request_id, blueprint, sources = load_generation_request()

    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        manifests = SqlManifestRepository(engine)
        generated = await DecisionPacketGenerator(RecordingArtifactWriter(), manifests).generate(
            request_id, blueprint, sources, NOW
        )

        changes = SqlWatchRepository(engine)
        await ManifestEvidenceRegistrar(changes).register("subject-1", generated.manifest, NOW)
        stream = await changes.get_or_create_stream("subject-1", "page-1", NOW)
        objects = MemorySnapshotObjects()
        snapshot_service = ImmutableSnapshotService(objects)
        baseline_capture = EvidenceCapture(
            subject="subject-1",
            packet_id=blueprint.packet_id,
            source_id="src-churn",
            resource_id="demo-sheet",
            workspace_version="sheet-v1",
            mime_type="application/vnd.google-apps.spreadsheet",
            evidence={"Metrics!B17": 0.04},
        )
        baseline = (await snapshot_service.capture(baseline_capture, None, NOW)).snapshot
        await changes.commit_snapshots_and_cursor(
            stream.stream_id, "page-1", "page-2", (baseline,), NOW
        )
        changed_capture = baseline_capture.model_copy(
            update={"workspace_version": "sheet-v2", "evidence": {"Metrics!B17": 0.09}}
        )
        changed = (
            await snapshot_service.capture(changed_capture, baseline, NOW + timedelta(minutes=1))
        ).snapshot
        await changes.commit_snapshots_and_cursor(
            stream.stream_id,
            "page-2",
            "page-3",
            (changed,),
            NOW + timedelta(minutes=1),
        )

        repository = SqlImpactRepository(engine)
        async with engine.begin() as connection:
            await connection.execute(
                update(claim_manifests)
                .where(claim_manifests.c.manifest_id == generated.manifest.manifest_id)
                .values(checksum="0" * 64)
            )
        with pytest.raises(ValueError, match="Claim Manifest checksum mismatch"):
            await repository.load_context(
                "subject-1", blueprint.packet_id, (changed.snapshot_id,)
            )
        async with engine.begin() as connection:
            await connection.execute(
                update(claim_manifests)
                .where(claim_manifests.c.manifest_id == generated.manifest.manifest_id)
                .values(checksum=generated.checksum)
            )

        service = ImpactAnalysisService(repository)
        result = await service.analyze(
            "subject-1",
            blueprint.packet_id,
            "impact-request-1",
            (changed.snapshot_id,),
            NOW + timedelta(minutes=2),
        )
        replay = await service.analyze(
            "subject-1",
            blueprint.packet_id,
            "impact-request-1",
            (changed.snapshot_id,),
            NOW + timedelta(minutes=2),
        )
        assert result.report.version == 1
        assert replay.reused is True
        assert len(result.report.affected_claims) == 4
        assert len(result.report.affected_artifacts) == 5

        with pytest.raises(ImpactIdempotencyConflict, match="different lineage inputs"):
            await service.analyze(
                "subject-1",
                blueprint.packet_id,
                "impact-request-1",
                (baseline.snapshot_id,),
                NOW + timedelta(minutes=2),
            )
        with pytest.raises(PermissionError, match="does not own"):
            await repository.load_context(
                "other-subject", blueprint.packet_id, (changed.snapshot_id,)
            )

        async with engine.begin() as connection:
            await connection.execute(
                update(impact_reports)
                .where(impact_reports.c.report_id == result.report.report_id)
                .values(checksum="0" * 64)
            )
        with pytest.raises(ValueError, match="checksum mismatch"):
            await repository.get_by_idempotency_key(
                f"subject-1:{blueprint.packet_id}:impact-request-1"
            )
        await engine.dispose()

    asyncio.run(scenario())
