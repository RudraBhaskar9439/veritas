import json
from datetime import UTC, datetime
from pathlib import Path

from veritas_runtime.changes.models import (
    DeltaKind,
    EvidenceSnapshot,
    StoredSnapshotObject,
)
from veritas_runtime.lineage.models import ImpactReport, ImpactReportDraft
from veritas_runtime.lineage.service import (
    ImpactIdempotencyConflict,
    LineageContext,
    PersistedImpact,
    impact_checksum,
)
from veritas_runtime.packets.models import ClaimManifest

ROOT = Path(__file__).parents[3]
NOW = datetime(2026, 8, 21, 2, 0, tzinfo=UTC)


def canonical_manifest() -> ClaimManifest:
    return ClaimManifest.model_validate(
        json.loads((ROOT / "fixtures/demo/q3-executive-review.json").read_text())
    )


def meaningful_snapshot(
    source_id: str = "src-churn",
    *,
    snapshot_id: str | None = None,
    subject: str = "subject-1",
    packet_id: str = "packet-q3-executive-review",
    delta_kind: DeltaKind = DeltaKind.MEANINGFUL,
) -> EvidenceSnapshot:
    resolved_id = snapshot_id or f"snapshot-{source_id}-changed"
    return EvidenceSnapshot(
        snapshot_id=resolved_id,
        subject=subject,
        packet_id=packet_id,
        source_id=source_id,
        resource_id="demo-sheet",
        workspace_version=f"version-{resolved_id}",
        content_hash="a" * 64,
        semantic_hash="b" * 64,
        storage=StoredSnapshotObject(
            bucket="snapshots",
            object_name=f"evidence/{resolved_id}.json",
            generation="1",
        ),
        delta_kind=delta_kind,
        created_at=NOW,
    )


class MemoryImpactRepository:
    def __init__(
        self,
        manifest: ClaimManifest | None = None,
        snapshots: tuple[EvidenceSnapshot, ...] | None = None,
    ) -> None:
        self.manifest = manifest or canonical_manifest()
        self.snapshots = {
            snapshot.snapshot_id: snapshot for snapshot in (snapshots or (meaningful_snapshot(),))
        }
        self.persisted: dict[str, PersistedImpact] = {}

    async def load_context(
        self,
        subject: str,
        packet_id: str,
        snapshot_ids: tuple[str, ...],
    ) -> LineageContext:
        if subject != "subject-1":
            raise PermissionError("denied")
        if packet_id != self.manifest.packet_id:
            raise LookupError("manifest not found")
        try:
            snapshots = tuple(self.snapshots[snapshot_id] for snapshot_id in snapshot_ids)
        except KeyError as error:
            raise LookupError("snapshot not found") from error
        return LineageContext(self.manifest, snapshots)

    async def get_by_idempotency_key(self, key: str) -> PersistedImpact | None:
        return self.persisted.get(key)

    async def persist(
        self,
        draft: ImpactReportDraft,
        idempotency_key: str,
        input_digest: str,
        now: datetime,
    ) -> PersistedImpact:
        existing = self.persisted.get(idempotency_key)
        if existing is not None:
            if existing.input_digest != input_digest:
                raise ImpactIdempotencyConflict("different lineage inputs")
            return existing
        report = ImpactReport(
            report_id=f"impact-{len(self.persisted) + 1}",
            packet_id=draft.packet_id,
            manifest_id=draft.manifest_id,
            manifest_version=draft.manifest_version,
            version=1 + len(self.persisted),
            created_at=now,
            snapshot_ids=draft.snapshot_ids,
            changed_source_ids=draft.changed_source_ids,
            affected_claims=draft.affected_claims,
            unaffected_registered_claim_ids=draft.unaffected_registered_claim_ids,
            candidate_claim_ids=draft.candidate_claim_ids,
            affected_artifacts=draft.affected_artifacts,
            lineage_paths=draft.lineage_paths,
            coverage=draft.coverage,
        )
        persisted = PersistedImpact(report, impact_checksum(report), input_digest)
        self.persisted[idempotency_key] = persisted
        return persisted
