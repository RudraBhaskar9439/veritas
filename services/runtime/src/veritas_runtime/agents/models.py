from datetime import datetime
from enum import StrEnum

from pydantic import Field

from veritas_runtime.packets.models import CamelModel


class AgentDisposition(StrEnum):
    PROCEED = "proceed"
    ESCALATE = "escalate"


class GeminiReviewPayload(CamelModel):
    disposition: AgentDisposition
    rationale: str = Field(min_length=12, max_length=600)
    recognized_claim_ids: tuple[str, ...]
    risk_flags: tuple[str, ...] = Field(max_length=8)


class AgentReview(CamelModel):
    review_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    packet_id: str = Field(min_length=1)
    model: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    disposition: AgentDisposition
    rationale: str = Field(min_length=12, max_length=600)
    recognized_claim_ids: tuple[str, ...]
    risk_flags: tuple[str, ...]
    input_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: datetime


class AgentReviewResult(CamelModel):
    review: AgentReview
    checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    reused: bool
