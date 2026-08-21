import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Table,
    Text,
    insert,
    select,
)
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncEngine

from veritas_runtime.auth.database import metadata
from veritas_runtime.changes.database import evidence_snapshots
from veritas_runtime.changes.models import (
    DeltaKind,
    EvidenceCapture,
    EvidenceSnapshot,
    StoredSnapshotObject,
)
from veritas_runtime.changes.semantic import canonical_capture, semantic_hash
from veritas_runtime.execution.database import SqlExecutionRepository, repair_runs
from veritas_runtime.packets.database import claim_manifests
from veritas_runtime.packets.generator import manifest_checksum
from veritas_runtime.packets.models import ClaimManifest, SourceSnapshot
from veritas_runtime.repairs.database import repair_plans
from veritas_runtime.repairs.models import RepairPlan
from veritas_runtime.repairs.service import repair_plan_checksum
from veritas_runtime.verification.models import (
    EvidenceIntegrityCertificate,
    ProtectedArtifactBaseline,
    VerificationReport,
)
from veritas_runtime.verification.service import (
    PersistedVerification,
    VerificationContext,
    VerificationIdempotencyConflict,
    certificate_checksum,
    verification_report_checksum,
)

artifact_protection_baselines = Table(
    "artifact_protection_baselines",
    metadata,
    Column("run_id", String(255), ForeignKey("repair_runs.run_id"), primary_key=True),
    Column("artifact_id", String(255), primary_key=True),
    Column("subject", String(255), nullable=False),
    Column("resource_id", String(255), nullable=False),
    Column("revision_id", String(255), nullable=False),
    Column("anchor_set_hash", String(64), nullable=False),
    Column("protected_content_hash", String(64), nullable=False),
    Column("baseline_json", Text, nullable=False),
    Column("checksum", String(64), nullable=False),
    Column("captured_at", DateTime(timezone=True), nullable=False),
)
Index(
    "artifact_protection_baselines_subject_run_idx",
    artifact_protection_baselines.c.subject,
    artifact_protection_baselines.c.run_id,
)

