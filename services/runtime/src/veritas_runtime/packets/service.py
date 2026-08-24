import httpx

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
    ) -> None:
        self._sessions = sessions
        self._manifests = manifests
        self._http = http

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
            return await DecisionPacketGenerator(writer, self._manifests).generate(
                f"{subject}:{request_id}",
                blueprint,
                sources,
            )
        except WorkspacePacketWriteError as error:
            raise PacketGenerationError(str(error)) from error
