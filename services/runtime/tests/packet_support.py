import json
from datetime import UTC, datetime
from pathlib import Path

from veritas_runtime.packets.generator import (
    IdempotencyConflict,
    PersistedManifest,
    manifest_checksum,
)
from veritas_runtime.packets.models import (
    ClaimManifest,
    DecisionPacketBlueprint,
    ManifestDraft,
    MaterializedArtifact,
    PacketArtifactDraft,
    SourceSnapshot,
)

REPOSITORY_ROOT = Path(__file__).parents[3]
NOW = datetime(2026, 8, 21, 0, 0, tzinfo=UTC)


def load_generation_request() -> tuple[str, DecisionPacketBlueprint, tuple[SourceSnapshot, ...]]:
    payload = json.loads((REPOSITORY_ROOT / "fixtures/demo/q3-generation-request.json").read_text())
    return (
        str(payload["requestId"]),
        DecisionPacketBlueprint.model_validate(payload["blueprint"]),
        tuple(SourceSnapshot.model_validate(source) for source in payload["sources"]),
    )


class RecordingArtifactWriter:
    def __init__(self, *, omit_anchor: bool = False, wrong_artifact: bool = False) -> None:
        self.calls: list[tuple[PacketArtifactDraft, str]] = []
        self._results: dict[str, MaterializedArtifact] = {}
        self._omit_anchor = omit_anchor
        self._wrong_artifact = wrong_artifact

    async def materialize(
        self,
        draft: PacketArtifactDraft,
        request_id: str,
    ) -> MaterializedArtifact:
        self.calls.append((draft, request_id))
        if request_id in self._results:
            return self._results[request_id]
        anchors = {
            block.claim_id: f"workspace://{draft.artifact_id}#{block.slot}"
            for block in draft.claim_blocks
        }
        if self._omit_anchor:
            anchors.pop(next(iter(anchors)))
        result = MaterializedArtifact(
            artifact_id=(
                "unexpected-artifact"
                if self._wrong_artifact and draft.artifact_id == "artifact-board-memo"
                else draft.artifact_id
            ),
            resource_id=f"workspace-{draft.artifact_id}",
            container_id=("workspace-task-list" if draft.kind.value == "google_task" else None),
            revision_id="workspace-revision-1",
            anchors=anchors,
        )
        self._results[request_id] = result
        return result


class MemoryManifestRepository:
    def __init__(self) -> None:
        self.records: dict[str, PersistedManifest] = {}
        self.persist_calls = 0

    async def get_by_idempotency_key(self, key: str) -> PersistedManifest | None:
        return self.records.get(key)

    async def persist(
        self,
        draft: ManifestDraft,
        idempotency_key: str,
        input_digest: str,
        now: datetime,
    ) -> PersistedManifest:
        self.persist_calls += 1
        existing = self.records.get(idempotency_key)
        if existing is not None:
            if existing.input_digest != input_digest:
                raise IdempotencyConflict("Generation request ID was reused with different inputs")
            return existing
        version = 1 + sum(
            record.manifest.packet_id == draft.packet_id for record in self.records.values()
        )
        manifest = ClaimManifest(
            manifest_id=f"manifest-memory-{len(self.records) + 1}",
            packet_id=draft.packet_id,
            version=version,
            created_at=now,
            sources=draft.sources,
            artifacts=draft.artifacts,
            claims=draft.claims,
        )
        persisted = PersistedManifest(
            manifest=manifest,
            checksum=manifest_checksum(manifest),
            input_digest=input_digest,
        )
        self.records[idempotency_key] = persisted
        return persisted
