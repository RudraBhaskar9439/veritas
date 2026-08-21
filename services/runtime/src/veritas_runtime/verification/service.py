import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from veritas_runtime.changes.models import EvidenceSnapshot
from veritas_runtime.execution.models import (
    RepairRun,
    RepairRunStatus,
    StepExecutionStatus,
)
from veritas_runtime.execution.service import WorkspaceSessionProvider
from veritas_runtime.packets.generator import manifest_checksum
from veritas_runtime.packets.models import (
    ArtifactMutability,
    ArtifactRecord,
    ClaimManifest,
    ProvenanceStatus,
    SourceSnapshot,
)
from veritas_runtime.packets.transformations import TransformationError, TransformationRegistry
from veritas_runtime.repairs.models import RepairOperation, RepairPlan, RepairStep, SourceVersionRef
from veritas_runtime.repairs.service import repair_plan_checksum
from veritas_runtime.verification.models import (
    CERTIFICATE_STATEMENT,
    EvidenceIntegrityCertificate,
    ObservedStatement,
    ProtectedArtifactBaseline,
    ProtectedArtifactState,
    VerificationCheck,
    VerificationCheckKind,
    VerificationCheckStatus,
    VerificationCoverage,
    VerificationReport,
    VerificationResult,
    VerificationStatus,
)


class VerificationIntegrityError(ValueError):
    """Persisted verification inputs violate an integrity boundary."""


class VerificationIdempotencyConflict(VerificationIntegrityError):
    """A verification request ID was reused with different immutable inputs."""


class VerificationReadError(RuntimeError):
    """An independent artifact read could not establish observable state."""


@dataclass(frozen=True)
class VerificationContext:
    manifest: ClaimManifest
    plan: RepairPlan
    run: RepairRun
    sources: tuple[SourceSnapshot, ...]
    snapshot_metadata: tuple[EvidenceSnapshot, ...]
    baselines: tuple[ProtectedArtifactBaseline, ...]


@dataclass(frozen=True)
class PersistedVerification:
    report: VerificationReport
    report_checksum: str
    certificate: EvidenceIntegrityCertificate | None
    certificate_checksum: str | None
    input_digest: str


class VerificationRepository(Protocol):
    async def load_context(self, subject: str, run_id: str) -> VerificationContext: ...

    async def get_by_idempotency_key(self, key: str) -> PersistedVerification | None: ...

    async def persist(
        self,
        subject: str,
        report: VerificationReport,
        certificate: EvidenceIntegrityCertificate | None,
        idempotency_key: str,
        input_digest: str,
    ) -> PersistedVerification: ...


class ProtectionBaselineRepository(Protocol):
    async def baselines_for_run(
        self, subject: str, run_id: str
    ) -> tuple[ProtectedArtifactBaseline, ...]: ...

    async def persist_baselines(
        self,
        subject: str,
        baselines: tuple[ProtectedArtifactBaseline, ...],
    ) -> tuple[ProtectedArtifactBaseline, ...]: ...


class IndependentWorkspaceVerifier(Protocol):
    async def read_registered(
        self,
        access_token: str,
        artifact: ArtifactRecord,
        anchor: str,
        expected: str,
        previous: str,
    ) -> ObservedStatement: ...

    async def read_correction(
        self,
        access_token: str,
        step: RepairStep,
        external_id: str,
    ) -> ObservedStatement: ...

    async def protected_state(
        self,
        access_token: str,
        artifact: ArtifactRecord,
        anchors: tuple[str, ...],
        registered_statements: tuple[str, ...],
    ) -> ProtectedArtifactState: ...


