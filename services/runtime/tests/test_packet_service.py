import asyncio

import httpx
import pytest

import veritas_runtime.packets.service as packet_service
from packet_support import (
    MemoryManifestRepository,
    RecordingArtifactWriter,
    load_generation_request,
)
from veritas_runtime.execution.service import WorkspaceSession
from veritas_runtime.packets.service import WorkspacePacketGenerationService
from veritas_runtime.workspace.contracts import WorkspaceAuthorization


class StaticSessions:
    def __init__(self, email: str | None = "owner@example.test") -> None:
        self.email = email

    async def get(self, subject: str) -> WorkspaceSession:
        assert subject == "subject-1"
        return WorkspaceSession(
            access_token="access-token",
            authorization=WorkspaceAuthorization(frozenset()),
            email=self.email,
        )


def test_subject_packet_service_binds_workspace_identity_and_idempotency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = RecordingArtifactWriter()

    def writer_factory(
        access_token: str, email: str, _http: httpx.AsyncClient
    ) -> RecordingArtifactWriter:
        assert access_token == "access-token"
        assert email == "owner@example.test"
        return writer

    monkeypatch.setattr(packet_service, "GoogleWorkspacePacketWriter", writer_factory)
    request_id, blueprint, sources = load_generation_request()
    manifests = MemoryManifestRepository()

    async def scenario() -> None:
        async with httpx.AsyncClient() as client:
            service = WorkspacePacketGenerationService(StaticSessions(), manifests, client)
            first = await service.generate_for_subject("subject-1", request_id, blueprint, sources)
            replay = await service.generate_for_subject("subject-1", request_id, blueprint, sources)
        assert first.reused is False
        assert replay.reused is True

    asyncio.run(scenario())
    assert len(writer.calls) == 5
    assert next(iter(manifests.records)).startswith("packet-q3-executive-review:subject-1:")


def test_subject_packet_service_rejects_session_without_verified_email() -> None:
    request_id, blueprint, sources = load_generation_request()

    async def scenario() -> None:
        async with httpx.AsyncClient() as client:
            service = WorkspacePacketGenerationService(
                StaticSessions(email=None), MemoryManifestRepository(), client
            )
            with pytest.raises(PermissionError, match="verified email"):
                await service.generate_for_subject("subject-1", request_id, blueprint, sources)

    asyncio.run(scenario())
