import pytest

from repair_support import canonical_repair_context
from veritas_runtime.execution.merge import decide_three_way_merge
from veritas_runtime.execution.models import ArtifactState, MergeOutcome
from veritas_runtime.repairs.planner import TypedRepairPlanner


def _step():  # type: ignore[no-untyped-def]
    context = canonical_repair_context()
    return (
        TypedRepairPlanner()
        .plan(
            "subject-1",
            context.manifest,
            context.impact,
            context.impact_checksum,
            context.sources,
            context.snapshot_metadata,
        )
        .steps[0]
    )


def test_three_way_merge_applies_only_when_registered_anchor_matches_base() -> None:
    step = _step()
    current = ArtifactState(
        resource_id=step.resource_id,
        revision_id="human-edited-revision",
        anchor=step.anchor,
        statement=step.before_statement,
    )
    assert decide_three_way_merge(step, current) == MergeOutcome.APPLY
    assert (
        decide_three_way_merge(
            step, current.model_copy(update={"statement": step.proposed_statement})
        )
        == MergeOutcome.ALREADY_APPLIED
    )
    assert (
        decide_three_way_merge(
            step, current.model_copy(update={"statement": "CFO changed this exact claim."})
        )
        == MergeOutcome.CONFLICT
    )


def test_three_way_merge_rejects_a_different_registered_target() -> None:
    step = _step()
    current = ArtifactState(
        resource_id="other-document",
        revision_id="revision",
        anchor=step.anchor,
        statement=step.before_statement,
    )
    with pytest.raises(ValueError, match="does not match"):
        decide_three_way_merge(step, current)
