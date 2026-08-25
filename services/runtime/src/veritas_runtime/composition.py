from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx
from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncEngine

from veritas_runtime.auth.factory import GoogleAuthComponents, build_google_auth_components
from veritas_runtime.auth.routes import (
    LOCAL_SESSION_COOKIE_NAME,
    PRODUCTION_SESSION_COOKIE_NAME,
)
from veritas_runtime.auth.sessions import (
    ApplicationSessionCodec,
    InvalidApplicationSession,
    SessionPrincipal,
)
from veritas_runtime.changes.bootstrap import WorkspaceEvidenceBootstrapService
from veritas_runtime.changes.database import SqlWatchRepository
from veritas_runtime.changes.drive import GoogleDriveChangesClient
from veritas_runtime.changes.extractor import GoogleEvidenceExtractor
from veritas_runtime.changes.registration import (
    EvidenceBaselineCaptureService,
    ManifestEvidenceRegistrar,
)
from veritas_runtime.changes.service import DriveWatchCoordinator
from veritas_runtime.changes.snapshots import GcsSnapshotObjectStore, ImmutableSnapshotService
from veritas_runtime.changes.tokens import ChannelTokenCodec
from veritas_runtime.command_center.database import SqlCommandCenterRepository
from veritas_runtime.command_center.service import CommandCenterService
from veritas_runtime.database_runtime import DatabaseRuntime, build_database_runtime
from veritas_runtime.execution.database import SqlExecutionRepository
from veritas_runtime.execution.google import GoogleWorkspaceRepairGateway
from veritas_runtime.execution.service import RepairExecutionService
from veritas_runtime.execution.sessions import EncryptedWorkspaceSessionProvider
from veritas_runtime.lineage.database import SqlImpactRepository
from veritas_runtime.lineage.service import ImpactAnalysisService
from veritas_runtime.operations.database import SqlOperationRepository
from veritas_runtime.operations.service import ReliableOperationService
from veritas_runtime.operations.telemetry import StructuredLogOperationTelemetry
from veritas_runtime.orchestration import (
    ConsequenceRepairOrchestrator,
    HumanApprovalContinuation,
)
from veritas_runtime.packets.database import SqlManifestRepository
from veritas_runtime.packets.service import WorkspacePacketGenerationService
from veritas_runtime.repairs.database import SqlRepairRepository
from veritas_runtime.repairs.models import ApprovalActor, ApprovalActorKind
from veritas_runtime.repairs.service import RepairPlanningService
from veritas_runtime.settings import Settings
from veritas_runtime.verification.database import SqlVerificationRepository
from veritas_runtime.verification.google import GoogleWorkspaceVerificationGateway
from veritas_runtime.verification.service import (
    ProtectedRegionBaselineService,
    VerificationService,
)

PrincipalResolver = Callable[[Request], Awaitable[SessionPrincipal]]
SubjectResolver = Callable[[Request], Awaitable[str]]
ApprovalActorResolver = Callable[[Request], Awaitable[ApprovalActor]]
OperationActorResolver = Callable[[Request], Awaitable[str]]


@dataclass(frozen=True)
class ApiComponents:
    database: DatabaseRuntime
    engine: AsyncEngine
    http: httpx.AsyncClient
    auth: GoogleAuthComponents
    session_codec: ApplicationSessionCodec
    evidence: WorkspaceEvidenceBootstrapService
    packets: WorkspacePacketGenerationService
    impact: ImpactAnalysisService
    repairs: RepairPlanningService
    execution: RepairExecutionService
    verification: VerificationService
    operations: ReliableOperationService
    command_center: CommandCenterService
    approval_continuation: HumanApprovalContinuation

    async def close(self) -> None:
        await self.http.aclose()
        await self.database.close()


