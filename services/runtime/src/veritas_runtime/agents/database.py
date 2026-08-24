import json

from sqlalchemy import Column, DateTime, ForeignKey, String, Table, Text, insert, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncEngine

from veritas_runtime.agents.models import AgentReview, AgentReviewResult
from veritas_runtime.agents.service import agent_review_checksum
from veritas_runtime.auth.database import metadata
from veritas_runtime.operations.database import operations
from veritas_runtime.repairs.database import repair_plans

agent_reviews = Table(
    "agent_reviews",
    metadata,
    Column("review_id", String(255), primary_key=True),
    Column("subject", String(255), nullable=False),
    Column(
        "operation_id",
        String(255),
        ForeignKey(operations.c.operation_id),
        nullable=False,
        unique=True,
    ),
    Column("plan_id", String(255), ForeignKey(repair_plans.c.plan_id), nullable=False),
    Column("packet_id", String(255), nullable=False),
    Column("model", String(255), nullable=False),
    Column("prompt_version", String(255), nullable=False),
    Column("input_digest", String(64), nullable=False),
    Column("checksum", String(64), nullable=False),
    Column("review_json", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


class SqlAgentReviewRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get(self, subject: str, operation_id: str) -> AgentReviewResult | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        select(agent_reviews).where(
                            agent_reviews.c.subject == subject,
                            agent_reviews.c.operation_id == operation_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _stored(row, reused=True) if row is not None else None

    async def persist(
        self,
        subject: str,
        review: AgentReview,
        checksum: str,
    ) -> AgentReviewResult:
        async with self._engine.begin() as connection:
            existing = (
                (
                    await connection.execute(
                        select(agent_reviews).where(
                            agent_reviews.c.subject == subject,
                            agent_reviews.c.operation_id == review.operation_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                return _stored(existing, reused=True)
            await connection.execute(
                insert(agent_reviews).values(
                    review_id=review.review_id,
                    subject=subject,
                    operation_id=review.operation_id,
                    plan_id=review.plan_id,
                    packet_id=review.packet_id,
                    model=review.model,
                    prompt_version=review.prompt_version,
                    input_digest=review.input_digest,
                    checksum=checksum,
                    review_json=review.model_dump_json(by_alias=True),
                    created_at=review.created_at,
                )
            )
        return AgentReviewResult(review=review, checksum=checksum, reused=False)


def _stored(row: RowMapping, *, reused: bool) -> AgentReviewResult:
    review = AgentReview.model_validate(json.loads(str(row["review_json"])))
    checksum = str(row["checksum"])
    if agent_review_checksum(review) != checksum:
        raise ValueError("Stored Gemini agent review checksum mismatch")
    if review.input_digest != str(row["input_digest"]):
        raise ValueError("Stored Gemini agent review input digest mismatch")
    return AgentReviewResult(review=review, checksum=checksum, reused=reused)
