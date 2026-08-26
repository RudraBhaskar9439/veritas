import json
from datetime import datetime

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
    return EmailTaskWorkflow.model_validate(payload)


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
    return event
