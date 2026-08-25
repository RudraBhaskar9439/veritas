import asyncio

from execution_support import StaticWorkspaceSessions
from verification_support import (
    NOW,
    MemoryIndependentVerifier,
    MemoryVerificationRepository,
    canonical_verification_context,
)
from veritas_runtime.execution.models import RepairRunStatus
from veritas_runtime.verification.models import (
    CERTIFICATE_STATEMENT,
    VerificationCheckKind,
    VerificationStatus,
)
from veritas_runtime.verification.service import VerificationService


def test_independent_verifier_issues_only_a_scoped_complete_certificate() -> None:
    async def scenario() -> None:
        context = await canonical_verification_context()
        repository = MemoryVerificationRepository(context)
        gateway = MemoryIndependentVerifier(context)
        service = VerificationService(repository, StaticWorkspaceSessions(), gateway)
        result = await service.verify("subject-1", context.run.run_id, "verify-1", NOW)

        assert result.report.status == VerificationStatus.VERIFIED
        assert result.certificate is not None
        assert result.certificate.statement == CERTIFICATE_STATEMENT
        assert result.report.coverage.registered_claims == 8
        assert result.report.coverage.verified_registered_claims == 8
        assert result.report.coverage.registered_targets == 13
        assert result.report.coverage.verified_registered_targets == 13
        assert result.report.coverage.protected_artifacts == 5
        assert result.report.coverage.verified_protected_artifacts == 5
        assert result.report.coverage.correction_drafts == 2
        assert len(result.certificate.evidence_versions) == 6
        replay = await service.verify("subject-1", context.run.run_id, "verify-1", NOW)
        assert replay.reused is True
        assert replay.report_checksum == result.report_checksum

    asyncio.run(scenario())


def test_deliberately_incorrect_repair_is_rejected_without_certificate() -> None:
    async def scenario() -> None:
        context = await canonical_verification_context()
        repository = MemoryVerificationRepository(context)
        gateway = MemoryIndependentVerifier(context)
        gateway.registered[("artifact-board-memo", "claim-churn-value")] = (
            "Q3 customer churn is 7%."
        )
        result = await VerificationService(repository, StaticWorkspaceSessions(), gateway).verify(
            "subject-1", context.run.run_id, "verify-wrong", NOW
        )

        assert result.report.status == VerificationStatus.REJECTED
        assert result.certificate is None
        assert any(
            check.kind == VerificationCheckKind.REGISTERED_TARGET and check.status.value == "failed"
            for check in result.report.checks
        )

    asyncio.run(scenario())


def test_source_change_during_repair_marks_run_stale_and_prevents_certificate() -> None:
    async def scenario() -> None:
        context = await canonical_verification_context()
        sources = tuple(
            source.model_copy(update={"version": "sheet-v3", "value": 0.1})
            if source.source_id == "src-churn"
            else source
            for source in context.sources
        )
        snapshots = tuple(
            snapshot.model_copy(
                update={
                    "snapshot_id": "snapshot-churn-v3",
                    "workspace_version": "sheet-v3",
                    "content_hash": "0" * 64,
                }
            )
            if snapshot.source_id == "src-churn"
            else snapshot
            for snapshot in context.snapshot_metadata
        )
        stale_context = VerificationContext(
            manifest=context.manifest,
            plan=context.plan,
            run=context.run,
            sources=sources,
            snapshot_metadata=snapshots,
            baselines=context.baselines,
        )
        result = await VerificationService(
            MemoryVerificationRepository(stale_context),
            StaticWorkspaceSessions(),
            MemoryIndependentVerifier(stale_context),
        ).verify("subject-1", stale_context.run.run_id, "verify-stale", NOW)

        assert result.report.status == VerificationStatus.STALE
        assert result.certificate is None
        assert any(
            check.kind == VerificationCheckKind.SOURCE_FRESHNESS
            and check.source_id == "src-churn"
            and check.status.value == "failed"
            for check in result.report.checks
        )

    from veritas_runtime.verification.service import VerificationContext

    asyncio.run(scenario())


