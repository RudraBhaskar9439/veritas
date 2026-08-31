from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from veritas_runtime.execution.google import WorkspaceExecutionError, WorkspacePreconditionFailed
from veritas_runtime.execution.merge import decide_three_way_merge
from veritas_runtime.execution.models import (
    ArtifactState,
    MergeOutcome,
    MutationReceipt,
    RepairRun,
    RepairRunStatus,
    StepExecutionRecord,
    StepExecutionStatus,
)
from veritas_runtime.repairs.models import (
    ApprovalRecord,
    ApprovalStatus,
    PolicyDisposition,
    RepairPlan,
    RepairStep,
)
from veritas_runtime.workspace.contracts import (
    MissingWorkspaceScope,
    WorkspaceAuthorization,
    WorkspaceCapability,
)


@dataclass(frozen=True)
class ExecutionContext:
    plan: RepairPlan
    approvals: tuple[ApprovalRecord, ...]


@dataclass(frozen=True)
class WorkspaceSession:
    access_token: str
    authorization: WorkspaceAuthorization
    email: str | None = None


class WorkspaceSessionProvider(Protocol):
    async def get(self, subject: str) -> WorkspaceSession: ...


class WorkspaceRepairGateway(Protocol):
    def capability(self, step: RepairStep) -> WorkspaceCapability: ...

    async def read(self, access_token: str, step: RepairStep) -> ArtifactState: ...

    async def apply(
        self, access_token: str, step: RepairStep, current: ArtifactState
    ) -> MutationReceipt: ...


class ExecutionBaselineCapture(Protocol):
    async def capture(
        self,
        subject: str,
        run: RepairRun,
        plan: RepairPlan,
        access_token: str,
        now: datetime,
    ) -> None: ...


class ExecutionRepository(Protocol):
    async def load_context(self, subject: str, plan_id: str) -> ExecutionContext: ...

    async def get_by_idempotency_key(self, key: str) -> RepairRun | None: ...

    async def get_by_run_id(self, subject: str, run_id: str) -> RepairRun: ...

    async def start(
        self,
        subject: str,
        plan: RepairPlan,
        idempotency_key: str,
        now: datetime,
    ) -> RepairRun: ...

    async def record_step(
        self, run: RepairRun, record: StepExecutionRecord, now: datetime
    ) -> RepairRun: ...

    async def finish(self, run: RepairRun, status: RepairRunStatus, now: datetime) -> RepairRun: ...


