import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from veritas_runtime.email_tasks.gemini import EmailTaskExtractionError
from veritas_runtime.email_tasks.google import (
    EmailTaskPreconditionFailed,
    GmailHistoryExpired,
)
from veritas_runtime.email_tasks.models import (
    EmailTaskDisposition,
    EmailTaskEvent,
    EmailTaskEventResult,
    EmailTaskEventStatus,
    EmailTaskUnmatchedRequest,
    EmailTaskUnmatchedStatus,
    EmailTaskWorkflow,
    EmailTaskWorkflowStatus,
    GeminiEmailTaskPayload,
    GmailHistoryPage,
    GmailWatchStream,
    GoogleTaskState,
    InboundEmail,
)
from veritas_runtime.email_tasks.policy import (
    deterministic_risk_flags,
    normalize_email,
)
from veritas_runtime.operations.models import Operation
from veritas_runtime.operations.service import PermanentOperationError, RetryableOperationError
from veritas_runtime.workspace.contracts import MissingWorkspaceScope, WorkspaceCapability

GMAIL_PROCESS_OPERATION = "gmail.process"
_MANAGED_BLOCK = re.compile(
    r"\n*--- Veritas customer update ---.*?--- End Veritas customer update ---\n*",
    flags=re.DOTALL,
)


class EmailTaskProcessorRepository(Protocol):
    async def get_by_thread(
        self,
        subject: str,
        gmail_thread_id: str,
    ) -> EmailTaskWorkflow | None: ...

    async def active_for_sender(
        self,
        subject: str,
        authorized_sender: str,
    ) -> tuple[EmailTaskWorkflow, ...]: ...

    async def get_watch(self, subject: str) -> GmailWatchStream | None: ...

    async def advance_history(
        self,
        subject: str,
        expected_history_id: str,
        history_id: str,
        updated_at: datetime,
    ) -> bool: ...

    async def get_event(
        self,
        workflow_id: str,
        gmail_message_id: str,
    ) -> EmailTaskEvent | None: ...

    async def persist_event(self, event: EmailTaskEvent) -> EmailTaskEventResult: ...

    async def persist_unmatched(
        self,
        request: EmailTaskUnmatchedRequest,
    ) -> EmailTaskUnmatchedRequest: ...


class GmailTaskGateway(Protocol):
    async def history_since(
        self,
        access_token: str,
        start_history_id: str,
    ) -> GmailHistoryPage: ...

    async def get_email(
        self,
        access_token: str,
        message_id: str,
        history_id: str,
    ) -> InboundEmail: ...

    async def get_task(
        self,
        access_token: str,
        task_list_id: str,
        task_id: str,
    ) -> GoogleTaskState: ...

    async def update_task(
        self,
        access_token: str,
        task_list_id: str,
        current: GoogleTaskState,
        title: str,
        notes: str,
    ) -> GoogleTaskState: ...


class EmailTaskExtractor(Protocol):
    async def extract(
        self,
        email: InboundEmail,
        current_task: GoogleTaskState,
    ) -> GeminiEmailTaskPayload: ...


