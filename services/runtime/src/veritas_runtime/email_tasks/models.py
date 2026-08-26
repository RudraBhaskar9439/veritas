from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator

from veritas_runtime.packets.models import CamelModel


class EmailTaskWorkflowStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"


class EmailTaskThreadSource(StrEnum):
    COMPANY_STARTED = "company_started"
    OPERATOR_BOUND = "operator_bound"


class EmailTaskUnmatchedStatus(StrEnum):
    PENDING = "pending"
    BOUND = "bound"


class EmailTaskEventStatus(StrEnum):
    RECEIVED = "received"
    IGNORED = "ignored"
    ESCALATED = "escalated"
    APPLIED = "applied"


class EmailTaskDisposition(StrEnum):
    UPDATE = "update"
    IGNORE = "ignore"
    ESCALATE = "escalate"


class RegisterEmailTaskWorkflowRequest(CamelModel):
    packet_id: str = Field(min_length=1, max_length=255)
    claim_id: str = Field(min_length=1, max_length=255)
    artifact_id: str = Field(min_length=1, max_length=255)
    authorized_sender: str = Field(min_length=3, max_length=320)

    @field_validator("authorized_sender")
    @classmethod
    def valid_sender(cls, value: str) -> str:
        from veritas_runtime.email_tasks.policy import normalize_email

        return normalize_email(value)


class EmailTaskWorkflow(CamelModel):
    workflow_id: str = Field(min_length=1, max_length=255)
    subject: str = Field(min_length=1, max_length=255, exclude=True, repr=False)
    mailbox_email: str = Field(min_length=3, max_length=320)
    authorized_sender: str = Field(min_length=3, max_length=320)
    routing_key: str = Field(pattern=r"^VX-[A-F0-9]{12}$", exclude=True, repr=False)
    packet_id: str = Field(min_length=1, max_length=255)
    manifest_id: str = Field(min_length=1, max_length=255)
    claim_id: str = Field(min_length=1, max_length=255)
    artifact_id: str = Field(min_length=1, max_length=255)
    task_id: str = Field(min_length=1, max_length=255)
    task_list_id: str = Field(min_length=1, max_length=255)
    status: EmailTaskWorkflowStatus
    created_at: datetime
    updated_at: datetime


class EmailTaskWorkflowResult(CamelModel):
    workflow: EmailTaskWorkflow
    reused: bool


class EmailTaskRegistrationResult(CamelModel):
    workflow: EmailTaskWorkflow
    watch: GmailWatchStream
    reused: bool


class GmailConversationSeed(CamelModel):
    gmail_message_id: str = Field(min_length=1, max_length=255)
    gmail_thread_id: str = Field(min_length=1, max_length=255)


class EmailTaskThreadBinding(CamelModel):
    binding_id: str = Field(min_length=1, max_length=255)
    subject: str = Field(min_length=1, max_length=255, exclude=True, repr=False)
    workflow_id: str = Field(min_length=1, max_length=255)
    gmail_thread_id: str = Field(min_length=1, max_length=255)
    bootstrap_message_id: str | None = Field(default=None, max_length=255)
    subject_line: str = Field(min_length=1, max_length=998)
    source: EmailTaskThreadSource
    created_at: datetime
    updated_at: datetime


class EmailTaskUnmatchedRequest(CamelModel):
    request_id: str = Field(min_length=1, max_length=255)
    subject: str = Field(min_length=1, max_length=255, exclude=True, repr=False)
    gmail_message_id: str = Field(min_length=1, max_length=255)
    gmail_thread_id: str = Field(min_length=1, max_length=255)
    mailbox_email: str = Field(min_length=3, max_length=320)
    sender: str = Field(min_length=3, max_length=320)
    recipient: str = Field(min_length=3, max_length=320)
    subject_line: str = Field(min_length=1, max_length=998)
    body_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    candidate_workflow_ids: tuple[str, ...]
    status: EmailTaskUnmatchedStatus
    bound_workflow_id: str | None = Field(default=None, max_length=255)
    receipt_checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    received_at: datetime
    created_at: datetime
    updated_at: datetime


