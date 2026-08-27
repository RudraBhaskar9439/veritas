import json
from datetime import UTC, datetime

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncEngine

from veritas_runtime.auth.database import metadata
from veritas_runtime.changes.database import registered_evidence_sources
from veritas_runtime.email_tasks.models import (
    EmailTaskEvent,
    EmailTaskEventResult,
    EmailTaskEventStatus,
    EmailTaskReviewDecision,
    EmailTaskThreadBinding,
    EmailTaskThreadSource,
    EmailTaskUnmatchedRequest,
    EmailTaskUnmatchedStatus,
    EmailTaskWorkflow,
    EmailTaskWorkflowResult,
    EmailTaskWorkflowStatus,
    GmailWatchStream,
)

email_task_workflows = Table(
    "email_task_workflows",
    metadata,
    Column("workflow_id", String(255), primary_key=True),
    Column("subject", String(255), nullable=False),
    Column("mailbox_email", String(320), nullable=False),
    Column("authorized_sender", String(320), nullable=False),
    Column("routing_key", String(32), nullable=False),
    Column("packet_id", String(255), nullable=False),
    Column("manifest_id", String(255), nullable=False),
    Column("claim_id", String(255), nullable=False),
    Column("artifact_id", String(255), nullable=False),
    Column("task_id", String(255), nullable=False),
    Column("task_list_id", String(255), nullable=False),
    Column("status", String(32), nullable=False),
    Column("input_digest", String(64), nullable=False),
    Column("workflow_json", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("subject", "routing_key", name="email_task_workflows_route_uq"),
)
Index(
    "email_task_workflows_mailbox_idx",
    email_task_workflows.c.mailbox_email,
    email_task_workflows.c.status,
)

gmail_watch_streams = Table(
    "gmail_watch_streams",
    metadata,
    Column("subject", String(255), primary_key=True),
    Column("mailbox_email", String(320), nullable=False, unique=True),
    Column("history_id", String(255), nullable=False),
    Column("expiration", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

email_task_events = Table(
    "email_task_events",
    metadata,
    Column("event_id", String(255), primary_key=True),
    Column("workflow_id", String(255), nullable=False),
    Column("gmail_message_id", String(255), nullable=False),
    Column("status", String(32), nullable=False),
    Column("receipt_checksum", String(64), nullable=False),
    Column("review_receipt_checksum", String(64), nullable=True),
    Column("event_json", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "workflow_id",
        "gmail_message_id",
        name="email_task_events_workflow_message_uq",
    ),
)
Index(
    "email_task_events_workflow_created_idx",
    email_task_events.c.workflow_id,
    email_task_events.c.created_at,
)

email_task_thread_bindings = Table(
    "email_task_thread_bindings",
    metadata,
    Column("binding_id", String(255), primary_key=True),
    Column("subject", String(255), nullable=False),
    Column("workflow_id", String(255), nullable=False),
    Column("gmail_thread_id", String(255), nullable=False),
    Column("bootstrap_message_id", String(255), nullable=True),
    Column("subject_line", String(998), nullable=False),
    Column("source", String(32), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("subject", "gmail_thread_id", name="email_task_thread_subject_uq"),
)
Index(
    "email_task_thread_workflow_idx",
    email_task_thread_bindings.c.workflow_id,
    email_task_thread_bindings.c.created_at,
)

email_task_unmatched_requests = Table(
    "email_task_unmatched_requests",
    metadata,
    Column("request_id", String(255), primary_key=True),
    Column("subject", String(255), nullable=False),
    Column("gmail_message_id", String(255), nullable=False),
    Column("gmail_thread_id", String(255), nullable=False),
    Column("mailbox_email", String(320), nullable=False),
    Column("sender", String(320), nullable=False),
    Column("recipient", String(320), nullable=False),
    Column("status", String(32), nullable=False),
    Column("bound_workflow_id", String(255), nullable=True),
    Column("receipt_checksum", String(64), nullable=False),
    Column("request_json", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "subject",
        "gmail_message_id",
        name="email_task_unmatched_message_uq",
    ),
)
Index(
    "email_task_unmatched_subject_idx",
    email_task_unmatched_requests.c.subject,
    email_task_unmatched_requests.c.status,
    email_task_unmatched_requests.c.created_at,
)


class SqlEmailTaskWorkflowRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def packet_registered_for_subject(self, subject: str, packet_id: str) -> bool:
        async with self._engine.connect() as connection:
            count = await connection.scalar(
                select(func.count())
                .select_from(registered_evidence_sources)
                .where(
                    registered_evidence_sources.c.subject == subject,
                    registered_evidence_sources.c.packet_id == packet_id,
                )
            )
        return bool(count)

    async def get_by_identity(
        self,
        subject: str,
        routing_key: str,
    ) -> EmailTaskWorkflow | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        select(email_task_workflows).where(
                            email_task_workflows.c.subject == subject,
                            email_task_workflows.c.routing_key == routing_key,
                            email_task_workflows.c.status == EmailTaskWorkflowStatus.ACTIVE.value,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _workflow(row) if row is not None else None

    async def get_by_workflow_id(
        self,
        subject: str,
        workflow_id: str,
    ) -> EmailTaskWorkflow | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        select(email_task_workflows).where(
                            email_task_workflows.c.subject == subject,
                            email_task_workflows.c.workflow_id == workflow_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _workflow(row) if row is not None else None

    async def get_by_thread(
        self,
        subject: str,
        gmail_thread_id: str,
    ) -> EmailTaskWorkflow | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        select(email_task_workflows)
                        .join(
                            email_task_thread_bindings,
                            email_task_thread_bindings.c.workflow_id
                            == email_task_workflows.c.workflow_id,
                        )
                        .where(
                            email_task_workflows.c.subject == subject,
                            email_task_thread_bindings.c.subject == subject,
                            email_task_thread_bindings.c.gmail_thread_id == gmail_thread_id,
                            email_task_workflows.c.status == EmailTaskWorkflowStatus.ACTIVE.value,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _workflow(row) if row is not None else None

    async def active_for_sender(
        self,
        subject: str,
        authorized_sender: str,
    ) -> tuple[EmailTaskWorkflow, ...]:
        async with self._engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        select(email_task_workflows).where(
                            email_task_workflows.c.subject == subject,
                            email_task_workflows.c.authorized_sender == authorized_sender,
                            email_task_workflows.c.status == EmailTaskWorkflowStatus.ACTIVE.value,
                        )
                    )
                )
                .mappings()
                .all()
            )
        return tuple(_workflow(row) for row in rows)

    async def active_for_mailbox(self, mailbox_email: str) -> tuple[EmailTaskWorkflow, ...]:
        async with self._engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        select(email_task_workflows).where(
                            email_task_workflows.c.mailbox_email == mailbox_email,
                            email_task_workflows.c.status == EmailTaskWorkflowStatus.ACTIVE.value,
                        )
                    )
                )
                .mappings()
                .all()
            )
        return tuple(_workflow(row) for row in rows)

    async def list_for_subject(self, subject: str) -> tuple[EmailTaskWorkflow, ...]:
        async with self._engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        select(email_task_workflows)
                        .where(email_task_workflows.c.subject == subject)
                        .order_by(email_task_workflows.c.created_at.desc())
                    )
                )
                .mappings()
                .all()
            )
        return tuple(_workflow(row) for row in rows)

    async def list_threads_for_subject(
        self,
        subject: str,
    ) -> tuple[EmailTaskThreadBinding, ...]:
        async with self._engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        select(email_task_thread_bindings)
                        .where(email_task_thread_bindings.c.subject == subject)
                        .order_by(email_task_thread_bindings.c.created_at.desc())
                    )
                )
                .mappings()
                .all()
            )
        return tuple(_thread(row) for row in rows)

    async def bind_thread(
        self,
        binding: EmailTaskThreadBinding,
    ) -> EmailTaskThreadBinding:
        async with self._engine.begin() as connection:
            row = (
                (
                    await connection.execute(
                        select(email_task_thread_bindings).where(
                            email_task_thread_bindings.c.subject == binding.subject,
                            email_task_thread_bindings.c.gmail_thread_id == binding.gmail_thread_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is not None:
                existing = _thread(row)
                if existing.workflow_id != binding.workflow_id:
                    raise ValueError("A Gmail thread is already bound to another workflow")
                return existing
            await connection.execute(
                insert(email_task_thread_bindings).values(
                    binding_id=binding.binding_id,
                    subject=binding.subject,
                    workflow_id=binding.workflow_id,
                    gmail_thread_id=binding.gmail_thread_id,
                    bootstrap_message_id=binding.bootstrap_message_id,
                    subject_line=binding.subject_line,
                    source=binding.source.value,
                    created_at=binding.created_at,
                    updated_at=binding.updated_at,
                )
            )
        return binding

    async def persist_unmatched(
        self,
        request: EmailTaskUnmatchedRequest,
    ) -> EmailTaskUnmatchedRequest:
        async with self._engine.begin() as connection:
            row = (
                (
                    await connection.execute(
                        select(email_task_unmatched_requests).where(
                            email_task_unmatched_requests.c.subject == request.subject,
                            email_task_unmatched_requests.c.gmail_message_id
                            == request.gmail_message_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is not None:
                existing = _unmatched(row)
                if (
                    existing.gmail_thread_id != request.gmail_thread_id
                    or existing.sender != request.sender
                    or existing.recipient != request.recipient
                    or existing.subject_line != request.subject_line
                    or existing.body_hash != request.body_hash
                    or existing.candidate_workflow_ids != request.candidate_workflow_ids
                ):
                    raise ValueError("Unmatched email was reused with different evidence")
                return existing
            await connection.execute(
                insert(email_task_unmatched_requests).values(
                    request_id=request.request_id,
                    subject=request.subject,
                    gmail_message_id=request.gmail_message_id,
                    gmail_thread_id=request.gmail_thread_id,
                    mailbox_email=request.mailbox_email,
                    sender=request.sender,
                    recipient=request.recipient,
                    status=request.status.value,
                    bound_workflow_id=request.bound_workflow_id,
                    receipt_checksum=request.receipt_checksum,
                    request_json=request.model_dump_json(by_alias=True),
                    created_at=request.created_at,
                    updated_at=request.updated_at,
                )
            )
        return request

    async def list_unmatched_for_subject(
        self,
        subject: str,
    ) -> tuple[EmailTaskUnmatchedRequest, ...]:
        async with self._engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        select(email_task_unmatched_requests)
                        .where(email_task_unmatched_requests.c.subject == subject)
                        .order_by(email_task_unmatched_requests.c.created_at.desc())
                    )
                )
                .mappings()
                .all()
            )
        return tuple(_unmatched(row) for row in rows)

    async def get_unmatched(
        self,
        subject: str,
        request_id: str,
    ) -> EmailTaskUnmatchedRequest | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        select(email_task_unmatched_requests).where(
                            email_task_unmatched_requests.c.subject == subject,
                            email_task_unmatched_requests.c.request_id == request_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _unmatched(row) if row is not None else None

    async def bind_unmatched(
        self,
        subject: str,
        request_id: str,
        workflow_id: str,
        updated_at: datetime,
    ) -> EmailTaskUnmatchedRequest | None:
        async with self._engine.begin() as connection:
            row = (
                (
                    await connection.execute(
                        select(email_task_unmatched_requests).where(
                            email_task_unmatched_requests.c.subject == subject,
                            email_task_unmatched_requests.c.request_id == request_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            request = _unmatched(row)
            if workflow_id not in request.candidate_workflow_ids:
                raise ValueError("The selected workflow is not authorized for this sender")
            bound = request.model_copy(
                update={
                    "status": EmailTaskUnmatchedStatus.BOUND,
                    "bound_workflow_id": workflow_id,
                    "updated_at": updated_at,
                }
            )
            await connection.execute(
                update(email_task_unmatched_requests)
                .where(
                    email_task_unmatched_requests.c.subject == subject,
                    email_task_unmatched_requests.c.request_id == request_id,
                )
                .values(
                    status=bound.status.value,
                    bound_workflow_id=workflow_id,
                    request_json=bound.model_dump_json(by_alias=True),
                    updated_at=updated_at,
                )
            )
        return bound

    async def pause_for_subject(
        self,
        subject: str,
        workflow_id: str,
        updated_at: datetime,
    ) -> EmailTaskWorkflow | None:
        async with self._engine.begin() as connection:
            row = (
                (
                    await connection.execute(
                        select(email_task_workflows).where(
                            email_task_workflows.c.subject == subject,
                            email_task_workflows.c.workflow_id == workflow_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            paused = _workflow(row).model_copy(
                update={
                    "status": EmailTaskWorkflowStatus.PAUSED,
                    "updated_at": updated_at,
                }
            )
            await connection.execute(
                update(email_task_workflows)
                .where(
                    email_task_workflows.c.subject == subject,
                    email_task_workflows.c.workflow_id == workflow_id,
                )
                .values(
                    status=EmailTaskWorkflowStatus.PAUSED.value,
                    workflow_json=paused.model_dump_json(by_alias=True),
                    updated_at=updated_at,
                )
            )
        return paused

    async def subject_for_mailbox(self, mailbox_email: str) -> str | None:
        async with self._engine.connect() as connection:
            subjects = (
                (
                    await connection.execute(
                        select(email_task_workflows.c.subject)
                        .where(
                            email_task_workflows.c.mailbox_email == mailbox_email,
                            email_task_workflows.c.status == EmailTaskWorkflowStatus.ACTIVE.value,
                        )
                        .distinct()
                    )
                )
                .scalars()
                .all()
            )
        if len(subjects) > 1:
            raise ValueError("A Gmail mailbox is bound to multiple account subjects")
        return str(subjects[0]) if subjects else None

    async def get_watch(self, subject: str) -> GmailWatchStream | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        select(gmail_watch_streams).where(gmail_watch_streams.c.subject == subject)
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _watch(row) if row is not None else None

    async def expiring_watches(
        self,
        before: datetime,
        limit: int,
    ) -> tuple[GmailWatchStream, ...]:
        async with self._engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        select(gmail_watch_streams)
                        .where(gmail_watch_streams.c.expiration <= before)
                        .order_by(gmail_watch_streams.c.expiration)
                        .limit(limit)
                    )
                )
                .mappings()
                .all()
            )
        return tuple(_watch(row) for row in rows)

    async def upsert_watch(self, stream: GmailWatchStream) -> GmailWatchStream:
        async with self._engine.begin() as connection:
            existing = (
                (
                    await connection.execute(
                        select(gmail_watch_streams).where(
                            gmail_watch_streams.c.subject == stream.subject
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            values = {
                "mailbox_email": stream.mailbox_email,
                "history_id": stream.history_id,
                "expiration": stream.expiration,
                "updated_at": stream.updated_at,
            }
            if existing is None:
                await connection.execute(
                    insert(gmail_watch_streams).values(
                        subject=stream.subject,
                        created_at=stream.created_at,
                        **values,
                    )
                )
            else:
                if str(existing["mailbox_email"]) != stream.mailbox_email:
                    raise ValueError("A subject cannot switch Gmail mailboxes silently")
                await connection.execute(
                    update(gmail_watch_streams)
                    .where(gmail_watch_streams.c.subject == stream.subject)
                    .values(**values)
                )
        loaded = await self.get_watch(stream.subject)
        if loaded is None:
            raise RuntimeError("Stored Gmail watch disappeared")
        return loaded

    async def advance_history(
        self,
        subject: str,
        expected_history_id: str,
        history_id: str,
        updated_at: datetime,
    ) -> bool:
        async with self._engine.begin() as connection:
            result = await connection.execute(
                update(gmail_watch_streams)
                .where(
                    gmail_watch_streams.c.subject == subject,
                    gmail_watch_streams.c.history_id == expected_history_id,
                )
                .values(history_id=history_id, updated_at=updated_at)
            )
        return result.rowcount == 1

    async def get_event(
        self,
        workflow_id: str,
        gmail_message_id: str,
    ) -> EmailTaskEvent | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        select(email_task_events).where(
                            email_task_events.c.workflow_id == workflow_id,
                            email_task_events.c.gmail_message_id == gmail_message_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _event(row) if row is not None else None

    async def get_event_by_id(
        self,
        subject: str,
        event_id: str,
    ) -> EmailTaskEvent | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        select(email_task_events)
                        .join(
                            email_task_workflows,
                            email_task_events.c.workflow_id == email_task_workflows.c.workflow_id,
                        )
                        .where(
                            email_task_workflows.c.subject == subject,
                            email_task_events.c.event_id == event_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _event(row) if row is not None else None

    async def claim_event_review(
        self,
        subject: str,
        event_id: str,
        decision: EmailTaskReviewDecision,
        request_id: str,
        reason: str,
        reviewed_by: str,
        reviewed_at: datetime,
    ) -> EmailTaskEventResult:
        async with self._engine.begin() as connection:
            row = (
                (
                    await connection.execute(
                        select(email_task_events)
                        .join(
                            email_task_workflows,
                            email_task_events.c.workflow_id == email_task_workflows.c.workflow_id,
                        )
                        .where(
                            email_task_workflows.c.subject == subject,
                            email_task_events.c.event_id == event_id,
                        )
                        .with_for_update()
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ValueError("The escalated email request was not found")
            current = _event(row)
            if current.review_request_id == request_id:
                if current.review_decision != decision:
                    raise ValueError("Review request identity was reused with another decision")
                return EmailTaskEventResult(event=current, reused=True)
            if current.status != EmailTaskEventStatus.ESCALATED:
                raise ValueError("The email request has already been resolved")
            claimed = current.model_copy(
                update={
                    "status": EmailTaskEventStatus.REVIEWING,
                    "review_decision": decision,
                    "review_request_id": request_id,
                    "review_reason": reason,
                    "reviewed_by": reviewed_by,
                    "reviewed_at": reviewed_at,
                    "updated_at": reviewed_at,
                }
            )
            await connection.execute(
                update(email_task_events)
                .where(
                    email_task_events.c.event_id == event_id,
                    email_task_events.c.status == EmailTaskEventStatus.ESCALATED.value,
                )
                .values(
                    status=claimed.status.value,
                    event_json=claimed.model_dump_json(by_alias=True),
                    updated_at=reviewed_at,
                )
            )
        return EmailTaskEventResult(event=claimed, reused=False)

    async def finalize_event_review(
        self,
        event_id: str,
        request_id: str,
        status: EmailTaskEventStatus,
        task_revision: str | None,
        review_receipt_checksum: str,
        updated_at: datetime,
    ) -> EmailTaskEventResult:
        if status not in {EmailTaskEventStatus.APPLIED, EmailTaskEventStatus.REJECTED}:
            raise ValueError("Email review can only finish as applied or rejected")
        async with self._engine.begin() as connection:
            row = (
                (
                    await connection.execute(
                        select(email_task_events)
                        .where(email_task_events.c.event_id == event_id)
                        .with_for_update()
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ValueError("The escalated email request was not found")
            current = _event(row)
            if current.review_request_id != request_id:
                raise ValueError("Another operator owns this email review")
            if current.status == status and current.review_receipt_checksum:
                return EmailTaskEventResult(event=current, reused=True)
            if current.status != EmailTaskEventStatus.REVIEWING:
                raise ValueError("The email request is not awaiting this review")
            resolved = current.model_copy(
                update={
                    "status": status,
                    "task_revision": task_revision,
                    "review_receipt_checksum": review_receipt_checksum,
                    "updated_at": updated_at,
                }
            )
            await connection.execute(
                update(email_task_events)
                .where(
                    email_task_events.c.event_id == event_id,
                    email_task_events.c.status == EmailTaskEventStatus.REVIEWING.value,
                )
                .values(
                    status=resolved.status.value,
                    review_receipt_checksum=review_receipt_checksum,
                    event_json=resolved.model_dump_json(by_alias=True),
                    updated_at=updated_at,
                )
            )
        return EmailTaskEventResult(event=resolved, reused=False)

    async def release_event_review(
        self,
        event_id: str,
        request_id: str,
        updated_at: datetime,
    ) -> EmailTaskEvent | None:
        async with self._engine.begin() as connection:
            row = (
                (
                    await connection.execute(
                        select(email_task_events)
                        .where(email_task_events.c.event_id == event_id)
                        .with_for_update()
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            current = _event(row)
            if (
                current.status != EmailTaskEventStatus.REVIEWING
                or current.review_request_id != request_id
            ):
                return current
            released = current.model_copy(
                update={
                    "status": EmailTaskEventStatus.ESCALATED,
                    "review_decision": None,
                    "review_request_id": None,
                    "review_reason": None,
                    "reviewed_by": None,
                    "reviewed_at": None,
                    "updated_at": updated_at,
                }
            )
            await connection.execute(
                update(email_task_events)
                .where(
                    email_task_events.c.event_id == event_id,
                    email_task_events.c.status == EmailTaskEventStatus.REVIEWING.value,
                )
                .values(
                    status=released.status.value,
                    event_json=released.model_dump_json(by_alias=True),
                    updated_at=updated_at,
                )
            )
        return released

    async def list_events_for_subject(
        self,
        subject: str,
        packet_id: str,
    ) -> tuple[EmailTaskEvent, ...]:
        async with self._engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        select(email_task_events)
                        .join(
                            email_task_workflows,
                            email_task_events.c.workflow_id == email_task_workflows.c.workflow_id,
                        )
                        .where(
                            email_task_workflows.c.subject == subject,
                            email_task_workflows.c.packet_id == packet_id,
                        )
                        .order_by(email_task_events.c.created_at.desc())
                    )
                )
                .mappings()
                .all()
            )
        return tuple(_event(row) for row in rows)

    async def persist_event(self, event: EmailTaskEvent) -> EmailTaskEventResult:
        async with self._engine.begin() as connection:
            row = (
                (
                    await connection.execute(
                        select(email_task_events).where(
                            email_task_events.c.workflow_id == event.workflow_id,
                            email_task_events.c.gmail_message_id == event.gmail_message_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is not None:
                existing = _event(row)
                if existing.receipt_checksum != event.receipt_checksum:
                    raise ValueError("Email-task event was reused with different evidence")
                return EmailTaskEventResult(event=existing, reused=True)
            await connection.execute(
                insert(email_task_events).values(
                    event_id=event.event_id,
                    workflow_id=event.workflow_id,
                    gmail_message_id=event.gmail_message_id,
                    status=event.status.value,
                    receipt_checksum=event.receipt_checksum,
                    review_receipt_checksum=event.review_receipt_checksum,
                    event_json=event.model_dump_json(by_alias=True),
                    created_at=event.created_at,
                    updated_at=event.updated_at,
                )
            )
        return EmailTaskEventResult(event=event, reused=False)

    async def persist(
        self,
        workflow: EmailTaskWorkflow,
        input_digest: str,
    ) -> EmailTaskWorkflowResult:
        async with self._engine.begin() as connection:
            row = (
                (
                    await connection.execute(
                        select(email_task_workflows).where(
                            email_task_workflows.c.subject == workflow.subject,
                            email_task_workflows.c.routing_key == workflow.routing_key,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is not None:
                if str(row["input_digest"]) != input_digest:
                    raise ValueError(
                        "Email-task workflow identity was reused with different inputs"
                    )
                return EmailTaskWorkflowResult(workflow=_workflow(row), reused=True)
            await connection.execute(
                insert(email_task_workflows).values(
                    workflow_id=workflow.workflow_id,
                    subject=workflow.subject,
                    mailbox_email=workflow.mailbox_email,
                    authorized_sender=workflow.authorized_sender,
                    routing_key=workflow.routing_key,
                    packet_id=workflow.packet_id,
                    manifest_id=workflow.manifest_id,
                    claim_id=workflow.claim_id,
                    artifact_id=workflow.artifact_id,
                    task_id=workflow.task_id,
                    task_list_id=workflow.task_list_id,
                    status=workflow.status.value,
                    input_digest=input_digest,
                    workflow_json=workflow.model_dump_json(by_alias=True),
                    created_at=workflow.created_at,
                    updated_at=workflow.updated_at,
                )
            )
        return EmailTaskWorkflowResult(workflow=workflow, reused=False)


def _workflow(row: RowMapping | dict[str, object]) -> EmailTaskWorkflow:
    raw = row["workflow_json"]
    if not isinstance(raw, str):
        raise TypeError("Stored email-task workflow JSON must be text")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise TypeError("Stored email-task workflow JSON must be an object")
    payload["subject"] = str(row["subject"])
    payload["routingKey"] = str(row["routing_key"])
    return EmailTaskWorkflow.model_validate(payload)


def _thread(row: RowMapping | dict[str, object]) -> EmailTaskThreadBinding:
    created_at = row["created_at"]
    updated_at = row["updated_at"]
    if not isinstance(created_at, datetime) or not isinstance(updated_at, datetime):
        raise TypeError("Stored Gmail thread timestamps must be datetimes")
    return EmailTaskThreadBinding(
        binding_id=str(row["binding_id"]),
        subject=str(row["subject"]),
        workflow_id=str(row["workflow_id"]),
        gmail_thread_id=str(row["gmail_thread_id"]),
        bootstrap_message_id=(
            str(row["bootstrap_message_id"]) if row["bootstrap_message_id"] is not None else None
        ),
        subject_line=str(row["subject_line"]),
        source=EmailTaskThreadSource(str(row["source"])),
        created_at=_utc(created_at),
        updated_at=_utc(updated_at),
    )


def _unmatched(row: RowMapping | dict[str, object]) -> EmailTaskUnmatchedRequest:
    raw = row["request_json"]
    if not isinstance(raw, str):
        raise TypeError("Stored unmatched email JSON must be text")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise TypeError("Stored unmatched email JSON must be an object")
    payload["subject"] = str(row["subject"])
    request = EmailTaskUnmatchedRequest.model_validate(payload)
    if request.receipt_checksum != str(row["receipt_checksum"]):
        raise ValueError("Stored unmatched email receipt checksum mismatch")
    return request


def _watch(row: RowMapping | dict[str, object]) -> GmailWatchStream:
    expiration = row["expiration"]
    created_at = row["created_at"]
    updated_at = row["updated_at"]
    if (
        not isinstance(expiration, datetime)
        or not isinstance(created_at, datetime)
        or not isinstance(updated_at, datetime)
    ):
        raise TypeError("Stored Gmail watch timestamps must be datetimes")
    return GmailWatchStream(
        subject=str(row["subject"]),
        mailbox_email=str(row["mailbox_email"]),
        history_id=str(row["history_id"]),
        expiration=expiration,
        created_at=created_at,
        updated_at=updated_at,
    )


def _event(row: RowMapping | dict[str, object]) -> EmailTaskEvent:
    raw = row["event_json"]
    if not isinstance(raw, str):
        raise TypeError("Stored email-task event JSON must be text")
    event = EmailTaskEvent.model_validate(json.loads(raw))
    if event.receipt_checksum != str(row["receipt_checksum"]):
        raise ValueError("Stored email-task receipt checksum mismatch")
    stored_review_checksum = row.get("review_receipt_checksum")
    if event.review_receipt_checksum != (
        str(stored_review_checksum) if stored_review_checksum is not None else None
    ):
        raise ValueError("Stored email-task review receipt checksum mismatch")
    return event


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
