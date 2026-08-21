from datetime import UTC, datetime
from typing import Protocol

from veritas_runtime.changes.models import EvidenceSourceRegistration
from veritas_runtime.packets.models import ClaimManifest


class EvidenceRegistrationRepository(Protocol):
    async def register_sources(
        self,
        registrations: tuple[EvidenceSourceRegistration, ...],
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
