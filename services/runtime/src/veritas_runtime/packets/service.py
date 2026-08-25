import httpx

from veritas_runtime.changes.registration import ManifestEvidenceRegistrar
from veritas_runtime.changes.service import DriveWatchCoordinator
from veritas_runtime.execution.service import WorkspaceSessionProvider
from veritas_runtime.packets.generator import (
    DecisionPacketGenerator,
    ManifestRepository,
    PacketGenerationError,
)
from veritas_runtime.packets.google import (
    GoogleWorkspacePacketWriter,
    WorkspacePacketWriteError,
)
from veritas_runtime.packets.models import (
    DecisionPacketBlueprint,
    PacketGenerationResult,
    SourceSnapshot,
)


class WorkspacePacketGenerationService:
    def __init__(
        self,
        sessions: WorkspaceSessionProvider,
        manifests: ManifestRepository,
        http: httpx.AsyncClient,
        evidence_registrar: ManifestEvidenceRegistrar | None = None,
        watch_coordinator: DriveWatchCoordinator | None = None,
        drive_webhook_url: str | None = None,
    ) -> None:
        self._sessions = sessions
        self._manifests = manifests
        self._http = http
        self._evidence_registrar = evidence_registrar
        self._watch_coordinator = watch_coordinator
        self._drive_webhook_url = drive_webhook_url

    async def generate_for_subject(
        self,
        subject: str,
        request_id: str,
        blueprint: DecisionPacketBlueprint,
        sources: tuple[SourceSnapshot, ...],
    ) -> PacketGenerationResult:
        session = await self._sessions.get(subject)
        if not session.email:
            raise PermissionError("Connected Google account has no verified email")
        writer = GoogleWorkspacePacketWriter(session.access_token, session.email, self._http)
        try:
            result = await DecisionPacketGenerator(writer, self._manifests).generate(
                f"{subject}:{request_id}",
                blueprint,
                sources,
            )
            if self._evidence_registrar is not None:
                await self._evidence_registrar.register(subject, result.manifest)
            if self._watch_coordinator is not None and self._drive_webhook_url is not None:
                await self._watch_coordinator.start(
                    subject,
                    session.access_token,
                    self._drive_webhook_url,
                )
            return result
        except WorkspacePacketWriteError as error:
            raise PacketGenerationError(str(error)) from error
