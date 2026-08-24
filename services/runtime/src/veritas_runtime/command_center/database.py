import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncEngine

from veritas_runtime.agents.database import agent_reviews
from veritas_runtime.agents.models import AgentReview
from veritas_runtime.agents.service import agent_review_checksum
from veritas_runtime.changes.database import evidence_snapshots
from veritas_runtime.changes.models import DeltaKind, EvidenceSnapshot, StoredSnapshotObject
from veritas_runtime.command_center.service import CommandCenterRecord
from veritas_runtime.execution.database import SqlExecutionRepository, repair_runs
from veritas_runtime.lineage.database import impact_reports
from veritas_runtime.lineage.models import ImpactReport
from veritas_runtime.lineage.service import impact_checksum
from veritas_runtime.packets.database import claim_manifests
from veritas_runtime.packets.generator import manifest_checksum
from veritas_runtime.packets.models import ClaimManifest
from veritas_runtime.repairs.database import repair_approvals, repair_plans
from veritas_runtime.repairs.models import ApprovalRecord, ApprovalStatus, RepairPlan
from veritas_runtime.repairs.service import repair_plan_checksum
from veritas_runtime.verification.database import integrity_certificates, verification_reports
from veritas_runtime.verification.models import EvidenceIntegrityCertificate, VerificationReport
from veritas_runtime.verification.service import certificate_checksum, verification_report_checksum


class SqlCommandCenterRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._execution = SqlExecutionRepository(engine)

    async def latest(self, subject: str) -> CommandCenterRecord | None:
        return await self._load(subject, None)

    async def get(self, subject: str, plan_id: str) -> CommandCenterRecord | None:
        return await self._load(subject, plan_id)

    async def _load(self, subject: str, plan_id: str | None) -> CommandCenterRecord | None:
        async with self._engine.connect() as connection:
            plan_query = select(repair_plans).where(repair_plans.c.subject == subject)
            if plan_id is not None:
                plan_query = plan_query.where(repair_plans.c.plan_id == plan_id)
            plan_row = (
                (
                    await connection.execute(
                        plan_query.order_by(repair_plans.c.created_at.desc()).limit(1)
                    )
                )
                .mappings()
                .one_or_none()
            )
            if plan_row is None:
                return None
            plan = _plan(plan_row)
            manifest_row = (
                (
                    await connection.execute(
                        select(claim_manifests).where(
                            claim_manifests.c.manifest_id == plan.manifest_id
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            impact_row = (
                (
                    await connection.execute(
                        select(impact_reports).where(
                            impact_reports.c.subject == subject,
                            impact_reports.c.report_id == plan.impact_report_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if manifest_row is None or impact_row is None:
                raise ValueError("Command Center incident has an incomplete integrity chain")
            manifest = _manifest(manifest_row)
            impact = _impact(impact_row)
            approval_rows = (
                (
                    await connection.execute(
                        select(repair_approvals)
                        .where(repair_approvals.c.plan_id == plan.plan_id)
                        .order_by(repair_approvals.c.approval_id)
                    )
                )
                .mappings()
                .all()
            )
            run_row = (
                (
                    await connection.execute(
                        select(repair_runs)
                        .where(
                            repair_runs.c.subject == subject,
                            repair_runs.c.plan_id == plan.plan_id,
                        )
                        .order_by(repair_runs.c.updated_at.desc())
                        .limit(1)
                    )
                )
                .mappings()
                .one_or_none()
            )
            verification_row = None
            certificate_row = None
            if run_row is not None:
                verification_row = (
                    (
                        await connection.execute(
                            select(verification_reports)
                            .where(
                                verification_reports.c.subject == subject,
                                verification_reports.c.run_id == run_row["run_id"],
                            )
                            .order_by(verification_reports.c.created_at.desc())
                            .limit(1)
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if verification_row is not None:
                    certificate_row = (
                        (
                            await connection.execute(
                                select(integrity_certificates).where(
                                    integrity_certificates.c.subject == subject,
                                    integrity_certificates.c.report_id
                                    == verification_row["report_id"],
                                )
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
            snapshot_rows = (
                (
                    await connection.execute(
                        select(evidence_snapshots).where(
                            evidence_snapshots.c.subject == subject,
                            evidence_snapshots.c.packet_id == plan.packet_id,
                            evidence_snapshots.c.snapshot_id.in_(plan.source_snapshot_ids),
                        )
                    )
                )
                .mappings()
                .all()
            )
            agent_review_row = (
                (
                    await connection.execute(
                        select(agent_reviews)
                        .where(
                            agent_reviews.c.subject == subject,
                            agent_reviews.c.plan_id == plan.plan_id,
                        )
                        .order_by(agent_reviews.c.created_at.desc())
                        .limit(1)
                    )
                )
                .mappings()
                .one_or_none()
            )
        loaded_snapshots = tuple(_snapshot(row) for row in snapshot_rows)
        snapshots = {snapshot.snapshot_id: snapshot for snapshot in loaded_snapshots}
        if set(snapshots) != set(plan.source_snapshot_ids):
            raise ValueError("Command Center incident is missing causal evidence snapshots")
        run = (
            await self._execution.get_by_run_id(subject, str(run_row["run_id"]))
            if run_row is not None
            else None
        )
        return CommandCenterRecord(
            plan=plan,
            manifest=manifest,
            impact=impact,
            approvals=tuple(_approval(row) for row in approval_rows),
            run=run,
            verification=_verification(verification_row) if verification_row is not None else None,
            certificate=_certificate(certificate_row) if certificate_row is not None else None,
            snapshots=tuple(snapshots[snapshot_id] for snapshot_id in plan.source_snapshot_ids),
            agent_review=_agent_review(agent_review_row) if agent_review_row is not None else None,
        )


def _plan(row: RowMapping) -> RepairPlan:
    plan = RepairPlan.model_validate(json.loads(str(row["plan_json"])))
    if repair_plan_checksum(plan) != str(row["checksum"]):
        raise ValueError("Stored repair plan checksum mismatch")
    return plan


def _manifest(row: RowMapping) -> ClaimManifest:
    manifest = ClaimManifest.model_validate(json.loads(str(row["manifest_json"])))
    if manifest_checksum(manifest) != str(row["checksum"]):
        raise ValueError("Stored Claim Manifest checksum mismatch")
    return manifest


def _impact(row: RowMapping) -> ImpactReport:
    impact = ImpactReport.model_validate(json.loads(str(row["report_json"])))
    if impact_checksum(impact) != str(row["checksum"]):
        raise ValueError("Stored impact report checksum mismatch")
    return impact


def _approval(row: RowMapping) -> ApprovalRecord:
    decided_at = row["decided_at"]
    return ApprovalRecord(
        approval_id=str(row["approval_id"]),
        plan_id=str(row["plan_id"]),
        claim_id=str(row["claim_id"]),
        status=ApprovalStatus(str(row["status"])),
        decided_by=str(row["decided_by"]) if row["decided_by"] is not None else None,
        reason=str(row["reason"]) if row["reason"] is not None else None,
        decided_at=_timestamp(decided_at) if isinstance(decided_at, datetime) else None,
    )


def _verification(row: RowMapping) -> VerificationReport:
    report = VerificationReport.model_validate(json.loads(str(row["report_json"])))
    if verification_report_checksum(report) != str(row["checksum"]):
        raise ValueError("Stored verification report checksum mismatch")
    return report


def _certificate(row: RowMapping) -> EvidenceIntegrityCertificate:
    certificate = EvidenceIntegrityCertificate.model_validate(
        json.loads(str(row["certificate_json"]))
    )
    if certificate_checksum(certificate) != str(row["checksum"]):
        raise ValueError("Stored integrity certificate checksum mismatch")
    return certificate


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


def _agent_review(row: RowMapping) -> AgentReview:
    review = AgentReview.model_validate(json.loads(str(row["review_json"])))
    if agent_review_checksum(review) != str(row["checksum"]):
        raise ValueError("Stored Gemini agent review checksum mismatch")
    return review


def _timestamp(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("Stored Command Center timestamp is invalid")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