verification_reports = Table(
    "verification_reports",
    metadata,
    Column("report_id", String(255), primary_key=True),
    Column("subject", String(255), nullable=False),
    Column("run_id", String(255), ForeignKey("repair_runs.run_id"), nullable=False),
    Column("plan_id", String(255), ForeignKey("repair_plans.plan_id"), nullable=False),
    Column("packet_id", String(255), nullable=False),
    Column("idempotency_key", String(1024), nullable=False, unique=True),
    Column("input_digest", String(64), nullable=False),
    Column("status", String(32), nullable=False),
    Column("report_json", Text, nullable=False),
    Column("checksum", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index(
    "verification_reports_packet_idx",
    verification_reports.c.subject,
    verification_reports.c.packet_id,
)

integrity_certificates = Table(
    "integrity_certificates",
    metadata,
    Column("certificate_id", String(255), primary_key=True),
    Column(
        "report_id",
        String(255),
        ForeignKey("verification_reports.report_id"),
        nullable=False,
        unique=True,
    ),
    Column("subject", String(255), nullable=False),
    Column("packet_id", String(255), nullable=False),
    Column("certificate_json", Text, nullable=False),
    Column("checksum", String(64), nullable=False),
    Column("issued_at", DateTime(timezone=True), nullable=False),
)


class SnapshotContentReader(Protocol):
    async def read(self, snapshot: EvidenceSnapshot) -> bytes: ...


class SqlVerificationRepository:
    def __init__(self, engine: AsyncEngine, content: SnapshotContentReader) -> None:
        self._engine = engine
        self._content = content
        self._execution = SqlExecutionRepository(engine)

    async def load_context(self, subject: str, run_id: str) -> VerificationContext:
        run = await self._execution.get_by_run_id(subject, run_id)
        async with self._engine.connect() as connection:
            plan_row = (
                (
                    await connection.execute(
                        select(repair_plans).where(
                            repair_plans.c.plan_id == run.plan_id,
                            repair_plans.c.subject == subject,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if plan_row is None:
                raise LookupError("Repair plan was not found")
            plan = _plan(plan_row)
            manifest_row = (
                (
                    await connection.execute(
                        select(claim_manifests).where(
                            claim_manifests.c.manifest_id == plan.manifest_id,
                            claim_manifests.c.packet_id == plan.packet_id,
                            claim_manifests.c.version == plan.manifest_version,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if manifest_row is None:
                raise LookupError("Bound Claim Manifest was not found")
            manifest = _manifest(manifest_row)
            snapshot_rows = (
                (
                    await connection.execute(
                        select(evidence_snapshots).where(
                            evidence_snapshots.c.subject == subject,
                            evidence_snapshots.c.packet_id == plan.packet_id,
                            evidence_snapshots.c.source_id.in_(
                                source.source_id for source in manifest.sources
                            ),
                        )
                    )
                )
                .mappings()
                .all()
            )
            baseline_rows = (
                (
                    await connection.execute(
                        select(artifact_protection_baselines)
                        .where(
                            artifact_protection_baselines.c.subject == subject,
                            artifact_protection_baselines.c.run_id == run_id,
                        )
                        .order_by(artifact_protection_baselines.c.artifact_id)
                    )
                )
                .mappings()
                .all()
            )
        latest = _latest_snapshots(snapshot_rows, manifest)
        sources: list[SourceSnapshot] = []
        source_records = {source.source_id: source for source in manifest.sources}
        for snapshot in latest:
            capture = _verified_capture(snapshot, await self._content.read(snapshot))
            record = source_records[snapshot.source_id]
            try:
                value = capture.evidence[record.anchor]
            except KeyError as error:
                raise ValueError(
                    f"Immutable snapshot lacks registered anchor {record.anchor}"
                ) from error
            if isinstance(value, (dict, list)):
                raise ValueError(
                    f"Registered anchor {record.anchor} is not a scalar transformation input"
                )
            sources.append(
                SourceSnapshot(
                    source_id=record.source_id,
                    kind=record.kind,
                    resource_id=record.resource_id,
                    anchor=record.anchor,
                    version=snapshot.workspace_version,
                    value=value,
                )
            )
        return VerificationContext(
            manifest=manifest,
            plan=plan,
            run=run,
            sources=tuple(sources),
            snapshot_metadata=latest,
            baselines=tuple(_baseline(row) for row in baseline_rows),
        )

    async def get_by_idempotency_key(self, key: str) -> PersistedVerification | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        select(verification_reports).where(
                            verification_reports.c.idempotency_key == key
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            certificate_row = (
                (
                    await connection.execute(
                        select(integrity_certificates).where(
                            integrity_certificates.c.report_id == row["report_id"]
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _persisted(row, certificate_row)

    async def persist(
        self,
        subject: str,
        report: VerificationReport,
        certificate: EvidenceIntegrityCertificate | None,
        idempotency_key: str,
        input_digest: str,
    ) -> PersistedVerification:
        report_hash = verification_report_checksum(report)
        cert_hash = certificate_checksum(certificate) if certificate is not None else None
        async with self._engine.begin() as connection:
            existing = (
                (
                    await connection.execute(
                        select(verification_reports).where(
                            verification_reports.c.idempotency_key == idempotency_key
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                if existing["input_digest"] != input_digest:
                    raise VerificationIdempotencyConflict(
                        "Verification request ID was reused with different immutable inputs"
                    )
                certificate_row = (
                    (
                        await connection.execute(
                            select(integrity_certificates).where(
                                integrity_certificates.c.report_id == existing["report_id"]
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                return _persisted(existing, certificate_row)
            await connection.execute(
                insert(verification_reports).values(
                    report_id=report.report_id,
                    subject=subject,
                    run_id=report.run_id,
                    plan_id=report.plan_id,
                    packet_id=report.packet_id,
                    idempotency_key=idempotency_key,
                    input_digest=input_digest,
                    status=report.status.value,
                    report_json=report.model_dump_json(by_alias=True),
                    checksum=report_hash,
                    created_at=report.verified_at,
                )
            )
            if certificate is not None and cert_hash is not None:
                await connection.execute(
                    insert(integrity_certificates).values(
                        certificate_id=certificate.certificate_id,
                        report_id=certificate.report_id,
                        subject=subject,
                        packet_id=certificate.packet_id,
                        certificate_json=certificate.model_dump_json(by_alias=True),
                        checksum=cert_hash,
                        issued_at=certificate.issued_at,
                    )
                )
        return PersistedVerification(
            report=report,
            report_checksum=report_hash,
            certificate=certificate,
            certificate_checksum=cert_hash,
            input_digest=input_digest,
        )

    async def baselines_for_run(
        self, subject: str, run_id: str
    ) -> tuple[ProtectedArtifactBaseline, ...]:
        async with self._engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        select(artifact_protection_baselines)
                        .where(
                            artifact_protection_baselines.c.subject == subject,
                            artifact_protection_baselines.c.run_id == run_id,
                        )
                        .order_by(artifact_protection_baselines.c.artifact_id)
                    )
                )
                .mappings()
                .all()
            )
        return tuple(_baseline(row) for row in rows)

    async def persist_baselines(
        self,
        subject: str,
        baselines: tuple[ProtectedArtifactBaseline, ...],
    ) -> tuple[ProtectedArtifactBaseline, ...]:
        if not baselines:
            raise ValueError("At least one protected-region baseline is required")
        run_ids = {baseline.run_id for baseline in baselines}
        if len(run_ids) != 1:
            raise ValueError("Protected-region baselines must belong to one repair run")
        run_id = next(iter(run_ids))
        async with self._engine.begin() as connection:
            owner = await connection.scalar(
                select(repair_runs.c.subject).where(repair_runs.c.run_id == run_id)
            )
            if owner != subject:
                raise PermissionError("Protected-region baseline capture denied")
            existing_rows = (
                (
                    await connection.execute(
                        select(artifact_protection_baselines).where(
                            artifact_protection_baselines.c.run_id == run_id
                        )
                    )
                )
                .mappings()
                .all()
            )
            if existing_rows:
                existing = tuple(
                    sorted(
                        (_baseline(row) for row in existing_rows), key=lambda item: item.artifact_id
                    )
                )
                supplied = tuple(sorted(baselines, key=lambda item: item.artifact_id))
                if existing != supplied:
                    raise VerificationIdempotencyConflict(
                        "Protected-region baselines cannot be replaced"
                    )
                return existing
            for baseline in baselines:
                payload = baseline.model_dump_json(by_alias=True)
                await connection.execute(
                    insert(artifact_protection_baselines).values(
                        run_id=baseline.run_id,
                        artifact_id=baseline.artifact_id,
                        subject=subject,
                        resource_id=baseline.resource_id,
                        revision_id=baseline.revision_id,
                        anchor_set_hash=baseline.anchor_set_hash,
                        protected_content_hash=baseline.protected_content_hash,
                        baseline_json=payload,
                        checksum=_baseline_checksum(baseline),
                        captured_at=baseline.captured_at,
                    )
                )
        return baselines


def _persisted(row: RowMapping, certificate_row: RowMapping | None) -> PersistedVerification:
    report = VerificationReport.model_validate_json(str(row["report_json"]))
    report_hash = str(row["checksum"])
    if verification_report_checksum(report) != report_hash:
        raise ValueError("Stored verification report checksum mismatch")
    certificate = None
    cert_hash = None
    if certificate_row is not None:
        certificate = EvidenceIntegrityCertificate.model_validate_json(
            str(certificate_row["certificate_json"])
        )
        cert_hash = str(certificate_row["checksum"])
        if certificate_checksum(certificate) != cert_hash:
            raise ValueError("Stored integrity certificate checksum mismatch")
        if certificate.report_id != report.report_id or certificate.report_checksum != report_hash:
            raise ValueError("Stored integrity certificate does not bind to its report")
    if (report.status.value == "verified") != (certificate is not None):
        raise ValueError("Stored verification result has invalid certificate eligibility")
    return PersistedVerification(
        report=report,
        report_checksum=report_hash,
        certificate=certificate,
        certificate_checksum=cert_hash,
        input_digest=str(row["input_digest"]),
    )


def _baseline(row: RowMapping) -> ProtectedArtifactBaseline:
    baseline = ProtectedArtifactBaseline.model_validate_json(str(row["baseline_json"]))
    if _baseline_checksum(baseline) != str(row["checksum"]):
        raise ValueError("Stored protected-region baseline checksum mismatch")
    return baseline


def _baseline_checksum(baseline: ProtectedArtifactBaseline) -> str:
    return hashlib.sha256(
        json.dumps(
            baseline.model_dump(mode="json", by_alias=True),
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


def _plan(row: RowMapping) -> RepairPlan:
    plan = RepairPlan.model_validate_json(str(row["plan_json"]))
    if repair_plan_checksum(plan) != str(row["checksum"]):
        raise ValueError("Stored repair plan checksum mismatch")
    return plan


def _manifest(row: RowMapping) -> ClaimManifest:
    manifest = ClaimManifest.model_validate_json(str(row["manifest_json"]))
    if manifest_checksum(manifest) != str(row["checksum"]):
        raise ValueError("Stored Claim Manifest checksum mismatch")
    return manifest


def _latest_snapshots(
    rows: Sequence[RowMapping], manifest: ClaimManifest
) -> tuple[EvidenceSnapshot, ...]:
    latest: dict[str, EvidenceSnapshot] = {}
    for row in rows:
        snapshot = _snapshot(row)
        current = latest.get(snapshot.source_id)
        if current is None or snapshot.created_at > current.created_at:
            latest[snapshot.source_id] = snapshot
    required = {source.source_id for source in manifest.sources}
    if set(latest) != required:
        raise LookupError("A registered source has no immutable verification snapshot")
    return tuple(latest[source_id] for source_id in sorted(latest))


def _snapshot(row: RowMapping) -> EvidenceSnapshot:
    return EvidenceSnapshot(
        snapshot_id=str(row["snapshot_id"]),
        subject=str(row["subject"]),
        packet_id=str(row["packet_id"]),
        source_id=str(row["source_id"]),
        resource_id=str(row["resource_id"]),
        workspace_version=str(row["workspace_version"]),
        content_hash=str(row["content_hash"]),
        semantic_hash=str(row["semantic_hash"]),
        storage=StoredSnapshotObject(
            bucket=str(row["bucket"]),
            object_name=str(row["object_name"]),
            generation=str(row["object_generation"]),
        ),
        delta_kind=DeltaKind(str(row["delta_kind"])),
        created_at=_timestamp(row["created_at"]),
    )


def _verified_capture(snapshot: EvidenceSnapshot, payload: bytes) -> EvidenceCapture:
    if hashlib.sha256(payload).hexdigest() != snapshot.content_hash:
        raise ValueError("Immutable snapshot content hash mismatch")
    try:
        capture = EvidenceCapture.model_validate_json(payload)
    except ValueError as error:
        raise ValueError("Immutable snapshot content is invalid") from error
    if canonical_capture(capture) != payload or semantic_hash(capture) != snapshot.semantic_hash:
        raise ValueError("Immutable snapshot canonical or semantic hash mismatch")
    if (
        capture.subject != snapshot.subject
        or capture.packet_id != snapshot.packet_id
        or capture.source_id != snapshot.source_id
        or capture.resource_id != snapshot.resource_id
        or capture.workspace_version != snapshot.workspace_version
    ):
        raise ValueError("Immutable snapshot metadata does not match its content")
    return capture


def _timestamp(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("Stored verification timestamp is invalid")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