class BindEmailTaskUnmatchedRequest(CamelModel):
    workflow_id: str = Field(min_length=1, max_length=255)


class EmailTaskEligibleRoute(CamelModel):
    claim_id: str = Field(min_length=1, max_length=255)
    claim_statement: str = Field(min_length=1, max_length=4000)
    claim_risk: str = Field(min_length=1, max_length=64)
    artifact_id: str = Field(min_length=1, max_length=255)
    task_id: str = Field(min_length=1, max_length=255)
    task_list_id: str = Field(min_length=1, max_length=255)


class EmailTaskSetup(CamelModel):
    packet_id: str = Field(min_length=1, max_length=255)
    mailbox_email: str = Field(min_length=3, max_length=320)
    routes: tuple[EmailTaskEligibleRoute, ...]
    workflows: tuple[EmailTaskWorkflow, ...]
    threads: tuple[EmailTaskThreadBinding, ...] = ()
    unmatched_requests: tuple[EmailTaskUnmatchedRequest, ...] = ()


class GmailWatchStream(CamelModel):
    subject: str = Field(min_length=1, max_length=255, exclude=True, repr=False)
    mailbox_email: str = Field(min_length=3, max_length=320)
    history_id: str = Field(min_length=1, max_length=255)
    expiration: datetime
    created_at: datetime
    updated_at: datetime


class GeminiEmailTaskPayload(CamelModel):
    disposition: EmailTaskDisposition
    proposed_title: str | None = Field(default=None, min_length=3, max_length=160)
    proposed_note: str | None = Field(default=None, min_length=3, max_length=1200)
    rationale: str = Field(min_length=12, max_length=600)
    confidence: float = Field(ge=0, le=1)
    risk_flags: tuple[str, ...] = Field(max_length=8)


class InboundEmail(CamelModel):
    message_id: str = Field(min_length=1, max_length=255)
    thread_id: str | None = Field(default=None, max_length=255)
    history_id: str = Field(min_length=1, max_length=255)
    sender: str = Field(min_length=3, max_length=320)
    recipient: str = Field(min_length=3, max_length=320)
    subject_line: str = Field(min_length=1, max_length=998)
    body: str = Field(min_length=1, max_length=20_000, exclude=True, repr=False)
    received_at: datetime


class EmailTaskEvent(CamelModel):
    event_id: str = Field(min_length=1, max_length=255)
    workflow_id: str = Field(min_length=1, max_length=255)
    gmail_message_id: str = Field(min_length=1, max_length=255)
    gmail_thread_id: str | None = Field(default=None, max_length=255)
    history_id: str = Field(min_length=1, max_length=255)
    sender: str = Field(min_length=3, max_length=320)
    recipient: str = Field(min_length=3, max_length=320)
    subject_line: str = Field(min_length=1, max_length=998)
    body_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    proposed_title: str | None = Field(default=None, max_length=160)
    proposed_note: str | None = Field(default=None, max_length=1200)
    status: EmailTaskEventStatus
    rationale: str = Field(min_length=1, max_length=600)
    risk_flags: tuple[str, ...] = Field(max_length=8)
    task_revision: str | None = Field(default=None, max_length=255)
    receipt_checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    received_at: datetime
    created_at: datetime
    updated_at: datetime


class EmailTaskEventResult(CamelModel):
    event: EmailTaskEvent
    reused: bool


class GmailPushNotification(CamelModel):
    pubsub_message_id: str = Field(min_length=1, max_length=255)
    mailbox_email: str = Field(min_length=3, max_length=320)
    history_id: str = Field(min_length=1, max_length=255)
    published_at: datetime | None = None


class GmailHistoryPage(CamelModel):
    history_id: str = Field(min_length=1, max_length=255)
    message_ids: tuple[str, ...]


class GoogleTaskState(CamelModel):
    task_id: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=1024)
    notes: str = Field(default="", max_length=8192)
    etag: str = Field(min_length=1, max_length=255)
