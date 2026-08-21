import json
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    insert,
    select,
)
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from veritas_runtime.auth.database import metadata
from veritas_runtime.changes.database import (
    evidence_snapshots,
    registered_evidence_sources,
)
from veritas_runtime.changes.models import DeltaKind, EvidenceSnapshot, StoredSnapshotObject
from veritas_runtime.lineage.models import ImpactReport, ImpactReportDraft
from veritas_runtime.lineage.service import (
    ImpactIdempotencyConflict,
    LineageContext,
    PersistedImpact,
    impact_checksum,
)
from veritas_runtime.packets.database import claim_manifests
from veritas_runtime.packets.generator import manifest_checksum
from veritas_runtime.packets.models import ClaimManifest

impact_reports = Table(
    "impact_reports",
    metadata,
    Column("report_id", String(255), primary_key=True),
    Column("subject", String(255), nullable=False),
    Column("packet_id", String(255), nullable=False),
    Column("version", Integer, nullable=False),
    Column("idempotency_key", String(1024), nullable=False, unique=True),
    Column("input_digest", String(64), nullable=False),
    Column("checksum", String(64), nullable=False),
    Column("report_json", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("subject", "packet_id", "version", name="impact_reports_version_uq"),
)
Index("impact_reports_packet_idx", impact_reports.c.subject, impact_reports.c.packet_id)


class SqlImpactRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def load_context(
        self,
        subject: str,
        packet_id: str,
        snapshot_ids: tuple[str, ...],
    ) -> LineageContext:
        async with self._engine.connect() as connection:
            manifest_row = (
                (
                    await connection.execute(
                        select(claim_manifests)
                        .where(claim_manifests.c.packet_id == packet_id)
                        .order_by(claim_manifests.c.version.desc())
                        .limit(1)
                    )
                )
                .mappings()
                .one_or_none()
            )
            if manifest_row is None:
                raise LookupError("Claim Manifest was not found")
            manifest = ClaimManifest.model_validate(json.loads(manifest_row["manifest_json"]))
            if manifest_checksum(manifest) != manifest_row["checksum"]:
                raise ValueError("Stored Claim Manifest checksum mismatch")
            registrations = (
                (
                    await connection.execute(
                        select(registered_evidence_sources.c.source_id).where(
                            registered_evidence_sources.c.subject == subject,
                            registered_evidence_sources.c.packet_id == packet_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            if set(registrations) != {source.source_id for source in manifest.sources}:
                raise PermissionError(
                    "Workspace subject does not own the manifest's registered evidence"
                )
            if not snapshot_ids:
                raise LookupError("At least one evidence snapshot is required")
            rows = (
                (
                    await connection.execute(
                        select(evidence_snapshots).where(
                            evidence_snapshots.c.subject == subject,
                            evidence_snapshots.c.packet_id == packet_id,
                            evidence_snapshots.c.snapshot_id.in_(snapshot_ids),
                        )
                    )
                )
                .mappings()
                .all()
            )
        indexed = {str(row["snapshot_id"]): _snapshot(row) for row in rows}
        if len(indexed) != len(set(snapshot_ids)) or set(indexed) != set(snapshot_ids):
            raise LookupError("One or more evidence snapshots were not found")
        return LineageContext(
            manifest=manifest,
            snapshots=tuple(indexed[snapshot_id] for snapshot_id in snapshot_ids),
        )

    async def get_by_idempotency_key(self, key: str) -> PersistedImpact | None:
        async with self._engine.connect() as connection:
            row = await _select_by_key(connection, key)
        return _persisted(row) if row is not None else None

    async def persist(
        self,
        draft: ImpactReportDraft,
        idempotency_key: str,
        input_digest: str,
        now: datetime,
    ) -> PersistedImpact:
        async with self._engine.begin() as connection:
            if self._engine.dialect.name == "postgresql":
                await connection.execute(
                    select(
                        func.pg_advisory_xact_lock(
                            func.hashtext(f"{draft.subject}:{draft.packet_id}")
                        )
                    )
                )
            existing = await _select_by_key(connection, idempotency_key)
            if existing is not None:
                persisted = _persisted(existing)
                if persisted.input_digest != input_digest:
                    raise ImpactIdempotencyConflict(
                        "Impact request ID was reused with different lineage inputs"
                    )
                return persisted
            current_version = await connection.scalar(
                select(func.max(impact_reports.c.version)).where(
                    impact_reports.c.subject == draft.subject,
                    impact_reports.c.packet_id == draft.packet_id,
                )
            )
            version = int(current_version or 0) + 1
            report = ImpactReport(
                report_id=f"impact-{uuid5(NAMESPACE_URL, idempotency_key)}",
                packet_id=draft.packet_id,
                manifest_id=draft.manifest_id,
                manifest_version=draft.manifest_version,
                version=version,
                created_at=now.astimezone(UTC),
                snapshot_ids=draft.snapshot_ids,
                changed_source_ids=draft.changed_source_ids,
                affected_claims=draft.affected_claims,
                unaffected_registered_claim_ids=draft.unaffected_registered_claim_ids,
                candidate_claim_ids=draft.candidate_claim_ids,
                affected_artifacts=draft.affected_artifacts,
                lineage_paths=draft.lineage_paths,
                coverage=draft.coverage,
            )
            checksum = impact_checksum(report)
            await connection.execute(
                insert(impact_reports).values(
                    report_id=report.report_id,
                    subject=draft.subject,
                    packet_id=draft.packet_id,
                    version=version,
                    idempotency_key=idempotency_key,
                    input_digest=input_digest,
                    checksum=checksum,
                    report_json=report.model_dump_json(by_alias=True),
                    created_at=report.created_at,
                )
            )
        return PersistedImpact(report, checksum, input_digest)


async def _select_by_key(connection: AsyncConnection, key: str) -> RowMapping | None:
    return (
        (
            await connection.execute(
                select(impact_reports).where(impact_reports.c.idempotency_key == key)
            )
        )
        .mappings()
        .one_or_none()
    )


def _persisted(row: RowMapping) -> PersistedImpact:
    report = ImpactReport.model_validate(json.loads(row["report_json"]))
    checksum = str(row["checksum"])
    if impact_checksum(report) != checksum:
        raise ValueError("Stored impact report checksum mismatch")
    return PersistedImpact(
        report=report,
        checksum=checksum,
        input_digest=str(row["input_digest"]),
    )


def _snapshot(row: RowMapping) -> EvidenceSnapshot:
    created_at: datetime = row["created_at"]
    return EvidenceSnapshot(
        snapshot_id=row["snapshot_id"],
        subject=row["subject"],
        packet_id=row["packet_id"],
        source_id=row["source_id"],
        resource_id=row["resource_id"],
        workspace_version=row["workspace_version"],
        content_hash=row["content_hash"],
        semantic_hash=row["semantic_hash"],
        storage=StoredSnapshotObject(
            bucket=row["bucket"],
            object_name=row["object_name"],
            generation=row["object_generation"],
        ),
        delta_kind=DeltaKind(row["delta_kind"]),
        created_at=(
            created_at.replace(tzinfo=UTC)
            if created_at.tzinfo is None
            else created_at.astimezone(UTC)
        ),
    )
