from dataclasses import dataclass

import httpx

from veritas_runtime.agents.database import SqlAgentReviewRepository
from veritas_runtime.agents.gemini import GeminiReviewGateway
from veritas_runtime.agents.service import GeminiConsequenceReviewService
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
from veritas_runtime.email_tasks.database import SqlEmailTaskWorkflowRepository
from veritas_runtime.email_tasks.gemini import GeminiEmailTaskGateway
from veritas_runtime.email_tasks.google import GoogleGmailTaskGateway
from veritas_runtime.email_tasks.processor import (
    GMAIL_PROCESS_OPERATION,
    GmailTaskOperationHandler,
    GmailTaskProcessor,
)
from veritas_runtime.email_tasks.service import GmailWatchRenewalService
from veritas_runtime.execution.database import SqlExecutionRepository
from veritas_runtime.execution.google import GoogleWorkspaceRepairGateway
from veritas_runtime.execution.service import RepairExecutionService
from veritas_runtime.execution.sessions import EncryptedWorkspaceSessionProvider
from veritas_runtime.lineage.database import SqlImpactRepository
from veritas_runtime.lineage.service import ImpactAnalysisService
from veritas_runtime.operations.database import SqlOperationRepository
from veritas_runtime.operations.models import OperationTick
from veritas_runtime.operations.service import ReliableOperationService
from veritas_runtime.operations.telemetry import StructuredLogOperationTelemetry
from veritas_runtime.orchestration import ConsequenceRepairOrchestrator
from veritas_runtime.repairs.database import SqlRepairRepository
from veritas_runtime.repairs.service import RepairPlanningService
from veritas_runtime.settings import Settings
from veritas_runtime.verification.database import SqlVerificationRepository
from veritas_runtime.verification.google import GoogleWorkspaceVerificationGateway
from veritas_runtime.verification.service import ProtectedRegionBaselineService, VerificationService


class WorkerRuntimeService:
    def __init__(
        self,
        operations: ReliableOperationService,
        outbox: DriveNotificationOutboxDispatcher,
        watch_renewer: GmailWatchRenewalService | None = None,
        *,
        batch_size: int = 10,
    ) -> None:
        self._operations = operations
        self._outbox = outbox
        self._watch_renewer = watch_renewer
        self._batch_size = batch_size

    async def tick(self, worker_id: str) -> tuple[OperationTick, ...]:
        await self._outbox.dispatch(limit=100)
        results: list[OperationTick] = []
        for index in range(self._batch_size):
            tick = await self._operations.tick(f"{worker_id}:{index}")
            results.append(tick)
            if tick.operation_id is None:
                break
        if self._watch_renewer is not None:
            await self._watch_renewer.renew()
        return tuple(results)


@dataclass(frozen=True)
class WorkerComponents:
    database: DatabaseRuntime
    http: httpx.AsyncClient
    auth: GoogleAuthComponents
    service: WorkerRuntimeService
    gemini: GeminiReviewGateway
    email_gemini: GeminiEmailTaskGateway

    async def close(self) -> None:
        await self.email_gemini.close()
        await self.gemini.close()
        await self.http.aclose()
        await self.database.close()


def build_worker_components(settings: Settings) -> WorkerComponents | None:
    if (
        not settings.database_configured
        or settings.snapshot_bucket is None
        or not settings.google_auth_configured
        or not settings.gemini_configured
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
    snapshot_objects = GcsSnapshotObjectStore(settings.snapshot_bucket)
    processor = DriveChangeProcessor(
        GoogleDriveChangesClient(http),
        GoogleEvidenceExtractor(http),
        ImmutableSnapshotService(snapshot_objects),
        watch_repository,
    )
    verification_repository = SqlVerificationRepository(database.engine, snapshot_objects)
    verification_gateway = GoogleWorkspaceVerificationGateway(http)
    assert settings.google_cloud_project is not None
    gemini = GeminiReviewGateway(
        settings.google_cloud_project,
        settings.google_cloud_location,
        settings.gemini_model,
    )
    email_gemini = GeminiEmailTaskGateway(
        settings.google_cloud_project,
        settings.google_cloud_location,
        settings.gemini_model,
    )
    execution = RepairExecutionService(
        SqlExecutionRepository(database.engine),
        sessions,
        GoogleWorkspaceRepairGateway(http),
        ProtectedRegionBaselineService(verification_repository, verification_gateway),
    )
    orchestrator = ConsequenceRepairOrchestrator(
        ImpactAnalysisService(SqlImpactRepository(database.engine)),
        RepairPlanningService(SqlRepairRepository(database.engine, snapshot_objects)),
        execution,
        VerificationService(verification_repository, sessions, verification_gateway),
        GeminiConsequenceReviewService(
            SqlAgentReviewRepository(database.engine),
            gemini,
            settings.gemini_model,
        ),
    )
    email_repository = SqlEmailTaskWorkflowRepository(database.engine)
    gmail_gateway = GoogleGmailTaskGateway(http)
    operations = ReliableOperationService(
        SqlOperationRepository(database.engine),
        {
            DRIVE_PROCESS_OPERATION: DriveStreamOperationHandler(
                processor,
                sessions,
                orchestrator,
            ),
            GMAIL_PROCESS_OPERATION: GmailTaskOperationHandler(
                GmailTaskProcessor(
                    email_repository,
                    gmail_gateway,
                    email_gemini,
                ),
                sessions,
            ),
        },
        telemetry=StructuredLogOperationTelemetry(),
    )
    return WorkerComponents(
        database=database,
        http=http,
        auth=auth,
        gemini=gemini,
        email_gemini=email_gemini,
        service=WorkerRuntimeService(
            operations,
            DriveNotificationOutboxDispatcher(watch_repository, operations),
            GmailWatchRenewalService(
                email_repository,
                sessions,
                gmail_gateway,
                settings.gmail_pubsub_topic,
            )
            if settings.gmail_pubsub_topic is not None
            else None,
        ),
    )