class ProtectedRegionBaselineService:
    """Captures all affected artifacts before the first mutation of a repair run."""

    def __init__(
        self,
        repository: ProtectionBaselineRepository,
        gateway: IndependentWorkspaceVerifier,
    ) -> None:
        self._repository = repository
        self._gateway = gateway

    async def capture(
        self,
        subject: str,
        run: RepairRun,
        plan: RepairPlan,
        access_token: str,
        now: datetime,
    ) -> None:
        existing = await self._repository.baselines_for_run(subject, run.run_id)
        affected_ids = {step.artifact_id for step in plan.steps}
        if existing:
            if {baseline.artifact_id for baseline in existing} != affected_ids:
                raise VerificationIntegrityError(
                    "Protected-region baseline set does not match the repair plan"
                )
            return
        grouped: dict[str, list[RepairStep]] = {}
        for step in plan.steps:
            grouped.setdefault(step.artifact_id, []).append(step)
        baselines: list[ProtectedArtifactBaseline] = []
        for artifact_id, steps in sorted(grouped.items()):
            first = steps[0]
            artifact = ArtifactRecord(
                artifact_id=artifact_id,
                kind=first.artifact_kind,
                resource_id=first.resource_id,
                container_id=first.container_id,
                base_revision_id=first.base_revision_id,
                mutability=_artifact_mutability(first),
            )
            anchors = tuple(step.anchor for step in steps)
            statements = tuple(step.before_statement for step in steps)
            state = await self._gateway.protected_state(
                access_token,
                artifact,
                anchors,
                statements,
            )
            if state.anchor_set_hash != anchor_set_hash(anchors):
                raise VerificationIntegrityError(
                    f"Protection gateway returned the wrong anchor set for {artifact_id}"
                )
            baselines.append(
                ProtectedArtifactBaseline(
                    run_id=run.run_id,
                    artifact_id=artifact_id,
                    resource_id=state.resource_id,
                    revision_id=state.revision_id,
                    anchor_set_hash=state.anchor_set_hash,
                    protected_content_hash=state.protected_content_hash,
                    captured_at=now,
                )
            )
        stored = await self._repository.persist_baselines(subject, tuple(baselines))
        if stored != tuple(baselines):
            raise VerificationIntegrityError("Protected-region baselines changed while persisting")


