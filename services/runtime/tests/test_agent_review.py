import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import create_async_engine

from repair_support import NOW, MemoryRepairRepository
from veritas_runtime.agents.database import SqlAgentReviewRepository, agent_reviews
from veritas_runtime.agents.gemini import GeminiReviewGateway
from veritas_runtime.agents.models import AgentDisposition, GeminiReviewPayload
from veritas_runtime.agents.service import (
    AgentEscalationRequired,
    AgentReviewError,
    GeminiConsequenceReviewService,
)
from veritas_runtime.auth.database import metadata
from veritas_runtime.repairs.service import RepairPlanningService


class MemoryReviews:
    def __init__(self) -> None:
        self.stored = None

    async def get(self, subject: str, operation_id: str):  # type: ignore[no-untyped-def]
        if self.stored is None:
            return None
        if subject == "subject-1" and self.stored.review.operation_id == operation_id:
            return self.stored
        return None

    async def persist(self, subject, review, checksum):  # type: ignore[no-untyped-def]
        from veritas_runtime.agents.models import AgentReviewResult

        assert subject == "subject-1"
        self.stored = AgentReviewResult(review=review, checksum=checksum, reused=False)
        return self.stored


class StaticReviewGateway:
    def __init__(self, payload: GeminiReviewPayload) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    async def review(self, payload: dict[str, object]) -> GeminiReviewPayload:
        self.calls.append(payload)
        return self.payload


async def _plan():  # type: ignore[no-untyped-def]
    repairs = MemoryRepairRepository()
    planned = await RepairPlanningService(repairs).create_plan(
        "subject-1",
        repairs.context.manifest.packet_id,
        "agent-review-plan",
        repairs.context.impact.report_id,
        NOW,
    )
    return repairs.context.impact, planned.plan


def test_gemini_review_is_scope_bound_persisted_and_idempotent() -> None:
    async def scenario() -> None:
        impact, plan = await _plan()
        claim_ids = tuple(claim.claim_id for claim in impact.affected_claims)
        gateway = StaticReviewGateway(
            GeminiReviewPayload(
                disposition=AgentDisposition.PROCEED,
                rationale="The registered scope and deterministic policy are internally coherent.",
                recognized_claim_ids=claim_ids,
                risk_flags=("decision claims remain approval gated",),
            )
        )
        repository = MemoryReviews()
        service = GeminiConsequenceReviewService(
            repository,  # type: ignore[arg-type]
            gateway,
            "gemini-3.5-flash",
        )
        first = await service.review("subject-1", "operation-1", impact, plan, NOW)
        replay = await service.review("subject-1", "operation-1", impact, plan, NOW)
        assert first.review.model == "gemini-3.5-flash"
        assert first.review.prompt_version == "consequence-safety-review-v2"
        assert first.review.disposition == AgentDisposition.PROCEED
        assert replay.reused is True
        assert len(gateway.calls) == 1
        assert gateway.calls[0]["repairRequiredClaimIds"] == sorted(
            {step.claim_id for step in plan.steps}
        )
        assert gateway.calls[0]["semanticallyUnchangedImpactedClaimIds"] == sorted(
            plan.unchanged_impacted_claim_ids
        )

        gateway.payload = gateway.payload.model_copy(
            update={"recognized_claim_ids": ("invented-claim",)}
        )
        with pytest.raises(AgentReviewError, match="changed the registered claim scope"):
            await GeminiConsequenceReviewService(
                MemoryReviews(),  # type: ignore[arg-type]
                gateway,
                "gemini-3.5-flash",
            ).review("subject-1", "operation-2", impact, plan, NOW)

        escalation = StaticReviewGateway(
            GeminiReviewPayload(
                disposition=AgentDisposition.ESCALATE,
                rationale="The authority boundary is ambiguous and requires a human decision.",
                recognized_claim_ids=claim_ids,
                risk_flags=("ambiguous authority",),
            )
        )
        with pytest.raises(AgentEscalationRequired, match="authority boundary"):
            await GeminiConsequenceReviewService(
                MemoryReviews(),  # type: ignore[arg-type]
                escalation,
                "gemini-3.5-flash",
            ).review("subject-1", "operation-3", impact, plan, NOW)

    asyncio.run(scenario())


