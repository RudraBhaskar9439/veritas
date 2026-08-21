from veritas_runtime.execution.models import ArtifactState, MergeOutcome
from veritas_runtime.repairs.models import RepairStep


def decide_three_way_merge(step: RepairStep, current: ArtifactState) -> MergeOutcome:
    """Compare base, desired, and current text only at the registered anchor."""
    if current.resource_id != step.resource_id or current.anchor != step.anchor:
        raise ValueError("Workspace state does not match the registered repair target")
    if current.statement == step.proposed_statement:
        return MergeOutcome.ALREADY_APPLIED
    if current.statement != step.before_statement:
        return MergeOutcome.CONFLICT
    return MergeOutcome.APPLY
