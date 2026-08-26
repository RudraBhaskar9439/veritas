import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from veritas_runtime.agents.models import AgentReview
from veritas_runtime.changes.models import EvidenceSnapshot
from veritas_runtime.command_center.models import (
    CommandCenterAgentReview,
    CommandCenterApproval,
    CommandCenterArtifact,
    CommandCenterCertificate,
    CommandCenterCheck,
    CommandCenterClaim,
    CommandCenterCoverage,
    CommandCenterEvidence,
    CommandCenterIncident,
    CommandCenterTimelineEvent,
    IncidentStatus,
)
from veritas_runtime.execution.models import (
    RepairRun,
    RepairRunStatus,
    StepExecutionRecord,
    StepExecutionStatus,
)
from veritas_runtime.lineage.models import ImpactReport
from veritas_runtime.packets.models import (
    ArtifactKind,
    ClaimManifest,
    ClaimRisk,
    SourceKind,
)
from veritas_runtime.repairs.models import (
    ApprovalRecord,
    PolicyDisposition,
    RepairOperation,
    RepairPlan,
    RepairStep,
)
from veritas_runtime.verification.models import (
    EvidenceIntegrityCertificate,
    VerificationCheckStatus,
    VerificationReport,
)


@dataclass(frozen=True)
class CommandCenterRecord:
    plan: RepairPlan
    manifest: ClaimManifest
    impact: ImpactReport
    approvals: tuple[ApprovalRecord, ...]
    run: RepairRun | None
    verification: VerificationReport | None
    certificate: EvidenceIntegrityCertificate | None
    snapshots: tuple[EvidenceSnapshot, ...]
    agent_review: AgentReview | None = None


class CommandCenterRepository(Protocol):
    async def latest(self, subject: str) -> CommandCenterRecord | None: ...

    async def get(self, subject: str, plan_id: str) -> CommandCenterRecord | None: ...


class CommandCenterService:
    def __init__(self, repository: CommandCenterRepository) -> None:
        self._repository = repository

    async def latest(self, subject: str) -> CommandCenterIncident | None:
        record = await self._repository.latest(subject)
        return _incident(record) if record is not None else None

    async def get(self, subject: str, plan_id: str) -> CommandCenterIncident:
        record = await self._repository.get(subject, plan_id)
        if record is None:
            raise LookupError("Command Center incident was not found")
        return _incident(record)


