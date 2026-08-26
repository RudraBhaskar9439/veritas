import asyncio
from datetime import UTC, datetime, timedelta

from operations_support import MemoryOperationRepository
from veritas_runtime.email_tasks.models import (
    EmailTaskDisposition,
    EmailTaskEventStatus,
    EmailTaskWorkflow,
    EmailTaskWorkflowStatus,
    GeminiEmailTaskPayload,
    GmailHistoryPage,
    GmailWatchStream,
    GoogleTaskState,
    InboundEmail,
)
from veritas_runtime.email_tasks.notifications import (
    GmailNotificationReceiver,
    decode_pubsub_push,
)
from veritas_runtime.email_tasks.processor import GmailTaskProcessor
from veritas_runtime.operations.models import OperationStatus
from veritas_runtime.operations.service import ReliableOperationService

NOW = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)


def _workflow() -> EmailTaskWorkflow:
    return EmailTaskWorkflow(
        workflow_id="workflow-1",
        subject="subject-1",
        mailbox_email="operator@example.com",
        authorized_sender="customer@example.com",
        routing_key="VX-ABCDEF123456",
        packet_id="packet-1",
        manifest_id="manifest-1",
        claim_id="claim-1",
        artifact_id="artifact-task",
        task_id="task-1",
        task_list_id="list-1",
        status=EmailTaskWorkflowStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )


class MemoryEmailRepository:
    def __init__(self) -> None:
        self.workflow = _workflow()
        self.watch = GmailWatchStream(
            subject="subject-1",
            mailbox_email="operator@example.com",
            history_id="10",
            expiration=NOW + timedelta(days=7),
            created_at=NOW,
            updated_at=NOW,
        )
        self.events = {}

    async def get_by_identity(self, subject, routing_key):  # type: ignore[no-untyped-def]
        if subject == "subject-1" and routing_key == self.workflow.routing_key:
            return self.workflow
        return None

    async def get_watch(self, subject):  # type: ignore[no-untyped-def]
        return self.watch if subject == "subject-1" else None

    async def advance_history(self, subject, expected, history, updated_at):  # type: ignore[no-untyped-def]
        if subject != "subject-1" or self.watch.history_id != expected:
            return False
        self.watch = self.watch.model_copy(update={"history_id": history, "updated_at": updated_at})
        return True

    async def get_event(self, workflow_id, message_id):  # type: ignore[no-untyped-def]
        return self.events.get((workflow_id, message_id))

    async def persist_event(self, event):  # type: ignore[no-untyped-def]
        from veritas_runtime.email_tasks.models import EmailTaskEventResult

        key = (event.workflow_id, event.gmail_message_id)
        existing = self.events.get(key)
        if existing is not None:
            return EmailTaskEventResult(event=existing, reused=True)
        self.events[key] = event
        return EmailTaskEventResult(event=event, reused=False)

    async def subject_for_mailbox(self, mailbox):  # type: ignore[no-untyped-def]
        return "subject-1" if mailbox == "operator@example.com" else None


class FakeGateway:
    def __init__(self, email: InboundEmail) -> None:
        self.email = email
        self.task = GoogleTaskState(
            task_id="task-1",
            title="Install equipment Thursday",
            notes="Keep the loading-bay instructions.",
            etag="v1",
        )
        self.updates = 0

    async def history_since(self, token, history_id):  # type: ignore[no-untyped-def]
        del token, history_id
        return GmailHistoryPage(history_id="11", message_ids=(self.email.message_id,))

    async def get_email(self, token, message_id, history_id):  # type: ignore[no-untyped-def]
        del token, message_id
        return self.email.model_copy(update={"history_id": history_id})

    async def get_task(self, token, task_list_id, task_id):  # type: ignore[no-untyped-def]
        del token, task_list_id, task_id
        return self.task

    async def update_task(self, token, task_list_id, current, title, notes):  # type: ignore[no-untyped-def]
        del token, task_list_id
        assert current.etag == self.task.etag
        self.updates += 1
        self.task = GoogleTaskState(task_id="task-1", title=title, notes=notes, etag="v2")
        return self.task


class StaticExtractor:
    def __init__(self, payload: GeminiEmailTaskPayload) -> None:
        self.payload = payload
        self.calls = 0

    async def extract(self, email, task):  # type: ignore[no-untyped-def]
        del email, task
        self.calls += 1
        return self.payload


def _email(**updates: str) -> InboundEmail:
    return InboundEmail(
        message_id="message-1",
        thread_id="thread-1",
        history_id="11",
        sender=updates.get("sender", "customer@example.com"),
        recipient="operator@example.com",
        subject_line=updates.get("subject", "Please move installation [VX-ABCDEF123456]"),
        body=updates.get("body", "Please move the installation to Friday at 10 AM."),
        received_at=NOW,
    )


