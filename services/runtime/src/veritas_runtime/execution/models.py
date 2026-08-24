from datetime import datetime
from enum import StrEnum

from pydantic import Field

from veritas_runtime.changes.models import JsonValue
from veritas_runtime.packets.models import CamelModel


class MergeOutcome(StrEnum):
    APPLY = "apply"
    ALREADY_APPLIED = "already_applied"
    CONFLICT = "conflict"


class StepExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    ALREADY_APPLIED = "already_applied"
    CONFLICT = "conflict"
    WAITING_APPROVAL = "waiting_approval"
    REJECTED = "rejected"
    BLOCKED = "blocked"
    FAILED = "failed"


class RepairRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    AWAITING_APPROVAL = "awaiting_approval"
    CONFLICT = "conflict"
    REJECTED = "rejected"
    BLOCKED = "blocked"
    FAILED = "failed"


class ArtifactState(CamelModel):
    resource_id: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    anchor: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    write_context: dict[str, JsonValue] = Field(default_factory=dict, exclude=True, repr=False)


class MutationReceipt(CamelModel):
    resource_id: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    external_id: str | None = None
    recovered: bool = False


class StepExecutionRecord(CamelModel):
    step_id: str = Field(min_length=1)
    status: StepExecutionStatus
    attempted_at: datetime
    completed_at: datetime | None = None
    before_revision_id: str | None = None
    after_revision_id: str | None = None
    external_id: str | None = None
    detail: str = Field(min_length=1)


class RepairRun(CamelModel):
    run_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    packet_id: str = Field(min_length=1)
    status: RepairRunStatus
    created_at: datetime
    updated_at: datetime
    steps: tuple[StepExecutionRecord, ...]
    reused: bool = False


class ExecuteRepairRequest(CamelModel):
    request_id: str = Field(min_length=1)


class ResumeRepairRequest(CamelModel):
    request_id: str = Field(min_length=1)