class RepairExecutionService:
    def __init__(
        self,
        repository: ExecutionRepository,
        sessions: WorkspaceSessionProvider,
        gateway: WorkspaceRepairGateway,
        baselines: ExecutionBaselineCapture,
    ) -> None:
        self._repository = repository
        self._sessions = sessions
        self._gateway = gateway
        self._baselines = baselines

    async def execute(
        self,
        subject: str,
        plan_id: str,
        request_id: str,
        now: datetime | None = None,
    ) -> RepairRun:
        if not subject or not plan_id or not request_id:
            raise ValueError("Subject, plan ID, and execution request ID are required")
        current_time = (now or datetime.now(UTC)).astimezone(UTC)
        context = await self._repository.load_context(subject, plan_id)
        key = f"{subject}:{plan_id}:{request_id}"
        existing = await self._repository.get_by_idempotency_key(key)
        run = existing or await self._repository.start(subject, context.plan, key, current_time)
        if existing is not None and existing.status in _FINAL_RUN_STATES:
            return existing.model_copy(update={"reused": True})
        return await self._advance(
            subject,
            context,
            run,
            current_time,
            reused=existing is not None,
        )

    async def resume(
        self,
        subject: str,
        run_id: str,
        request_id: str,
        now: datetime | None = None,
    ) -> RepairRun:
        if not subject or not run_id or not request_id:
            raise ValueError("Subject, run ID, and resume request ID are required")
        current_time = (now or datetime.now(UTC)).astimezone(UTC)
        run = await self._repository.get_by_run_id(subject, run_id)
        if run.status in _FINAL_RUN_STATES:
            return run.model_copy(update={"reused": True})
        context = await self._repository.load_context(subject, run.plan_id)
        return await self._advance(subject, context, run, current_time, reused=True)

    async def reconcile_conflict(
        self,
        subject: str,
        run_id: str,
        request_id: str,
        actor: str,
        reason: str,
        now: datetime | None = None,
    ) -> RepairRun:
        """Rebase conflicted registered anchors and start a fresh guarded run.

        The failed run and its conflict receipts remain immutable. Recovery
        re-reads only the manifest-owned anchors that conflicted and uses those
        exact native revisions as the new three-way merge base.
        """
        if not all((subject, run_id, request_id, actor, reason.strip())):
            raise ValueError(
                "Subject, run ID, request ID, actor, and reconciliation reason are required"
            )
        current_time = (now or datetime.now(UTC)).astimezone(UTC)
        conflicted_run = await self._repository.get_by_run_id(subject, run_id)
        if conflicted_run.status != RepairRunStatus.CONFLICT:
            raise ValueError("Only a conflicted repair run can be reconciled")
        conflict_step_ids = {
            record.step_id
            for record in conflicted_run.steps
            if record.status == StepExecutionStatus.CONFLICT
        }
        if not conflict_step_ids:
            raise ValueError("The repair run has no persisted conflict receipt")

        context = await self._repository.load_context(subject, conflicted_run.plan_id)
        session = await self._sessions.get(subject)
        rebased_steps: list[RepairStep] = []
        for step in context.plan.steps:
            if step.step_id not in conflict_step_ids:
                rebased_steps.append(step)
                continue
            session.authorization.require(self._gateway.capability(step))
            current = await self._gateway.read(session.access_token, step)
            if current.resource_id != step.resource_id or current.anchor != step.anchor:
                raise ValueError("Workspace state does not match the registered repair target")
            rebased_steps.append(
                step.model_copy(
                    update={
                        "before_statement": current.statement,
                        "base_revision_id": current.revision_id,
                    }
                )
            )

        reconciled_plan = context.plan.model_copy(update={"steps": tuple(rebased_steps)})
        reconciled_context = ExecutionContext(reconciled_plan, context.approvals)
        key = f"{subject}:{run_id}:reconcile:{request_id}"
        existing = await self._repository.get_by_idempotency_key(key)
        recovered = existing or await self._repository.start(
            subject,
            reconciled_plan,
            key,
            current_time,
        )
        if existing is not None and existing.status in _FINAL_RUN_STATES:
            return existing.model_copy(update={"reused": True})
        return await self._advance(
            subject,
            reconciled_context,
            recovered,
            current_time,
            reused=existing is not None,
            recovery_notes={
                step_id: (f"Conflict reconciliation authorized by {actor}: {reason.strip()}")
                for step_id in conflict_step_ids
            },
        )

    async def _advance(
        self,
        subject: str,
        context: ExecutionContext,
        run: RepairRun,
        current_time: datetime,
        *,
        reused: bool,
        recovery_notes: Mapping[str, str] | None = None,
    ) -> RepairRun:
        session = await self._sessions.get(subject)
        await self._baselines.capture(
            subject,
            run,
            context.plan,
            session.access_token,
            current_time,
        )
        approval_index = {approval.approval_id: approval for approval in context.approvals}
        record_index = {record.step_id: record for record in run.steps}
        for step in context.plan.steps:
            prior = record_index.get(step.step_id)
            if prior is not None and prior.status in _FINAL_STEP_STATES:
                continue
            policy_record = _policy_record(step, approval_index, current_time)
            if policy_record is not None:
                run = await self._repository.record_step(run, policy_record, current_time)
                record_index[step.step_id] = policy_record
                continue
            record = await self._execute_step(step, session, current_time)
            recovery_note = (recovery_notes or {}).get(step.step_id)
            if recovery_note is not None:
                record = record.model_copy(update={"detail": f"{record.detail} {recovery_note}"})
            run = await self._repository.record_step(run, record, current_time)
            record_index[step.step_id] = record
        status = _aggregate_status(run.steps)
        finished = await self._repository.finish(run, status, current_time)
        return finished.model_copy(update={"reused": reused})

    async def _execute_step(
        self,
        step: RepairStep,
        session: WorkspaceSession,
        now: datetime,
    ) -> StepExecutionRecord:
        try:
            session.authorization.require(self._gateway.capability(step))
        except MissingWorkspaceScope:
            return _record(
                step,
                StepExecutionStatus.FAILED,
                now,
                "The connected account lacks the required Workspace capability.",
            )
        current = None
        for attempt in range(2):
            try:
                current = await self._gateway.read(session.access_token, step)
                outcome = decide_three_way_merge(step, current)
                if outcome == MergeOutcome.ALREADY_APPLIED:
                    return _record(
                        step,
                        StepExecutionStatus.ALREADY_APPLIED,
                        now,
                        "The registered anchor already contains the proposed statement.",
                        before_revision=current.revision_id,
                        after_revision=current.revision_id,
                    )
                if outcome == MergeOutcome.CONFLICT:
                    return _record(
                        step,
                        StepExecutionStatus.CONFLICT,
                        now,
                        "A human edit overlaps the registered claim anchor.",
                        before_revision=current.revision_id,
                    )
                receipt = await self._gateway.apply(session.access_token, step, current)
                return _record(
                    step,
                    StepExecutionStatus.SUCCEEDED,
                    now,
                    (
                        "Recovered the existing idempotent mutation."
                        if receipt.recovered
                        else "Applied the registered repair mutation."
                    ),
                    before_revision=current.revision_id,
                    after_revision=receipt.revision_id,
                    external_id=receipt.external_id,
                )
            except WorkspacePreconditionFailed:
                if attempt == 0:
                    continue
                return _record(
                    step,
                    StepExecutionStatus.CONFLICT,
                    now,
                    "The artifact changed during both guarded write attempts.",
                    before_revision=current.revision_id if current is not None else None,
                )
            except WorkspaceExecutionError:
                return _record(
                    step,
                    StepExecutionStatus.FAILED,
                    now,
                    "The Workspace adapter rejected the mutation safely.",
                    before_revision=current.revision_id if current is not None else None,
                )
        raise AssertionError("guarded execution loop did not terminate")


