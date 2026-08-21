import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from veritas_runtime.auth.database import metadata
from veritas_runtime.operations.database import SqlOperationRepository
from veritas_runtime.operations.models import OperationRequest, OperationStatus
from veritas_runtime.operations.service import OperationIdempotencyConflict

NOW = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)


def test_sql_repository_lifecycle_recovery_and_audited_replay() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        repository = SqlOperationRepository(engine)
        request = OperationRequest(
            subject="subject-1",
            kind="repair.execute",
            correlation_id="incident-042",
            idempotency_key="operation-request-1",
            payload={"planId": "plan-1"},
            max_attempts=2,
        )
        queued, reused = await repository.enqueue(request, NOW)
        duplicate, duplicate_reused = await repository.enqueue(request, NOW)
        assert reused is False and duplicate_reused is True
        assert duplicate.operation_id == queued.operation_id
        with pytest.raises(OperationIdempotencyConflict):
            await repository.enqueue(
                request.model_copy(update={"payload": {"planId": "changed"}}), NOW
            )

        claimed = await repository.claim("worker-1", NOW, NOW + timedelta(seconds=10))
        assert claimed is not None and claimed.attempt == 1
        assert await repository.recover_expired(NOW + timedelta(seconds=11)) == 1
        recovered = await repository.claim(
            "worker-2", NOW + timedelta(seconds=11), NOW + timedelta(seconds=21)
        )
        assert recovered is not None and recovered.attempt == 2
        dead = await repository.dead_letter(
            recovered,
            "worker-2",
            "quota_exhausted",
            "abc123",
            NOW + timedelta(seconds=11),
        )
        assert dead.status == OperationStatus.DEAD_LETTER
        summaries = await repository.list_dead_letters("subject-1")
        assert len(summaries) == 1 and summaries[0].error_code == "quota_exhausted"
        replay, replay_reused = await repository.replay(
            "subject-1",
            dead.operation_id,
            "replay-1",
            "operator@example.test",
            "Dependency was corrected after reviewing the failure.",
            NOW + timedelta(seconds=12),
        )
        duplicate_replay, duplicate_was_reused = await repository.replay(
            "subject-1",
            dead.operation_id,
            "replay-1",
            "operator@example.test",
            "Dependency was corrected after reviewing the failure.",
            NOW + timedelta(seconds=12),
        )
        assert replay_reused is False and duplicate_was_reused is True
        assert duplicate_replay.operation_id == replay.operation_id
        replay_claim = await repository.claim(
            "worker-3", NOW + timedelta(seconds=12), NOW + timedelta(seconds=22)
        )
        assert replay_claim is not None
        succeeded = await repository.succeed(replay_claim, "worker-3", NOW + timedelta(seconds=13))
        assert succeeded.status == OperationStatus.SUCCEEDED
        await engine.dispose()

    asyncio.run(scenario())


def test_sql_repository_rejects_lost_lease_and_missing_dead_letter() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        repository = SqlOperationRepository(engine)
        request = OperationRequest(
            subject="subject-1",
            kind="repair.execute",
            correlation_id="incident-042",
            idempotency_key="operation-request-2",
            payload={},
        )
        await repository.enqueue(request, NOW)
        claimed = await repository.claim("worker-1", NOW, NOW + timedelta(seconds=60))
        assert claimed is not None
        with pytest.raises(RuntimeError):
            await repository.retry(
                claimed,
                "wrong-worker",
                "timeout",
                "fingerprint",
                NOW + timedelta(seconds=5),
                NOW,
            )
        with pytest.raises(LookupError):
            await repository.replay(
                "subject-1",
                "missing",
                "request",
                "actor",
                "A sufficiently detailed replay reason.",
                NOW,
            )
        await engine.dispose()

    asyncio.run(scenario())
