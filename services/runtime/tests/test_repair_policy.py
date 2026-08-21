import pytest

from veritas_runtime.packets.models import (
    ArtifactKind,
    ArtifactMutability,
    ArtifactRecord,
    ClaimRisk,
)
from veritas_runtime.repairs.models import PolicyDisposition, RepairOperation
from veritas_runtime.repairs.policy import RepairPolicyEngine


@pytest.mark.parametrize(
    ("risk", "expected"),
    [
        (ClaimRisk.INFORMATIONAL, PolicyDisposition.AUTO_EXECUTE),
        (ClaimRisk.REVERSIBLE, PolicyDisposition.AUTO_EXECUTE),
        (ClaimRisk.DECISION_CHANGING, PolicyDisposition.REQUIRES_APPROVAL),
        (ClaimRisk.IRREVERSIBLE, PolicyDisposition.REQUIRES_APPROVAL),
    ],
)
def test_editable_policy_matrix(risk: ClaimRisk, expected: PolicyDisposition) -> None:
    artifact = ArtifactRecord(
        artifact_id="doc",
        kind=ArtifactKind.GOOGLE_DOC,
        resource_id="doc-1",
        base_revision_id="rev-1",
        mutability=ArtifactMutability.EDITABLE,
    )
    assert RepairPolicyEngine().decide(risk, artifact).disposition == expected


@pytest.mark.parametrize("risk", list(ClaimRisk))
def test_draft_only_and_immutable_email_never_become_direct_mutations(
    risk: ClaimRisk,
) -> None:
    draft = ArtifactRecord(
        artifact_id="draft",
        kind=ArtifactKind.GMAIL,
        resource_id="draft-1",
        base_revision_id="rev-1",
        mutability=ArtifactMutability.DRAFT_ONLY,
    )
    sent = draft.model_copy(
        update={"artifact_id": "sent", "mutability": ArtifactMutability.IMMUTABLE}
    )
    assert RepairPolicyEngine().decide(risk, draft).disposition == PolicyDisposition.DRAFT_ONLY
    decision = RepairPolicyEngine().decide(risk, sent)
    assert decision.disposition == PolicyDisposition.DRAFT_ONLY
    assert decision.operation == RepairOperation.CREATE_CORRECTION_DRAFT


def test_unknown_immutable_artifact_is_blocked() -> None:
    artifact = ArtifactRecord(
        artifact_id="doc",
        kind=ArtifactKind.GOOGLE_DOC,
        resource_id="doc-1",
        base_revision_id="rev-1",
        mutability=ArtifactMutability.IMMUTABLE,
    )
    decision = RepairPolicyEngine().decide(ClaimRisk.REVERSIBLE, artifact)
    assert decision.disposition == PolicyDisposition.BLOCKED
    assert decision.operation == RepairOperation.MANUAL_REVIEW
