import asyncio
from datetime import UTC, datetime

import pytest

from operations_support import MemoryOperationRepository
from veritas_runtime.agents.service import AgentEscalationRequired, AgentReviewError
from veritas_runtime.changes.models import DriveNotificationOutboxEvent, EvidenceSnapshot
from veritas_runtime.changes.operations import (
    DRIVE_PROCESS_OPERATION,
    DriveNotificationOutboxDispatcher,
    DriveStreamOperationHandler,
)
from veritas_runtime.execution.service import WorkspaceSession
from veritas_runtime.operations.models import OperationRequest
from veritas_runtime.operations.service import (
    PermanentOperationError,
    ReliableOperationService,
    RetryableOperationError,
)
from veritas_runtime.settings import Settings
from veritas_runtime.worker_runtime import WorkerRuntimeService, build_worker_components
from veritas_runtime.workspace.contracts import WorkspaceAuthorization

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


class MemoryOutbox:
    def __init__(self) -> None:
        self.event = DriveNotificationOutboxEvent(
            event_id="drive-notification:channel-1:2",
            stream_id="stream-1",
            subject="subject-1",
            channel_id="channel-1",
            message_number=2,
            attempts=0,
            created_at=NOW,
        )
        self.dispatched = False

    async def pending_notification_events(
        self, limit: int = 100
    ) -> tuple[DriveNotificationOutboxEvent, ...]:
        assert limit == 100
        return () if self.dispatched else (self.event,)

    async def mark_notification_dispatched(self, event_id: str) -> bool:
        assert event_id == self.event.event_id
        if self.dispatched:
            return False
        self.dispatched = True
        return True


class FakeSessions:
    async def get(self, subject: str) -> WorkspaceSession:
        assert subject == "subject-1"
        return WorkspaceSession(
            access_token="access-token",
            authorization=WorkspaceAuthorization(frozenset()),
        )


class FakeProcessor:
    def __init__(self, snapshots: tuple[EvidenceSnapshot, ...] = ()) -> None:
        self.calls: list[tuple[str, str, str | None]] = []
        self.snapshots = snapshots

    async def process_stream(
        self,
        stream_id: str,
        access_token: str,
        *,
        expected_subject: str | None = None,
    ) -> tuple[EvidenceSnapshot, ...]:
        self.calls.append((stream_id, access_token, expected_subject))
        return self.snapshots


class FakeOrchestrator:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, tuple[EvidenceSnapshot, ...]]] = []
        self.error = error

    async def process(
        self,
        operation,
        snapshots: tuple[EvidenceSnapshot, ...],
    ) -> None:  # type: ignore[no-untyped-def]
        self.calls.append((operation.operation_id, snapshots))
        if self.error is not None:
            raise self.error


def test_outbox_dispatches_once_and_worker_processes_subject_bound_stream() -> None:
    repository = MemoryOperationRepository()
    outbox = MemoryOutbox()
    processor = FakeProcessor()
    operations = ReliableOperationService(
        repository,
        {DRIVE_PROCESS_OPERATION: DriveStreamOperationHandler(processor, FakeSessions())},
    )
    dispatcher = DriveNotificationOutboxDispatcher(outbox, operations)

    async def scenario() -> None:
        assert await dispatcher.dispatch() == 1
        assert await dispatcher.dispatch() == 0
        tick = await operations.tick("worker-1", NOW)
        assert tick.operation_id is not None
        assert processor.calls == [("stream-1", "access-token", "subject-1")]

    asyncio.run(scenario())


def test_worker_runtime_drains_outbox_and_processes_a_bounded_batch() -> None:
    repository = MemoryOperationRepository()
    outbox = MemoryOutbox()
    processor = FakeProcessor()
    operations = ReliableOperationService(
        repository,
        {DRIVE_PROCESS_OPERATION: DriveStreamOperationHandler(processor, FakeSessions())},
    )
    runtime = WorkerRuntimeService(
        operations,
        DriveNotificationOutboxDispatcher(outbox, operations),
        batch_size=2,
    )

    async def scenario() -> None:
        ticks = await runtime.tick("scheduler")
        assert len(ticks) == 2
        assert ticks[0].operation_id is not None
        assert ticks[1].operation_id is None
        assert processor.calls == [("stream-1", "access-token", "subject-1")]

    asyncio.run(scenario())


def test_worker_composition_fails_closed_without_runtime_dependencies() -> None:
    assert build_worker_components(Settings()) is None


def test_drive_operation_rejects_missing_stream_payload() -> None:
    repository = MemoryOperationRepository()
    processor = FakeProcessor()
    handler = DriveStreamOperationHandler(processor, FakeSessions())

    async def scenario() -> None:
        operation, _ = await repository.enqueue(
            OperationRequest(
                subject="subject-1",
                kind=DRIVE_PROCESS_OPERATION,
                correlation_id="event-1",
                idempotency_key="event-1",
                payload={},
            ),
            NOW,
        )
        with pytest.raises(PermanentOperationError, match="invalid_drive_stream_operation"):
            await handler.handle(operation)
        assert processor.calls == []

    asyncio.run(scenario())


def test_drive_operation_hands_captured_snapshots_to_the_orchestrator() -> None:
    from repair_support import canonical_repair_context

    repository = MemoryOperationRepository()
    snapshots = canonical_repair_context().snapshot_metadata
    processor = FakeProcessor(snapshots)
    orchestrator = FakeOrchestrator()
    handler = DriveStreamOperationHandler(processor, FakeSessions(), orchestrator)

    async def scenario() -> None:
        operation, _ = await repository.enqueue(
            OperationRequest(
                subject="subject-1",
                kind=DRIVE_PROCESS_OPERATION,
                correlation_id="event-orchestrated",
                idempotency_key="event-orchestrated",
                payload={"streamId": "stream-1"},
            ),
            NOW,
        )
        await handler.handle(operation)
        assert orchestrator.calls == [(operation.operation_id, snapshots)]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("agent_error", "expected_error", "code"),
    [
        (
            AgentEscalationRequired("ambiguous authority"),
            PermanentOperationError,
            "gemini_escalation_required",
        ),
        (
            AgentReviewError("temporary model outage"),
            RetryableOperationError,
            "gemini_review_unavailable",
        ),
    ],
)
def test_drive_operation_translates_gemini_failures_without_leaking_payloads(
    agent_error: Exception,
    expected_error: type[Exception],
    code: str,
) -> None:
    repository = MemoryOperationRepository()
    handler = DriveStreamOperationHandler(
        FakeProcessor(),
        FakeSessions(),
        FakeOrchestrator(agent_error),
    )

    async def scenario() -> None:
        operation, _ = await repository.enqueue(
            OperationRequest(
                subject="subject-1",
                kind=DRIVE_PROCESS_OPERATION,
                correlation_id="event-gemini-error",
                idempotency_key="event-gemini-error",
                payload={"streamId": "stream-1"},
            ),
            NOW,
        )
        with pytest.raises(expected_error, match=code):
            await handler.handle(operation)

    asyncio.run(scenario())