def _incident(record: CommandCenterRecord) -> CommandCenterIncident:
    plan = record.plan
    manifest = record.manifest
    run = record.run
    verification = record.verification
    claim_index = {claim.claim_id: claim for claim in manifest.claims}
    source_index = {source.source_id: source for source in manifest.sources}
    step_records = {step.step_id: step for step in run.steps} if run is not None else {}

    claims: list[CommandCenterClaim] = []
    for impact_claim in record.impact.affected_claims:
        claim = claim_index[impact_claim.claim_id]
        steps = tuple(step for step in plan.steps if step.claim_id == claim.claim_id)
        # Lineage deliberately includes every registered claim that depends on the
        # changed source. A typed plan, however, omits claims whose rendered
        # statement is still semantically unchanged. Keep that valid in-flight
        # state visible without pretending a repair exists for it.
        if not steps:
            continue
        representative = steps[0]
        dispositions = {step.disposition for step in steps}
        claims.append(
            CommandCenterClaim(
                id=claim.claim_id,
                short_label=_title(claim.claim_id),
                before=representative.before_statement,
                after=representative.proposed_statement,
                transformation=(
                    f"{claim.transformation.name}@{claim.transformation.version}"
                    if claim.transformation is not None
                    else "manual"
                ),
                evidence=" · ".join(
                    f"{source_index[ref.source_id].anchor} · {ref.workspace_version}"
                    for ref in representative.source_versions
                ),
                policy=_policy_label(dispositions),
                risk="decision" if claim.risk == ClaimRisk.DECISION_CHANGING else "reversible",
                risk_label=(
                    "Decision-changing"
                    if claim.risk == ClaimRisk.DECISION_CHANGING
                    else "Reversible fact"
                ),
                target_count=len(claim.artifact_anchors),
            )
        )

    artifacts: list[CommandCenterArtifact] = []
    for impact_artifact in record.impact.affected_artifacts:
        steps = tuple(
            step for step in plan.steps if step.artifact_id == impact_artifact.artifact_id
        )
        if not steps:
            continue
        artifact = next(
            item for item in manifest.artifacts if item.artifact_id == impact_artifact.artifact_id
        )
        artifacts.append(
            CommandCenterArtifact(
                id=artifact.artifact_id,
                code=_artifact_code(artifact.kind),
                surface=_artifact_surface(artifact.kind),
                name=_title(artifact.artifact_id),
                target_count=len(steps),
                action=_artifact_action(steps),
                guardrail=_guardrail(artifact.kind, steps),
                result=_artifact_result(steps, step_records),
            )
        )

    registered_claims = tuple(
        claim for claim in manifest.claims if claim.provenance.value == "registered"
    )
    registered_targets = sum(len(claim.artifact_anchors) for claim in registered_claims)
    coverage = verification.coverage if verification is not None else None
    status = (
        IncidentStatus.ATTENTION
        if record.agent_review is not None and record.agent_review.disposition.value == "escalate"
        else _status(run, verification)
    )
    changed_source_ids = set(record.impact.changed_source_ids)
    changed_snapshots = tuple(
        snapshot for snapshot in record.snapshots if snapshot.source_id in changed_source_ids
    )
    detected_at = min(
        (snapshot.created_at for snapshot in changed_snapshots),
        default=record.impact.created_at,
    )
    updated_at = (
        record.certificate.issued_at
        if record.certificate is not None
        else verification.verified_at
        if verification is not None
        else run.updated_at
        if run is not None
        else plan.created_at
    )
    return CommandCenterIncident(
        id=plan.plan_id,
        packet_id=plan.packet_id,
        run_id=run.run_id if run is not None else None,
        status=status,
        headline=_headline(len(claims), len(artifacts), status),
        summary=_summary(record, status),
        detected_at=detected_at,
        updated_at=updated_at,
        claims=tuple(claims),
        artifacts=tuple(artifacts),
        timeline=_timeline(record, detected_at),
        coverage=CommandCenterCoverage(
            claims=len(registered_claims),
            affected_claims=len(claims),
            targets=registered_targets,
            verified_targets=coverage.verified_registered_targets if coverage else 0,
            protected_artifacts=(
                coverage.protected_artifacts if coverage else len(record.impact.affected_artifacts)
            ),
            verified_protected_artifacts=(coverage.verified_protected_artifacts if coverage else 0),
            sources=len(manifest.sources),
            lineage_paths=len(record.impact.lineage_paths),
        ),
        certificate=(
            CommandCenterCertificate(
                short_id=_short(record.certificate.certificate_id),
                statement=record.certificate.statement,
                issued_at=record.certificate.issued_at,
            )
            if record.certificate is not None
            else None
        ),
        checks=tuple(
            CommandCenterCheck(
                label=_title(check.kind.value),
                detail=check.detail,
                receipt=_receipt(check.check_id, check.detail),
                passed=check.status == VerificationCheckStatus.PASSED,
            )
            for check in (verification.checks if verification is not None else ())
        ),
        evidence=tuple(
            CommandCenterEvidence(
                id=source.source_id,
                label=_title(source.source_id),
                kind=_source_surface(source.kind),
                anchor=source.anchor,
                version=snapshot.workspace_version,
                snapshot=_short(snapshot.snapshot_id),
                snapshot_id=snapshot.snapshot_id,
                content_hash=snapshot.content_hash,
                captured_at=snapshot.created_at,
                changed=source.source_id in changed_source_ids,
                current=verification is not None,
            )
            for snapshot in record.snapshots
            for source in (source_index[snapshot.source_id],)
        ),
        approvals=tuple(
            CommandCenterApproval(
                approval_id=approval.approval_id,
                plan_id=approval.plan_id,
                run_id=run.run_id if run is not None else None,
                claim_id=approval.claim_id,
                claim_label=_title(approval.claim_id),
                status=approval.status,
                reason=approval.reason,
            )
            for approval in record.approvals
        ),
        agent_review=(
            CommandCenterAgentReview(
                model=record.agent_review.model,
                disposition=record.agent_review.disposition,
                rationale=record.agent_review.rationale,
                risk_flags=record.agent_review.risk_flags,
                receipt=_receipt(
                    record.agent_review.review_id,
                    record.agent_review.input_digest,
                ),
            )
            if record.agent_review is not None
            else None
        ),
    )


