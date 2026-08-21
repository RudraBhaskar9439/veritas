import json

import pytest

from lineage_support import ROOT, canonical_manifest, meaningful_snapshot
from veritas_runtime.changes.models import DeltaKind
from veritas_runtime.lineage.engine import LineageIntegrityError, RegisteredLineageEngine
from veritas_runtime.packets.models import ClaimRecord, ClaimRisk, ProvenanceStatus


def test_canonical_churn_blast_radius_matches_golden_fixture_exactly() -> None:
    manifest = canonical_manifest()
    impact = RegisteredLineageEngine().analyze("subject-1", manifest, (meaningful_snapshot(),))
    expected = json.loads((ROOT / "fixtures/demo/expected-churn-impact.json").read_text())

    assert [claim.claim_id for claim in impact.affected_claims] == expected["affectedClaimIds"]
    assert list(impact.unaffected_registered_claim_ids) == expected["unaffectedClaimIds"]
    assert [artifact.artifact_id for artifact in impact.affected_artifacts] == expected[
        "affectedArtifactIds"
    ]
    assert impact.changed_source_ids == (expected["changedSourceId"],)
    assert impact.coverage.registered_claim_count == 8
    assert impact.coverage.affected_registered_claim_count == 4
    assert len(impact.lineage_paths) == 9


def test_candidate_and_semantically_similar_unregistered_edges_never_enter_impact() -> None:
    manifest = canonical_manifest()
    candidate = ClaimRecord(
        claim_id="candidate-churn",
        statement="Churn might imply a pricing issue.",
        source_ids=("src-churn",),
        artifact_anchors=manifest.claims[0].artifact_anchors,
        risk=ClaimRisk.DECISION_CHANGING,
        provenance=ProvenanceStatus.CANDIDATE,
        freshness_hours=24,
    )
    similar_but_unlinked = ClaimRecord(
        claim_id="registered-similar-words",
        statement="Q3 customer churn is discussed here.",
        source_ids=("src-revenue",),
        artifact_anchors=(manifest.claims[0].artifact_anchors[0],),
        risk=ClaimRisk.REVERSIBLE,
        provenance=ProvenanceStatus.REGISTERED,
        freshness_hours=24,
    )
    expanded = manifest.model_copy(
        update={"claims": (*manifest.claims, candidate, similar_but_unlinked)}
    )
    impact = RegisteredLineageEngine().analyze("subject-1", expanded, (meaningful_snapshot(),))

    assert impact.candidate_claim_ids == ("candidate-churn",)
    assert "candidate-churn" not in {claim.claim_id for claim in impact.affected_claims}
    assert "registered-similar-words" in impact.unaffected_registered_claim_ids
    assert {claim.claim_id for claim in impact.affected_claims} == {
        "claim-churn-value",
        "claim-churn-improved",
        "claim-retention-target",
        "claim-scale-acquisition",
    }


@pytest.mark.parametrize(
    ("snapshot", "message"),
    [
        (meaningful_snapshot(delta_kind=DeltaKind.COSMETIC), "Only meaningful"),
        (meaningful_snapshot(source_id="unknown-source"), "not registered"),
        (meaningful_snapshot(subject="other-subject"), "outside"),
        (meaningful_snapshot(packet_id="other-packet"), "outside"),
    ],
)
def test_lineage_rejects_nonmeaningful_unregistered_or_cross_boundary_snapshots(
    snapshot: object,
    message: str,
) -> None:
    with pytest.raises(LineageIntegrityError, match=message):
        RegisteredLineageEngine().analyze(
            "subject-1",
            canonical_manifest(),
            (snapshot,),  # type: ignore[arg-type]
        )


def test_lineage_rejects_empty_and_duplicate_source_changes() -> None:
    engine = RegisteredLineageEngine()
    manifest = canonical_manifest()
    with pytest.raises(LineageIntegrityError, match="At least one"):
        engine.analyze("subject-1", manifest, ())
    with pytest.raises(LineageIntegrityError, match="Snapshot IDs"):
        snapshot = meaningful_snapshot()
        engine.analyze("subject-1", manifest, (snapshot, snapshot))
    with pytest.raises(LineageIntegrityError, match="one changed snapshot per source"):
        engine.analyze(
            "subject-1",
            manifest,
            (meaningful_snapshot(), meaningful_snapshot(snapshot_id="snapshot-newer")),
        )
