import base64
from datetime import UTC, datetime
from html import unescape
from typing import Any, cast
from urllib.parse import quote

import httpx

from veritas_runtime.email_tasks.models import (
    GmailHistoryPage,
    GmailWatchStream,
    GoogleTaskState,
    InboundEmail,
)
from veritas_runtime.email_tasks.policy import normalize_email


class GmailIntegrationError(RuntimeError):
    pass


class GmailHistoryExpired(GmailIntegrationError):
    pass


class EmailTaskPreconditionFailed(GmailIntegrationError):
    pass


class GoogleGmailTaskGateway:
    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        gmail_root: str = "https://gmail.googleapis.com/gmail/v1",
        tasks_root: str = "https://tasks.googleapis.com/tasks/v1",
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=20)
        self._gmail_root = gmail_root.rstrip("/")
        self._tasks_root = tasks_root.rstrip("/")

    async def start_watch(
        self,
        subject: str,
        mailbox_email: str,
        access_token: str,
        topic_name: str,
        now: datetime | None = None,
    ) -> GmailWatchStream:
        response = await self._client.post(
            f"{self._gmail_root}/users/me/watch",
            headers=_authorization(access_token),
            json={"topicName": topic_name, "labelIds": ["INBOX"], "labelFilterBehavior": "include"},
        )
        payload = _response_object(response)
        history_id = _required_string(payload, "historyId", "Gmail watch history ID")
        expiration_raw = _required_string(payload, "expiration", "Gmail watch expiration")
        try:
            expiration = datetime.fromtimestamp(int(expiration_raw) / 1000, tz=UTC)
        except ValueError as error:
            raise GmailIntegrationError("Gmail watch expiration is invalid") from error
        instant = (now or datetime.now(UTC)).astimezone(UTC)
        return GmailWatchStream(
            subject=subject,
            mailbox_email=normalize_email(mailbox_email),
            history_id=history_id,
            expiration=expiration,
            created_at=instant,
            updated_at=instant,
        )

    async def history_since(
        self,
        access_token: str,
        start_history_id: str,
    ) -> GmailHistoryPage:
        message_ids: set[str] = set()
        page_token: str | None = None
        latest_history_id = start_history_id
        while True:
            params: dict[str, str | int] = {
                "startHistoryId": start_history_id,
                "historyTypes": "messageAdded",
                "labelId": "INBOX",
                "maxResults": 100,
            }
            if page_token:
                params["pageToken"] = page_token
            response = await self._client.get(
                f"{self._gmail_root}/users/me/history",
                headers=_authorization(access_token),
                params=params,
            )
            if response.status_code == 404:
                raise GmailHistoryExpired("Gmail history cursor expired; renew the mailbox watch")
            payload = _response_object(response)
            latest_history_id = str(payload.get("historyId") or latest_history_id)
            history = payload.get("history")
            if isinstance(history, list):
                for item in history:
                    additions = item.get("messagesAdded") if isinstance(item, dict) else None
                    if not isinstance(additions, list):
                        continue
                    for addition in additions:
                        message = addition.get("message") if isinstance(addition, dict) else None
                        message_id = message.get("id") if isinstance(message, dict) else None
                        labels = message.get("labelIds") if isinstance(message, dict) else None
                        if isinstance(message_id, str) and (
                            not isinstance(labels, list) or "INBOX" in labels
                        ):
                            message_ids.add(message_id)
            next_page = payload.get("nextPageToken")
            if not isinstance(next_page, str) or not next_page:
                break
            page_token = next_page
        return GmailHistoryPage(
            history_id=latest_history_id,
            message_ids=tuple(sorted(message_ids)),
        )

    async def get_email(
        self,
        access_token: str,
        message_id: str,
        history_id: str,
    ) -> InboundEmail:
        response = await self._client.get(
            f"{self._gmail_root}/users/me/messages/{quote(message_id, safe='')}",
            headers=_authorization(access_token),
            params={"format": "full"},
        )
        payload = _response_object(response)
        message_payload = payload.get("payload")
        if not isinstance(message_payload, dict):
            raise GmailIntegrationError("Gmail message payload is missing")
        headers = _headers(message_payload)
        sender = normalize_email(headers.get("from", ""))
        recipient = normalize_email(headers.get("to", ""))
        subject_line = headers.get("subject", "").strip()
        body = _plain_body(message_payload).strip()
        if not subject_line or not body:
            raise GmailIntegrationError("Gmail task request requires a subject and plain-text body")
        internal_date = payload.get("internalDate")
        try:
            received_at = datetime.fromtimestamp(int(str(internal_date)) / 1000, tz=UTC)
        except (TypeError, ValueError) as error:
            raise GmailIntegrationError("Gmail message timestamp is invalid") from error
        return InboundEmail(
            message_id=_required_string(payload, "id", "Gmail message ID"),
            thread_id=str(payload.get("threadId")) if payload.get("threadId") else None,
            history_id=history_id,
            sender=sender,
            recipient=recipient,
            subject_line=subject_line,
            body=body,
            received_at=received_at,
        )

    async def get_task(
        self,
        access_token: str,
        task_list_id: str,
        task_id: str,
    ) -> GoogleTaskState:
        response = await self._client.get(
            f"{self._tasks_root}/lists/{quote(task_list_id, safe='')}/tasks/"
            f"{quote(task_id, safe='')}",
            headers=_authorization(access_token),
        )
        payload = _response_object(response)
        return GoogleTaskState(
            task_id=_required_string(payload, "id", "Google Task ID"),
            title=_required_string(payload, "title", "Google Task title"),
            notes=str(payload.get("notes") or ""),
            etag=_required_string(payload, "etag", "Google Task ETag"),
        )

    async def update_task(
        self,
        access_token: str,
        task_list_id: str,
        current: GoogleTaskState,
        title: str,
        notes: str,
    ) -> GoogleTaskState:
        response = await self._client.patch(
            f"{self._tasks_root}/lists/{quote(task_list_id, safe='')}/tasks/"
            f"{quote(current.task_id, safe='')}",
            headers={**_authorization(access_token), "If-Match": current.etag},
            json={"title": title, "notes": notes},
        )
        if response.status_code in {409, 412}:
            raise EmailTaskPreconditionFailed(
                "The Google Task changed after it was read; no overwrite was attempted"
            )
        payload = _response_object(response)
        return GoogleTaskState(
            task_id=_required_string(payload, "id", "Updated Google Task ID"),
            title=_required_string(payload, "title", "Updated Google Task title"),
            notes=str(payload.get("notes") or ""),
            etag=_required_string(payload, "etag", "Updated Google Task ETag"),
        )