def _status(run: RepairRun | None, verification: VerificationReport | None) -> IncidentStatus:
    if verification is not None and verification.status.value == "verified":
        return IncidentStatus.VERIFIED
    if run is None or run.status == RepairRunStatus.RUNNING:
        return IncidentStatus.REPAIRING
    if run.status == RepairRunStatus.AWAITING_APPROVAL:
        return IncidentStatus.AWAITING_APPROVAL
    if run.status == RepairRunStatus.COMPLETED:
        return IncidentStatus.REPAIRING
    return IncidentStatus.ATTENTION


def _timeline(
    record: CommandCenterRecord, detected_at: datetime
) -> tuple[CommandCenterTimelineEvent, ...]:
    events = [
        CommandCenterTimelineEvent(
            time=_clock(detected_at),
            occurred_at=detected_at,
            label="Detected",
            detail="Meaningful evidence delta accepted",
            receipt=_timeline_receipt(
                "detected",
                *(f"{item.snapshot_id}:{item.content_hash}" for item in record.snapshots),
            ),
        ),
        CommandCenterTimelineEvent(
            time=_clock(record.impact.created_at),
            occurred_at=record.impact.created_at,
            label="Traced",
            detail=f"{len(record.impact.lineage_paths)} registered lineage paths",
            receipt=_timeline_receipt("traced", record.impact.report_id),
        ),
        CommandCenterTimelineEvent(
            time=_clock(record.plan.created_at),
            occurred_at=record.plan.created_at,
            label="Planned",
            detail=f"{len(record.plan.steps)} typed repair steps",
            receipt=_timeline_receipt("planned", record.plan.plan_id),
        ),
    ]
    decided = tuple(item.decided_at for item in record.approvals if item.decided_at is not None)
    if decided:
        events.append(
            CommandCenterTimelineEvent(
                time=_clock(max(decided)),
                occurred_at=max(decided),
                label="Decided",
                detail=f"{len(decided)} human approval decisions",
                receipt=_timeline_receipt(
                    "decided",
                    *(
                        f"{item.approval_id}:{item.status.value}:{item.decided_at.isoformat()}"
                        for item in record.approvals
                        if item.decided_at is not None
                    ),
                ),
            )
        )
    if record.run is not None:
        events.append(
            CommandCenterTimelineEvent(
                time=_clock(record.run.updated_at),
                occurred_at=record.run.updated_at,
                label="Repaired",
                detail=f"Run {record.run.status.value.replace('_', ' ')}",
                receipt=_timeline_receipt("repaired", record.run.run_id, record.run.status.value),
            )
        )
    if record.verification is not None:
        events.append(
            CommandCenterTimelineEvent(
                time=_clock(record.verification.verified_at),
                occurred_at=record.verification.verified_at,
                label="Verified",
                detail=f"{len(record.verification.checks)} independent checks",
                receipt=_timeline_receipt(
                    "verified",
                    record.verification.report_id,
                    *(item.check_id for item in record.verification.checks),
                ),
            )
        )
    if record.certificate is not None:
        events.append(
            CommandCenterTimelineEvent(
                time=_clock(record.certificate.issued_at),
                occurred_at=record.certificate.issued_at,
                label="Certified",
                detail="Scoped integrity record issued",
                receipt=_timeline_receipt(
                    "certified",
                    record.certificate.certificate_id,
                    record.certificate.report_checksum,
                ),
            )
        )
    return tuple(events)


def _policy_label(dispositions: set[PolicyDisposition]) -> str:
    if PolicyDisposition.REQUIRES_APPROVAL in dispositions:
        return "Human approval required"
    if PolicyDisposition.DRAFT_ONLY in dispositions:
        return "Draft-only correction"
    if PolicyDisposition.BLOCKED in dispositions:
        return "Blocked by policy"
    return "Auto-execute"