class VerificationService:
    def __init__(
        self,
        repository: VerificationRepository,
        sessions: WorkspaceSessionProvider,
        gateway: IndependentWorkspaceVerifier,
        transformations: TransformationRegistry | None = None,
    ) -> None:
        self._repository = repository
        self._sessions = sessions
        self._gateway = gateway
        self._transformations = transformations or TransformationRegistry()

    async def verify(
        self,
        subject: str,
        run_id: str,
        request_id: str,
        now: datetime | None = None,
    ) -> VerificationResult:
        if not subject or not run_id or not request_id:
            raise VerificationIntegrityError(
                "Subject, run ID, and verification request ID are required"
            )
        context = await self._repository.load_context(subject, run_id)
        _validate_context(context)
        input_digest = _input_digest(context)
        key = f"{subject}:{run_id}:{request_id}"
        existing = await self._repository.get_by_idempotency_key(key)
        if existing is not None:
            if existing.input_digest != input_digest:
                raise VerificationIdempotencyConflict(
                    "Verification request ID was reused with different immutable inputs"
                )
            return _result(existing, reused=True)

        verified_at = (now or datetime.now(UTC)).astimezone(UTC)
        session = await self._sessions.get(subject)
        checks: list[VerificationCheck] = []
        checks.append(_run_check(context))
        freshness_checks, is_stale = _freshness_checks(context)
        checks.extend(freshness_checks)

        expected_statements, deterministic_checks = self._recompute_claims(context)
        checks.extend(deterministic_checks)
        (
            target_checks,
            verified_claims,
            verified_targets,
            correction_count,
        ) = await self._verify_registered_targets(
            context,
            session.access_token,
            expected_statements,
        )
        checks.extend(target_checks)
        protection_checks, verified_protected = await self._verify_protected_regions(
            context,
            session.access_token,
            expected_statements,
        )
        checks.extend(protection_checks)

        registered_claims = tuple(
            claim
            for claim in context.manifest.claims
            if claim.provenance == ProvenanceStatus.REGISTERED
        )
        registered_targets = sum(len(claim.artifact_anchors) for claim in registered_claims)
        affected_artifacts = {step.artifact_id for step in context.plan.steps}
        candidates = sum(
            claim.provenance == ProvenanceStatus.CANDIDATE for claim in context.manifest.claims
        )
        coverage = VerificationCoverage(
            registered_claims=len(registered_claims),
            verified_registered_claims=len(verified_claims),
            registered_targets=registered_targets,
            verified_registered_targets=verified_targets,
            protected_artifacts=len(affected_artifacts),
            verified_protected_artifacts=verified_protected,
            correction_drafts=correction_count,
            candidate_claims_excluded=candidates,
        )
        coverage_ok = (
            coverage.verified_registered_claims == coverage.registered_claims
            and coverage.verified_registered_targets == coverage.registered_targets
            and coverage.verified_protected_artifacts == coverage.protected_artifacts
        )
        checks.append(
            _check(
                VerificationCheckKind.COVERAGE,
                "coverage",
                coverage_ok,
                (
                    "Every registered claim, target, and affected protected artifact was checked; "
                    f"{candidates} candidate claims were explicitly excluded."
                    if coverage_ok
                    else "Registered verification coverage is incomplete."
                ),
            )
        )
        failures = [check for check in checks if check.status == VerificationCheckStatus.FAILED]
        status = (
            VerificationStatus.STALE
            if is_stale
            else VerificationStatus.REJECTED
            if failures
            else VerificationStatus.VERIFIED
        )
        report_id = f"verification-{uuid5(NAMESPACE_URL, key)}"
        report = VerificationReport(
            report_id=report_id,
            run_id=context.run.run_id,
            plan_id=context.plan.plan_id,
            packet_id=context.manifest.packet_id,
            manifest_id=context.manifest.manifest_id,
            manifest_version=context.manifest.version,
            status=status,
            verified_at=verified_at,
            checks=tuple(checks),
            coverage=coverage,
        )
        report_hash = verification_report_checksum(report)
        certificate = None
        if status == VerificationStatus.VERIFIED:
            certificate = EvidenceIntegrityCertificate(
                certificate_id=f"certificate-{uuid5(NAMESPACE_URL, report_id)}",
                report_id=report_id,
                run_id=context.run.run_id,
                packet_id=context.manifest.packet_id,
                issued_at=verified_at,
                statement=CERTIFICATE_STATEMENT,
                coverage=coverage,
                evidence_versions=_certificate_sources(context),
                report_checksum=report_hash,
            )
        persisted = await self._repository.persist(
            subject,
            report,
            certificate,
            key,
            input_digest,
        )
        return _result(persisted, reused=False)

    def _recompute_claims(
        self, context: VerificationContext
    ) -> tuple[dict[str, str], list[VerificationCheck]]:
        sources = {source.source_id: source for source in context.sources}
        expected: dict[str, str] = {}
        checks: list[VerificationCheck] = []
        for claim in context.manifest.claims:
            if claim.provenance != ProvenanceStatus.REGISTERED:
                continue
            try:
                statement = self._transformations.render(claim, sources)
            except TransformationError:
                checks.append(
                    _check(
                        VerificationCheckKind.DETERMINISTIC_CLAIM,
                        f"claim:{claim.claim_id}",
                        False,
                        "The registered transformation could not be recomputed.",
                        claim_id=claim.claim_id,
                    )
                )
                continue
            expected[claim.claim_id] = statement
            checks.append(
                _check(
                    VerificationCheckKind.DETERMINISTIC_CLAIM,
                    f"claim:{claim.claim_id}",
                    True,
                    "The registered transformation recomputed deterministically.",
                    claim_id=claim.claim_id,
                    expected=statement,
                    observed=statement,
                )
            )
        return expected, checks

    async def _verify_registered_targets(
        self,
        context: VerificationContext,
        access_token: str,
        expected_statements: dict[str, str],
    ) -> tuple[list[VerificationCheck], set[str], int, int]:
        checks: list[VerificationCheck] = []
        verified_by_claim: dict[str, int] = {}
        target_count_by_claim: dict[str, int] = {}
        verified_targets = 0
        correction_count = 0
        artifacts = {artifact.artifact_id: artifact for artifact in context.manifest.artifacts}
        steps = {
            (step.claim_id, step.artifact_id, step.anchor): step for step in context.plan.steps
        }
        records = {record.step_id: record for record in context.run.steps}
        for claim in context.manifest.claims:
            if claim.provenance != ProvenanceStatus.REGISTERED:
                continue
            target_count_by_claim[claim.claim_id] = len(claim.artifact_anchors)
            expected = expected_statements.get(claim.claim_id)
            if expected is None:
                continue
            for anchor in claim.artifact_anchors:
                artifact = artifacts[anchor.artifact_id]
                step = steps.get((claim.claim_id, anchor.artifact_id, anchor.anchor))
                if step is not None and step.operation == RepairOperation.CREATE_CORRECTION_DRAFT:
                    record = records.get(step.step_id)
                    external_id = record.external_id if record is not None else None
                    correction_count += 1
                    correction_ok = False
                    if external_id:
                        try:
                            observed = await self._gateway.read_correction(
                                access_token, step, external_id
                            )
                            correction_ok = (
                                observed.resource_id == external_id
                                and observed.statement == expected
                            )
                            observed_statement = observed.statement
                        except VerificationReadError:
                            observed_statement = None
                        checks.append(
                            _check(
                                VerificationCheckKind.CORRECTION_DRAFT,
                                f"correction:{step.step_id}",
                                correction_ok,
                                (
                                    "The independently read correction draft contains the "
                                    "recomputed claim."
                                    if correction_ok
                                    else (
                                        "The correction draft does not contain the "
                                        "recomputed claim."
                                    )
                                ),
                                claim_id=claim.claim_id,
                                artifact_id=artifact.artifact_id,
                                expected=expected,
                                observed=observed_statement,
                            )
                        )
                    else:
                        checks.append(
                            _check(
                                VerificationCheckKind.CORRECTION_DRAFT,
                                f"correction:{step.step_id}",
                                False,
                                (
                                    "The completed correction step has no independently "
                                    "readable draft ID."
                                ),
                                claim_id=claim.claim_id,
                                artifact_id=artifact.artifact_id,
                            )
                        )
                    try:
                        original = await self._gateway.read_registered(
                            access_token,
                            artifact,
                            anchor.anchor,
                            claim.statement,
                            claim.statement,
                        )
                        original_ok = (
                            original.resource_id == artifact.resource_id
                            and original.statement == claim.statement
                        )
                        original_statement = original.statement
                    except VerificationReadError:
                        original_ok = False
                        original_statement = None
                    checks.append(
                        _check(
                            VerificationCheckKind.IMMUTABLE_ORIGINAL,
                            f"original:{step.step_id}",
                            original_ok,
                            (
                                "The sent original remains byte-stable and is superseded by the "
                                "verified correction draft."
                                if original_ok
                                else (
                                    "The immutable original no longer matches its registered state."
                                )
                            ),
                            claim_id=claim.claim_id,
                            artifact_id=artifact.artifact_id,
                            expected=claim.statement,
                            observed=original_statement,
                        )
                    )
                    target_ok = correction_ok and original_ok
                else:
                    try:
                        observed = await self._gateway.read_registered(
                            access_token,
                            artifact,
                            anchor.anchor,
                            expected,
                            claim.statement,
                        )
                        target_ok = (
                            observed.resource_id == artifact.resource_id
                            and observed.statement == expected
                        )
                        observed_statement = observed.statement
                    except VerificationReadError:
                        target_ok = False
                        observed_statement = None
                    checks.append(
                        _check(
                            VerificationCheckKind.REGISTERED_TARGET,
                            f"target:{claim.claim_id}:{artifact.artifact_id}:{anchor.anchor}",
                            target_ok,
                            (
                                "The independently read registered target matches the "
                                "recomputed claim."
                                if target_ok
                                else "The registered target does not match the recomputed claim."
                            ),
                            claim_id=claim.claim_id,
                            artifact_id=artifact.artifact_id,
                            expected=expected,
                            observed=observed_statement,
                        )
                    )
                if target_ok:
                    verified_targets += 1
                    verified_by_claim[claim.claim_id] = verified_by_claim.get(claim.claim_id, 0) + 1
        verified_claims = {
            claim_id
            for claim_id, target_count in target_count_by_claim.items()
            if verified_by_claim.get(claim_id, 0) == target_count
        }
        return checks, verified_claims, verified_targets, correction_count

    async def _verify_protected_regions(
        self,
        context: VerificationContext,
        access_token: str,
        expected_statements: dict[str, str],
    ) -> tuple[list[VerificationCheck], int]:
        checks: list[VerificationCheck] = []
        verified = 0
        artifact_index = {artifact.artifact_id: artifact for artifact in context.manifest.artifacts}
        baseline_index = {baseline.artifact_id: baseline for baseline in context.baselines}
        affected_ids = sorted({step.artifact_id for step in context.plan.steps})
        for artifact_id in affected_ids:
            artifact = artifact_index[artifact_id]
            baseline = baseline_index.get(artifact_id)
            steps = [step for step in context.plan.steps if step.artifact_id == artifact_id]
            anchors = tuple(step.anchor for step in steps)
            statements = tuple(
                step.before_statement
                if step.operation == RepairOperation.CREATE_CORRECTION_DRAFT
                else expected_statements.get(step.claim_id, step.proposed_statement)
                for step in steps
            )
            try:
                current = await self._gateway.protected_state(
                    access_token,
                    artifact,
                    anchors,
                    statements,
                )
                ok = bool(
                    baseline is not None
                    and current.artifact_id == artifact_id
                    and baseline.resource_id == current.resource_id
                    and baseline.anchor_set_hash == current.anchor_set_hash
                    and baseline.protected_content_hash == current.protected_content_hash
                )
                observed_hash = current.protected_content_hash
            except VerificationReadError:
                ok = False
                observed_hash = None
            if ok:
                verified += 1
            checks.append(
                _check(
                    VerificationCheckKind.PROTECTED_REGION,
                    f"protected:{artifact_id}",
                    ok,
                    (
                        "The independently computed protected-region hash matches the "
                        "pre-repair baseline."
                        if ok
                        else "The protected-region baseline is missing or does not match."
                    ),
                    artifact_id=artifact_id,
                    expected_hash=(
                        baseline.protected_content_hash if baseline is not None else None
                    ),
                    observed_hash=observed_hash,
                )
            )
        return checks, verified


