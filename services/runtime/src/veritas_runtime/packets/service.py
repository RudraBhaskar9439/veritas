import httpx

from veritas_runtime.changes.models import EvidenceSourceRegistration
from veritas_runtime.changes.registration import (
    EvidenceBaselineCaptureService,
    ManifestEvidenceRegistrar,
)
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
        baseline_capture: EvidenceBaselineCaptureService | None = None,
    ) -> None:
        self._sessions = sessions
        self._manifests = manifests
        self._http = http
        self._evidence_registrar = evidence_registrar
        self._watch_coordinator = watch_coordinator
        self._drive_webhook_url = drive_webhook_url
        self._baseline_capture = baseline_capture

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
        if self._baseline_capture is not None and self._evidence_registrar is None:
            raise PacketGenerationError(
                "Evidence registration is required before baseline capture"
            )
        writer = GoogleWorkspacePacketWriter(session.access_token, session.email, self._http)
        try:
            registrations: tuple[EvidenceSourceRegistration, ...] = ()
            packet_sources = sources
            if self._evidence_registrar is not None and self._baseline_capture is not None:
                registrations = await self._evidence_registrar.register_snapshots(
                    subject,
                    blueprint.packet_id,
                    sources,
                )
                if self._watch_coordinator is not None and self._drive_webhook_url is not None:
                    await self._watch_coordinator.start(
                        subject,
                        session.access_token,
                        self._drive_webhook_url,
                    )
                baselines = await self._baseline_capture.capture(
                    registrations,
                    sources,
                    session.access_token,
                    reconcile_workspace_versions=True,
                    include_existing=True,
                )
                versions = {
                    snapshot.source_id: snapshot.workspace_version for snapshot in baselines
                }
                if set(versions) != {source.source_id for source in sources}:
                    raise PacketGenerationError("Every registered source requires a baseline")
                packet_sources = tuple(
                    source.model_copy(update={"version": versions[source.source_id]})
                    for source in sources
                )
            result = await DecisionPacketGenerator(writer, self._manifests).generate(
                f"{subject}:{request_id}",
                blueprint,
                packet_sources,
            )
            if self._evidence_registrar is not None and not registrations:
                registrations = await self._evidence_registrar.register(subject, result.manifest)
            if (
                self._watch_coordinator is not None
                and self._drive_webhook_url is not None
                and self._baseline_capture is None
            ):
                await self._watch_coordinator.start(
                    subject,
                    session.access_token,
                    self._drive_webhook_url,
                )
            return result
        except WorkspacePacketWriteError as error:
            raise PacketGenerationError(str(error)) from error