def _artifact_action(steps: tuple[RepairStep, ...]) -> str:
    operations = {step.operation for step in steps}
    if RepairOperation.CREATE_CORRECTION_DRAFT in operations:
        return f"Create {len(steps)} unsent correction draft(s)"
    if RepairOperation.UPDATE_TASK in operations:
        return f"Update {len(steps)} task title and registered decision note(s)"
    return f"Replace {len(steps)} registered claim anchor(s)"


def _guardrail(kind: ArtifactKind, steps: tuple[RepairStep, ...]) -> str:
    dispositions = {step.disposition for step in steps}
    if kind == ArtifactKind.GMAIL:
        return "immutable original"
    if PolicyDisposition.REQUIRES_APPROVAL in dispositions:
        return "human approved"
    if kind == ArtifactKind.GOOGLE_TASK:
        return "If-Match ETag"
    return "requiredRevisionId"


def _artifact_result(
    steps: tuple[RepairStep, ...], records: Mapping[str, StepExecutionRecord]
) -> str:
    statuses = {
        record.status if (record := records.get(step.step_id)) is not None else None
        for step in steps
    }
    if not records:
        return "planned"
    if StepExecutionStatus.WAITING_APPROVAL in statuses:
        return "awaiting approval"
    if StepExecutionStatus.CONFLICT in statuses or StepExecutionStatus.FAILED in statuses:
        return "attention required"
    operations = {step.operation for step in steps}
    if RepairOperation.CREATE_CORRECTION_DRAFT in operations:
        return "drafted"
    if RepairOperation.UPDATE_TASK in operations:
        return "updated"
    return "repaired"


def _headline(claims: int, artifacts: int, status: IncidentStatus) -> str:
    action = "repaired" if status == IncidentStatus.VERIFIED else "traced"
    return f"{claims} claims changed. {artifacts} consequences {action}."


def _summary(record: CommandCenterRecord, status: IncidentStatus) -> str:
    if status == IncidentStatus.AWAITING_APPROVAL:
        pending = sum(item.status.value == "pending" for item in record.approvals)
        return (
            f"Safe automatic repairs ran. {pending} decision-changing approval(s) require a human."
        )
    if status == IncidentStatus.VERIFIED:
        return (
            "Every registered target was independently re-read and the monitored packet "
            "was certified."
        )
    if status == IncidentStatus.ATTENTION:
        return (
            "The agent stopped safely because a conflict, rejection, or dependency needs attention."
        )
    return (
        "Veritas is advancing the registered consequences through repair and independent "
        "verification."
    )


def _artifact_code(kind: ArtifactKind) -> str:
    return {
        ArtifactKind.GOOGLE_DOC: "D",
        ArtifactKind.GOOGLE_SLIDES: "S",
        ArtifactKind.GMAIL: "G",
        ArtifactKind.GOOGLE_TASK: "T",
    }[kind]


def _artifact_surface(kind: ArtifactKind) -> str:
    return {
        ArtifactKind.GOOGLE_DOC: "Google Docs",
        ArtifactKind.GOOGLE_SLIDES: "Google Slides",
        ArtifactKind.GMAIL: "Gmail",
        ArtifactKind.GOOGLE_TASK: "Google Tasks",
    }[kind]


def _source_surface(kind: SourceKind) -> str:
    return {SourceKind.GOOGLE_SHEET: "Google Sheets", SourceKind.GOOGLE_DOC: "Google Docs"}[kind]


def _title(value: str) -> str:
    return value.replace("_", " ").replace("-", " ").strip().title()


def _clock(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%H:%M:%S")


def _short(value: str) -> str:
    return value[-12:].upper()


def _receipt(check_id: str, detail: str) -> str:
    return hashlib.sha256(f"{check_id}:{detail}".encode()).hexdigest()[:10]


def _timeline_receipt(stage: str, *parts: str) -> str:
    material = ":".join((stage, *parts))
    return hashlib.sha256(material.encode()).hexdigest()[:16]