def _policy_record(
    step: RepairStep,
    approvals: dict[str, ApprovalRecord],
    now: datetime,
) -> StepExecutionRecord | None:
    if step.disposition == PolicyDisposition.BLOCKED:
        return _record(
            step,
            StepExecutionStatus.BLOCKED,
            now,
            "The deterministic repair policy blocks this mutation.",
        )
    if step.disposition != PolicyDisposition.REQUIRES_APPROVAL:
        return None
    approval = approvals.get(step.approval_id or "")
    if approval is None or approval.status == ApprovalStatus.PENDING:
        return _record(
            step,
            StepExecutionStatus.WAITING_APPROVAL,
            now,
            "An authenticated human decision is required.",
        )
    if approval.status == ApprovalStatus.REJECTED:
        return _record(
            step,
            StepExecutionStatus.REJECTED,
            now,
            "The human approver rejected this repair.",
        )
    return None


def _record(
    step: RepairStep,
    status: StepExecutionStatus,
    now: datetime,
    detail: str,
    *,
    before_revision: str | None = None,
    after_revision: str | None = None,
    external_id: str | None = None,
) -> StepExecutionRecord:
    return StepExecutionRecord(
        step_id=step.step_id,
        status=status,
        attempted_at=now,
        completed_at=now,
        before_revision_id=before_revision,
        after_revision_id=after_revision,
        external_id=external_id,
        detail=detail,
    )


def _aggregate_status(records: tuple[StepExecutionRecord, ...]) -> RepairRunStatus:
    statuses = {record.status for record in records}
    if StepExecutionStatus.FAILED in statuses:
        return RepairRunStatus.FAILED
    if StepExecutionStatus.CONFLICT in statuses:
        return RepairRunStatus.CONFLICT
    if StepExecutionStatus.BLOCKED in statuses:
        return RepairRunStatus.BLOCKED
    if StepExecutionStatus.REJECTED in statuses:
        return RepairRunStatus.REJECTED
    if StepExecutionStatus.WAITING_APPROVAL in statuses:
        return RepairRunStatus.AWAITING_APPROVAL
    return RepairRunStatus.COMPLETED


_FINAL_STEP_STATES = {
    StepExecutionStatus.SUCCEEDED,
    StepExecutionStatus.ALREADY_APPLIED,
    StepExecutionStatus.CONFLICT,
    StepExecutionStatus.REJECTED,
    StepExecutionStatus.BLOCKED,
}

_FINAL_RUN_STATES = {
    RepairRunStatus.COMPLETED,
    RepairRunStatus.CONFLICT,
    RepairRunStatus.REJECTED,
    RepairRunStatus.BLOCKED,
}
