import asyncio

import pytest

from change_support import MemorySnapshotObjects
from packet_support import (
    NOW,
    MemoryManifestRepository,
    RecordingArtifactWriter,
    load_generation_request,
)
from veritas_runtime.changes.models import EvidenceCapture, EvidenceSourceRegistration
from veritas_runtime.changes.registration import (
    EvidenceBaselineCaptureService,
    ManifestEvidenceRegistrar,
)
from veritas_runtime.changes.snapshots import ImmutableSnapshotService, SnapshotIntegrityError
from veritas_runtime.packets.generator import DecisionPacketGenerator
from veritas_runtime.packets.models import SourceKind, SourceSnapshot


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
        assert len(registrations) == 6
        assert {registration.packet_id for registration in registrations} == {
            "packet-q3-executive-review"
        }
        assert {registration.subject for registration in registrations} == {"workspace-subject-1"}
        assert {registration.anchor for registration in registrations} == {
            "Metrics!B17",
            "Metrics!B16",
            "Metrics!B5",
            "Metrics!B8",
            "Metrics!B20",
            "launch-date",
        }

        with pytest.raises(ValueError, match="subject"):
            await ManifestEvidenceRegistrar(repository).register("", result.manifest, NOW)

    asyncio.run(scenario())


class MemoryBaselines:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str, str], object] = {}

    async def latest_snapshot(self, subject: str, packet_id: str, source_id: str) -> object | None:
        return self.values.get((subject, packet_id, source_id))

    async def persist_baseline_snapshots(self, snapshots: tuple[object, ...]) -> None:
        for snapshot in snapshots:
            key = (snapshot.subject, snapshot.packet_id, snapshot.source_id)  # type: ignore[attr-defined]
            self.values[key] = snapshot


class StaticExtractor:
    def __init__(self, capture: EvidenceCapture) -> None:
        self.capture = capture
        self.calls = 0

    async def extract(
        self, access_token: str, registration: EvidenceSourceRegistration
    ) -> EvidenceCapture:
        assert access_token == "access-token"
        assert registration.source_id == self.capture.source_id
        self.calls += 1
        return self.capture


def test_baseline_capture_binds_live_evidence_and_never_rebaselines_history() -> None:
    registration = EvidenceSourceRegistration(
        subject="subject-1",
        packet_id="packet-1",
        source_id="source-1",
        kind=SourceKind.GOOGLE_SHEET,
        resource_id="sheet-1",
        anchor="Metrics!B17",
        registered_at=NOW,
    )
    source = SourceSnapshot(
        source_id="source-1",
        kind=SourceKind.GOOGLE_SHEET,
        resource_id="sheet-1",
        anchor="Metrics!B17",
        version="7",
        value=0.04,
    )
    capture = EvidenceCapture(
        subject="subject-1",
        packet_id="packet-1",
        source_id="source-1",
        resource_id="sheet-1",
        workspace_version="7",
        mime_type="application/vnd.google-apps.spreadsheet",
        evidence={"Metrics!B17": 0.04},
    )
    repository = MemoryBaselines()
    extractor = StaticExtractor(capture)
    service = EvidenceBaselineCaptureService(
        repository,  # type: ignore[arg-type]
        extractor,
        ImmutableSnapshotService(MemorySnapshotObjects()),
    )

    async def scenario() -> None:
        first = await service.capture((registration,), (source,), "access-token", NOW)
        assert len(first) == 1
        assert first[0].delta_kind.value == "baseline"
        replay = await service.capture((registration,), (source,), "access-token", NOW)
        assert replay == ()
        assert extractor.calls == 1

        mismatched = EvidenceBaselineCaptureService(
            MemoryBaselines(),  # type: ignore[arg-type]
            StaticExtractor(capture.model_copy(update={"evidence": {"Metrics!B17": 0.09}})),
            ImmutableSnapshotService(MemorySnapshotObjects()),
        )
        with pytest.raises(SnapshotIntegrityError, match="does not match"):
            await mismatched.capture((registration,), (source,), "access-token", NOW)

        with pytest.raises(SnapshotIntegrityError, match="do not match"):
            await service.capture((), (source,), "access-token", NOW)

    asyncio.run(scenario())
