from dataclasses import dataclass

import httpx

from veritas_runtime.auth.factory import GoogleAuthComponents, build_google_auth_components
from veritas_runtime.changes.database import SqlWatchRepository
from veritas_runtime.changes.drive import GoogleDriveChangesClient
from veritas_runtime.changes.extractor import GoogleEvidenceExtractor
from veritas_runtime.changes.operations import (
    DRIVE_PROCESS_OPERATION,
    DriveNotificationOutboxDispatcher,
    DriveStreamOperationHandler,
)
from veritas_runtime.changes.processor import DriveChangeProcessor
from veritas_runtime.changes.snapshots import GcsSnapshotObjectStore, ImmutableSnapshotService
from veritas_runtime.database_runtime import DatabaseRuntime, build_database_runtime
from veritas_runtime.execution.sessions import EncryptedWorkspaceSessionProvider
from veritas_runtime.operations.database import SqlOperationRepository
from veritas_runtime.operations.models import OperationTick
from veritas_runtime.operations.service import ReliableOperationService
from veritas_runtime.operations.telemetry import StructuredLogOperationTelemetry
from veritas_runtime.settings import Settings


class WorkerRuntimeService:
    def __init__(
        self,
        operations: ReliableOperationService,
        outbox: DriveNotificationOutboxDispatcher,
        *,
        batch_size: int = 10,
    ) -> None:
        self._operations = operations
        self._outbox = outbox
        self._batch_size = batch_size

    async def tick(self, worker_id: str) -> tuple[OperationTick, ...]:
        await self._outbox.dispatch(limit=100)
        results: list[OperationTick] = []
        for index in range(self._batch_size):
            tick = await self._operations.tick(f"{worker_id}:{index}")
            results.append(tick)
            if tick.operation_id is None:
                break
        return tuple(results)


@dataclass(frozen=True)
class WorkerComponents:
    database: DatabaseRuntime
    http: httpx.AsyncClient
    auth: GoogleAuthComponents
    service: WorkerRuntimeService

    async def close(self) -> None:
        await self.http.aclose()
        await self.database.close()


def build_worker_components(settings: Settings) -> WorkerComponents | None:
    if (
        not settings.database_configured
        or settings.snapshot_bucket is None
        or not settings.google_auth_configured
    ):
        return None
    database = build_database_runtime(settings)
    if database is None:
        return None
    auth = build_google_auth_components(settings, database.engine)
    if auth is None:
        return None
    http = httpx.AsyncClient(timeout=httpx.Timeout(20, connect=5))
    sessions = EncryptedWorkspaceSessionProvider(auth.vault, auth.oauth)
    watch_repository = SqlWatchRepository(database.engine)
    processor = DriveChangeProcessor(
        GoogleDriveChangesClient(http),
        GoogleEvidenceExtractor(http),
        ImmutableSnapshotService(GcsSnapshotObjectStore(settings.snapshot_bucket)),
        watch_repository,
    )
    operations = ReliableOperationService(
        SqlOperationRepository(database.engine),
        {DRIVE_PROCESS_OPERATION: DriveStreamOperationHandler(processor, sessions)},
        telemetry=StructuredLogOperationTelemetry(),
    )
    return WorkerComponents(
        database=database,
        http=http,
        auth=auth,
        service=WorkerRuntimeService(
            operations,
            DriveNotificationOutboxDispatcher(watch_repository, operations),
        ),
    )