def _authorization(token: str) -> dict[str, str]:
    if not token:
        raise ValueError("Google access token is required")
    return {"Authorization": f"Bearer {token}"}


def _response_object(response: httpx.Response) -> dict[str, Any]:
    try:
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise GmailIntegrationError(
            f"Google Workspace request failed with status {response.status_code}"
        ) from error
    try:
        payload = response.json()
    except ValueError as error:
        raise GmailIntegrationError("Google Workspace response was not JSON") from error
    if not isinstance(payload, dict):
        raise GmailIntegrationError("Google Workspace response must be an object")
    return cast(dict[str, Any], payload)


def _required_string(payload: dict[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise GmailIntegrationError(f"{label} is missing")
    return value


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    raw = payload.get("headers")
    if not isinstance(raw, list):
        return {}
    headers: dict[str, str] = {}
    for item in raw:
        name = item.get("name") if isinstance(item, dict) else None
        value = item.get("value") if isinstance(item, dict) else None
        if isinstance(name, str) and isinstance(value, str):
            headers[name.lower()] = value
    return headers


def _plain_body(payload: dict[str, Any]) -> str:
    mime_type = payload.get("mimeType")
    body = payload.get("body")
    data = body.get("data") if isinstance(body, dict) else None
    if mime_type == "text/plain" and isinstance(data, str):
        return _decode_base64url(data)
    parts = payload.get("parts")
    if isinstance(parts, list):
        for part in parts:
            if isinstance(part, dict):
                text = _plain_body(part)
                if text:
                    return text
    if mime_type == "text/html" and isinstance(data, str):
        html = _decode_base64url(data)
        return unescape(" ".join(html.replace("<br>", "\n").split("<"))).strip()
    return ""


def _decode_base64url(value: str) -> str:
    padded = value + "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode()).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as error:
        raise GmailIntegrationError("Gmail message body encoding is invalid") from error