def test_authorized_email_updates_exact_task_once_and_preserves_human_notes() -> None:
    async def scenario() -> None:
        repository = MemoryEmailRepository()
        gateway = FakeGateway(_email())
        extractor = StaticExtractor(
            GeminiEmailTaskPayload(
                disposition=EmailTaskDisposition.UPDATE,
                proposed_title="Install equipment Friday at 10 AM",
                proposed_note="Customer requested installation on Friday at 10 AM.",
                rationale="The authorized customer made a clear reversible scheduling request.",
                confidence=0.98,
                risk_flags=(),
            )
        )
        processor = GmailTaskProcessor(repository, gateway, extractor)  # type: ignore[arg-type]
        first = await processor.process("subject-1", "operator@example.com", "token", NOW)
        replay = await processor.process("subject-1", "operator@example.com", "token", NOW)
        assert first[0].status == EmailTaskEventStatus.APPLIED
        assert replay[0] == first[0]
        assert gateway.updates == 1
        assert extractor.calls == 1
        assert gateway.task.title == "Install equipment Friday at 10 AM"
        assert "Keep the loading-bay instructions." in gateway.task.notes
        assert first[0].event_id in gateway.task.notes
        assert len(first[0].receipt_checksum) == 64

    asyncio.run(scenario())


def test_wrong_sender_is_ignored_and_sensitive_request_is_escalated() -> None:
    async def scenario() -> None:
        ignored_repo = MemoryEmailRepository()
        ignored_gateway = FakeGateway(_email(sender="attacker@example.com"))
        extractor = StaticExtractor(
            GeminiEmailTaskPayload(
                disposition=EmailTaskDisposition.UPDATE,
                proposed_title="Unsafe",
                proposed_note="Unsafe request",
                rationale="This payload should never be reached by the bounded workflow.",
                confidence=1,
                risk_flags=(),
            )
        )
        ignored = await GmailTaskProcessor(
            ignored_repo,
            ignored_gateway,
            extractor,
        ).process("subject-1", "operator@example.com", "token", NOW)  # type: ignore[arg-type]
        assert ignored[0].status == EmailTaskEventStatus.IGNORED
        assert ignored_gateway.updates == 0
        assert extractor.calls == 0

        risky_repo = MemoryEmailRepository()
        risky_gateway = FakeGateway(
            _email(body="Cancel the job and refund the customer's payment.")
        )
        risky = await GmailTaskProcessor(
            risky_repo,
            risky_gateway,
            extractor,
        ).process("subject-1", "operator@example.com", "token", NOW)  # type: ignore[arg-type]
        assert risky[0].status == EmailTaskEventStatus.ESCALATED
        assert set(risky[0].risk_flags) == {
            "sensitive:cancel",
            "sensitive:payment",
            "sensitive:refund",
        }
        assert risky_gateway.updates == 0
        assert extractor.calls == 0

    asyncio.run(scenario())


def test_paused_route_cannot_reach_the_registered_task() -> None:
    async def scenario() -> None:
        repository = MemoryEmailRepository()
        repository.workflow = repository.workflow.model_copy(
            update={"status": EmailTaskWorkflowStatus.PAUSED}
        )
        gateway = FakeGateway(_email())
        extractor = StaticExtractor(
            GeminiEmailTaskPayload(
                disposition=EmailTaskDisposition.UPDATE,
                proposed_title="Should not be used",
                proposed_note="Should not be used",
                rationale="The paused route must be rejected before model interpretation.",
                confidence=1,
                risk_flags=(),
            )
        )

        events = await GmailTaskProcessor(
            repository,
            gateway,
            extractor,
        ).process("subject-1", "operator@example.com", "token", NOW)  # type: ignore[arg-type]

        assert events == ()
        assert gateway.updates == 0
        assert extractor.calls == 0

    asyncio.run(scenario())


def test_pubsub_notification_is_decoded_and_durably_enqueued() -> None:
    async def scenario() -> None:
        import base64
        import json

        repository = MemoryEmailRepository()
        operations_repository = MemoryOperationRepository()
        operations = ReliableOperationService(operations_repository, {})
        receiver = GmailNotificationReceiver(repository, operations)
        data = base64.b64encode(
            json.dumps({"emailAddress": "operator@example.com", "historyId": "12"}).encode()
        ).decode()
        notification = decode_pubsub_push(
            {
                "message": {
                    "messageId": "pubsub-1",
                    "publishTime": "2026-08-26T10:00:00Z",
                    "data": data,
                }
            }
        )
        assert await receiver.receive(notification) is True
        operation = next(iter(operations_repository.operations.values()))
        assert operation.kind == "gmail.process"
        assert operation.status == OperationStatus.QUEUED
        assert operation.payload == {
            "mailboxEmail": "operator@example.com",
            "historyId": "12",
        }

    asyncio.run(scenario())