class GmailTaskProcessor:
    """Consumes one Gmail history cursor and updates only the manifest-bound task."""

    def __init__(
        self,
        repository: EmailTaskProcessorRepository,
        gateway: GmailTaskGateway,
        extractor: EmailTaskExtractor,
    ) -> None:
        self._repository = repository
        self._gateway = gateway
        self._extractor = extractor

    async def process(
        self,
        subject: str,
        mailbox_email: str,
        access_token: str,
        now: datetime | None = None,
    ) -> tuple[EmailTaskEvent, ...]:
        stream = await self._repository.get_watch(subject)
        mailbox = normalize_email(mailbox_email)
        if stream is None or stream.mailbox_email != mailbox:
            raise PermanentOperationError("gmail_watch_not_registered")
        try:
            page = await self._gateway.history_since(access_token, stream.history_id)
        except GmailHistoryExpired as error:
            raise PermanentOperationError("gmail_history_expired") from error
        instant = (now or datetime.now(UTC)).astimezone(UTC)
        events: list[EmailTaskEvent] = []
        for message_id in page.message_ids:
            email = await self._gateway.get_email(access_token, message_id, page.history_id)
            event = await self._process_email(subject, stream, email, access_token, instant)
            if event is not None:
                events.append(event)
        if page.history_id != stream.history_id and not await self._repository.advance_history(
            subject,
            stream.history_id,
            page.history_id,
            instant,
        ):
            raise RetryableOperationError("gmail_history_cursor_conflict")
        return tuple(events)

    async def _process_email(
        self,
        subject: str,
        stream: GmailWatchStream,
        email: InboundEmail,
        access_token: str,
        now: datetime,
    ) -> EmailTaskEvent | None:
        if email.thread_id is None:
            return None
        workflow = await self._repository.get_by_thread(subject, email.thread_id)
        if workflow is None:
            await self._persist_unmatched(subject, stream, email, now)
            return None
        if workflow.status != EmailTaskWorkflowStatus.ACTIVE:
            return None
        existing = await self._repository.get_event(workflow.workflow_id, email.message_id)
        if existing is not None:
            return existing
        sender = normalize_email(email.sender)
        recipient = normalize_email(email.recipient)
        if sender != workflow.authorized_sender or recipient != stream.mailbox_email:
            return await self._persist(
                workflow,
                email,
                EmailTaskEventStatus.IGNORED,
                "Sender or recipient did not match the registered workflow authority.",
                (),
                now,
            )
        current = await self._gateway.get_task(
            access_token,
            workflow.task_list_id,
            workflow.task_id,
        )
        event_id = _event_id(workflow.workflow_id, email.message_id)
        if event_id in current.notes:
            return await self._persist(
                workflow,
                email,
                EmailTaskEventStatus.APPLIED,
                "Recovered an already-applied idempotent Google Task update.",
                (),
                now,
                proposed_title=current.title,
                proposed_note="Recovered from the task evidence marker.",
                task_revision=current.etag,
            )
        policy_flags = deterministic_risk_flags(email.subject_line, email.body)
        if policy_flags:
            return await self._persist(
                workflow,
                email,
                EmailTaskEventStatus.ESCALATED,
                "Deterministic policy blocked a sensitive customer request.",
                policy_flags,
                now,
            )
        try:
            instruction = await self._extractor.extract(email, current)
        except EmailTaskExtractionError as error:
            raise RetryableOperationError("gmail_instruction_unavailable") from error
        combined_flags = tuple(sorted(set(instruction.risk_flags)))
        if instruction.disposition == EmailTaskDisposition.IGNORE:
            return await self._persist(
                workflow,
                email,
                EmailTaskEventStatus.IGNORED,
                instruction.rationale,
                combined_flags,
                now,
            )
        if (
            instruction.disposition != EmailTaskDisposition.UPDATE
            or instruction.confidence < 0.85
            or combined_flags
            or not instruction.proposed_title
            or not instruction.proposed_note
        ):
            return await self._persist(
                workflow,
                email,
                EmailTaskEventStatus.ESCALATED,
                instruction.rationale,
                combined_flags or ("ambiguous_instruction",),
                now,
                proposed_title=instruction.proposed_title,
                proposed_note=instruction.proposed_note,
            )
        notes = managed_task_notes(
            current.notes,
            event_id,
            sender,
            email.message_id,
            instruction.proposed_note,
        )
        try:
            updated = await self._gateway.update_task(
                access_token,
                workflow.task_list_id,
                current,
                instruction.proposed_title,
                notes,
            )
        except EmailTaskPreconditionFailed as error:
            raise PermanentOperationError("gmail_task_revision_conflict") from error
        return await self._persist(
            workflow,
            email,
            EmailTaskEventStatus.APPLIED,
            instruction.rationale,
            combined_flags,
            now,
            proposed_title=instruction.proposed_title,
            proposed_note=instruction.proposed_note,
            task_revision=updated.etag,
        )

    async def _persist_unmatched(
        self,
        subject: str,
        stream: GmailWatchStream,
        email: InboundEmail,
        now: datetime,
    ) -> EmailTaskUnmatchedRequest | None:
        sender = normalize_email(email.sender)
        recipient = normalize_email(email.recipient)
        if recipient != stream.mailbox_email or email.thread_id is None:
            return None
        candidates = await self._repository.active_for_sender(subject, sender)
        if not candidates:
            return None
        values = {
            "requestId": f"unmatched-{uuid5(NAMESPACE_URL, f'{subject}:{email.message_id}')}",
            "subject": subject,
            "gmailMessageId": email.message_id,
            "gmailThreadId": email.thread_id,
            "mailboxEmail": stream.mailbox_email,
            "sender": sender,
            "recipient": recipient,
            "subjectLine": email.subject_line,
            "bodyHash": hashlib.sha256(email.body.encode()).hexdigest(),
            "candidateWorkflowIds": sorted(workflow.workflow_id for workflow in candidates),
            "status": EmailTaskUnmatchedStatus.PENDING.value,
            "boundWorkflowId": None,
            "receivedAt": email.received_at.isoformat(),
            "createdAt": now.isoformat(),
            "updatedAt": now.isoformat(),
        }
        checksum = hashlib.sha256(
            json.dumps(values, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
        request = EmailTaskUnmatchedRequest.model_validate({**values, "receiptChecksum": checksum})
        return await self._repository.persist_unmatched(request)

    async def _persist(
        self,
        workflow: EmailTaskWorkflow,
        email: InboundEmail,
        status: EmailTaskEventStatus,
        rationale: str,
        risk_flags: tuple[str, ...],
        now: datetime,
        *,
        proposed_title: str | None = None,
        proposed_note: str | None = None,
        task_revision: str | None = None,
    ) -> EmailTaskEvent:
        values = {
            "eventId": _event_id(workflow.workflow_id, email.message_id),
            "workflowId": workflow.workflow_id,
            "gmailMessageId": email.message_id,
            "gmailThreadId": email.thread_id,
            "historyId": email.history_id,
            "sender": normalize_email(email.sender),
            "recipient": normalize_email(email.recipient),
            "subjectLine": email.subject_line,
            "bodyHash": hashlib.sha256(email.body.encode()).hexdigest(),
            "proposedTitle": proposed_title,
            "proposedNote": proposed_note,
            "status": status.value,
            "rationale": rationale,
            "riskFlags": list(risk_flags),
            "taskRevision": task_revision,
            "receivedAt": email.received_at.isoformat(),
            "createdAt": now.isoformat(),
            "updatedAt": now.isoformat(),
        }
        checksum = hashlib.sha256(
            json.dumps(values, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
        event = EmailTaskEvent.model_validate({**values, "receiptChecksum": checksum})
        return (await self._repository.persist_event(event)).event


class GmailTaskOperationHandler:
    def __init__(
        self,
        processor: GmailTaskProcessor,
        sessions: object,
    ) -> None:
        self._processor = processor
        self._sessions = sessions

    async def handle(self, operation: Operation) -> None:
        mailbox_email = operation.payload.get("mailboxEmail")
        if not isinstance(mailbox_email, str) or not mailbox_email:
            raise PermanentOperationError("invalid_gmail_operation")
        session = await self._sessions.get(operation.subject)  # type: ignore[attr-defined]
        try:
            session.authorization.require(WorkspaceCapability.GMAIL_INBOX_READ)
            session.authorization.require(WorkspaceCapability.TASKS_REPAIR)
        except MissingWorkspaceScope as error:
            raise PermanentOperationError("gmail_workspace_scope_missing") from error
        await self._processor.process(
            operation.subject,
            mailbox_email,
            session.access_token,
        )


def managed_task_notes(
    existing_notes: str,
    event_id: str,
    sender: str,
    gmail_message_id: str,
    proposed_note: str,
) -> str:
    human_notes = _MANAGED_BLOCK.sub("\n", existing_notes).strip()
    managed = (
        "--- Veritas customer update ---\n"
        f"{proposed_note.strip()}\n"
        f"Customer: {sender}\n"
        f"Source message: {gmail_message_id}\n"
        f"Evidence receipt: {event_id}\n"
        "--- End Veritas customer update ---"
    )
    return f"{human_notes}\n\n{managed}" if human_notes else managed


def _event_id(workflow_id: str, gmail_message_id: str) -> str:
    return f"email-event-{uuid5(NAMESPACE_URL, f'{workflow_id}:{gmail_message_id}')}"