def test_gemini_review_distinguishes_lineage_impact_from_required_repairs() -> None:
    async def scenario() -> None:
        impact, plan = await _plan()
        unchanged_claim_id = plan.steps[0].claim_id
        remaining_steps = tuple(step for step in plan.steps if step.claim_id != unchanged_claim_id)
        partial_plan = plan.model_copy(
            update={
                "steps": remaining_steps,
                "unchanged_impacted_claim_ids": (
                    *plan.unchanged_impacted_claim_ids,
                    unchanged_claim_id,
                ),
            }
        )
        gateway = StaticReviewGateway(
            GeminiReviewPayload(
                disposition=AgentDisposition.PROCEED,
                rationale="Unchanged lineage claims explain the deliberately smaller repair scope.",
                recognized_claim_ids=tuple(claim.claim_id for claim in impact.affected_claims),
                risk_flags=(),
            )
        )

        await GeminiConsequenceReviewService(
            MemoryReviews(),  # type: ignore[arg-type]
            gateway,
            "gemini-3.5-flash",
        ).review("subject-1", "operation-partial", impact, partial_plan, NOW)

        payload = gateway.calls[0]
        assert payload["semanticallyUnchangedImpactedClaimIds"] == [unchanged_claim_id]
        assert payload["repairRequiredClaimIds"] == sorted(
            {step.claim_id for step in remaining_steps}
        )
        affected = payload["affectedClaims"]
        assert isinstance(affected, list)
        repair_flags = {
            item["claimId"]: item["requiresRepair"] for item in affected if isinstance(item, dict)
        }
        assert repair_flags[unchanged_claim_id] is False
        assert all(
            repair_flags[claim_id] for claim_id in {step.claim_id for step in remaining_steps}
        )

    asyncio.run(scenario())


def test_sql_agent_review_rejects_tampered_reasoning_receipts() -> None:
    async def scenario() -> None:
        impact, plan = await _plan()
        gateway = StaticReviewGateway(
            GeminiReviewPayload(
                disposition=AgentDisposition.PROCEED,
                rationale="The registered scope and deterministic policy are internally coherent.",
                recognized_claim_ids=tuple(claim.claim_id for claim in impact.affected_claims),
                risk_flags=(),
            )
        )
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        repository = SqlAgentReviewRepository(engine)
        created = await GeminiConsequenceReviewService(
            repository,
            gateway,
            "gemini-3.5-flash",
        ).review("subject-1", "operation-sql", impact, plan, NOW)
        loaded = await repository.get("subject-1", "operation-sql")
        assert loaded is not None
        assert loaded.review == created.review
        async with engine.begin() as connection:
            await connection.execute(
                update(agent_reviews)
                .where(agent_reviews.c.review_id == created.review.review_id)
                .values(checksum="0" * 64)
            )
        with pytest.raises(ValueError, match="checksum mismatch"):
            await repository.get("subject-1", "operation-sql")
        await engine.dispose()

    asyncio.run(scenario())


def test_google_genai_sdk_uses_vertex_structured_output(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    payload = GeminiReviewPayload(
        disposition=AgentDisposition.PROCEED,
        rationale="The registered scope and deterministic policy are internally coherent.",
        recognized_claim_ids=("claim-1",),
        risk_flags=(),
    )
    calls: list[dict[str, object]] = []

    class Models:
        async def generate_content(self, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(kwargs)
            return SimpleNamespace(parsed=payload, text=None)

    class AsyncClient:
        models = Models()

        async def aclose(self) -> None:
            return None

    class Client:
        def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
            calls.append(kwargs)
            self.aio = AsyncClient()

        def close(self) -> None:
            return None

    monkeypatch.setattr("veritas_runtime.agents.gemini.genai.Client", Client)

    async def scenario() -> None:
        gateway = GeminiReviewGateway("project-1", "us-central1", "gemini-3.5-flash")
        result = await gateway.review({"packetId": "packet-1"})
        assert result == payload
        assert calls[0] == {
            "vertexai": True,
            "project": "project-1",
            "location": "us-central1",
        }
        assert calls[1]["model"] == "gemini-3.5-flash"
        assert calls[1]["config"].response_mime_type == "application/json"
        assert calls[1]["config"].max_output_tokens == 2048
        prompt = calls[1]["contents"][0].parts[0].text
        assert "approvalRequiredSteps greater than zero" in prompt
        assert "not reasons to escalate" in prompt
        await gateway.close()

    asyncio.run(scenario())
