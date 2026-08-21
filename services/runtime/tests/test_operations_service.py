import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from operations_support import MemoryOperationRepository, RecordingTelemetry, ScriptedHandler
from veritas_runtime.operations.models import OperationRequest, OperationStatus
from veritas_runtime.operations.service import (
    OperationIdempotencyConflict,
    PermanentOperationError,
    ReliableOperationService,
    RetryableOperationError,
    RetryPolicy,
)
from veritas_runtime.operations.telemetry import StructuredLogOperationTelemetry

NOW = datetime(2026, 8, 21, 8, 0, tzinfo=UTC)


def request(*, max_attempts: int = 3) -> OperationRequest:
    return OperationRequest(
        subject="subject-1",
        kind="repair.execute",
        correlation_id="incident-042",
        idempotency_key="repair:incident-042",
        payload={"planId": "plan-1", "secret": "never-log-me"},
        max_attempts=max_attempts,
    )


def test_transient_failure_retries_deterministically_then_succeeds() -> None:
    async def scenario() -> None:
        repository = MemoryOperationRepository()
        telemetry = RecordingTelemetry()
        handler = ScriptedHandler(RetryableOperationError("quota_exhausted"), None)
        service = ReliableOperationService(
            repository,
            {"repair.execute": handler},
            telemetry=telemetry,
            retry_policy=RetryPolicy(base_seconds=5, cap_seconds=60),
        )
        operation, reused = await service.enqueue(request(), NOW)
        duplicate, duplicate_reused = await service.enqueue(request(), NOW)
        assert reused is False and duplicate_reused is True
        assert duplicate.operation_id == operation.operation_id

        first = await service.tick("worker-1", NOW)
        assert first.status == OperationStatus.RETRY_WAIT
        assert first.retry_at is not None and first.retry_at > NOW
        assert (await service.tick("worker-1", NOW)).status is None
        second = await service.tick("worker-1", first.retry_at)
        assert second.status == OperationStatus.SUCCEEDED
        assert len(handler.calls) == 2
        assert [event for event, _fields in telemetry.events].count("operation.enqueued") == 2

    asyncio.run(scenario())


def test_permanent_failure_is_quarantined_and_replay_is_idempotent() -> None:
    async def scenario() -> None:
        repository = MemoryOperationRepository()
        service = ReliableOperationService(
            repository,
            {"repair.execute": ScriptedHandler(PermanentOperationError("invalid_output"))},
        )
        operation, _ = await service.enqueue(request(), NOW)
        tick = await service.tick("worker-1", NOW)
        assert tick.status == OperationStatus.DEAD_LETTER
        dead = await service.list_dead_letters("subject-1")
        assert len(dead) == 1 and dead[0].error_code == "invalid_output"
        replay, reused = await service.replay(
            "subject-1",
            operation.operation_id,
            "replay-1",
            "operator@example.test",
            "Reviewed the failure and corrected its dependency.",
            NOW,
        )
        duplicate, duplicate_reused = await service.replay(
            "subject-1",
            operation.operation_id,
            "replay-1",
            "operator@example.test",
            "Reviewed the failure and corrected its dependency.",
            NOW,
        )
        assert reused is False and duplicate_reused is True
        assert replay.operation_id == duplicate.operation_id
        assert replay.replay_of == operation.operation_id

    asyncio.run(scenario())


def test_unknown_failure_is_redacted_and_exhaustion_dead_letters() -> None:
    async def scenario() -> None:
        repository = MemoryOperationRepository()
        secret_error = RuntimeError("access_token=super-secret")
        service = ReliableOperationService(
            repository,
            {"repair.execute": ScriptedHandler(secret_error, secret_error)},
        )
        operation, _ = await service.enqueue(request(max_attempts=2), NOW)
        first = await service.tick("worker-1", NOW)
        assert first.status == OperationStatus.RETRY_WAIT and first.retry_at is not None
        second = await service.tick("worker-1", first.retry_at)
        assert second.status == OperationStatus.DEAD_LETTER
        persisted = repository.operations[operation.operation_id]
        assert persisted.last_error_code == "unhandled_operation_failure"
        assert persisted.diagnostic_fingerprint
        assert "super-secret" not in persisted.model_dump_json()

    asyncio.run(scenario())