def build_api_components(settings: Settings) -> ApiComponents | None:
    if (
        not settings.database_configured
        or settings.snapshot_bucket is None
        or settings.application_session_key is None
        or not settings.google_auth_configured
    ):
        return None
    database = build_database_runtime(settings)
    if database is None:
        return None
    engine = database.engine
    auth = build_google_auth_components(settings, engine)
    if auth is None:
        return None
    session_codec = ApplicationSessionCodec.from_base64(
        settings.application_session_key.get_secret_value()
    )
    snapshot_objects = GcsSnapshotObjectStore(settings.snapshot_bucket)
    sessions = EncryptedWorkspaceSessionProvider(auth.vault, auth.oauth)
    http = httpx.AsyncClient(timeout=httpx.Timeout(20, connect=5))
    watch_repository = SqlWatchRepository(engine)
    watch_coordinator = None
    if settings.drive_channel_token_key is not None and settings.drive_webhook_url is not None:
        watch_coordinator = DriveWatchCoordinator(
            GoogleDriveChangesClient(http),
            watch_repository,
            ChannelTokenCodec.from_base64(settings.drive_channel_token_key.get_secret_value()),
        )
    snapshot_service = ImmutableSnapshotService(snapshot_objects)
    verification_repository = SqlVerificationRepository(engine, snapshot_objects)
    verification_gateway = GoogleWorkspaceVerificationGateway(http)
    repairs = RepairPlanningService(SqlRepairRepository(engine, snapshot_objects))
    execution = RepairExecutionService(
        SqlExecutionRepository(engine),
        sessions,
        GoogleWorkspaceRepairGateway(http),
        ProtectedRegionBaselineService(verification_repository, verification_gateway),
    )
    verification = VerificationService(
        verification_repository,
        sessions,
        verification_gateway,
    )
    command_center = CommandCenterService(SqlCommandCenterRepository(engine))
    orchestrator = ConsequenceRepairOrchestrator(
        ImpactAnalysisService(SqlImpactRepository(engine)),
        repairs,
        execution,
        verification,
    )
    return ApiComponents(
        database=database,
        engine=engine,
        http=http,
        auth=auth,
        session_codec=session_codec,
        evidence=WorkspaceEvidenceBootstrapService(sessions, http),
        packets=WorkspacePacketGenerationService(
            sessions,
            SqlManifestRepository(engine),
            http,
            ManifestEvidenceRegistrar(watch_repository),
            watch_coordinator,
            settings.drive_webhook_url,
            EvidenceBaselineCaptureService(
                watch_repository,
                GoogleEvidenceExtractor(http),
                snapshot_service,
            ),
        ),
        impact=ImpactAnalysisService(SqlImpactRepository(engine)),
        repairs=repairs,
        execution=execution,
        verification=verification,
        operations=ReliableOperationService(
            SqlOperationRepository(engine),
            {},
            telemetry=StructuredLogOperationTelemetry(),
        ),
        command_center=command_center,
        approval_continuation=HumanApprovalContinuation(
            command_center,
            repairs,
            orchestrator,
        ),
    )


def session_principal_resolver(
    codec: ApplicationSessionCodec,
    *,
    secure_cookie: bool,
) -> PrincipalResolver:
    cookie_name = PRODUCTION_SESSION_COOKIE_NAME if secure_cookie else LOCAL_SESSION_COOKIE_NAME

    async def resolve(request: Request) -> SessionPrincipal:
        encoded = request.cookies.get(cookie_name)
        if not encoded:
            raise HTTPException(status_code=401, detail="Application session is required")
        try:
            return codec.decode(encoded)
        except InvalidApplicationSession as error:
            raise HTTPException(status_code=401, detail="Application session is invalid") from error

    return resolve


def subject_resolver(codec: ApplicationSessionCodec, *, secure_cookie: bool) -> SubjectResolver:
    principal = session_principal_resolver(codec, secure_cookie=secure_cookie)

    async def resolve(request: Request) -> str:
        return (await principal(request)).subject

    return resolve


def approval_actor_resolver(
    codec: ApplicationSessionCodec, *, secure_cookie: bool
) -> ApprovalActorResolver:
    principal = session_principal_resolver(codec, secure_cookie=secure_cookie)

    async def resolve(request: Request) -> ApprovalActor:
        resolved = await principal(request)
        return ApprovalActor(
            kind=ApprovalActorKind.HUMAN,
            principal=resolved.email,
        )

    return resolve


def operation_actor_resolver(
    codec: ApplicationSessionCodec, *, secure_cookie: bool
) -> OperationActorResolver:
    principal = session_principal_resolver(codec, secure_cookie=secure_cookie)

    async def resolve(request: Request) -> str:
        return (await principal(request)).email

    return resolve
