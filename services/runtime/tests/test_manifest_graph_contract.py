import pytest
from pydantic import ValidationError

from lineage_support import canonical_manifest


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("duplicate-source", "source IDs must be unique"),
        ("unknown-source", "invalid source lineage"),
        ("unknown-artifact", "invalid artifact lineage"),
    ],
)
def test_claim_manifest_rejects_ambiguous_or_dangling_graphs(
    mutation: str,
    message: str,
) -> None:
    payload = canonical_manifest().model_dump(mode="json", by_alias=True)
    if mutation == "duplicate-source":
        payload["sources"].append(payload["sources"][0])
    elif mutation == "unknown-source":
        payload["claims"][0]["sourceIds"] = ["unknown-source"]
    else:
        payload["claims"][0]["artifactAnchors"][0]["artifactId"] = "unknown-artifact"
    with pytest.raises(ValidationError, match=message):
        canonical_manifest().__class__.model_validate(payload)
