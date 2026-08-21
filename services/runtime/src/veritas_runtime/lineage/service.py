import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from veritas_runtime.changes.models import EvidenceSnapshot
from veritas_runtime.lineage.engine import RegisteredLineageEngine
from veritas_runtime.lineage.models import (
    ImpactAnalysisResult,
    ImpactReport,
    ImpactReportDraft,
)
from veritas_runtime.packets.models import ClaimManifest


class ImpactAnalysisError(ValueError):
    """A persisted blast-radius report cannot be safely produced."""


class ImpactIdempotencyConflict(ImpactAnalysisError):
    """An impact request ID was reused with different inputs."""


@dataclass(frozen=True)
class LineageContext:
    manifest: ClaimManifest
    snapshots: tuple[EvidenceSnapshot, ...]


@dataclass(frozen=True)
class PersistedImpact:
    report: ImpactReport
    checksum: str
    input_digest: str


class ImpactRepository(Protocol):
    async def load_context(
        self,
        subject: str,
        packet_id: str,
        snapshot_ids: tuple[str, ...],
    ) -> LineageContext: ...

    async def get_by_idempotency_key(self, key: str) -> PersistedImpact | None: ...

    async def persist(
        self,
        draft: ImpactReportDraft,
        idempotency_key: str,
        input_digest: str,
        now: datetime,
    ) -> PersistedImpact: ...


class ImpactAnalysisService:
    def __init__(
        self,
        repository: ImpactRepository,
        engine: RegisteredLineageEngine | None = None,
    ) -> None:
        self._repository = repository
        self._engine = engine or RegisteredLineageEngine()

    async def analyze(
        self,
        subject: str,
        packet_id: str,
        request_id: str,
        snapshot_ids: tuple[str, ...],
        now: datetime | None = None,
    ) -> ImpactAnalysisResult:
        if not subject or not packet_id or not request_id:
            raise ImpactAnalysisError("Subject, packet ID, and request ID are required")
        context = await self._repository.load_context(subject, packet_id, snapshot_ids)
        input_digest = _input_digest(context.manifest, snapshot_ids)
        idempotency_key = f"{subject}:{packet_id}:{request_id}"
        existing = await self._repository.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            return _reuse(existing, input_digest)
        draft = self._engine.analyze(subject, context.manifest, context.snapshots)
        persisted = await self._repository.persist(
            draft,
            idempotency_key,
            input_digest,
            (now or datetime.now(UTC)).astimezone(UTC),
        )
        return _result(persisted, reused=False)


def impact_checksum(report: ImpactReport) -> str:
    canonical = json.dumps(
        report.model_dump(mode="json", by_alias=True),
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _input_digest(manifest: ClaimManifest, snapshot_ids: tuple[str, ...]) -> str:
    payload = {
        "manifestId": manifest.manifest_id,
        "manifestVersion": manifest.version,
        "snapshotIds": sorted(snapshot_ids),
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _reuse(existing: PersistedImpact, input_digest: str) -> ImpactAnalysisResult:
    if existing.input_digest != input_digest:
        raise ImpactIdempotencyConflict(
            "Impact request ID was reused with different lineage inputs"
        )
    return _result(existing, reused=True)


def _result(persisted: PersistedImpact, reused: bool) -> ImpactAnalysisResult:
    return ImpactAnalysisResult(
        report=persisted.report,
        checksum=persisted.checksum,
        reused=reused,
    )
