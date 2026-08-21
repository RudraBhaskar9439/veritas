import asyncio
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from veritas_runtime.packets.models import (
    AnchoredClaimBlock,
    ArtifactAnchor,
    ArtifactRecord,
    ClaimManifest,
    ClaimRecord,
    DecisionPacketBlueprint,
    ManifestDraft,
    MaterializedArtifact,
    PacketArtifactDraft,
    PacketGenerationResult,
    SourceRecord,
    SourceSnapshot,
    TransformationSpec,
)
from veritas_runtime.packets.transformations import TransformationError, TransformationRegistry


class PacketGenerationError(ValueError):
    """A packet cannot be generated without violating its provenance contract."""


class IdempotencyConflict(PacketGenerationError):
    """A request ID was reused with different packet inputs."""


@dataclass(frozen=True)
class PersistedManifest:
    manifest: ClaimManifest
    checksum: str
    input_digest: str


class PacketArtifactWriter(Protocol):
    async def materialize(
        self,
        draft: PacketArtifactDraft,
        request_id: str,
    ) -> MaterializedArtifact: ...


class ManifestRepository(Protocol):
    async def get_by_idempotency_key(self, key: str) -> PersistedManifest | None: ...

    async def persist(
        self,
        draft: ManifestDraft,
        idempotency_key: str,
        input_digest: str,
        now: datetime,
    ) -> PersistedManifest: ...


class DecisionPacketGenerator:
    def __init__(
        self,
        writer: PacketArtifactWriter,
        manifests: ManifestRepository,
        transformations: TransformationRegistry | None = None,
    ) -> None:
        self._writer = writer
        self._manifests = manifests
        self._transformations = transformations or TransformationRegistry()

    async def generate(
        self,
        request_id: str,
        blueprint: DecisionPacketBlueprint,
        source_snapshots: tuple[SourceSnapshot, ...],
        now: datetime | None = None,
    ) -> PacketGenerationResult:
        if not request_id:
            raise PacketGenerationError("Generation request ID is required")
        sources = _indexed_sources(source_snapshots)
        artifact_ids = {artifact.artifact_id for artifact in blueprint.artifacts}
        _validate_lineage(blueprint, sources, artifact_ids)
        input_digest = _input_digest(blueprint, source_snapshots)
        idempotency_key = f"{blueprint.packet_id}:{request_id}"
        existing = await self._manifests.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            return _reuse(existing, input_digest)

        try:
            rendered_claims = {
                claim.claim_id: self._transformations.render(claim, sources)
                for claim in blueprint.claims
            }
        except TransformationError as error:
            raise PacketGenerationError(str(error)) from error
        drafts = tuple(
            PacketArtifactDraft(
                artifact_id=artifact.artifact_id,
                kind=artifact.kind,
                title=artifact.title,
                mutability=artifact.mutability,
                claim_blocks=tuple(
                    AnchoredClaimBlock(
                        claim_id=claim.claim_id,
                        slot=target.slot,
                        statement=rendered_claims[claim.claim_id],
                    )
                    for claim in blueprint.claims
                    for target in claim.artifact_targets
                    if target.artifact_id == artifact.artifact_id
                ),
            )
            for artifact in blueprint.artifacts
        )
        if any(not draft.claim_blocks for draft in drafts):
            raise PacketGenerationError("Every packet artifact must contain a monitored claim")

        materialized = await asyncio.gather(
            *(
                self._writer.materialize(
                    draft,
                    request_id=f"{idempotency_key}:{draft.artifact_id}",
                )
                for draft in drafts
            )
        )
        artifact_results = _validate_materialized(drafts, tuple(materialized))
        manifest_draft = _manifest_draft(
            blueprint,
            source_snapshots,
            rendered_claims,
            artifact_results,
        )
        persisted = await self._manifests.persist(
            manifest_draft,
            idempotency_key,
            input_digest,
            (now or datetime.now(UTC)).astimezone(UTC),
        )
        return _result(persisted, reused=False)


def _indexed_sources(snapshots: tuple[SourceSnapshot, ...]) -> dict[str, SourceSnapshot]:
    sources = {snapshot.source_id: snapshot for snapshot in snapshots}
    if not sources:
        raise PacketGenerationError("At least one source snapshot is required")
    if len(sources) != len(snapshots):
        raise PacketGenerationError("Source snapshot IDs must be unique")
    return sources


