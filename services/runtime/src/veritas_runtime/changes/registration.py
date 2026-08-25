from datetime import UTC, datetime
from typing import Protocol

from veritas_runtime.changes.extractor import EvidenceExtractor
from veritas_runtime.changes.models import (
    DeltaKind,
    EvidenceSnapshot,
    EvidenceSourceRegistration,
)
from veritas_runtime.changes.snapshots import ImmutableSnapshotService, SnapshotIntegrityError
from veritas_runtime.packets.models import ClaimManifest, SourceSnapshot


class EvidenceRegistrationRepository(Protocol):
    async def register_sources(
        self,
        registrations: tuple[EvidenceSourceRegistration, ...],
    ) -> None: ...


class EvidenceBaselineRepository(Protocol):
    async def latest_snapshot(
        self,
        subject: str,
        packet_id: str,
        source_id: str,
    ) -> EvidenceSnapshot | None: ...

    async def persist_baseline_snapshots(
        self,
        snapshots: tuple[EvidenceSnapshot, ...],
    ) -> None: ...


class ManifestEvidenceRegistrar:
    def __init__(self, repository: EvidenceRegistrationRepository) -> None:
        self._repository = repository

    async def register(
        self,
        subject: str,
        manifest: ClaimManifest,
        now: datetime | None = None,
    ) -> tuple[EvidenceSourceRegistration, ...]:
        if not subject:
            raise ValueError("Workspace subject is required for evidence registration")
        registered_at = (now or datetime.now(UTC)).astimezone(UTC)
        registrations = tuple(
            EvidenceSourceRegistration(
                subject=subject,
                packet_id=manifest.packet_id,
                source_id=source.source_id,
                kind=source.kind,
                resource_id=source.resource_id,
                anchor=source.anchor,
                registered_at=registered_at,
            )
            for source in manifest.sources
        )
        await self._repository.register_sources(registrations)
        return registrations

    async def register_snapshots(
        self,
        subject: str,
        packet_id: str,
        sources: tuple[SourceSnapshot, ...],
        now: datetime | None = None,
    ) -> tuple[EvidenceSourceRegistration, ...]:
        if not subject or not packet_id:
            raise ValueError("Workspace subject and packet are required for evidence registration")
        registered_at = (now or datetime.now(UTC)).astimezone(UTC)
        registrations = tuple(
            EvidenceSourceRegistration(
                subject=subject,
                packet_id=packet_id,
                source_id=source.source_id,
                kind=source.kind,
                resource_id=source.resource_id,
                anchor=source.anchor,
                registered_at=registered_at,
            )
            for source in sources
        )
        await self._repository.register_sources(registrations)
        return registrations


class EvidenceBaselineCaptureService:
    """Captures the packet's real Workspace evidence before change processing begins."""

    def __init__(
        self,
        repository: EvidenceBaselineRepository,
        extractor: EvidenceExtractor,
        snapshots: ImmutableSnapshotService,
    ) -> None:
        self._repository = repository
        self._extractor = extractor
        self._snapshots = snapshots

    async def capture(
        self,
        registrations: tuple[EvidenceSourceRegistration, ...],
        sources: tuple[SourceSnapshot, ...],
        access_token: str,
        now: datetime | None = None,
        *,
        reconcile_workspace_versions: bool = False,
        include_existing: bool = False,
    ) -> tuple[EvidenceSnapshot, ...]:
        if not access_token:
            raise ValueError("Google access token is required for evidence baseline capture")
        source_by_id = {source.source_id: source for source in sources}
        if len(source_by_id) != len(sources):
            raise SnapshotIntegrityError("Baseline source IDs must be unique")
        registration_ids = {registration.source_id for registration in registrations}
        if registration_ids != set(source_by_id) or len(registration_ids) != len(registrations):
            raise SnapshotIntegrityError("Baseline sources do not match registered evidence")

        current_time = (now or datetime.now(UTC)).astimezone(UTC)
        baselines: list[EvidenceSnapshot] = []
        new_baselines: list[EvidenceSnapshot] = []
        for registration in registrations:
            source = source_by_id[registration.source_id]
            if (
                source.kind != registration.kind
                or source.resource_id != registration.resource_id
                or source.anchor != registration.anchor
            ):
                raise SnapshotIntegrityError("Baseline source identity does not match registration")
            existing = await self._repository.latest_snapshot(
                registration.subject,
                registration.packet_id,
                registration.source_id,
            )
            if existing is not None:
                if include_existing:
                    baselines.append(existing)
                continue

            capture = await self._extractor.extract(access_token, registration)
            if (
                capture.workspace_version != source.version
                and not reconcile_workspace_versions
            ):
                raise SnapshotIntegrityError("Workspace evidence changed before baseline capture")
            if capture.evidence != {registration.anchor: source.value}:
                raise SnapshotIntegrityError(
                    "Workspace evidence does not match packet source value"
                )
            result = await self._snapshots.capture(capture, None, current_time)
            if result.snapshot.delta_kind != DeltaKind.BASELINE:
                raise SnapshotIntegrityError("Initial evidence snapshot was not a baseline")
            baselines.append(result.snapshot)
            new_baselines.append(result.snapshot)

        await self._repository.persist_baseline_snapshots(tuple(new_baselines))
        return tuple(baselines)
