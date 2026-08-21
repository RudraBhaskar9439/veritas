import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from veritas_runtime.auth.database import metadata
from veritas_runtime.changes.database import evidence_snapshots
from veritas_runtime.changes.models import (
    DeltaKind,
    EvidenceCapture,
    EvidenceSnapshot,
    StoredSnapshotObject,
)
from veritas_runtime.changes.semantic import canonical_capture, semantic_hash
from veritas_runtime.lineage.database import impact_reports
from veritas_runtime.lineage.models import ImpactReport
from veritas_runtime.lineage.service import impact_checksum
from veritas_runtime.packets.database import claim_manifests
from veritas_runtime.packets.generator import manifest_checksum
from veritas_runtime.packets.models import ClaimManifest, ClaimRecord, SourceSnapshot
from veritas_runtime.repairs.models import (
    ApprovalActor,
    ApprovalDecision,
    ApprovalDecisionResult,
    ApprovalRecord,
    ApprovalStatus,
    RepairPlan,
    RepairPlanDraft,
)
from veritas_runtime.repairs.service import (
    ApprovalConflict,
    PersistedRepairPlan,
    RepairPlanIdempotencyConflict,
    RepairPlanningContext,
    repair_plan_checksum,
)

repair_plans = Table(
    "repair_plans",
    metadata,
    Column("plan_id", String(255), primary_key=True),
    Column("subject", String(255), nullable=False),
    Column("packet_id", String(255), nullable=False),
    Column("impact_report_id", String(255), nullable=False),
    Column("version", Integer, nullable=False),
    Column("idempotency_key", String(1024), nullable=False, unique=True),
    Column("input_digest", String(64), nullable=False),
    Column("checksum", String(64), nullable=False),
    Column("plan_json", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("subject", "packet_id", "version", name="repair_plans_version_uq"),
)
Index("repair_plans_packet_idx", repair_plans.c.subject, repair_plans.c.packet_id)

repair_approvals = Table(
    "repair_approvals",
    metadata,
    Column("approval_id", String(255), primary_key=True),
    Column("plan_id", String(255), ForeignKey("repair_plans.plan_id"), nullable=False),
    Column("claim_id", String(255), nullable=False),
    Column("status", String(32), nullable=False),
    Column("decided_by", String(255), nullable=True),
    Column("reason", Text, nullable=True),
    Column("decided_at", DateTime(timezone=True), nullable=True),
)
Index("repair_approvals_plan_idx", repair_approvals.c.plan_id)

repair_approval_events = Table(
    "repair_approval_events",
    metadata,
    Column("event_id", String(255), primary_key=True),
    Column("idempotency_key", String(1024), nullable=False, unique=True),
    Column("subject", String(255), nullable=False),
    Column("plan_id", String(255), ForeignKey("repair_plans.plan_id"), nullable=False),
    Column(
        "approval_id",
        String(255),
        ForeignKey("repair_approvals.approval_id"),
        nullable=False,
    ),
    Column("actor", String(255), nullable=False),
    Column("decision", String(32), nullable=False),
    Column("reason", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


class SnapshotContentReader(Protocol):
    async def read(self, snapshot: EvidenceSnapshot) -> bytes: ...


class SqlRepairRepository:
    def __init__(self, engine: AsyncEngine, content: SnapshotContentReader) -> None:
        self._engine = engine
        self._content = content

    async def load_context(
        self,
        subject: str,
        packet_id: str,
        impact_report_id: str,
    ) -> RepairPlanningContext:
        async with self._engine.connect() as connection:
            impact_row = (
                (
                    await connection.execute(
                        select(impact_reports).where(
                            impact_reports.c.subject == subject,
                            impact_reports.c.packet_id == packet_id,
                            impact_reports.c.report_id == impact_report_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if impact_row is None:
                raise LookupError("Impact report was not found")
            impact = _impact(impact_row)
            manifest_row = (
                (
                    await connection.execute(
                        select(claim_manifests).where(
                            claim_manifests.c.manifest_id == impact.manifest_id,
                            claim_manifests.c.packet_id == packet_id,
                            claim_manifests.c.version == impact.manifest_version,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if manifest_row is None:
                raise LookupError("Bound Claim Manifest was not found")
            manifest = _manifest(manifest_row)
            required_source_ids = {
                source_id
                for impacted in impact.affected_claims
                for source_id in _claim(manifest, impacted.claim_id).source_ids
            }
            snapshot_rows = (
                (
                    await connection.execute(
                        select(evidence_snapshots).where(
                            evidence_snapshots.c.subject == subject,
                            evidence_snapshots.c.packet_id == packet_id,
                            evidence_snapshots.c.source_id.in_(required_source_ids),
                        )
                    )
                )
                .mappings()
                .all()
            )
        selected = _select_causal_snapshots(impact, snapshot_rows, required_source_ids)
        source_records = {source.source_id: source for source in manifest.sources}
        sources: list[SourceSnapshot] = []
        snapshots: list[EvidenceSnapshot] = []
        for source_id in sorted(required_source_ids):
            snapshot = selected[source_id]
            record = source_records[source_id]
            payload = await self._content.read(snapshot)
            capture = _verified_capture(snapshot, payload)
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
                    source_id=source_id,
                    kind=record.kind,
                    resource_id=record.resource_id,
                    anchor=record.anchor,
                    version=snapshot.workspace_version,
                    value=value,
                )
            )
            snapshots.append(snapshot)
        return RepairPlanningContext(
            manifest=manifest,
            manifest_checksum=str(manifest_row["checksum"]),
            impact=impact,
            impact_checksum=str(impact_row["checksum"]),
            sources=tuple(sources),
            snapshot_metadata=tuple(snapshots),
        )

    async def get_by_idempotency_key(self, key: str) -> PersistedRepairPlan | None:
        async with self._engine.connect() as connection:
            row = await _plan_by_key(connection, key)
            if row is None:
                return None
            approvals = await _approval_rows(connection, str(row["plan_id"]))
        return _persisted_plan(row, approvals)

    async def persist(
        self,
        draft: RepairPlanDraft,
        idempotency_key: str,
        input_digest: str,
        now: datetime,
    ) -> PersistedRepairPlan:
        async with self._engine.begin() as connection:
            if self._engine.dialect.name == "postgresql":
                await connection.execute(
                    select(
                        func.pg_advisory_xact_lock(
                            func.hashtext(f"{draft.subject}:{draft.packet_id}")
                        )
                    )
                )
            existing = await _plan_by_key(connection, idempotency_key)
            if existing is not None:
                persisted = _persisted_plan(
                    existing,
                    await _approval_rows(connection, str(existing["plan_id"])),
                )
                if persisted.input_digest != input_digest:
                    raise RepairPlanIdempotencyConflict(
                        "Repair request ID was reused with different immutable inputs"
                    )
                return persisted
            current_version = await connection.scalar(
                select(func.max(repair_plans.c.version)).where(
                    repair_plans.c.subject == draft.subject,
                    repair_plans.c.packet_id == draft.packet_id,
                )
            )
            version = int(current_version or 0) + 1
            plan_id = f"plan-{uuid5(NAMESPACE_URL, idempotency_key)}"
            plan = RepairPlan(
                plan_id=plan_id,
                packet_id=draft.packet_id,
                impact_report_id=draft.impact_report_id,
                impact_report_checksum=draft.impact_report_checksum,
                manifest_id=draft.manifest_id,
                manifest_version=draft.manifest_version,
                version=version,
                created_at=now.astimezone(UTC),
                source_snapshot_ids=draft.source_snapshot_ids,
                steps=draft.steps,
                unchanged_impacted_claim_ids=draft.unchanged_impacted_claim_ids,
                approvals=draft.approvals,
                state=draft.state,
                policy_summary=draft.policy_summary,
            )
            checksum = repair_plan_checksum(plan)
            await connection.execute(
                insert(repair_plans).values(
                    plan_id=plan.plan_id,
                    subject=draft.subject,
                    packet_id=plan.packet_id,
                    impact_report_id=plan.impact_report_id,
                    version=version,
                    idempotency_key=idempotency_key,
                    input_digest=input_digest,
                    checksum=checksum,
                    plan_json=plan.model_dump_json(by_alias=True),
                    created_at=plan.created_at,
                )
            )
            approval_records = tuple(
                ApprovalRecord(
                    approval_id=requirement.approval_id,
                    plan_id=plan.plan_id,
                    claim_id=requirement.claim_id,
                    status=ApprovalStatus.PENDING,
                )
                for requirement in plan.approvals
            )
            for approval in approval_records:
                await connection.execute(
                    insert(repair_approvals).values(
                        approval_id=approval.approval_id,
                        plan_id=approval.plan_id,
                        claim_id=approval.claim_id,
                        status=approval.status.value,
                    )
                )
        return PersistedRepairPlan(plan, approval_records, checksum, input_digest)

    async def decide_approval(
        self,
        subject: str,
        actor: ApprovalActor,
        plan_id: str,
        approval_id: str,
        request_id: str,
        decision: ApprovalDecision,
        reason: str,
        now: datetime,
    ) -> ApprovalDecisionResult:
        idempotency_key = f"{subject}:{plan_id}:{approval_id}:{request_id}"
        async with self._engine.begin() as connection:
            event = (
                (
                    await connection.execute(
                        select(repair_approval_events).where(
                            repair_approval_events.c.idempotency_key == idempotency_key
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if event is not None:
                if (
                    event["actor"] != actor.principal
                    or event["decision"] != decision.value
                    or event["reason"] != reason
                ):
                    raise ApprovalConflict(
                        "Approval request ID was reused with a different decision"
                    )
                row = await _approval_row(connection, plan_id, approval_id, subject)
                if row is None:
                    raise LookupError("Approval requirement was not found")
                return ApprovalDecisionResult(approval=_approval(row), reused=True)
            row = await _approval_row(connection, plan_id, approval_id, subject)
            if row is None:
                raise LookupError("Approval requirement was not found")
            if row["status"] != ApprovalStatus.PENDING.value:
                raise ApprovalConflict("Approval requirement already has a terminal decision")
            status = (
                ApprovalStatus.APPROVED
                if decision == ApprovalDecision.APPROVE
                else ApprovalStatus.REJECTED
            )
            result = await connection.execute(
                update(repair_approvals)
                .where(
                    repair_approvals.c.approval_id == approval_id,
                    repair_approvals.c.plan_id == plan_id,
                    repair_approvals.c.status == ApprovalStatus.PENDING.value,
                )
                .values(
                    status=status.value,
                    decided_by=actor.principal,
                    reason=reason,
                    decided_at=now,
                )
            )
            if result.rowcount != 1:
                raise ApprovalConflict("Approval requirement was decided concurrently")
            await connection.execute(
                insert(repair_approval_events).values(
                    event_id=f"approval-event-{uuid5(NAMESPACE_URL, idempotency_key)}",
                    idempotency_key=idempotency_key,
                    subject=subject,
                    plan_id=plan_id,
                    approval_id=approval_id,
                    actor=actor.principal,
                    decision=decision.value,
                    reason=reason,
                    created_at=now,
                )
            )
            decided = await _approval_row(connection, plan_id, approval_id, subject)
        if decided is None:
            raise LookupError("Decided approval requirement was not found")
        return ApprovalDecisionResult(approval=_approval(decided), reused=False)


async def _plan_by_key(connection: AsyncConnection, key: str) -> RowMapping | None:
    return (
        (
            await connection.execute(
                select(repair_plans).where(repair_plans.c.idempotency_key == key)
            )
        )
        .mappings()
        .one_or_none()
    )


async def _approval_rows(connection: AsyncConnection, plan_id: str) -> tuple[RowMapping, ...]:
    return tuple(
        (
            await connection.execute(
                select(repair_approvals)
                .where(repair_approvals.c.plan_id == plan_id)
                .order_by(repair_approvals.c.approval_id)
            )
        )
        .mappings()
        .all()
    )


async def _approval_row(
    connection: AsyncConnection,
    plan_id: str,
    approval_id: str,
    subject: str,
) -> RowMapping | None:
    return (
        (
            await connection.execute(
                select(repair_approvals)
                .join(repair_plans, repair_plans.c.plan_id == repair_approvals.c.plan_id)
                .where(
                    repair_approvals.c.plan_id == plan_id,
                    repair_approvals.c.approval_id == approval_id,
                    repair_plans.c.subject == subject,
                )
            )
        )
        .mappings()
        .one_or_none()
    )


def _persisted_plan(row: RowMapping, approvals: tuple[RowMapping, ...]) -> PersistedRepairPlan:
    plan = RepairPlan.model_validate(json.loads(str(row["plan_json"])))
    checksum = str(row["checksum"])
    if repair_plan_checksum(plan) != checksum:
        raise ValueError("Stored repair plan checksum mismatch")
    return PersistedRepairPlan(
        plan=plan,
        approvals=tuple(_approval(item) for item in approvals),
        checksum=checksum,
        input_digest=str(row["input_digest"]),
    )


def _approval(row: RowMapping) -> ApprovalRecord:
    decided_at = row["decided_at"]
    if isinstance(decided_at, datetime) and decided_at.tzinfo is None:
        decided_at = decided_at.replace(tzinfo=UTC)
    return ApprovalRecord(
        approval_id=str(row["approval_id"]),
        plan_id=str(row["plan_id"]),
        claim_id=str(row["claim_id"]),
        status=ApprovalStatus(str(row["status"])),
        decided_by=str(row["decided_by"]) if row["decided_by"] is not None else None,
        reason=str(row["reason"]) if row["reason"] is not None else None,
        decided_at=decided_at if isinstance(decided_at, datetime) else None,
    )


def _impact(row: RowMapping) -> ImpactReport:
    impact = ImpactReport.model_validate(json.loads(str(row["report_json"])))
    if impact_checksum(impact) != str(row["checksum"]):
        raise ValueError("Stored impact report checksum mismatch")
    return impact


def _manifest(row: RowMapping) -> ClaimManifest:
    manifest = ClaimManifest.model_validate(json.loads(str(row["manifest_json"])))
    if manifest_checksum(manifest) != str(row["checksum"]):
        raise ValueError("Stored Claim Manifest checksum mismatch")
    return manifest


def _claim(manifest: ClaimManifest, claim_id: str) -> ClaimRecord:
    claim = next((item for item in manifest.claims if item.claim_id == claim_id), None)
    if claim is None:
        raise ValueError(f"Impact report references unknown claim {claim_id}")
    return claim


def _select_causal_snapshots(
    impact: ImpactReport,
    rows: Sequence[RowMapping],
    required_source_ids: set[str],
) -> dict[str, EvidenceSnapshot]:
    snapshots = tuple(_snapshot(row) for row in rows)
    by_id = {snapshot.snapshot_id: snapshot for snapshot in snapshots}
    try:
        changed = tuple(by_id[snapshot_id] for snapshot_id in impact.snapshot_ids)
    except KeyError as error:
        raise LookupError("An impact snapshot is no longer available") from error
    if len({snapshot.source_id for snapshot in changed}) != len(changed):
        raise ValueError("Impact report has ambiguous changed-source snapshots")
    cutoff = max(snapshot.created_at for snapshot in changed)
    selected = {snapshot.source_id: snapshot for snapshot in changed}
    for source_id in required_source_ids - set(selected):
        candidates = [
            snapshot
            for snapshot in snapshots
            if snapshot.source_id == source_id and snapshot.created_at <= cutoff
        ]
        if not candidates:
            raise LookupError(f"No causal immutable snapshot exists for source {source_id}")
        selected[source_id] = max(candidates, key=lambda item: item.created_at)
    return selected


def _verified_capture(snapshot: EvidenceSnapshot, payload: bytes) -> EvidenceCapture:
    if hashlib.sha256(payload).hexdigest() != snapshot.content_hash:
        raise ValueError("Immutable snapshot content hash mismatch")
    try:
        capture = EvidenceCapture.model_validate(json.loads(payload))
    except (json.JSONDecodeError, ValueError) as error:
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


def _snapshot(row: RowMapping) -> EvidenceSnapshot:
    created_at = row["created_at"]
    if not isinstance(created_at, datetime):
        raise TypeError("Evidence snapshot timestamp is invalid")
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
        created_at=(
            created_at.replace(tzinfo=UTC)
            if created_at.tzinfo is None
            else created_at.astimezone(UTC)
        ),
    )
