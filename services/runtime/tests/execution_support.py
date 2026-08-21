from datetime import UTC, datetime

from repair_support import MemoryRepairRepository
from veritas_runtime.execution.models import (
    ArtifactState,
    MutationReceipt,
    RepairRun,
    RepairRunStatus,
    StepExecutionRecord,
)
from veritas_runtime.execution.service import (
    ExecutionContext,
    WorkspaceSession,
)
from veritas_runtime.packets.models import ArtifactKind
from veritas_runtime.repairs.models import ApprovalRecord, RepairPlan, RepairStep
from veritas_runtime.workspace.contracts import (
    REQUIRED_WORKSPACE_SCOPES,
    WorkspaceAuthorization,
    WorkspaceCapability,
)

NOW = datetime(2026, 8, 21, 4, 0, tzinfo=UTC)


def plan_from_memory(
    repository: MemoryRepairRepository,
) -> tuple[RepairPlan, tuple[ApprovalRecord, ...]]:
    persisted = next(iter(repository.plans.values()))
    return persisted.plan, persisted.approvals


class MemoryExecutionRepository:
    def __init__(self, repairs: MemoryRepairRepository) -> None:
        self.repairs = repairs
        self.runs: dict[str, RepairRun] = {}
        self.subjects: dict[str, str] = {}

    async def load_context(self, subject: str, plan_id: str) -> ExecutionContext:
        if subject != "subject-1":
            raise PermissionError("denied")
        persisted = next(
            (item for item in self.repairs.plans.values() if item.plan.plan_id == plan_id),
            None,
        )
        if persisted is None:
            raise LookupError("plan not found")
        return ExecutionContext(persisted.plan, persisted.approvals)

    async def get_by_idempotency_key(self, key: str) -> RepairRun | None:
        return self.runs.get(key)

    async def start(
        self,
        subject: str,
        plan: RepairPlan,
        idempotency_key: str,
        now: datetime,
    ) -> RepairRun:
        existing = self.runs.get(idempotency_key)
        if existing is not None:
            return existing
        run = RepairRun(
            run_id=f"run-{len(self.runs) + 1}",
            plan_id=plan.plan_id,
            packet_id=plan.packet_id,
            status=RepairRunStatus.RUNNING,
            created_at=now,
            updated_at=now,
            steps=(),
        )
        self.runs[idempotency_key] = run
        self.subjects[run.run_id] = subject
        return run

    async def record_step(
        self, run: RepairRun, record: StepExecutionRecord, now: datetime
    ) -> RepairRun:
        records = {item.step_id: item for item in run.steps}
        records[record.step_id] = record
        updated = run.model_copy(
            update={
                "status": RepairRunStatus.RUNNING,
                "updated_at": now,
                "steps": tuple(records.values()),
            }
        )
        self._replace(run, updated)
        return updated

    async def finish(self, run: RepairRun, status: RepairRunStatus, now: datetime) -> RepairRun:
        updated = run.model_copy(update={"status": status, "updated_at": now})
        self._replace(run, updated)
        return updated

    def _replace(self, old: RepairRun, new: RepairRun) -> None:
        key = next(key for key, value in self.runs.items() if value.run_id == old.run_id)
        self.runs[key] = new


class StaticWorkspaceSessions:
    async def get(self, subject: str) -> WorkspaceSession:
        assert subject == "subject-1"
        return WorkspaceSession(
            access_token="access-token",
            authorization=WorkspaceAuthorization(frozenset(REQUIRED_WORKSPACE_SCOPES)),
        )


class MemoryWorkspaceGateway:
    def __init__(self, steps: tuple[RepairStep, ...]) -> None:
        self.statements = {(step.resource_id, step.anchor): step.before_statement for step in steps}
        self.revisions = {step.resource_id: "current-revision-1" for step in steps}
        self.human_regions = {
            "artifact-board-memo": "CFO: keep this original paragraph byte-for-byte."
        }
        self.apply_calls: list[str] = []

    def capability(self, step: RepairStep) -> WorkspaceCapability:
        return {
            ArtifactKind.GOOGLE_DOC: WorkspaceCapability.DOCS_REPAIR,
            ArtifactKind.GOOGLE_SLIDES: WorkspaceCapability.SLIDES_REPAIR,
            ArtifactKind.GMAIL: WorkspaceCapability.GMAIL_CORRECTION_DRAFT,
            ArtifactKind.GOOGLE_TASK: WorkspaceCapability.TASKS_REPAIR,
        }[step.artifact_kind]

    async def read(self, access_token: str, step: RepairStep) -> ArtifactState:
        assert access_token
        return ArtifactState(
            resource_id=step.resource_id,
            revision_id=self.revisions[step.resource_id],
            anchor=step.anchor,
            statement=self.statements[(step.resource_id, step.anchor)],
        )

    async def apply(
        self, access_token: str, step: RepairStep, current: ArtifactState
    ) -> MutationReceipt:
        assert access_token and current.revision_id == self.revisions[step.resource_id]
        self.apply_calls.append(step.step_id)
        self.statements[(step.resource_id, step.anchor)] = step.proposed_statement
        revision = f"current-revision-{len(self.apply_calls) + 1}"
        self.revisions[step.resource_id] = revision
        return MutationReceipt(
            resource_id=step.resource_id,
            revision_id=revision,
            external_id=f"external-{step.step_id}"
            if step.artifact_kind == ArtifactKind.GMAIL
            else None,
        )
