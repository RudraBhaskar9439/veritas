from collections import Counter
from collections.abc import Mapping
from uuid import NAMESPACE_URL, uuid5

from veritas_runtime.changes.models import EvidenceSnapshot
from veritas_runtime.lineage.models import ImpactReport
from veritas_runtime.packets.models import (
    ClaimManifest,
    ProvenanceStatus,
    SourceSnapshot,
)
from veritas_runtime.packets.transformations import TransformationError, TransformationRegistry
from veritas_runtime.repairs.models import (
    ApprovalRequirement,
    PolicyDisposition,
    RepairPlanDraft,
    RepairPlanState,
    RepairPolicySummary,
    RepairStep,
    SourceVersionRef,
)
from veritas_runtime.repairs.policy import RepairPolicyEngine


class RepairPlanningIntegrityError(ValueError):
    """A repair plan cannot be derived from the registered, immutable inputs."""


class TypedRepairPlanner:
    def __init__(
        self,
        transformations: TransformationRegistry | None = None,
        policies: RepairPolicyEngine | None = None,
    ) -> None:
        self._transformations = transformations or TransformationRegistry()
        self._policies = policies or RepairPolicyEngine()

    def plan(
        self,
        subject: str,
        manifest: ClaimManifest,
        impact: ImpactReport,
        impact_checksum: str,
        sources: tuple[SourceSnapshot, ...],
        snapshot_metadata: tuple[EvidenceSnapshot, ...],
    ) -> RepairPlanDraft:
        if not subject:
            raise RepairPlanningIntegrityError("Workspace subject is required")
        if (
            impact.packet_id != manifest.packet_id
            or impact.manifest_id != manifest.manifest_id
            or impact.manifest_version != manifest.version
        ):
            raise RepairPlanningIntegrityError("Impact report does not bind to the Claim Manifest")
        source_index = _unique_sources(sources)
        metadata_index = _unique_metadata(snapshot_metadata)
        claim_index = {claim.claim_id: claim for claim in manifest.claims}
        artifact_index = {artifact.artifact_id: artifact for artifact in manifest.artifacts}
        impacted_ids = tuple(claim.claim_id for claim in impact.affected_claims)
        if len(set(impacted_ids)) != len(impacted_ids):
            raise RepairPlanningIntegrityError("Impact report contains duplicate affected claims")

        steps: list[RepairStep] = []
        unchanged: list[str] = []
        approvals_by_claim: dict[str, list[str]] = {}
        approval_ids: dict[str, str] = {}
        for claim_id in impacted_ids:
            claim = claim_index.get(claim_id)
            if claim is None or claim.provenance != ProvenanceStatus.REGISTERED:
                raise RepairPlanningIntegrityError(
                    f"Affected claim {claim_id} is not registered in the manifest"
                )
            claim_sources = _claim_sources(claim.source_ids, source_index, metadata_index)
            try:
                proposed = self._transformations.render(claim, source_index)
            except TransformationError as error:
                raise RepairPlanningIntegrityError(str(error)) from error
            if proposed == claim.statement:
                unchanged.append(claim_id)
                continue
            for anchor in claim.artifact_anchors:
                artifact = artifact_index.get(anchor.artifact_id)
                if artifact is None:
                    raise RepairPlanningIntegrityError(
                        f"Claim {claim_id} references an unknown artifact"
                    )
                decision = self._policies.decide(claim.risk, artifact)
                approval_id = None
                if decision.disposition == PolicyDisposition.REQUIRES_APPROVAL:
                    approval_id = approval_ids.setdefault(
                        claim_id,
                        f"approval-{uuid5(NAMESPACE_URL, f'{impact.report_id}:{claim_id}')}",
                    )
                identity = f"{impact.report_id}:{claim_id}:{artifact.artifact_id}:{anchor.anchor}"
                step_id = f"step-{uuid5(NAMESPACE_URL, identity)}"
                step = RepairStep(
                    step_id=step_id,
                    execution_key=f"repair:{step_id}",
                    claim_id=claim_id,
                    claim_risk=claim.risk,
                    artifact_id=artifact.artifact_id,
                    artifact_kind=artifact.kind,
                    resource_id=artifact.resource_id,
                    base_revision_id=artifact.base_revision_id,
                    anchor=anchor.anchor,
                    operation=decision.operation,
                    disposition=decision.disposition,
                    policy_rule=decision.rule,
                    before_statement=claim.statement,
                    proposed_statement=proposed,
                    source_versions=claim_sources,
                    approval_id=approval_id,
                )
                steps.append(step)
                if approval_id is not None:
                    approvals_by_claim.setdefault(claim_id, []).append(step_id)

        if not steps:
            raise RepairPlanningIntegrityError("Impact report produced no required repair steps")
        approvals = tuple(
            ApprovalRequirement(
                approval_id=approval_ids[claim_id],
                claim_id=claim_id,
                claim_risk=claim_index[claim_id].risk,
                step_ids=tuple(step_ids),
                reason=(
                    "A consequential registered claim cannot be changed without a human decision."
                ),
            )
            for claim_id, step_ids in approvals_by_claim.items()
        )
        dispositions = Counter(step.disposition for step in steps)
        summary = RepairPolicySummary(
            auto_execute_steps=dispositions[PolicyDisposition.AUTO_EXECUTE],
            approval_required_steps=dispositions[PolicyDisposition.REQUIRES_APPROVAL],
            draft_only_steps=dispositions[PolicyDisposition.DRAFT_ONLY],
            blocked_steps=dispositions[PolicyDisposition.BLOCKED],
        )
        state = (
            RepairPlanState.BLOCKED
            if summary.blocked_steps
            else RepairPlanState.AWAITING_APPROVAL
            if approvals
            else RepairPlanState.READY
        )
        used_snapshot_ids = sorted(
            {source.snapshot_id for step in steps for source in step.source_versions}
        )
        return RepairPlanDraft(
            subject=subject,
            packet_id=manifest.packet_id,
            impact_report_id=impact.report_id,
            impact_report_checksum=impact_checksum,
            manifest_id=manifest.manifest_id,
            manifest_version=manifest.version,
            source_snapshot_ids=tuple(used_snapshot_ids),
            steps=tuple(steps),
            unchanged_impacted_claim_ids=tuple(unchanged),
            approvals=approvals,
            state=state,
            policy_summary=summary,
        )


