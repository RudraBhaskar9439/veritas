import asyncio
from datetime import UTC, datetime

import pytest

from change_support import MemorySnapshotObjects
from veritas_runtime.changes.models import DeltaKind, EvidenceCapture
from veritas_runtime.changes.semantic import InvalidEvidenceCapture, semantic_hash
from veritas_runtime.changes.snapshots import ImmutableSnapshotService, SnapshotIntegrityError

NOW = datetime(2026, 8, 21, 1, 0, tzinfo=UTC)


def _capture(
    *,
    version: str = "sheet-v1",
    churn: float = 0.04,
    presentation: dict[str, object] | None = None,
) -> EvidenceCapture:
    return EvidenceCapture.model_validate(
        {
            "subject": "workspace-user-1",
            "packetId": "packet-q3-executive-review",
            "sourceId": "src-churn",
            "resourceId": "drive-sheet-1",
            "workspaceVersion": version,
            "mimeType": "application/vnd.google-apps.spreadsheet",
            "evidence": {"Metrics!B17": churn, "Metrics!B16": "Churn"},
            "presentation": presentation or {"Metrics!B17": {"numberFormat": "0%"}},
        }
    )


def test_snapshots_distinguish_duplicate_cosmetic_and_meaningful_changes() -> None:
    objects = MemorySnapshotObjects()
    service = ImmutableSnapshotService(objects)

    async def scenario() -> None:
        baseline = await service.capture(_capture(), None, NOW)
        assert baseline.snapshot.delta_kind == DeltaKind.BASELINE
        assert "workspace-user-1" not in baseline.snapshot.storage.object_name
        assert "drive-sheet-1" not in baseline.snapshot.storage.object_name

        duplicate = await service.capture(_capture(), baseline.snapshot, NOW)
        assert duplicate.snapshot.delta_kind == DeltaKind.DUPLICATE
        assert duplicate.snapshot.snapshot_id == baseline.snapshot.snapshot_id

        cosmetic = await service.capture(
            _capture(version="sheet-v2", presentation={"Metrics!B17": {"fill": "blue"}}),
            baseline.snapshot,
            NOW,
        )
        assert cosmetic.snapshot.delta_kind == DeltaKind.COSMETIC
        assert cosmetic.snapshot.semantic_hash == baseline.snapshot.semantic_hash
        assert cosmetic.snapshot.content_hash != baseline.snapshot.content_hash

        meaningful = await service.capture(
            _capture(version="sheet-v3", churn=0.09), cosmetic.snapshot, NOW
        )
        assert meaningful.snapshot.delta_kind == DeltaKind.MEANINGFUL
        assert meaningful.snapshot.semantic_hash != cosmetic.snapshot.semantic_hash
        assert len(objects.objects) == 3

    asyncio.run(scenario())


def test_snapshot_lineage_and_noncanonical_numbers_fail_closed() -> None:
    service = ImmutableSnapshotService(MemorySnapshotObjects())

    async def scenario() -> None:
        baseline = await service.capture(_capture(), None, NOW)
        other = baseline.snapshot.model_copy(update={"source_id": "other-source"})
        with pytest.raises(SnapshotIntegrityError, match="different evidence"):
            await service.capture(_capture(), other, NOW)

    asyncio.run(scenario())

    invalid = _capture().model_copy(update={"evidence": {"Metrics!B17": float("nan")}})
    with pytest.raises(InvalidEvidenceCapture, match="finite"):
        semantic_hash(invalid)


def test_semantic_hash_normalizes_equivalent_unicode_and_numbers() -> None:
    composed = _capture().model_copy(update={"evidence": {"a": "café", "b": 1.0}})
    decomposed = _capture().model_copy(update={"evidence": {"b": 1, "a": "cafe\u0301"}})
    assert semantic_hash(composed) == semantic_hash(decomposed)
