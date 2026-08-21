import pytest

from packet_support import load_generation_request
from veritas_runtime.packets.transformations import TransformationError, TransformationRegistry


def test_transformations_reject_missing_or_invalid_values() -> None:
    _, blueprint, snapshots = load_generation_request()
    sources = {source.source_id: source for source in snapshots}
    registry = TransformationRegistry()

    missing_parameter = blueprint.claims[0].model_copy(update={"parameters": {}})
    with pytest.raises(TransformationError, match="requires string parameter"):
        registry.render(missing_parameter, sources)

    bad_number = sources["src-churn"].model_copy(update={"value": "not-a-number"})
    with pytest.raises(TransformationError, match="invalid"):
        registry.render(blueprint.claims[0], {**sources, "src-churn": bad_number})

    bool_number = sources["src-churn"].model_copy(update={"value": True})
    with pytest.raises(TransformationError, match="required"):
        registry.render(blueprint.claims[0], {**sources, "src-churn": bool_number})

    launch_claim = next(
        claim for claim in blueprint.claims if claim.claim_id == "claim-launch-date"
    )
    bad_date = sources["src-launch"].model_copy(update={"value": "15/10/2026"})
    with pytest.raises(TransformationError, match="ISO-8601"):
        registry.render(launch_claim, {**sources, "src-launch": bad_date})


def test_comparison_handles_equal_source_values_and_empty_output() -> None:
    _, blueprint, snapshots = load_generation_request()
    sources = {source.source_id: source for source in snapshots}
    registry = TransformationRegistry()
    comparison = next(
        claim for claim in blueprint.claims if claim.claim_id == "claim-churn-improved"
    )
    equal_previous = sources["src-churn-previous"].model_copy(
        update={"value": sources["src-churn"].value}
    )
    assert registry.render(comparison, {**sources, "src-churn-previous": equal_previous}) == (
        "Customer churn was unchanged during Q3."
    )

    empty_registry = TransformationRegistry({"empty": lambda _claim, _source: "  "})
    empty_claim = comparison.model_copy(update={"transformation": "empty"})
    with pytest.raises(TransformationError, match="empty statement"):
        empty_registry.render(empty_claim, sources)
