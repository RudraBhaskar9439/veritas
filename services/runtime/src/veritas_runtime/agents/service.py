import hashlib
import json
from datetime import UTC, datetime
from typing import Protocol

from veritas_runtime.agents.models import (
    AgentDisposition,
    AgentReview,
    AgentReviewResult,
    GeminiReviewPayload,
)
from veritas_runtime.lineage.models import ImpactReport
from veritas_runtime.repairs.models import RepairPlan

PROMPT_VERSION = "consequence-safety-review-v2"


class AgentReviewError(RuntimeError):
    """Gemini could not produce a safe, contract-bound review."""


class AgentEscalationRequired(AgentReviewError):
    """Gemini identified ambiguity that must stop autonomous execution."""


class AgentReviewGateway(Protocol):
    async def review(self, payload: dict[str, object]) -> GeminiReviewPayload: ...


class AgentReviewRepository(Protocol):
    async def get(self, subject: str, operation_id: str) -> AgentReviewResult | None: ...

    async def persist(
        self,
        subject: str,
        review: AgentReview,
        checksum: str,
    ) -> AgentReviewResult: ...


class GeminiConsequenceReviewService:
    """Lets Gemini veto unsafe work but never invent scope or authorize mutations."""

    def __init__(
        self,
        repository: AgentReviewRepository,
        gateway: AgentReviewGateway,
        model: str,
    ) -> None:
        self._repository = repository
        self._gateway = gateway
        self._model = model

    async def review(
        self,
        subject: str,
        operation_id: str,
        impact: ImpactReport,
        plan: RepairPlan,
        now: datetime | None = None,
    ) -> AgentReviewResult:
        if not subject or not operation_id:
            raise AgentReviewError("Subject and operation ID are required")
        payload = _review_input(operation_id, impact, plan)
        input_digest = _digest(payload)
        existing = await self._repository.get(subject, operation_id)
        if existing is not None:
            if existing.review.input_digest != input_digest:
                raise AgentReviewError("Agent review operation was reused with different inputs")
            if existing.review.disposition == AgentDisposition.ESCALATE:
                raise AgentEscalationRequired(existing.review.rationale)
            return existing.model_copy(update={"reused": True})
        generated = await self._gateway.review(payload)
        expected_claims = {claim.claim_id for claim in impact.affected_claims}
        if set(generated.recognized_claim_ids) != expected_claims:
            raise AgentReviewError("Gemini review changed the registered claim scope")
        review = AgentReview(
            review_id=f"agent-review-{hashlib.sha256(f'{subject}:{operation_id}'.encode()).hexdigest()[:24]}",
            operation_id=operation_id,
            plan_id=plan.plan_id,
            packet_id=plan.packet_id,
            model=self._model,
            prompt_version=PROMPT_VERSION,
            disposition=generated.disposition,
            rationale=generated.rationale,
            recognized_claim_ids=tuple(sorted(generated.recognized_claim_ids)),
            risk_flags=generated.risk_flags,
            input_digest=input_digest,
            created_at=(now or datetime.now(UTC)).astimezone(UTC),
        )
        stored = await self._repository.persist(subject, review, agent_review_checksum(review))
        if stored.review.disposition == AgentDisposition.ESCALATE:
            raise AgentEscalationRequired(stored.review.rationale)
        return stored


def agent_review_checksum(review: AgentReview) -> str:
    return _digest(review.model_dump(mode="json", by_alias=True))


def _review_input(
    operation_id: str,
    impact: ImpactReport,
    plan: RepairPlan,
) -> dict[str, object]:
    repair_claim_ids = {step.claim_id for step in plan.steps}
    repair_artifact_ids = {step.artifact_id for step in plan.steps}
    return {
        "instruction": (
            "Review this already-scoped consequence repair. Proceed only when the registered "
            "lineage impact, deterministically unchanged claims, repair-required claims, and "
            "policy are internally coherent. Never add claims, artifacts, permissions, or "
            "actions. Escalate ambiguity to a human."
        ),
        "operationId": operation_id,
        "packetId": impact.packet_id,
        "affectedClaims": [
            {
                "claimId": claim.claim_id,
                "risk": claim.risk.value,
                "requiresRepair": claim.claim_id in repair_claim_ids,
            }
            for claim in impact.affected_claims
        ],
        "registeredPathCount": len(impact.lineage_paths),
        "lineageAffectedArtifactCount": len(impact.affected_artifacts),
        "repairRequiredClaimIds": sorted(repair_claim_ids),
        "semanticallyUnchangedImpactedClaimIds": sorted(plan.unchanged_impacted_claim_ids),
        "repairArtifactCount": len(repair_artifact_ids),
        "repairTargetCount": len(plan.steps),
        "policySummary": plan.policy_summary.model_dump(mode="json", by_alias=True),
        "planState": plan.state.value,
    }


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()