def test_unaffected_source_accepts_latest_immutable_container_revision() -> None:
    async def scenario() -> None:
        context = await canonical_verification_context()
        sources = tuple(
            source.model_copy(update={"version": "sheet-v3"})
            if source.source_id == "src-revenue"
            else source
            for source in context.sources
        )
        snapshots = tuple(
            snapshot.model_copy(
                update={
                    "snapshot_id": "snapshot-revenue-v3",
                    "workspace_version": "sheet-v3",
                }
            )
            if snapshot.source_id == "src-revenue"
            else snapshot
            for snapshot in context.snapshot_metadata
        )
        current_context = VerificationContext(
            manifest=context.manifest,
            plan=context.plan,
            run=context.run,
            sources=sources,
            snapshot_metadata=snapshots,
            baselines=context.baselines,
        )
        result = await VerificationService(
            MemoryVerificationRepository(current_context),
            StaticWorkspaceSessions(),
            MemoryIndependentVerifier(current_context),
        ).verify("subject-1", current_context.run.run_id, "verify-container-revision", NOW)

        assert result.report.status == VerificationStatus.VERIFIED
        assert result.certificate is not None
        revenue = next(
            source
            for source in result.certificate.evidence_versions
            if source.source_id == "src-revenue"
        )
        assert revenue.workspace_version == "sheet-v3"

    from veritas_runtime.verification.service import VerificationContext

    asyncio.run(scenario())


def test_planned_anchor_remains_fresh_when_only_container_revision_advances() -> None:
    async def scenario() -> None:
        context = await canonical_verification_context()
        sources = tuple(
            source.model_copy(update={"version": "sheet-v3"})
            if source.source_id == "src-churn"
            else source
            for source in context.sources
        )
        snapshots = tuple(
            snapshot.model_copy(
                update={
                    "snapshot_id": "duplicate-capture-later-container-version",
                    "workspace_version": "sheet-v3",
                }
            )
            if snapshot.source_id == "src-churn"
            else snapshot
            for snapshot in context.snapshot_metadata
        )
        duplicate_context = VerificationContext(
            manifest=context.manifest,
            plan=context.plan,
            run=context.run,
            sources=sources,
            snapshot_metadata=snapshots,
            baselines=context.baselines,
        )
        result = await VerificationService(
            MemoryVerificationRepository(duplicate_context),
            StaticWorkspaceSessions(),
            MemoryIndependentVerifier(duplicate_context),
        ).verify("subject-1", duplicate_context.run.run_id, "verify-duplicate-capture", NOW)

        assert result.report.status == VerificationStatus.VERIFIED
        assert result.certificate is not None
        churn = next(
            source
            for source in result.certificate.evidence_versions
            if source.source_id == "src-churn"
        )
        assert churn.workspace_version == "sheet-v3"

    from veritas_runtime.verification.service import VerificationContext

    asyncio.run(scenario())


def test_nonterminal_run_and_protected_region_change_cannot_certify() -> None:
    async def scenario() -> None:
        context = await canonical_verification_context()
        incomplete = context.run.model_copy(update={"status": RepairRunStatus.RUNNING})
        incomplete_context = context.__class__(
            manifest=context.manifest,
            plan=context.plan,
            run=incomplete,
            sources=context.sources,
            snapshot_metadata=context.snapshot_metadata,
            baselines=context.baselines,
        )
        first = await VerificationService(
            MemoryVerificationRepository(incomplete_context),
            StaticWorkspaceSessions(),
            MemoryIndependentVerifier(incomplete_context),
        ).verify("subject-1", incomplete.run_id, "verify-incomplete", NOW)
        assert first.report.status == VerificationStatus.REJECTED
        assert first.certificate is None

        gateway = MemoryIndependentVerifier(context)
        gateway.protected["artifact-board-memo"] = "0" * 64
        second = await VerificationService(
            MemoryVerificationRepository(context), StaticWorkspaceSessions(), gateway
        ).verify("subject-1", context.run.run_id, "verify-protected", NOW)
        assert second.report.status == VerificationStatus.REJECTED
        assert second.certificate is None
        assert any(
            check.kind == VerificationCheckKind.PROTECTED_REGION
            and check.artifact_id == "artifact-board-memo"
            and check.status.value == "failed"
            for check in second.report.checks
        )

    asyncio.run(scenario())


def test_missing_correction_draft_prevents_certificate() -> None:
    async def scenario() -> None:
        context = await canonical_verification_context()
        gateway = MemoryIndependentVerifier(context)
        gateway.corrections.clear()
        result = await VerificationService(
            MemoryVerificationRepository(context), StaticWorkspaceSessions(), gateway
        ).verify("subject-1", context.run.run_id, "verify-missing-draft", NOW)
        assert result.report.status == VerificationStatus.REJECTED
        assert result.certificate is None
        assert any(
            check.kind == VerificationCheckKind.CORRECTION_DRAFT and check.status.value == "failed"
            for check in result.report.checks
        )

    asyncio.run(scenario())
