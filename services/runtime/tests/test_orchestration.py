import asyncio

from operations_support import MemoryOperationRepository
from repair_support import NOW, MemoryRepairRepository
from veritas_runtime.agents.models import AgentDisposition, AgentReview, AgentReviewResult
from veritas_runtime.agents.service import agent_review_checksum
from veritas_runtime.changes.models import DeltaKind
from veritas_runtime.execution.models import RepairRun, RepairRunStatus
from veritas_runtime.lineage.models import ImpactAnalysisResult
from veritas_runtime.lineage.service import impact_checksum
from veritas_runtime.operations.models import OperationRequest
from veritas_runtime.orchestration import ConsequenceRepairOrchestrator
from veritas_runtime.repairs.service import RepairPlanningService


class RecordingImpact:
    def __init__(self, report) -> None:  # type: ignore[no-untyped-def]
        self.report = report
        self.calls: list[tuple[str, str, str, tuple[str, ...]]] = []

    async def analyze(self, subject, packet_id, request_id, snapshot_ids):  # type: ignore[no-untyped-def]
        self.calls.append((subject, packet_id, request_id, snapshot_ids))
        return ImpactAnalysisResult(
            report=self.report,
            checksum=impact_checksum(self.report),
            reused=False,
        )


class StaticPlans:
    def __init__(self, result) -> None:  # type: ignore[no-untyped-def]
        self.result = result
        self.calls: list[tuple[str, str, str, str]] = []

    async def create_plan(self, subject, packet_id, request_id, report_id):  # type: ignore[no-untyped-def]
        self.calls.append((subject, packet_id, request_id, report_id))
        return self.result


class StaticExecution:
    def __init__(self, run: RepairRun) -> None:
        self.run = run
        self.execute_calls: list[tuple[str, str, str]] = []
        self.resume_calls: list[tuple[str, str, str]] = []

    async def execute(self, subject: str, plan_id: str, request_id: str) -> RepairRun:
        self.execute_calls.append((subject, plan_id, request_id))
        return self.run

    async def resume(self, subject: str, run_id: str, request_id: str) -> RepairRun:
        self.resume_calls.append((subject, run_id, request_id))
        return self.run


class RecordingVerification:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.result = object()

    async def verify(self, subject: str, run_id: str, request_id: str):
        self.calls.append((subject, run_id, request_id))
        return self.result


class StaticAgentReview:
    def __init__(self, plan_id: str, packet_id: str) -> None:
        review = AgentReview(
            review_id="agent-review-orchestration",
            operation_id="operation-placeholder",
            plan_id=plan_id,
            packet_id=packet_id,
            model="gemini-3.5-flash",
            prompt_version="consequence-safety-review-v1",
            disposition=AgentDisposition.PROCEED,
            rationale="The registered scope and deterministic policy are internally coherent.",
            recognized_claim_ids=(),
            risk_flags=(),
            input_digest="a" * 64,
            created_at=NOW,
        )
        self.result = AgentReviewResult(
            review=review,
            checksum=agent_review_checksum(review),
            reused=False,
        )
        self.calls: list[tuple[str, str]] = []

    async def review(self, subject, operation_id, impact, plan):  # type: ignore[no-untyped-def]
        assert impact and plan
        self.calls.append((subject, operation_id))
        return self.result


def test_meaningful_snapshots_advance_the_complete_repair_lifecycle() -> None:
    async def scenario() -> None:
        repairs = MemoryRepairRepository()
        planned = await RepairPlanningService(repairs).create_plan(
            "subject-1",
            repairs.context.manifest.packet_id,
            "orchestration-plan",
            repairs.context.impact.report_id,
            NOW,
        )
        run = RepairRun(
            run_id="run-orchestrated",
            plan_id=planned.plan.plan_id,
            packet_id=planned.plan.packet_id,
            status=RepairRunStatus.COMPLETED,
            created_at=NOW,
            updated_at=NOW,
            steps=(),
        )
        impact = RecordingImpact(repairs.context.impact)
        plans = StaticPlans(planned)
        execution = StaticExecution(run)
        verification = RecordingVerification()
        agent_review = StaticAgentReview(planned.plan.plan_id, planned.plan.packet_id)
        orchestrator = ConsequenceRepairOrchestrator(  # type: ignore[arg-type]
            impact,
            plans,
            execution,
            verification,
            agent_review,
        )
        operations = MemoryOperationRepository()
        operation, _ = await operations.enqueue(
            OperationRequest(
                subject="subject-1",
                kind="drive.process",
                correlation_id="drive-event-1",
                idempotency_key="drive-event-1",
                payload={"streamId": "stream-1"},
            ),
            NOW,
        )
        meaningful, baseline = repairs.context.snapshot_metadata
        outcomes = await orchestrator.process(operation, (baseline, meaningful))

        assert len(outcomes) == 1
        assert outcomes[0].verification is verification.result
        assert outcomes[0].agent_review == agent_review.result.review
        assert impact.calls[0][3] == (meaningful.snapshot_id,)
        assert plans.calls[0][2].endswith(":plan")
        assert execution.execute_calls[0][2].endswith(":execute")
        assert verification.calls[0][2].endswith(":verify")
        assert agent_review.calls == [("subject-1", operation.operation_id)]

        cosmetic = meaningful.model_copy(update={"delta_kind": DeltaKind.COSMETIC})
        assert await orchestrator.process(operation, (baseline, cosmetic)) == ()
        assert len(impact.calls) == 1

        resumed, verified = await orchestrator.resume_and_verify(
            "subject-1", run.run_id, "human-decision"
        )
        assert resumed.run_id == run.run_id
        assert verified is verification.result
        assert execution.resume_calls == [("subject-1", run.run_id, "human-decision")]

    asyncio.run(scenario())


def test_nonterminal_repair_waits_for_human_without_false_verification() -> None:
    async def scenario() -> None:
        repairs = MemoryRepairRepository()
        planned = await RepairPlanningService(repairs).create_plan(
            "subject-1",
            repairs.context.manifest.packet_id,
            "awaiting-plan",
            repairs.context.impact.report_id,
            NOW,
        )
        run = RepairRun(
            run_id="run-awaiting",
            plan_id=planned.plan.plan_id,
            packet_id=planned.plan.packet_id,
            status=RepairRunStatus.AWAITING_APPROVAL,
            created_at=NOW,
            updated_at=NOW,
            steps=(),
        )
        verification = RecordingVerification()
        orchestrator = ConsequenceRepairOrchestrator(  # type: ignore[arg-type]
            RecordingImpact(repairs.context.impact),
            StaticPlans(planned),
            StaticExecution(run),
            verification,
        )
        operation, _ = await MemoryOperationRepository().enqueue(
            OperationRequest(
                subject="subject-1",
                kind="drive.process",
                correlation_id="drive-event-awaiting",
                idempotency_key="drive-event-awaiting",
                payload={"streamId": "stream-1"},
            ),
            NOW,
        )
        outcome = await orchestrator.process(
            operation,
            (repairs.context.snapshot_metadata[0],),
        )
        assert outcome[0].run.status == RepairRunStatus.AWAITING_APPROVAL
        assert outcome[0].verification is None
        assert verification.calls == []

    asyncio.run(scenario())