def _unique_sources(sources: tuple[SourceSnapshot, ...]) -> dict[str, SourceSnapshot]:
    indexed = {source.source_id: source for source in sources}
    if len(indexed) != len(sources):
        raise RepairPlanningIntegrityError("Repair source IDs must be unique")
    return indexed


def _unique_metadata(snapshots: tuple[EvidenceSnapshot, ...]) -> dict[str, EvidenceSnapshot]:
    indexed = {snapshot.source_id: snapshot for snapshot in snapshots}
    if len(indexed) != len(snapshots):
        raise RepairPlanningIntegrityError("Repair snapshot sources must be unique")
    return indexed


def _claim_sources(
    source_ids: tuple[str, ...],
    sources: Mapping[str, SourceSnapshot],
    snapshots: Mapping[str, EvidenceSnapshot],
) -> tuple[SourceVersionRef, ...]:
    result: list[SourceVersionRef] = []
    for source_id in source_ids:
        source = sources.get(source_id)
        snapshot = snapshots.get(source_id)
        if source is None or snapshot is None:
            raise RepairPlanningIntegrityError(
                f"No immutable current snapshot exists for source {source_id}"
            )
        if source.version != snapshot.workspace_version:
            raise RepairPlanningIntegrityError(
                f"Source {source_id} does not match its immutable snapshot version"
            )
        result.append(
            SourceVersionRef(
                source_id=source_id,
                snapshot_id=snapshot.snapshot_id,
                workspace_version=snapshot.workspace_version,
                content_hash=snapshot.content_hash,
            )
        )
    return tuple(result)
