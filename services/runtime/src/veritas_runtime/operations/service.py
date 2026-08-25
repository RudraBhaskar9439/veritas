import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Protocol

from veritas_runtime.operations.models import (
    DeadLetterSummary,
    Operation,
    OperationRequest,
    OperationTick,
)


class OperationIdempotencyConflict(ValueError):
    """Raised when an idempotency key is reused with different work."""


class RetryableOperationError(RuntimeError):
    def __init__(self, code: str, *, retry_after_seconds: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.retry_after_seconds = retry_after_seconds


class PermanentOperationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class OperationRepository(Protocol):
    async def enqueue(self, request: OperationRequest, now: datetime) -> tuple[Operation, bool]: ...

    async def recover_expired(self, now: datetime) -> int: ...

    async def claim(
        self, worker_id: str, now: datetime, lease_expires_at: datetime
    ) -> Operation | None: ...

    async def succeed(self, operation: Operation, worker_id: str, now: datetime) -> Operation: ...

    async def retry(
        self,
        operation: Operation,
        worker_id: str,
        error_code: str,
        diagnostic_fingerprint: str,
        available_at: datetime,
        now: datetime,
    ) -> Operation: ...

    async def dead_letter(
        self,
        operation: Operation,
        worker_id: str,
        error_code: str,
        diagnostic_fingerprint: str,
        now: datetime,
    ) -> Operation: ...

    async def list_dead_letters(self, subject: str) -> tuple[DeadLetterSummary, ...]: ...

    async def replay(
        self,
        subject: str,
        operation_id: str,
        request_id: str,
        actor: str,
        reason: str,
        now: datetime,
    ) -> tuple[Operation, bool]: ...


class OperationHandler(Protocol):
    async def handle(self, operation: Operation) -> None: ...


class OperationTelemetry(Protocol):
    async def emit(self, event: str, **fields: str | int | bool | None) -> None: ...


class NullOperationTelemetry:
    async def emit(self, event: str, **fields: str | int | bool | None) -> None:
        del event, fields


class RetryPolicy:
    def __init__(self, base_seconds: int = 5, cap_seconds: int = 300) -> None:
        if base_seconds < 1 or cap_seconds < base_seconds:
            raise ValueError("Retry bounds are invalid")
        self._base_seconds = base_seconds
        self._cap_seconds = cap_seconds

    def delay_seconds(
        self,
        operation_id: str,
        attempt: int,
        retry_after_seconds: int | None = None,
    ) -> int:
        exponent: int = min(self._base_seconds * int(2 ** max(attempt - 1, 0)), self._cap_seconds)
        digest = hashlib.sha256(f"{operation_id}:{attempt}".encode()).digest()
        jitter = int.from_bytes(digest[:2]) % (min(self._base_seconds, exponent) + 1)
        computed = min(exponent + jitter, self._cap_seconds)
        if retry_after_seconds is None:
            return computed
        return min(max(computed, retry_after_seconds), self._cap_seconds)


class ReliableOperationService:
    def __init__(
        self,
        repository: OperationRepository,
        handlers: Mapping[str, OperationHandler],
        *,
        telemetry: OperationTelemetry | None = None,
        retry_policy: RetryPolicy | None = None,
        lease_seconds: int = 60,
    ) -> None:
        if lease_seconds < 10 or lease_seconds > 900:
            raise ValueError("Lease duration must be between 10 and 900 seconds")
        self._repository = repository
        self._handlers = dict(handlers)
        self._telemetry = telemetry or NullOperationTelemetry()
        self._retry_policy = retry_policy or RetryPolicy()
        self._lease_seconds = lease_seconds

    async def enqueue(
        self, request: OperationRequest, now: datetime | None = None
    ) -> tuple[Operation, bool]:
        current = _utc(now)
        operation, reused = await self._repository.enqueue(request, current)
        await self._telemetry.emit(
            "operation.enqueued",
            operation_id=operation.operation_id,
            kind=operation.kind,
            correlation_id=operation.correlation_id,
            reused=reused,
        )
        return operation, reused

    async def tick(self, worker_id: str, now: datetime | None = None) -> OperationTick:
        if not worker_id or len(worker_id) > 128:
            raise ValueError("A bounded worker ID is required")
        current = _utc(now)
        recovered = await self._repository.recover_expired(current)
        if recovered:
            await self._telemetry.emit("operation.leases_recovered", count=recovered)
        operation = await self._repository.claim(
            worker_id,
            current,
            current + timedelta(seconds=self._lease_seconds),
        )
        if operation is None:
            return OperationTick(status=None, recovered_leases=recovered)
        await self._telemetry.emit(
            "operation.started",
            operation_id=operation.operation_id,
            kind=operation.kind,
            attempt=operation.attempt,
            correlation_id=operation.correlation_id,
        )
        handler = self._handlers.get(operation.kind)
        if handler is None:
            return await self._quarantine(
                operation,
                worker_id,
                "unsupported_operation_kind",
                _fingerprint_text(operation.kind),
                current,
                recovered,
            )
        try:
            await handler.handle(operation)
        except PermanentOperationError as error:
            return await self._quarantine(
                operation,
                worker_id,
                _safe_code(error.code),
                _fingerprint(error),
                current,
                recovered,
            )
        except RetryableOperationError as error:
            return await self._retry_or_quarantine(
                operation,
                worker_id,
                _safe_code(error.code),
                _fingerprint(error),
                current,
                recovered,
                error.retry_after_seconds,
            )
        except Exception as error:
            fingerprint = _fingerprint(error)
            await self._telemetry.emit(
                "operation.failed",
                operation_id=operation.operation_id,
                kind=operation.kind,
                attempt=operation.attempt,
                error_type=type(error).__name__,
                diagnostic_fingerprint=fingerprint,
            )
            return await self._retry_or_quarantine(
                operation,
                worker_id,
                "unhandled_operation_failure",
                fingerprint,
                current,
                recovered,
                None,
            )
        completed = await self._repository.succeed(operation, worker_id, current)
        await self._telemetry.emit(
            "operation.succeeded",
            operation_id=completed.operation_id,
            kind=completed.kind,
            attempt=completed.attempt,
            correlation_id=completed.correlation_id,
        )
        return OperationTick(
            status=completed.status,
            operation_id=completed.operation_id,
            recovered_leases=recovered,
        )

    async def list_dead_letters(self, subject: str) -> tuple[DeadLetterSummary, ...]:
        if not subject:
            raise ValueError("Subject is required")
        return await self._repository.list_dead_letters(subject)

    async def replay(
        self,
        subject: str,
        operation_id: str,
        request_id: str,
        actor: str,
        reason: str,
        now: datetime | None = None,
    ) -> tuple[Operation, bool]:
        if not all((subject, operation_id, request_id, actor)) or len(reason.strip()) < 12:
            raise ValueError("Replay requires subject, operation, request, actor, and reason")
        replayed, reused = await self._repository.replay(
            subject,
            operation_id,
            request_id,
            actor,
            reason.strip(),
            _utc(now),
        )
        await self._telemetry.emit(
            "operation.replayed",
            operation_id=replayed.operation_id,
            replay_of=operation_id,
            actor=actor,
            reused=reused,
        )
        return replayed, reused

    async def _retry_or_quarantine(
        self,
        operation: Operation,
        worker_id: str,
        error_code: str,
        fingerprint: str,
        now: datetime,
        recovered: int,
        retry_after_seconds: int | None,
    ) -> OperationTick:
        if operation.attempt >= operation.max_attempts:
            return await self._quarantine(
                operation, worker_id, error_code, fingerprint, now, recovered
            )
        delay = self._retry_policy.delay_seconds(
            operation.operation_id,
            operation.attempt,
            retry_after_seconds,
        )
        available_at = now + timedelta(seconds=delay)
        retried = await self._repository.retry(
            operation,
            worker_id,
            error_code,
            fingerprint,
            available_at,
            now,
        )
        await self._telemetry.emit(
            "operation.retry_scheduled",
            operation_id=retried.operation_id,
            kind=retried.kind,
            attempt=retried.attempt,
            error_code=error_code,
            retry_delay_seconds=delay,
        )
        return OperationTick(
            status=retried.status,
            operation_id=retried.operation_id,
            recovered_leases=recovered,
            retry_at=available_at,
        )

    async def _quarantine(
        self,
        operation: Operation,
        worker_id: str,
        error_code: str,
        fingerprint: str,
        now: datetime,
        recovered: int,
    ) -> OperationTick:
        dead = await self._repository.dead_letter(
            operation,
            worker_id,
            error_code,
            fingerprint,
            now,
        )
        await self._telemetry.emit(
            "operation.dead_lettered",
            operation_id=dead.operation_id,
            kind=dead.kind,
            attempt=dead.attempt,
            error_code=error_code,
            diagnostic_fingerprint=fingerprint,
        )
        return OperationTick(
            status=dead.status,
            operation_id=dead.operation_id,
            recovered_leases=recovered,
        )


def payload_hash(payload: Mapping[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(UTC)
    return current.replace(tzinfo=UTC) if current.tzinfo is None else current.astimezone(UTC)


def _safe_code(value: str) -> str:
    normalized = "".join(
        character for character in value.lower() if character.isalnum() or character == "_"
    )
    return normalized[:80] or "operation_failure"


def _fingerprint(error: Exception) -> str:
    return _fingerprint_text(f"{type(error).__name__}:{error}")


def _fingerprint_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:24]
