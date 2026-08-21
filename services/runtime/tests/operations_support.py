from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from veritas_runtime.operations.models import (
    DeadLetterSummary,
    Operation,
    OperationRequest,
    OperationStatus,
)
from veritas_runtime.operations.service import OperationIdempotencyConflict, payload_hash


class MemoryOperationRepository:
    def __init__(self) -> None:
        self.operations: dict[str, Operation] = {}
        self.keys: dict[str, str] = {}

    async def enqueue(self, request: OperationRequest, now: datetime) -> tuple[Operation, bool]:
        digest = payload_hash(request.payload)
        existing_id = self.keys.get(request.idempotency_key)
        if existing_id is not None:
            existing = self.operations[existing_id]
            if (
                existing.subject != request.subject
                or existing.kind != request.kind
                or existing.payload_hash != digest
            ):
                raise OperationIdempotencyConflict("conflicting work")
            return existing, True
        operation_id = f"op-{uuid5(NAMESPACE_URL, request.idempotency_key)}"
        operation = Operation(
            operation_id=operation_id,
            subject=request.subject,
            kind=request.kind,
            correlation_id=request.correlation_id,
            idempotency_key=request.idempotency_key,
            payload=request.payload,
            payload_hash=digest,
            status=OperationStatus.QUEUED,
            attempt=0,
            max_attempts=request.max_attempts,
            available_at=now,
            created_at=now,
            updated_at=now,
        )
        self.operations[operation_id] = operation
        self.keys[request.idempotency_key] = operation_id
        return operation, False

    async def recover_expired(self, now: datetime) -> int:
        recovered = 0
        for operation_id, operation in tuple(self.operations.items()):
            if (
                operation.status == OperationStatus.RUNNING
                and operation.lease_expires_at is not None
                and operation.lease_expires_at <= now
            ):
                self.operations[operation_id] = operation.model_copy(
                    update={
                        "status": OperationStatus.QUEUED,
                        "available_at": now,
                        "lease_owner": None,
                        "lease_expires_at": None,
                        "last_error_code": "worker_lease_expired",
                        "updated_at": now,
                    }
                )
                recovered += 1
        return recovered

    async def claim(
        self, worker_id: str, now: datetime, lease_expires_at: datetime
    ) -> Operation | None:
        eligible = [
            item
            for item in self.operations.values()
            if item.status in {OperationStatus.QUEUED, OperationStatus.RETRY_WAIT}
            and item.available_at <= now
        ]
        if not eligible:
            return None
        operation = sorted(eligible, key=lambda item: (item.available_at, item.created_at))[0]
        claimed = operation.model_copy(
            update={
                "status": OperationStatus.RUNNING,
                "attempt": operation.attempt + 1,
                "lease_owner": worker_id,
                "lease_expires_at": lease_expires_at,
                "updated_at": now,
            }
        )
        self.operations[operation.operation_id] = claimed
        return claimed

    async def succeed(self, operation: Operation, worker_id: str, now: datetime) -> Operation:
        return self._transition(operation, worker_id, OperationStatus.SUCCEEDED, now)

    async def retry(
        self,
        operation: Operation,
        worker_id: str,
        error_code: str,
        diagnostic_fingerprint: str,
        available_at: datetime,
        now: datetime,
    ) -> Operation:
        return self._transition(
            operation,
            worker_id,
            OperationStatus.RETRY_WAIT,
            now,
            available_at=available_at,
            error_code=error_code,
            diagnostic_fingerprint=diagnostic_fingerprint,
        )

    async def dead_letter(
        self,
        operation: Operation,
        worker_id: str,
        error_code: str,
        diagnostic_fingerprint: str,
        now: datetime,
    ) -> Operation:
        return self._transition(
            operation,
            worker_id,
            OperationStatus.DEAD_LETTER,
            now,
            error_code=error_code,
            diagnostic_fingerprint=diagnostic_fingerprint,
        )

    async def list_dead_letters(self, subject: str) -> tuple[DeadLetterSummary, ...]:
        return tuple(
            DeadLetterSummary(
                operation_id=item.operation_id,
                kind=item.kind,
                correlation_id=item.correlation_id,
                attempt=item.attempt,
                max_attempts=item.max_attempts,
                error_code=item.last_error_code or "missing_error",
                diagnostic_fingerprint=item.diagnostic_fingerprint or "missing_fingerprint",
                replay_of=item.replay_of,
                updated_at=item.updated_at,
            )
            for item in self.operations.values()
            if item.subject == subject and item.status == OperationStatus.DEAD_LETTER
        )

    async def replay(
        self,
        subject: str,
        operation_id: str,
        request_id: str,
        actor: str,
        reason: str,
        now: datetime,
    ) -> tuple[Operation, bool]:
        del actor, reason
        original = self.operations.get(operation_id)
        if (
            original is None
            or original.subject != subject
            or original.status != OperationStatus.DEAD_LETTER
        ):
            raise LookupError("dead letter not found")
        request = OperationRequest(
            subject=subject,
            kind=original.kind,
            correlation_id=original.correlation_id,
            idempotency_key=f"{subject}:replay:{operation_id}:{request_id}",
            payload=original.payload,
            max_attempts=original.max_attempts,
        )
        replayed, reused = await self.enqueue(request, now)
        if not reused:
            replayed = replayed.model_copy(update={"replay_of": operation_id})
            self.operations[replayed.operation_id] = replayed
        return replayed, reused

    def _transition(
        self,
        operation: Operation,
        worker_id: str,
        status: OperationStatus,
        now: datetime,
        *,
        available_at: datetime | None = None,
        error_code: str | None = None,
        diagnostic_fingerprint: str | None = None,
    ) -> Operation:
        current = self.operations[operation.operation_id]
        if current.status != OperationStatus.RUNNING or current.lease_owner != worker_id:
            raise RuntimeError("lease lost")
        updated = current.model_copy(
            update={
                "status": status,
                "available_at": available_at or current.available_at,
                "lease_owner": None,
                "lease_expires_at": None,
                "last_error_code": error_code,
                "diagnostic_fingerprint": diagnostic_fingerprint,
                "updated_at": now,
            }
        )
        self.operations[operation.operation_id] = updated
        return updated


class ScriptedHandler:
    def __init__(self, *outcomes: Exception | None) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[str] = []

    async def handle(self, operation: Operation) -> None:
        self.calls.append(operation.operation_id)
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if outcome is not None:
            raise outcome


class RecordingTelemetry:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, str | int | bool | None]]] = []

    async def emit(self, event: str, **fields: str | int | bool | None) -> None:
        self.events.append((event, fields))
