from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from veritas_runtime.packets.models import ArtifactKind, CamelModel, ClaimRisk


class RepairOperation(StrEnum):
    REPLACE_REGISTERED_CLAIM = "replace_registered_claim"
    UPDATE_TASK = "update_task"
    CREATE_CORRECTION_DRAFT = "create_correction_draft"
    MANUAL_REVIEW = "manual_review"


class PolicyDisposition(StrEnum):
    AUTO_EXECUTE = "auto_execute"
    REQUIRES_APPROVAL = "requires_approval"
    DRAFT_ONLY = "draft_only"
    BLOCKED = "blocked"


class RepairPlanState(StrEnum):
    READY = "ready"
    AWAITING_APPROVAL = "awaiting_approval"
    BLOCKED = "blocked"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class ApprovalActorKind(StrEnum):
    HUMAN = "human"
    SERVICE = "service"


class ApprovalActor(CamelModel):
    principal: str = Field(min_length=1)
    kind: ApprovalActorKind


class SourceVersionRef(CamelModel):
    source_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    workspace_version: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class RepairStep(CamelModel):
    step_id: str = Field(min_length=1)
    execution_key: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    claim_risk: ClaimRisk
    artifact_id: str = Field(min_length=1)
    artifact_kind: ArtifactKind
    resource_id: str = Field(min_length=1)
    base_revision_id: str = Field(min_length=1)
    anchor: str = Field(min_length=1)
    operation: RepairOperation
    disposition: PolicyDisposition
    policy_rule: str = Field(min_length=1)
    before_statement: str = Field(min_length=1)
    proposed_statement: str = Field(min_length=1)
    source_versions: tuple[SourceVersionRef, ...] = Field(min_length=1)
    approval_id: str | None = None

    @model_validator(mode="after")
    def approval_binding_matches_disposition(self) -> "RepairStep":
        requires_approval = self.disposition == PolicyDisposition.REQUIRES_APPROVAL
        if requires_approval != (self.approval_id is not None):
            raise ValueError("approval binding must match the step policy disposition")
        return self


class ApprovalRequirement(CamelModel):
    approval_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    claim_risk: ClaimRisk
    step_ids: tuple[str, ...] = Field(min_length=1)
    reason: str = Field(min_length=1)


class RepairPolicySummary(CamelModel):
    auto_execute_steps: int = Field(ge=0)
    approval_required_steps: int = Field(ge=0)
    draft_only_steps: int = Field(ge=0)
    blocked_steps: int = Field(ge=0)


class RepairPlanDraft(CamelModel):
    subject: str = Field(min_length=1, exclude=True, repr=False)
    packet_id: str = Field(min_length=1)
    impact_report_id: str = Field(min_length=1)
    impact_report_checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    manifest_id: str = Field(min_length=1)
    manifest_version: int = Field(ge=1)
    source_snapshot_ids: tuple[str, ...] = Field(min_length=1)
    steps: tuple[RepairStep, ...] = Field(min_length=1)
    unchanged_impacted_claim_ids: tuple[str, ...]
    approvals: tuple[ApprovalRequirement, ...]
    state: RepairPlanState
    policy_summary: RepairPolicySummary


class RepairPlan(CamelModel):
    plan_id: str = Field(min_length=1)
    packet_id: str = Field(min_length=1)
    impact_report_id: str = Field(min_length=1)
    impact_report_checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    manifest_id: str = Field(min_length=1)
    manifest_version: int = Field(ge=1)
    version: int = Field(ge=1)
    created_at: datetime
    source_snapshot_ids: tuple[str, ...] = Field(min_length=1)
    steps: tuple[RepairStep, ...] = Field(min_length=1)
    unchanged_impacted_claim_ids: tuple[str, ...]
    approvals: tuple[ApprovalRequirement, ...]
    state: RepairPlanState
    policy_summary: RepairPolicySummary


class ApprovalRecord(CamelModel):
    approval_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    status: ApprovalStatus
    decided_by: str | None = None
    reason: str | None = None
    decided_at: datetime | None = None


class RepairPlanResult(CamelModel):
    plan: RepairPlan
    approvals: tuple[ApprovalRecord, ...]
    checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    reused: bool


class RepairPlanRequest(CamelModel):
    request_id: str = Field(min_length=1)
    impact_report_id: str = Field(min_length=1)


class ApprovalDecisionRequest(CamelModel):
    request_id: str = Field(min_length=1)
    decision: ApprovalDecision
    reason: str = Field(min_length=1, max_length=1000)


class ApprovalDecisionResult(CamelModel):
    approval: ApprovalRecord
    reused: bool
