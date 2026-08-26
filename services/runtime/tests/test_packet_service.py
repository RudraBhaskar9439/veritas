import asyncio
from types import SimpleNamespace

import httpx
import pytest

import veritas_runtime.packets.service as packet_service
from packet_support import (
    NOW,
    MemoryManifestRepository,
    RecordingArtifactWriter,
    load_generation_request,
)
from veritas_runtime.changes.models import EvidenceSourceRegistration
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


def test_subject_packet_service_registers_watch_before_capturing_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    writer = RecordingArtifactWriter()

    monkeypatch.setattr(
        packet_service,
        "GoogleWorkspacePacketWriter",
        lambda _token, _email, _http: writer,
    )
    request_id, blueprint, sources = load_generation_request()

    class Registrar:
        async def register_snapshots(
            self,
            subject: str,
            packet_id: str,
            packet_sources: tuple[object, ...],
        ) -> tuple[object, ...]:
            events.append("register")
            return tuple(
                EvidenceSourceRegistration(
                    subject=subject,
                    packet_id=packet_id,
                    source_id=source.source_id,
                    kind=source.kind,
                    resource_id=source.resource_id,
                    anchor=source.anchor,
                    registered_at=NOW,
                )
                for source in packet_sources
            )

    class Watch:
        async def start(self, subject: str, token: str, url: str) -> None:
            assert (subject, token, url) == (
                "subject-1",
                "access-token",
                "https://veritas.test/drive",
            )
            events.append("watch")

    class Baseline:
        async def capture(
            self,
            registrations: tuple[object, ...],
            packet_sources: tuple[object, ...],
            token: str,
            *,
            reconcile_workspace_versions: bool,
            include_existing: bool,
        ) -> tuple[object, ...]:
            assert len(registrations) == len(sources)
            assert packet_sources == sources
            assert token == "access-token"
            assert reconcile_workspace_versions is True
            assert include_existing is True
            events.append("baseline")
            return tuple(
                SimpleNamespace(
                    source_id=source.source_id,
                    workspace_version=f"settled-{source.source_id}",
                )
                for source in sources
            )

    async def scenario() -> None:
        async with httpx.AsyncClient() as client:
            service = WorkspacePacketGenerationService(
                StaticSessions(),
                MemoryManifestRepository(),
                client,
                Registrar(),  # type: ignore[arg-type]
                Watch(),  # type: ignore[arg-type]
                "https://veritas.test/drive",
                Baseline(),  # type: ignore[arg-type]
            )
            result = await service.generate_for_subject("subject-1", request_id, blueprint, sources)
            assert {source.version for source in result.manifest.sources} == {
                f"settled-{source.source_id}" for source in sources
            }

    asyncio.run(scenario())
    assert events == ["register", "watch", "baseline"]
