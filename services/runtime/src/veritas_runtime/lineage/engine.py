from veritas_runtime.changes.models import DeltaKind, EvidenceSnapshot
from veritas_runtime.lineage.models import (
    ImpactArtifact,
    ImpactClaim,
    ImpactCoverage,
    ImpactReportDraft,
    LineagePath,
)
from veritas_runtime.packets.models import ClaimManifest, ProvenanceStatus


class LineageIntegrityError(ValueError):
    """Impact analysis cannot proceed without valid registered lineage."""


class RegisteredLineageEngine:
    def analyze(
        self,
        subject: str,
        manifest: ClaimManifest,
        snapshots: tuple[EvidenceSnapshot, ...],
    ) -> ImpactReportDraft:
        if not subject:
            raise LineageIntegrityError("Workspace subject is required")
        if not snapshots:
            raise LineageIntegrityError("At least one meaningful snapshot is required")
        snapshot_ids = [snapshot.snapshot_id for snapshot in snapshots]
        if len(set(snapshot_ids)) != len(snapshot_ids):
            raise LineageIntegrityError("Snapshot IDs must be unique")
        changed_source_ids = [snapshot.source_id for snapshot in snapshots]
        if len(set(changed_source_ids)) != len(changed_source_ids):
            raise LineageIntegrityError("Only one changed snapshot per source is allowed")

        known_source_ids = {source.source_id for source in manifest.sources}
        for snapshot in snapshots:
            if snapshot.subject != subject or snapshot.packet_id != manifest.packet_id:
                raise LineageIntegrityError("Snapshot is outside the requested packet boundary")
            if snapshot.delta_kind != DeltaKind.MEANINGFUL:
                raise LineageIntegrityError("Only meaningful evidence changes enter lineage")
            if snapshot.source_id not in known_source_ids:
                raise LineageIntegrityError(
                    f"Snapshot source {snapshot.source_id} is not registered in the manifest"
                )

        changed_sources = set(changed_source_ids)
        registered_claims = tuple(
            claim for claim in manifest.claims if claim.provenance == ProvenanceStatus.REGISTERED
        )
        candidate_claims = tuple(
            claim for claim in manifest.claims if claim.provenance == ProvenanceStatus.CANDIDATE
        )
        affected_claim_records = tuple(
            claim for claim in registered_claims if changed_sources.intersection(claim.source_ids)
        )
        affected_claim_ids = {claim.claim_id for claim in affected_claim_records}
        affected_claims = tuple(
            ImpactClaim(
                claim_id=claim.claim_id,
                statement=claim.statement,
                changed_source_ids=tuple(
                    source_id for source_id in claim.source_ids if source_id in changed_sources
                ),
                artifact_anchors=claim.artifact_anchors,
                risk=claim.risk,
            )
            for claim in affected_claim_records
        )

        artifact_claims: dict[str, list[str]] = {}
        artifact_anchors: dict[str, list[str]] = {}
        paths: list[LineagePath] = []
        for claim in affected_claim_records:
            for anchor in claim.artifact_anchors:
                artifact_claims.setdefault(anchor.artifact_id, []).append(claim.claim_id)
                artifact_anchors.setdefault(anchor.artifact_id, []).append(anchor.anchor)
                paths.extend(
                    LineagePath(
                        source_id=source_id,
                        claim_id=claim.claim_id,
                        artifact_id=anchor.artifact_id,
                        anchor=anchor.anchor,
                    )
                    for source_id in claim.source_ids
                    if source_id in changed_sources
                )

        affected_artifacts = tuple(
            ImpactArtifact(
                artifact_id=artifact.artifact_id,
                kind=artifact.kind,
                resource_id=artifact.resource_id,
                mutability=artifact.mutability,
                affected_claim_ids=tuple(artifact_claims[artifact.artifact_id]),
                anchors=tuple(artifact_anchors[artifact.artifact_id]),
            )
            for artifact in manifest.artifacts
            if artifact.artifact_id in artifact_claims
        )
        return ImpactReportDraft(
            subject=subject,
            packet_id=manifest.packet_id,
            manifest_id=manifest.manifest_id,
            manifest_version=manifest.version,
            snapshot_ids=tuple(snapshot_ids),
            changed_source_ids=tuple(changed_source_ids),
            affected_claims=affected_claims,
            unaffected_registered_claim_ids=tuple(
                claim.claim_id
                for claim in registered_claims
                if claim.claim_id not in affected_claim_ids
            ),
            candidate_claim_ids=tuple(claim.claim_id for claim in candidate_claims),
            affected_artifacts=affected_artifacts,
            lineage_paths=tuple(paths),
            coverage=ImpactCoverage(
                registered_claim_count=len(registered_claims),
                candidate_claim_count=len(candidate_claims),
                affected_registered_claim_count=len(affected_claims),
                affected_artifact_count=len(affected_artifacts),
            ),
        )
