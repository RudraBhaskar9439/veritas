from datetime import datetime
from enum import StrEnum

from pydantic import Field

from veritas_runtime.changes.models import JsonValue
from veritas_runtime.packets.models import CamelModel


class OperationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    DEAD_LETTER = "dead_letter"


class Operation(CamelModel):
    operation_id: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    kind: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,79}$")
    correlation_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=512)
    payload: dict[str, JsonValue] = Field(default_factory=dict, exclude=True, repr=False)
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: OperationStatus
    attempt: int = Field(ge=0)
    max_attempts: int = Field(ge=1, le=10)
    available_at: datetime
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    last_error_code: str | None = None
    diagnostic_fingerprint: str | None = None
    replay_of: str | None = None
    created_at: datetime
    updated_at: datetime


class OperationRequest(CamelModel):
    subject: str = Field(min_length=1)
    kind: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,79}$")
    correlation_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=512)
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    max_attempts: int = Field(default=5, ge=1, le=10)


class OperationTick(CamelModel):
    status: OperationStatus | None
    operation_id: str | None = None
    recovered_leases: int = Field(default=0, ge=0)
    retry_at: datetime | None = None


class DeadLetterSummary(CamelModel):
    operation_id: str
    kind: str
    correlation_id: str
    attempt: int
    max_attempts: int
    error_code: str
    diagnostic_fingerprint: str
    replay_of: str | None = None
    packet_ids: tuple[str, ...] = ()
    updated_at: datetime


class ReplayOperationRequest(CamelModel):
    request_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=12, max_length=1000)


class ReplayOperationResult(CamelModel):
    operation: Operation
    reused: bool


class WorkerTickRequest(CamelModel):
    worker_id: str = Field(min_length=1, max_length=128)
