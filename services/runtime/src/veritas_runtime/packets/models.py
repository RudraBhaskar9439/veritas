from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

type JsonScalar = str | int | float | bool | None


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )


class SourceKind(StrEnum):
    GOOGLE_SHEET = "google_sheet"
    GOOGLE_DOC = "google_doc"


class ArtifactKind(StrEnum):
    GOOGLE_DOC = "google_doc"
    GOOGLE_SLIDES = "google_slides"
    GMAIL = "gmail"
    GOOGLE_TASK = "google_task"


class ArtifactMutability(StrEnum):
    EDITABLE = "editable"
    DRAFT_ONLY = "draft_only"
    IMMUTABLE = "immutable"


class ClaimRisk(StrEnum):
    INFORMATIONAL = "informational"
    REVERSIBLE = "reversible"
    DECISION_CHANGING = "decision_changing"
    IRREVERSIBLE = "irreversible"


class ProvenanceStatus(StrEnum):
    REGISTERED = "registered"
    CANDIDATE = "candidate"


class SourceSnapshot(CamelModel):
    source_id: str = Field(min_length=1)
    kind: SourceKind
    resource_id: str = Field(min_length=1)
    anchor: str = Field(min_length=1)
    version: str = Field(min_length=1)
    value: JsonScalar
    context: dict[str, JsonScalar] = Field(default_factory=dict)


class ArtifactBlueprint(CamelModel):
    artifact_id: str = Field(min_length=1)
    kind: ArtifactKind
    title: str = Field(min_length=1)
    mutability: ArtifactMutability


class ArtifactTarget(CamelModel):
    artifact_id: str = Field(min_length=1)
    slot: str = Field(min_length=1)


class ClaimBlueprint(CamelModel):
    claim_id: str = Field(min_length=1)
    source_ids: tuple[str, ...] = Field(min_length=1)
    artifact_targets: tuple[ArtifactTarget, ...] = Field(min_length=1)
    transformation: str = Field(min_length=1)
    parameters: dict[str, JsonScalar] = Field(default_factory=dict)
    risk: ClaimRisk
    provenance: ProvenanceStatus = ProvenanceStatus.REGISTERED
    freshness_hours: int = Field(ge=1)

    @model_validator(mode="after")
    def unique_references(self) -> "ClaimBlueprint":
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("claim source IDs must be unique")
        artifact_ids = [target.artifact_id for target in self.artifact_targets]
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("a claim may target an artifact only once")
        return self


class DecisionPacketBlueprint(CamelModel):
    packet_id: str = Field(min_length=1)
    artifacts: tuple[ArtifactBlueprint, ...] = Field(min_length=1)
    claims: tuple[ClaimBlueprint, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids(self) -> "DecisionPacketBlueprint":
        artifact_ids = [artifact.artifact_id for artifact in self.artifacts]
        claim_ids = [claim.claim_id for claim in self.claims]
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("artifact IDs must be unique")
        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError("claim IDs must be unique")
        return self


class SourceRecord(CamelModel):
    source_id: str
    kind: SourceKind
    resource_id: str
    anchor: str
    version: str


class ArtifactRecord(CamelModel):
    artifact_id: str
    kind: ArtifactKind
    resource_id: str
    mutability: ArtifactMutability


class ArtifactAnchor(CamelModel):
    artifact_id: str
    anchor: str


class ClaimRecord(CamelModel):
    claim_id: str
    statement: str
    source_ids: tuple[str, ...]
    artifact_anchors: tuple[ArtifactAnchor, ...]
    transformation: str | None = None
    risk: ClaimRisk
    provenance: ProvenanceStatus
    freshness_hours: int


class ClaimManifest(CamelModel):
    manifest_id: str
    packet_id: str
    version: int = Field(ge=1)
    created_at: datetime
    sources: tuple[SourceRecord, ...]
    artifacts: tuple[ArtifactRecord, ...]
    claims: tuple[ClaimRecord, ...]


class ManifestDraft(CamelModel):
    packet_id: str
    sources: tuple[SourceRecord, ...]
    artifacts: tuple[ArtifactRecord, ...]
    claims: tuple[ClaimRecord, ...]


class AnchoredClaimBlock(CamelModel):
    claim_id: str
    slot: str
    statement: str


class PacketArtifactDraft(CamelModel):
    artifact_id: str
    kind: ArtifactKind
    title: str
    mutability: ArtifactMutability
    claim_blocks: tuple[AnchoredClaimBlock, ...]


class MaterializedArtifact(CamelModel):
    artifact_id: str
    resource_id: str
    revision_id: str
    anchors: dict[str, str]


class PacketGenerationResult(CamelModel):
    manifest: ClaimManifest
    checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    reused: bool