def verification_report_checksum(report: VerificationReport) -> str:
    return _checksum(report.model_dump(mode="json", by_alias=True))


def certificate_checksum(certificate: EvidenceIntegrityCertificate) -> str:
    return _checksum(certificate.model_dump(mode="json", by_alias=True))


def anchor_set_hash(anchors: tuple[str, ...]) -> str:
    return _checksum(sorted(set(anchors)))


def _artifact_mutability(step: RepairStep) -> ArtifactMutability:
    if step.operation == RepairOperation.CREATE_CORRECTION_DRAFT:
        return ArtifactMutability.IMMUTABLE
    return ArtifactMutability.EDITABLE


def _validate_context(context: VerificationContext) -> None:
    if (
        context.plan.packet_id != context.manifest.packet_id
        or context.run.packet_id != context.manifest.packet_id
    ):
        raise VerificationIntegrityError("Verification inputs do not bind to one Decision Packet")
    if (
        context.plan.manifest_id != context.manifest.manifest_id
        or context.plan.manifest_version != context.manifest.version
    ):
        raise VerificationIntegrityError("Repair plan does not bind to the supplied Claim Manifest")
    if context.run.plan_id != context.plan.plan_id:
        raise VerificationIntegrityError("Repair run does not bind to the supplied repair plan")
    if len({source.source_id for source in context.sources}) != len(context.sources):
        raise VerificationIntegrityError("Verification sources must be unique")
    if len({snapshot.source_id for snapshot in context.snapshot_metadata}) != len(
        context.snapshot_metadata
    ):
        raise VerificationIntegrityError("Latest verification snapshots must be unique by source")
    if len({baseline.artifact_id for baseline in context.baselines}) != len(context.baselines):
        raise VerificationIntegrityError("Protected-region baselines must be unique by artifact")
    manifest_sources = {source.source_id: source for source in context.manifest.sources}
    sources = {source.source_id: source for source in context.sources}
    snapshots = {snapshot.source_id: snapshot for snapshot in context.snapshot_metadata}
    if set(sources) != set(manifest_sources) or set(snapshots) != set(manifest_sources):
        raise VerificationIntegrityError(
            "Verification requires exactly one current value and snapshot per registered source"
        )
    for source_id, source in sources.items():
        record = manifest_sources[source_id]
        snapshot = snapshots[source_id]
        if (
            source.kind != record.kind
            or source.resource_id != record.resource_id
            or source.anchor != record.anchor
            or snapshot.resource_id != record.resource_id
            or source.version != snapshot.workspace_version
        ):
            raise VerificationIntegrityError(
                f"Verification source {source_id} does not match its registered identity"
            )
    affected_artifacts = {step.artifact_id for step in context.plan.steps}
    if {baseline.artifact_id for baseline in context.baselines} != affected_artifacts:
        raise VerificationIntegrityError(
            "Protected-region baselines do not exactly cover affected artifacts"
        )
    step_ids = [step.step_id for step in context.plan.steps]
    step_targets = [(step.claim_id, step.artifact_id, step.anchor) for step in context.plan.steps]
    if len(set(step_ids)) != len(step_ids) or len(set(step_targets)) != len(step_targets):
        raise VerificationIntegrityError("Repair plan contains duplicate verification targets")


