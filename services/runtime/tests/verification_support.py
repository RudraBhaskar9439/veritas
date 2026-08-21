import hashlib
from datetime import UTC, datetime

from packet_support import load_generation_request
from repair_support import MemoryRepairRepository
from veritas_runtime.changes.models import (
    DeltaKind,
    EvidenceSnapshot,
    StoredSnapshotObject,
)
from veritas_runtime.execution.models import (
    RepairRun,
    RepairRunStatus,
    StepExecutionRecord,
    StepExecutionStatus,
)
from veritas_runtime.packets.models import ArtifactRecord
from veritas_runtime.repairs.models import RepairOperation
from veritas_runtime.repairs.service import RepairPlanningService
from veritas_runtime.verification.models import (
    EvidenceIntegrityCertificate,
    ObservedStatement,
    ProtectedArtifactBaseline,
    ProtectedArtifactState,
    VerificationReport,
)
from veritas_runtime.verification.service import (
    PersistedVerification,
    VerificationContext,
    VerificationIdempotencyConflict,
    anchor_set_hash,
    certificate_checksum,
    verification_report_checksum,
)

NOW = datetime(2026, 8, 21, 5, 0, tzinfo=UTC)


async def canonical_verification_context() -> VerificationContext:
    repairs = MemoryRepairRepository()
    planned = await RepairPlanningService(repairs).create_plan(
        "subject-1",
        repairs.context.manifest.packet_id,
        "repair-request-1",
        repairs.context.impact.report_id,
        NOW,
    )
    plan = planned.plan
    records = tuple(
        StepExecutionRecord(
            step_id=step.step_id,
            status=StepExecutionStatus.SUCCEEDED,
            attempted_at=NOW,
            completed_at=NOW,
            before_revision_id="revision-before",
            after_revision_id="revision-after",
            external_id=(
                f"draft-{step.step_id}"
                if step.operation == RepairOperation.CREATE_CORRECTION_DRAFT
                else None
            ),
            detail="Applied the registered repair mutation.",
        )
        for step in plan.steps
    )
    run = RepairRun(
        run_id="run-canonical",
        plan_id=plan.plan_id,
        packet_id=plan.packet_id,
        status=RepairRunStatus.COMPLETED,
        created_at=NOW,
        updated_at=NOW,
        steps=records,
    )
    _, _, generation_sources = load_generation_request()
    sources = tuple(
        source.model_copy(update={"value": 0.09, "version": "sheet-v2"})
        if source.source_id == "src-churn"
        else source
        for source in generation_sources
    )
    plan_refs = {ref.source_id: ref for step in plan.steps for ref in step.source_versions}
    snapshots = tuple(
        EvidenceSnapshot(
            snapshot_id=(
                plan_refs[source.source_id].snapshot_id
                if source.source_id in plan_refs
                else f"snapshot-{source.source_id}-v1"
            ),
            subject="subject-1",
            packet_id=plan.packet_id,
            source_id=source.source_id,
            resource_id=source.resource_id,
            workspace_version=source.version,
            content_hash=(
                plan_refs[source.source_id].content_hash
                if source.source_id in plan_refs
                else hashlib.sha256(source.source_id.encode()).hexdigest()
            ),
            semantic_hash=hashlib.sha256(f"semantic:{source.source_id}".encode()).hexdigest(),
            storage=StoredSnapshotObject(
                bucket="snapshots",
                object_name=f"evidence/{source.source_id}.json",
                generation="1",
            ),
            delta_kind=(
                DeltaKind.MEANINGFUL if source.source_id == "src-churn" else DeltaKind.BASELINE
            ),
            created_at=NOW,
        )
        for source in sources
    )
    affected = sorted({step.artifact_id for step in plan.steps})
    baselines = tuple(
        ProtectedArtifactBaseline(
            run_id=run.run_id,
            artifact_id=artifact_id,
            resource_id=next(
                step.resource_id for step in plan.steps if step.artifact_id == artifact_id
            ),
            revision_id="revision-before",
            anchor_set_hash=anchor_set_hash(
                tuple(step.anchor for step in plan.steps if step.artifact_id == artifact_id)
            ),
            protected_content_hash=_protected_hash(artifact_id),
            captured_at=NOW,
        )
        for artifact_id in affected
    )
    return VerificationContext(
        manifest=repairs.context.manifest,
        plan=plan,
        run=run,
        sources=sources,
        snapshot_metadata=snapshots,
        baselines=baselines,
    )


