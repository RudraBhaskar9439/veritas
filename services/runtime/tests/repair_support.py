from datetime import UTC, datetime

from lineage_support import canonical_manifest, meaningful_snapshot
from packet_support import load_generation_request
from veritas_runtime.changes.models import DeltaKind, EvidenceSnapshot
from veritas_runtime.lineage.engine import RegisteredLineageEngine
from veritas_runtime.lineage.models import ImpactReport
from veritas_runtime.lineage.service import impact_checksum
from veritas_runtime.packets.generator import manifest_checksum
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

NOW = datetime(2026, 8, 21, 3, 0, tzinfo=UTC)


def canonical_repair_context() -> RepairPlanningContext:
    manifest = canonical_manifest()
    changed = meaningful_snapshot(snapshot_id="snapshot-churn-v2").model_copy(
        update={"workspace_version": "sheet-v2"}
    )
    draft = RegisteredLineageEngine().analyze("subject-1", manifest, (changed,))
    impact = ImpactReport(
        report_id="impact-canonical-churn",
        packet_id=draft.packet_id,
        manifest_id=draft.manifest_id,
        manifest_version=draft.manifest_version,
        version=1,
        created_at=NOW,
        snapshot_ids=draft.snapshot_ids,
        changed_source_ids=draft.changed_source_ids,
        affected_claims=draft.affected_claims,
        unaffected_registered_claim_ids=draft.unaffected_registered_claim_ids,
        candidate_claim_ids=draft.candidate_claim_ids,
        affected_artifacts=draft.affected_artifacts,
        lineage_paths=draft.lineage_paths,
        coverage=draft.coverage,
    )
    _, _, fixture_sources = load_generation_request()
    sources = tuple(
        source.model_copy(update={"value": 0.09, "version": "sheet-v2"})
        if source.source_id == "src-churn"
        else source
        for source in fixture_sources
        if source.source_id in {"src-churn", "src-churn-previous"}
    )
    previous = meaningful_snapshot(
        "src-churn-previous",
        snapshot_id="snapshot-churn-previous-v1",
        delta_kind=DeltaKind.BASELINE,
    ).model_copy(update={"workspace_version": "sheet-v1"})
    return RepairPlanningContext(
        manifest=manifest,
        manifest_checksum=manifest_checksum(manifest),
        impact=impact,
        impact_checksum=impact_checksum(impact),
        sources=sources,
        snapshot_metadata=(changed, previous),
    )


class MemoryRepairRepository:
    def __init__(self, context: RepairPlanningContext | None = None) -> None:
        self.context = context or canonical_repair_context()
        self.plans: dict[str, PersistedRepairPlan] = {}
        self.approval_events: dict[
            str, tuple[str, ApprovalDecision, str, ApprovalDecisionResult]
        ] = {}

    async def load_context(
        self, subject: str, packet_id: str, impact_report_id: str
    ) -> RepairPlanningContext:
        if subject != "subject-1":
            raise PermissionError("denied")
        if (
            packet_id != self.context.manifest.packet_id
            or impact_report_id != self.context.impact.report_id
        ):
            raise LookupError("repair inputs not found")
        return self.context

    async def get_by_idempotency_key(self, key: str) -> PersistedRepairPlan | None:
        return self.plans.get(key)

    async def persist(
        self,
        draft: RepairPlanDraft,
        idempotency_key: str,
        input_digest: str,
        now: datetime,
    ) -> PersistedRepairPlan:
        existing = self.plans.get(idempotency_key)
        if existing is not None:
            if existing.input_digest != input_digest:
                raise RepairPlanIdempotencyConflict("different immutable inputs")
            return existing
        plan = RepairPlan(
            plan_id=f"plan-memory-{len(self.plans) + 1}",
            packet_id=draft.packet_id,
            impact_report_id=draft.impact_report_id,
            impact_report_checksum=draft.impact_report_checksum,
            manifest_id=draft.manifest_id,
            manifest_version=draft.manifest_version,
            version=len(self.plans) + 1,
            created_at=now,
            source_snapshot_ids=draft.source_snapshot_ids,
            steps=draft.steps,
            unchanged_impacted_claim_ids=draft.unchanged_impacted_claim_ids,
            approvals=draft.approvals,
            state=draft.state,
            policy_summary=draft.policy_summary,
        )
        approvals = tuple(
            ApprovalRecord(
                approval_id=requirement.approval_id,
                plan_id=plan.plan_id,
                claim_id=requirement.claim_id,
                status=ApprovalStatus.PENDING,
            )
            for requirement in plan.approvals
        )
        persisted = PersistedRepairPlan(
            plan,
            approvals,
            repair_plan_checksum(plan),
            input_digest,
        )
        self.plans[idempotency_key] = persisted
        return persisted

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
        key = f"{subject}:{plan_id}:{approval_id}:{request_id}"
        event = self.approval_events.get(key)
        if event is not None:
            if event[:3] != (actor.principal, decision, reason):
                raise ApprovalConflict("different decision")
            return event[3].model_copy(update={"reused": True})
        persisted = next(
            (item for item in self.plans.values() if item.plan.plan_id == plan_id), None
        )
        if subject != "subject-1":
            raise PermissionError("denied")
        if persisted is None:
            raise LookupError("plan not found")
        current = next(
            (item for item in persisted.approvals if item.approval_id == approval_id), None
        )
        if current is None:
            raise LookupError("approval not found")
        if current.status != ApprovalStatus.PENDING:
            raise ApprovalConflict("already terminal")
        decided = current.model_copy(
            update={
                "status": (
                    ApprovalStatus.APPROVED
                    if decision == ApprovalDecision.APPROVE
                    else ApprovalStatus.REJECTED
                ),
                "decided_by": actor.principal,
                "reason": reason,
                "decided_at": now,
            }
        )
        approvals = tuple(
            decided if item.approval_id == approval_id else item for item in persisted.approvals
        )
        self.plans[next(key for key, value in self.plans.items() if value is persisted)] = (
            PersistedRepairPlan(
                persisted.plan,
                approvals,
                persisted.checksum,
                persisted.input_digest,
            )
        )
        result = ApprovalDecisionResult(approval=decided, reused=False)
        self.approval_events[key] = (actor.principal, decision, reason, result)
        return result


class MemorySnapshotReader:
    def __init__(self, objects: dict[str, tuple[bytes, str, str]]) -> None:
        self._objects = objects

    async def read(self, snapshot: EvidenceSnapshot) -> bytes:
        try:
            return self._objects[snapshot.storage.object_name][0]
        except KeyError as error:
            raise LookupError("snapshot object not found") from error