def _validate_lineage(
    blueprint: DecisionPacketBlueprint,
    sources: Mapping[str, SourceSnapshot],
    artifact_ids: set[str],
) -> None:
    for claim in blueprint.claims:
        unknown_sources = set(claim.source_ids) - set(sources)
        if unknown_sources:
            raise PacketGenerationError(
                f"Claim {claim.claim_id} references unknown source {sorted(unknown_sources)[0]}"
            )
        unknown_artifacts = {target.artifact_id for target in claim.artifact_targets} - artifact_ids
        if unknown_artifacts:
            raise PacketGenerationError(
                f"Claim {claim.claim_id} references unknown artifact {sorted(unknown_artifacts)[0]}"
            )


def _validate_materialized(
    drafts: tuple[PacketArtifactDraft, ...],
    results: tuple[MaterializedArtifact, ...],
) -> dict[str, MaterializedArtifact]:
    indexed = {result.artifact_id: result for result in results}
    if len(indexed) != len(results):
        raise PacketGenerationError("Artifact writer returned duplicate artifact IDs")
    if set(indexed) != {draft.artifact_id for draft in drafts}:
        raise PacketGenerationError("Artifact writer returned an unexpected artifact set")
    for draft in drafts:
        expected_claims = {block.claim_id for block in draft.claim_blocks}
        if set(indexed[draft.artifact_id].anchors) != expected_claims:
            raise PacketGenerationError(
                f"Artifact {draft.artifact_id} did not return every provenance anchor"
            )
    return indexed


def _manifest_draft(
    blueprint: DecisionPacketBlueprint,
    snapshots: tuple[SourceSnapshot, ...],
    rendered_claims: Mapping[str, str],
    artifacts: Mapping[str, MaterializedArtifact],
) -> ManifestDraft:
    artifact_blueprints = {artifact.artifact_id: artifact for artifact in blueprint.artifacts}
    return ManifestDraft(
        packet_id=blueprint.packet_id,
        sources=tuple(
            SourceRecord(
                source_id=source.source_id,
                kind=source.kind,
                resource_id=source.resource_id,
                anchor=source.anchor,
                version=source.version,
            )
            for source in snapshots
        ),
        artifacts=tuple(
            ArtifactRecord(
                artifact_id=artifact_id,
                kind=artifact_blueprints[artifact_id].kind,
                resource_id=result.resource_id,
                container_id=result.container_id,
                base_revision_id=result.revision_id,
                mutability=artifact_blueprints[artifact_id].mutability,
            )
            for artifact_id, result in artifacts.items()
        ),
        claims=tuple(
            ClaimRecord(
                claim_id=claim.claim_id,
                statement=rendered_claims[claim.claim_id],
                source_ids=claim.source_ids,
                artifact_anchors=tuple(
                    ArtifactAnchor(
                        artifact_id=target.artifact_id,
                        anchor=artifacts[target.artifact_id].anchors[claim.claim_id],
                    )
                    for target in claim.artifact_targets
                ),
                transformation=TransformationSpec(
                    name=claim.transformation,
                    version=claim.transformation_version,
                    parameters=claim.parameters,
                ),
                risk=claim.risk,
                provenance=claim.provenance,
                freshness_hours=claim.freshness_hours,
            )
            for claim in blueprint.claims
        ),
    )


def manifest_checksum(manifest: ClaimManifest) -> str:
    canonical = json.dumps(
        manifest.model_dump(mode="json", by_alias=True),
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _input_digest(
    blueprint: DecisionPacketBlueprint,
    snapshots: tuple[SourceSnapshot, ...],
) -> str:
    payload = {
        "blueprint": blueprint.model_dump(mode="json", by_alias=True),
        "sources": [
            source.model_dump(mode="json", by_alias=True)
            for source in sorted(snapshots, key=lambda item: item.source_id)
        ],
    }
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(canonical).hexdigest()


def _reuse(existing: PersistedManifest, input_digest: str) -> PacketGenerationResult:
    if existing.input_digest != input_digest:
        raise IdempotencyConflict("Generation request ID was reused with different inputs")
    return _result(existing, reused=True)


def _result(persisted: PersistedManifest, reused: bool) -> PacketGenerationResult:
    return PacketGenerationResult(
        manifest=persisted.manifest,
        checksum=persisted.checksum,
        reused=reused,
    )
