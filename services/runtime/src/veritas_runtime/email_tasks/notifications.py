import base64
import json
from datetime import UTC, datetime
from typing import Protocol

from veritas_runtime.email_tasks.models import GmailPushNotification
from veritas_runtime.email_tasks.policy import normalize_email
from veritas_runtime.email_tasks.processor import GMAIL_PROCESS_OPERATION
from veritas_runtime.operations.models import OperationRequest
from veritas_runtime.operations.service import ReliableOperationService


class GmailNotificationError(ValueError):
    pass


class GmailNotificationRepository(Protocol):
    async def subject_for_mailbox(self, mailbox_email: str) -> str | None: ...


class GmailNotificationReceiver:
    def __init__(
        self,
        repository: GmailNotificationRepository,
        operations: ReliableOperationService,
    ) -> None:
        self._repository = repository
        self._operations = operations

    async def receive(self, notification: GmailPushNotification) -> bool:
        mailbox = normalize_email(notification.mailbox_email)
        subject = await self._repository.subject_for_mailbox(mailbox)
        if subject is None:
            return False
        await self._operations.enqueue(
            OperationRequest(
                subject=subject,
                kind=GMAIL_PROCESS_OPERATION,
                correlation_id=notification.pubsub_message_id,
                idempotency_key=f"gmail-push:{notification.pubsub_message_id}",
                payload={
                    "mailboxEmail": mailbox,
                    "historyId": notification.history_id,
                },
            ),
            notification.published_at or datetime.now(UTC),
        )
        return True


def decode_pubsub_push(payload: object) -> GmailPushNotification:
    if not isinstance(payload, dict):
        raise GmailNotificationError("Pub/Sub push body must be an object")
    message = payload.get("message")
    if not isinstance(message, dict):
        raise GmailNotificationError("Pub/Sub message is missing")
    message_id = message.get("messageId") or message.get("message_id")
    data = message.get("data")
    if not isinstance(message_id, str) or not isinstance(data, str):
        raise GmailNotificationError("Pub/Sub message identity or data is missing")
    try:
        padded = data + "=" * (-len(data) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GmailNotificationError("Pub/Sub Gmail data is invalid") from error
    if not isinstance(decoded, dict):
        raise GmailNotificationError("Pub/Sub Gmail data must be an object")
    mailbox = decoded.get("emailAddress")
    history_id = decoded.get("historyId")
    if isinstance(history_id, int) and not isinstance(history_id, bool) and history_id >= 0:
        history_id = str(history_id)
    if not isinstance(mailbox, str) or not isinstance(history_id, str) or not history_id.strip():
        raise GmailNotificationError("Pub/Sub Gmail cursor is incomplete")
    published = message.get("publishTime") or message.get("publish_time")
    try:
        published_at = (
            datetime.fromisoformat(published.replace("Z", "+00:00")).astimezone(UTC)
            if isinstance(published, str)
            else None
        )
    except ValueError as error:
        raise GmailNotificationError("Pub/Sub publish time is invalid") from error
    return GmailPushNotification(
        pubsub_message_id=message_id,
        mailbox_email=mailbox,
        history_id=history_id,
        published_at=published_at,
    )
