import asyncio

import pytest

from packet_support import (
    NOW,
    MemoryManifestRepository,
    RecordingArtifactWriter,
    load_generation_request,
)
from veritas_runtime.changes.registration import ManifestEvidenceRegistrar
from veritas_runtime.packets.generator import DecisionPacketGenerator


class MemoryRegistrations:
    def __init__(self) -> None:
        self.values: tuple[object, ...] = ()

    async def register_sources(self, registrations: tuple[object, ...]) -> None:
        self.values = registrations


def test_manifest_sources_become_subject_and_packet_scoped_registrations() -> None:
    request_id, blueprint, sources = load_generation_request()
    repository = MemoryRegistrations()

    async def scenario() -> None:
        result = await DecisionPacketGenerator(
            RecordingArtifactWriter(), MemoryManifestRepository()
        ).generate(request_id, blueprint, sources, NOW)
        registrations = await ManifestEvidenceRegistrar(repository).register(
            "workspace-subject-1", result.manifest, NOW
        )
        assert len(registrations) == 5
        assert {registration.packet_id for registration in registrations} == {
            "packet-q3-executive-review"
        }
        assert {registration.subject for registration in registrations} == {"workspace-subject-1"}
        assert {registration.anchor for registration in registrations} == {
            "Metrics!B17",
            "Metrics!B5",
            "Metrics!B8",
            "Metrics!B20",
            "launch-date",
        }

        with pytest.raises(ValueError, match="subject"):
            await ManifestEvidenceRegistrar(repository).register("", result.manifest, NOW)

    asyncio.run(scenario())