def _run_check(context: VerificationContext) -> VerificationCheck:
    records = {record.step_id: record for record in context.run.steps}
    expected_steps = {step.step_id for step in context.plan.steps}
    allowed = {StepExecutionStatus.SUCCEEDED, StepExecutionStatus.ALREADY_APPLIED}
    ok = (
        context.run.status == RepairRunStatus.COMPLETED
        and set(records) == expected_steps
        and len(records) == len(context.run.steps)
        and all(record.status in allowed for record in records.values())
    )
    return _check(
        VerificationCheckKind.REPAIR_RUN,
        "repair-run",
        ok,
        (
            "Every planned repair step has a successful terminal execution record."
            if ok
            else "The repair run is incomplete, unsuccessful, or does not match its plan."
        ),
    )


def _freshness_checks(
    context: VerificationContext,
) -> tuple[list[VerificationCheck], bool]:
    expected: dict[str, tuple[str, str | None, str | None]] = {
        source.source_id: (source.version, None, None) for source in context.manifest.sources
    }
    for step in context.plan.steps:
        for source_ref in step.source_versions:
            prior = expected.get(source_ref.source_id)
            resolved = (
                source_ref.workspace_version,
                source_ref.snapshot_id,
                source_ref.content_hash,
            )
            if prior is not None and prior[1] is not None and prior != resolved:
                raise VerificationIntegrityError("Repair plan contains conflicting source versions")
            expected[source_ref.source_id] = resolved
    sources = {source.source_id: source for source in context.sources}
    snapshots = {snapshot.source_id: snapshot for snapshot in context.snapshot_metadata}
    checks: list[VerificationCheck] = []
    stale = False
    for source_id in sorted(expected):
        version, snapshot_id, content_hash = expected[source_id]
        source = sources.get(source_id)
        snapshot = snapshots.get(source_id)
        ok = bool(
            source is not None
            and snapshot is not None
            and source.version == version
            and snapshot.workspace_version == version
            and (snapshot_id is None or snapshot.snapshot_id == snapshot_id)
            and (content_hash is None or snapshot.content_hash == content_hash)
        )
        stale = stale or not ok
        checks.append(
            _check(
                VerificationCheckKind.SOURCE_FRESHNESS,
                f"source:{source_id}",
                ok,
                (
                    "The latest immutable source snapshot matches the repair's causal version."
                    if ok
                    else "The source changed after planning or its causal snapshot is unavailable."
                ),
                source_id=source_id,
                expected=version,
                observed=(snapshot.workspace_version if snapshot is not None else "missing"),
            )
        )
    return checks, stale