class MemoryVerificationRepository:
    def __init__(self, context: VerificationContext) -> None:
        self.context = context
        self.persisted: dict[str, PersistedVerification] = {}
        self.baselines = context.baselines

    async def load_context(self, subject: str, run_id: str) -> VerificationContext:
        if subject != "subject-1":
            raise PermissionError("denied")
        if run_id != self.context.run.run_id:
            raise LookupError("run not found")
        return self.context.model_copy() if hasattr(self.context, "model_copy") else self.context

    async def get_by_idempotency_key(self, key: str) -> PersistedVerification | None:
        return self.persisted.get(key)

    async def persist(
        self,
        subject: str,
        report: VerificationReport,
        certificate: EvidenceIntegrityCertificate | None,
        idempotency_key: str,
        input_digest: str,
    ) -> PersistedVerification:
        assert subject == "subject-1"
        existing = self.persisted.get(idempotency_key)
        if existing is not None:
            if existing.input_digest != input_digest:
                raise VerificationIdempotencyConflict("different immutable inputs")
            return existing
        stored = PersistedVerification(
            report=report,
            report_checksum=verification_report_checksum(report),
            certificate=certificate,
            certificate_checksum=(
                certificate_checksum(certificate) if certificate is not None else None
            ),
            input_digest=input_digest,
        )
        self.persisted[idempotency_key] = stored
        return stored

    async def baselines_for_run(
        self, subject: str, run_id: str
    ) -> tuple[ProtectedArtifactBaseline, ...]:
        assert subject == "subject-1"
        return tuple(baseline for baseline in self.baselines if baseline.run_id == run_id)

    async def persist_baselines(
        self,
        subject: str,
        baselines: tuple[ProtectedArtifactBaseline, ...],
    ) -> tuple[ProtectedArtifactBaseline, ...]:
        assert subject == "subject-1"
        if self.baselines and self.baselines != baselines:
            raise VerificationIdempotencyConflict("baseline conflict")
        self.baselines = baselines
        return baselines


class MemoryIndependentVerifier:
    def __init__(self, context: VerificationContext) -> None:
        self.context = context
        self.registered: dict[tuple[str, str], str] = {}
        self.corrections: dict[str, str] = {}
        self.protected = {
            baseline.artifact_id: baseline.protected_content_hash for baseline in context.baselines
        }
        steps = {
            (step.claim_id, step.artifact_id, step.anchor): step for step in context.plan.steps
        }
        records = {record.step_id: record for record in context.run.steps}
        source_values = {source.source_id: source for source in context.sources}
        from veritas_runtime.packets.transformations import TransformationRegistry

        transformations = TransformationRegistry()
        for claim in context.manifest.claims:
            expected = transformations.render(claim, source_values)
            for anchor in claim.artifact_anchors:
                step = steps.get((claim.claim_id, anchor.artifact_id, anchor.anchor))
                if step is not None and step.operation == RepairOperation.CREATE_CORRECTION_DRAFT:
                    self.registered[(anchor.artifact_id, anchor.anchor)] = claim.statement
                    external_id = records[step.step_id].external_id
                    assert external_id is not None
                    self.corrections[external_id] = expected
                else:
                    self.registered[(anchor.artifact_id, anchor.anchor)] = expected

    async def read_registered(
        self,
        access_token: str,
        artifact: ArtifactRecord,
        anchor: str,
        expected: str,
        previous: str,
    ) -> ObservedStatement:
        assert access_token and expected and previous
        return ObservedStatement(
            resource_id=artifact.resource_id,
            revision_id="verification-revision",
            statement=self.registered[(artifact.artifact_id, anchor)],
        )

    async def read_correction(
        self,
        access_token: str,
        step,
        external_id: str,
    ) -> ObservedStatement:
        assert access_token and step
        return ObservedStatement(
            resource_id=external_id,
            revision_id="draft-revision",
            statement=self.corrections.get(external_id, "Missing correction draft."),
        )

    async def protected_state(
        self,
        access_token: str,
        artifact: ArtifactRecord,
        anchors: tuple[str, ...],
        registered_statements: tuple[str, ...],
    ) -> ProtectedArtifactState:
        assert access_token and len(anchors) == len(registered_statements)
        return ProtectedArtifactState(
            artifact_id=artifact.artifact_id,
            resource_id=artifact.resource_id,
            revision_id="verification-revision",
            anchor_set_hash=anchor_set_hash(anchors),
            protected_content_hash=self.protected[artifact.artifact_id],
        )


def _protected_hash(artifact_id: str) -> str:
    return hashlib.sha256(f"protected:{artifact_id}".encode()).hexdigest()
