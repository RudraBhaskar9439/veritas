from datetime import datetime

from pydantic import Field

from veritas_runtime.packets.models import (
    ArtifactAnchor,
    ArtifactKind,
    ArtifactMutability,
    CamelModel,
    ClaimRisk,
)


class LineagePath(CamelModel):
    source_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    anchor: str = Field(min_length=1)


class ImpactClaim(CamelModel):
    claim_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    changed_source_ids: tuple[str, ...] = Field(min_length=1)
    artifact_anchors: tuple[ArtifactAnchor, ...] = Field(min_length=1)
    risk: ClaimRisk


class ImpactArtifact(CamelModel):
    artifact_id: str = Field(min_length=1)
    kind: ArtifactKind
    resource_id: str = Field(min_length=1)
    mutability: ArtifactMutability
    affected_claim_ids: tuple[str, ...] = Field(min_length=1)
    anchors: tuple[str, ...] = Field(min_length=1)


class ImpactCoverage(CamelModel):
    registered_claim_count: int = Field(ge=0)
    candidate_claim_count: int = Field(ge=0)
    affected_registered_claim_count: int = Field(ge=0)
    affected_artifact_count: int = Field(ge=0)


class ImpactReportDraft(CamelModel):
    subject: str = Field(min_length=1, exclude=True, repr=False)
    packet_id: str = Field(min_length=1)
    manifest_id: str = Field(min_length=1)
    manifest_version: int = Field(ge=1)
    snapshot_ids: tuple[str, ...] = Field(min_length=1)
    changed_source_ids: tuple[str, ...] = Field(min_length=1)
    affected_claims: tuple[ImpactClaim, ...]
    unaffected_registered_claim_ids: tuple[str, ...]
    candidate_claim_ids: tuple[str, ...]
    affected_artifacts: tuple[ImpactArtifact, ...]
    lineage_paths: tuple[LineagePath, ...]
    coverage: ImpactCoverage


class ImpactReport(CamelModel):
    report_id: str = Field(min_length=1)
    packet_id: str = Field(min_length=1)
    manifest_id: str = Field(min_length=1)
    manifest_version: int = Field(ge=1)
    version: int = Field(ge=1)
    created_at: datetime
    snapshot_ids: tuple[str, ...] = Field(min_length=1)
    changed_source_ids: tuple[str, ...] = Field(min_length=1)
    affected_claims: tuple[ImpactClaim, ...]
    unaffected_registered_claim_ids: tuple[str, ...]
    candidate_claim_ids: tuple[str, ...]
    affected_artifacts: tuple[ImpactArtifact, ...]
    lineage_paths: tuple[LineagePath, ...]
    coverage: ImpactCoverage


class ImpactAnalysisResult(CamelModel):
    report: ImpactReport
    checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    reused: bool


class ImpactRequest(CamelModel):
    request_id: str = Field(min_length=1)
    snapshot_ids: tuple[str, ...] = Field(min_length=1)