def _certificate_sources(context: VerificationContext) -> tuple[SourceVersionRef, ...]:
    snapshots = {snapshot.source_id: snapshot for snapshot in context.snapshot_metadata}
    return tuple(
        SourceVersionRef(
            source_id=source.source_id,
            snapshot_id=snapshots[source.source_id].snapshot_id,
            workspace_version=source.version,
            content_hash=snapshots[source.source_id].content_hash,
        )
        for source in sorted(context.sources, key=lambda item: item.source_id)
    )


def _check(
    kind: VerificationCheckKind,
    identity: str,
    ok: bool,
    detail: str,
    *,
    source_id: str | None = None,
    claim_id: str | None = None,
    artifact_id: str | None = None,
    expected: str | None = None,
    observed: str | None = None,
    expected_hash: str | None = None,
    observed_hash: str | None = None,
) -> VerificationCheck:
    return VerificationCheck(
        check_id=f"check-{uuid5(NAMESPACE_URL, identity)}",
        kind=kind,
        status=VerificationCheckStatus.PASSED if ok else VerificationCheckStatus.FAILED,
        detail=detail,
        source_id=source_id,
        claim_id=claim_id,
        artifact_id=artifact_id,
        expected_hash=expected_hash or (_text_hash(expected) if expected is not None else None),
        observed_hash=observed_hash or (_text_hash(observed) if observed is not None else None),
    )


def _input_digest(context: VerificationContext) -> str:
    return _checksum(
        {
            "manifestChecksum": manifest_checksum(context.manifest),
            "planChecksum": repair_plan_checksum(context.plan),
            "run": context.run.model_dump(mode="json", by_alias=True),
            "sources": [
                source.model_dump(mode="json", by_alias=True)
                for source in sorted(context.sources, key=lambda item: item.source_id)
            ],
            "snapshots": [
                snapshot.model_dump(mode="json", by_alias=True)
                for snapshot in sorted(context.snapshot_metadata, key=lambda item: item.source_id)
            ],
            "baselines": [
                baseline.model_dump(mode="json", by_alias=True)
                for baseline in sorted(context.baselines, key=lambda item: item.artifact_id)
            ],
        }
    )


def _result(persisted: PersistedVerification, reused: bool) -> VerificationResult:
    return VerificationResult(
        report=persisted.report,
        report_checksum=persisted.report_checksum,
        certificate=persisted.certificate,
        certificate_checksum=persisted.certificate_checksum,
        reused=reused,
    )


def _checksum(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
