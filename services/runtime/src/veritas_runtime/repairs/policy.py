from dataclasses import dataclass

from veritas_runtime.packets.models import (
    ArtifactKind,
    ArtifactMutability,
    ArtifactRecord,
    ClaimRisk,
)
from veritas_runtime.repairs.models import PolicyDisposition, RepairOperation


@dataclass(frozen=True)
class PolicyDecisionResult:
    operation: RepairOperation
    disposition: PolicyDisposition
    rule: str


class RepairPolicyEngine:
    """A deterministic safety boundary; model output cannot override these rules."""

    def decide(self, risk: ClaimRisk, artifact: ArtifactRecord) -> PolicyDecisionResult:
        if artifact.mutability == ArtifactMutability.IMMUTABLE:
            if artifact.kind == ArtifactKind.GMAIL:
                return PolicyDecisionResult(
                    RepairOperation.CREATE_CORRECTION_DRAFT,
                    PolicyDisposition.DRAFT_ONLY,
                    "immutable.gmail.correction-draft.v1",
                )
            return PolicyDecisionResult(
                RepairOperation.MANUAL_REVIEW,
                PolicyDisposition.BLOCKED,
                "immutable.non-email.block.v1",
            )
        if artifact.mutability == ArtifactMutability.DRAFT_ONLY:
            return PolicyDecisionResult(
                _operation(artifact.kind),
                PolicyDisposition.DRAFT_ONLY,
                "artifact.draft-only.v1",
            )
        if risk in {ClaimRisk.DECISION_CHANGING, ClaimRisk.IRREVERSIBLE}:
            return PolicyDecisionResult(
                _operation(artifact.kind),
                PolicyDisposition.REQUIRES_APPROVAL,
                f"claim.{risk.value}.human-approval.v1",
            )
        return PolicyDecisionResult(
            _operation(artifact.kind),
            PolicyDisposition.AUTO_EXECUTE,
            "claim.low-risk.registered-auto.v1",
        )


def _operation(kind: ArtifactKind) -> RepairOperation:
    if kind == ArtifactKind.GOOGLE_TASK:
        return RepairOperation.UPDATE_TASK
    return RepairOperation.REPLACE_REGISTERED_CLAIM
