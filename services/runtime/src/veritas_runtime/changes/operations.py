from typing import Protocol

from veritas_runtime.agents.service import AgentEscalationRequired, AgentReviewError
from veritas_runtime.changes.models import DriveNotificationOutboxEvent, EvidenceSnapshot
from veritas_runtime.execution.service import WorkspaceSession
from veritas_runtime.operations.models import Operation, OperationRequest
from veritas_runtime.operations.service import (
    PermanentOperationError,
    ReliableOperationService,
    RetryableOperationError,
)

DRIVE_PROCESS_OPERATION = "drive.process"


class NotificationOutboxRepository(Protocol):
    async def pending_notification_events(
        self, limit: int = 100
    ) -> tuple[DriveNotificationOutboxEvent, ...]: ...

    async def mark_notification_dispatched(self, event_id: str) -> bool: ...


class DriveStreamProcessor(Protocol):
    async def process_stream(
        self,
        stream_id: str,
        access_token: str,
        *,
        expected_subject: str | None = None,
    ) -> tuple[EvidenceSnapshot, ...]: ...


class WorkspaceSessionProvider(Protocol):
    async def get(self, subject: str) -> WorkspaceSession: ...


class SnapshotOrchestrator(Protocol):
    async def process(
        self,
        operation: Operation,
        snapshots: tuple[EvidenceSnapshot, ...],
    ) -> object: ...


class DriveNotificationOutboxDispatcher:
    """Moves committed webhook events into the idempotent operation ledger."""

    def __init__(
        self,
        repository: NotificationOutboxRepository,
        operations: ReliableOperationService,
    ) -> None:
        self._repository = repository
        self._operations = operations

    async def dispatch(self, limit: int = 100) -> int:
        dispatched = 0
        for event in await self._repository.pending_notification_events(limit):
            await self._operations.enqueue(
                OperationRequest(
                    subject=event.subject,
                    kind=DRIVE_PROCESS_OPERATION,
                    correlation_id=event.event_id,
                    idempotency_key=event.event_id,
                    payload={"streamId": event.stream_id},
                ),
                event.created_at,
            )
            if await self._repository.mark_notification_dispatched(event.event_id):
                dispatched += 1
        return dispatched


class DriveStreamOperationHandler:
    def __init__(
        self,
        processor: DriveStreamProcessor,
        sessions: WorkspaceSessionProvider,
        orchestrator: SnapshotOrchestrator | None = None,
    ) -> None:
        self._processor = processor
        self._sessions = sessions
        self._orchestrator = orchestrator

    async def handle(self, operation: Operation) -> None:
        stream_id = operation.payload.get("streamId")
        if not isinstance(stream_id, str) or not stream_id:
            raise PermanentOperationError("invalid_drive_stream_operation")
        session = await self._sessions.get(operation.subject)
        snapshots = await self._processor.process_stream(
            stream_id,
            session.access_token,
            expected_subject=operation.subject,
        )
        if self._orchestrator is not None:
            try:
                await self._orchestrator.process(operation, snapshots)
            except AgentEscalationRequired as error:
                raise PermanentOperationError("gemini_escalation_required") from error
            except AgentReviewError as error:
                raise RetryableOperationError("gemini_review_unavailable") from error