def test_unsupported_kind_and_retry_after_are_bounded() -> None:
    async def scenario() -> None:
        repository = MemoryOperationRepository()
        unsupported = ReliableOperationService(repository, {})
        await unsupported.enqueue(request(), NOW)
        assert (await unsupported.tick("worker-1", NOW)).status == OperationStatus.DEAD_LETTER

        second_repository = MemoryOperationRepository()
        service = ReliableOperationService(
            second_repository,
            {
                "repair.execute": ScriptedHandler(
                    RetryableOperationError("rate_limited", retry_after_seconds=9999)
                )
            },
            retry_policy=RetryPolicy(base_seconds=5, cap_seconds=30),
        )
        await service.enqueue(request(), NOW)
        tick = await service.tick("worker-1", NOW)
        assert tick.retry_at == NOW + timedelta(seconds=30)

    asyncio.run(scenario())


def test_expired_lease_is_recovered_before_new_claim() -> None:
    async def scenario() -> None:
        repository = MemoryOperationRepository()
        telemetry = RecordingTelemetry()
        service = ReliableOperationService(
            repository,
            {"repair.execute": ScriptedHandler(None)},
            telemetry=telemetry,
            lease_seconds=10,
        )
        operation, _ = await service.enqueue(request(), NOW)
        claimed = await repository.claim("crashed-worker", NOW, NOW + timedelta(seconds=10))
        assert claimed is not None
        tick = await service.tick("recovery-worker", NOW + timedelta(seconds=11))
        assert tick.status == OperationStatus.SUCCEEDED
        assert tick.recovered_leases == 1
        assert repository.operations[operation.operation_id].attempt == 2
        assert any(event == "operation.leases_recovered" for event, _ in telemetry.events)

    asyncio.run(scenario())


def test_validation_and_idempotency_conflicts_fail_closed() -> None:
    with pytest.raises(ValueError):
        RetryPolicy(0, 10)
    with pytest.raises(ValueError):
        ReliableOperationService(MemoryOperationRepository(), {}, lease_seconds=1)

    async def scenario() -> None:
        repository = MemoryOperationRepository()
        service = ReliableOperationService(repository, {})
        await service.enqueue(request(), NOW)
        changed = request().model_copy(update={"payload": {"planId": "different"}})
        with pytest.raises(OperationIdempotencyConflict):
            await service.enqueue(changed, NOW)
        with pytest.raises(ValueError):
            await service.tick("", NOW)
        with pytest.raises(ValueError):
            await service.list_dead_letters("")
        with pytest.raises(ValueError):
            await service.replay("subject-1", "op", "request", "actor", "too short", NOW)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (RetryableOperationError("workspace_token_expired"), OperationStatus.RETRY_WAIT),
        (RetryableOperationError("google_quota_exhausted"), OperationStatus.RETRY_WAIT),
        (RetryableOperationError("gemini_timeout"), OperationStatus.RETRY_WAIT),
        (RetryableOperationError("partial_artifact_failure"), OperationStatus.RETRY_WAIT),
        (PermanentOperationError("invalid_structured_output"), OperationStatus.DEAD_LETTER),
        (PermanentOperationError("human_edit_conflict"), OperationStatus.DEAD_LETTER),
        (
            PermanentOperationError("source_changed_during_execution"),
            OperationStatus.DEAD_LETTER,
        ),
    ],
)
def test_failure_taxonomy_is_explicit(
    failure: Exception,
    expected: OperationStatus,
) -> None:
    async def scenario() -> None:
        repository = MemoryOperationRepository()
        service = ReliableOperationService(
            repository,
            {"repair.execute": ScriptedHandler(failure)},
        )
        await service.enqueue(request(max_attempts=2), NOW)
        assert (await service.tick("worker-1", NOW)).status == expected

    asyncio.run(scenario())


def test_structured_log_telemetry_forwards_only_supplied_fields() -> None:
    class RecordingLogger:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        async def ainfo(self, event: str, **fields: object) -> None:
            self.calls.append((event, fields))

    async def scenario() -> None:
        telemetry = StructuredLogOperationTelemetry()
        logger = RecordingLogger()
        telemetry._logger = logger  # type: ignore[assignment]
        await telemetry.emit("operation.test", operation_id="op-1", attempt=2)
        assert logger.calls == [("operation.test", {"operation_id": "op-1", "attempt": 2})]

    asyncio.run(scenario())
