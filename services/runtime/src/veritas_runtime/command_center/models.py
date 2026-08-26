from datetime import datetime
from enum import StrEnum

from pydantic import Field

from veritas_runtime.agents.models import AgentDisposition
from veritas_runtime.execution.models import RepairRun
from veritas_runtime.packets.models import CamelModel
from veritas_runtime.repairs.models import (
    ApprovalDecision,
    ApprovalDecisionResult,
    ApprovalStatus,
)
from veritas_runtime.verification.models import VerificationResult


class IncidentStatus(StrEnum):
    AWAITING_APPROVAL = "awaiting_approval"
    REPAIRING = "repairing"
    VERIFIED = "verified"
    ATTENTION = "attention"


class CommandCenterClaim(CamelModel):
    id: str
    short_label: str
    before: str
    after: str
    transformation: str
    evidence: str
    policy: str
    risk: str
    risk_label: str
    target_count: int = Field(ge=0)


class CommandCenterArtifact(CamelModel):
    id: str
    code: str
    surface: str
    name: str
    target_count: int = Field(ge=0)
    action: str
    guardrail: str
    result: str


class CommandCenterTimelineEvent(CamelModel):
    time: str
    occurred_at: datetime
    label: str
    detail: str
    receipt: str


class CommandCenterCoverage(CamelModel):
    claims: int = Field(ge=0)
    affected_claims: int = Field(ge=0)
    targets: int = Field(ge=0)
    verified_targets: int = Field(ge=0)
    protected_artifacts: int = Field(ge=0)
    verified_protected_artifacts: int = Field(ge=0)
    sources: int = Field(ge=0)
    lineage_paths: int = Field(ge=0)


class CommandCenterCertificate(CamelModel):
    short_id: str
    statement: str
    issued_at: datetime


class CommandCenterCheck(CamelModel):
    label: str
    detail: str
    receipt: str
    passed: bool


class CommandCenterEvidence(CamelModel):
    id: str
    label: str
    kind: str
    anchor: str
    version: str
    snapshot: str
    snapshot_id: str
    content_hash: str
    captured_at: datetime
    changed: bool
    current: bool


class CommandCenterApproval(CamelModel):
    approval_id: str
    plan_id: str
    run_id: str | None = None
    claim_id: str
    claim_label: str
    status: ApprovalStatus
    reason: str | None = None


class CommandCenterAgentReview(CamelModel):
    model: str
    disposition: AgentDisposition
    rationale: str
    risk_flags: tuple[str, ...]
    receipt: str


class CommandCenterIncident(CamelModel):
    id: str
    packet_id: str
    run_id: str | None = None
    status: IncidentStatus
    source: str = "live"
    headline: str
    summary: str
    detected_at: datetime
    updated_at: datetime
    claims: tuple[CommandCenterClaim, ...]
    artifacts: tuple[CommandCenterArtifact, ...]
    timeline: tuple[CommandCenterTimelineEvent, ...]
    coverage: CommandCenterCoverage
    certificate: CommandCenterCertificate | None = None
    checks: tuple[CommandCenterCheck, ...]
    evidence: tuple[CommandCenterEvidence, ...]
    approvals: tuple[CommandCenterApproval, ...]
    agent_review: CommandCenterAgentReview | None = None


class CommandCenterApprovalRequest(CamelModel):
    request_id: str = Field(min_length=1, max_length=128)
    decision: ApprovalDecision
    reason: str = Field(min_length=12, max_length=1000)


class CommandCenterApprovalResult(CamelModel):
    approval: ApprovalDecisionResult
    run: RepairRun
    verification: VerificationResult | None = None
