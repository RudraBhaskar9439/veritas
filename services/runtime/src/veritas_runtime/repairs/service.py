import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from veritas_runtime.changes.models import EvidenceSnapshot
from veritas_runtime.lineage.models import ImpactReport
from veritas_runtime.packets.models import ClaimManifest, SourceSnapshot
from veritas_runtime.repairs.models import (
    ApprovalActor,
    ApprovalActorKind,
    ApprovalDecision,
    ApprovalDecisionResult,
    ApprovalRecord,
    RepairPlan,
    RepairPlanDraft,
    RepairPlanResult,
)
from veritas_runtime.repairs.planner import TypedRepairPlanner


class RepairPlanningError(ValueError):
    """A repair request cannot be safely planned or persisted."""


class RepairPlanIdempotencyConflict(RepairPlanningError):
    """A repair request ID was reused with different immutable inputs."""


class ApprovalConflict(RepairPlanningError):
    """An approval request conflicts with the existing human decision."""


@dataclass(frozen=True)
class RepairPlanningContext:
    manifest: ClaimManifest
    manifest_checksum: str
    impact: ImpactReport
    impact_checksum: str
    sources: tuple[SourceSnapshot, ...]
    snapshot_metadata: tuple[EvidenceSnapshot, ...]


@dataclass(frozen=True)
class PersistedRepairPlan:
    plan: RepairPlan
    approvals: tuple[ApprovalRecord, ...]
    checksum: str
    input_digest: str


class RepairPlanRepository(Protocol):
    async def load_context(
        self, subject: str, packet_id: str, impact_report_id: str
    ) -> RepairPlanningContext: ...

    async def get_by_idempotency_key(self, key: str) -> PersistedRepairPlan | None: ...

    async def persist(
        self,
        draft: RepairPlanDraft,
        idempotency_key: str,
        input_digest: str,
        now: datetime,
    ) -> PersistedRepairPlan: ...

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
    ) -> ApprovalDecisionResult: ...


class RepairPlanningService:
    def __init__(
        self,
        repository: RepairPlanRepository,
        planner: TypedRepairPlanner | None = None,
    ) -> None:
        self._repository = repository
        self._planner = planner or TypedRepairPlanner()

    async def create_plan(
        self,
        subject: str,
        packet_id: str,
        request_id: str,
        impact_report_id: str,
        now: datetime | None = None,
    ) -> RepairPlanResult:
        if not subject or not packet_id or not request_id or not impact_report_id:
            raise RepairPlanningError(
                "Subject, packet ID, request ID, and impact report ID are required"
            )
        context = await self._repository.load_context(subject, packet_id, impact_report_id)
        input_digest = _input_digest(context)
        idempotency_key = f"{subject}:{packet_id}:{request_id}"
        existing = await self._repository.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            return _reuse(existing, input_digest)
        draft = self._planner.plan(
            subject,
            context.manifest,
            context.impact,
            context.impact_checksum,
            context.sources,
            context.snapshot_metadata,
        )
        persisted = await self._repository.persist(
            draft,
            idempotency_key,
            input_digest,
            (now or datetime.now(UTC)).astimezone(UTC),
        )
        return _result(persisted, reused=False)

    async def decide_approval(
        self,
        subject: str,
        actor: ApprovalActor,
        plan_id: str,
        approval_id: str,
        request_id: str,
        decision: ApprovalDecision,
        reason: str,
        now: datetime | None = None,
    ) -> ApprovalDecisionResult:
        if not all((subject, actor.principal, plan_id, approval_id, request_id, reason.strip())):
            raise RepairPlanningError("A complete authenticated approval decision is required")
        if actor.kind != ApprovalActorKind.HUMAN:
            raise PermissionError("Only an authenticated human can approve a repair plan")
        return await self._repository.decide_approval(
            subject,
            actor,
            plan_id,
            approval_id,
            request_id,
            decision,
            reason.strip(),
            (now or datetime.now(UTC)).astimezone(UTC),
        )


def repair_plan_checksum(plan: RepairPlan) -> str:
    return hashlib.sha256(
        json.dumps(
            plan.model_dump(mode="json", by_alias=True),
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


def _input_digest(context: RepairPlanningContext) -> str:
    payload = {
        "manifestChecksum": context.manifest_checksum,
        "impactChecksum": context.impact_checksum,
        "sources": [
            source.model_dump(mode="json", by_alias=True)
            for source in sorted(context.sources, key=lambda item: item.source_id)
        ],
        "snapshots": [
            {
                "snapshotId": snapshot.snapshot_id,
                "contentHash": snapshot.content_hash,
                "workspaceVersion": snapshot.workspace_version,
            }
            for snapshot in sorted(context.snapshot_metadata, key=lambda item: item.source_id)
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _reuse(existing: PersistedRepairPlan, input_digest: str) -> RepairPlanResult:
    if existing.input_digest != input_digest:
        raise RepairPlanIdempotencyConflict(
            "Repair request ID was reused with different immutable inputs"
        )
    return _result(existing, reused=True)


def _result(persisted: PersistedRepairPlan, reused: bool) -> RepairPlanResult:
    return RepairPlanResult(
        plan=persisted.plan,
        approvals=persisted.approvals,
        checksum=persisted.checksum,
        reused=reused,
    )
