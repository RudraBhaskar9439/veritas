import base64
import hashlib
from email.message import EmailMessage
from typing import Any, cast
from urllib.parse import quote

import httpx

from veritas_runtime.packets.models import (
    ArtifactKind,
    MaterializedArtifact,
    PacketArtifactDraft,
)


class WorkspacePacketWriteError(RuntimeError):
    """A native packet artifact could not be materialized safely."""


class GoogleWorkspacePacketWriter:
    """Creates replay-safe native Workspace artifacts with writer-owned anchors."""

    def __init__(
        self,
        access_token: str,
        user_email: str,
        client: httpx.AsyncClient,
        *,
        docs_root: str = "https://docs.googleapis.com/v1",
        slides_root: str = "https://slides.googleapis.com/v1",
        drive_root: str = "https://www.googleapis.com/drive/v3",
        gmail_root: str = "https://gmail.googleapis.com/gmail/v1",
        tasks_root: str = "https://tasks.googleapis.com/tasks/v1",
    ) -> None:
        if not access_token or not user_email:
            raise ValueError("Workspace packet writer requires an authenticated account")
        self._token = access_token
        self._email = user_email
        self._client = client
        self._docs_root = docs_root.rstrip("/")
        self._slides_root = slides_root.rstrip("/")
        self._drive_root = drive_root.rstrip("/")
        self._gmail_root = gmail_root.rstrip("/")
        self._tasks_root = tasks_root.rstrip("/")

    async def materialize(
        self,
        draft: PacketArtifactDraft,
        request_id: str,
    ) -> MaterializedArtifact:
        key = hashlib.sha256(f"{request_id}:{draft.artifact_id}".encode()).hexdigest()
        if draft.kind == ArtifactKind.GOOGLE_DOC:
            return await self._document(draft, key)
        if draft.kind == ArtifactKind.GOOGLE_SLIDES:
            return await self._presentation(draft, key)
        if draft.kind == ArtifactKind.GMAIL:
            return await self._gmail_draft(draft, key)
        if draft.kind == ArtifactKind.GOOGLE_TASK:
            return await self._task(draft, key)
        raise WorkspacePacketWriteError(f"Unsupported packet artifact kind: {draft.kind}")

    async def _document(self, draft: PacketArtifactDraft, key: str) -> MaterializedArtifact:
        document_id = await self._find_drive_file(key, "application/vnd.google-apps.document")
        if document_id is None:
            created = await self._post(
                f"{self._docs_root}/documents",
                json={"title": draft.title},
            )
            document_id = _required_string(created, "documentId", "Docs document ID")
            text, ranges = _document_text(draft)
            requests: list[dict[str, object]] = [
                {"insertText": {"location": {"index": 1}, "text": text}}
            ]
            requests.extend(
                {
                    "createNamedRange": {
                        "name": block.slot,
                        "range": {"startIndex": start, "endIndex": end},
                    }
                }
                for block, (start, end) in zip(draft.claim_blocks, ranges, strict=True)
            )
            await self._post(
                f"{self._docs_root}/documents/{quote(document_id, safe='')}:batchUpdate",
                json={"requests": requests},
            )
            await self._mark_drive_file(document_id, key)
        document = await self._get(
            f"{self._docs_root}/documents/{quote(document_id, safe='')}",
            params={"includeTabsContent": "true"},
        )
        revision = _required_string(document, "revisionId", "Docs revision")
        return MaterializedArtifact(
            artifact_id=draft.artifact_id,
            resource_id=document_id,
            revision_id=revision,
            anchors={
                block.claim_id: f"workspace://docs/{document_id}#{block.slot}"
                for block in draft.claim_blocks
            },
        )

    async def _presentation(self, draft: PacketArtifactDraft, key: str) -> MaterializedArtifact:
        presentation_id = await self._find_drive_file(
            key, "application/vnd.google-apps.presentation"
        )
        if presentation_id is None:
            created = await self._post(
                f"{self._slides_root}/presentations",
                json={"title": draft.title},
            )
            presentation_id = _required_string(created, "presentationId", "Slides presentation ID")
            slides = created.get("slides")
            if not isinstance(slides, list) or not slides or not isinstance(slides[0], dict):
                created = await self._get(
                    f"{self._slides_root}/presentations/{quote(presentation_id, safe='')}"
                )
                slides = created.get("slides")
            if not isinstance(slides, list) or not slides or not isinstance(slides[0], dict):
                raise WorkspacePacketWriteError("Slides presentation has no initial page")
            page_id = _required_string(slides[0], "objectId", "Slides page ID")
            requests: list[dict[str, object]] = []
            for index, block in enumerate(draft.claim_blocks):
                object_id = _slide_object_id(key, block.slot)
                requests.extend(
                    [
                        {
                            "createShape": {
                                "objectId": object_id,
                                "shapeType": "TEXT_BOX",
                                "elementProperties": {
                                    "pageObjectId": page_id,
                                    "size": {
                                        "width": {"magnitude": 3_300_000, "unit": "EMU"},
                                        "height": {"magnitude": 1_100_000, "unit": "EMU"},
                                    },
                                    "transform": {
                                        "scaleX": 1,
                                        "scaleY": 1,
                                        "translateX": 450_000 + (index % 2) * 3_600_000,
                                        "translateY": 650_000 + (index // 2) * 1_400_000,
                                        "unit": "EMU",
                                    },
                                },
                            }
                        },
                        {
                            "insertText": {
                                "objectId": object_id,
                                "insertionIndex": 0,
                                "text": block.statement,
                            }
                        },
                    ]
                )
            await self._post(
                f"{self._slides_root}/presentations/{quote(presentation_id, safe='')}:batchUpdate",
                json={"requests": requests},
            )
            await self._mark_drive_file(presentation_id, key)
        presentation = await self._get(
            f"{self._slides_root}/presentations/{quote(presentation_id, safe='')}"
        )
        revision = _required_string(presentation, "revisionId", "Slides revision")
        return MaterializedArtifact(
            artifact_id=draft.artifact_id,
            resource_id=presentation_id,
            revision_id=revision,
            anchors={
                block.claim_id: (
                    f"workspace://slides/{presentation_id}#{_slide_object_id(key, block.slot)}"
                )
                for block in draft.claim_blocks
            },
        )

    async def _gmail_draft(self, draft: PacketArtifactDraft, key: str) -> MaterializedArtifact:
        message_id = f"<veritas-packet-{key[:32]}@veritas.invalid>"
        listed = await self._get(
            f"{self._gmail_root}/users/me/messages",
            params={"q": f"in:drafts rfc822msgid:{message_id}", "maxResults": 1},
        )
        messages = listed.get("messages")
        resource_id: str | None = None
        if isinstance(messages, list) and messages and isinstance(messages[0], dict):
            candidate = messages[0].get("id")
            resource_id = candidate if isinstance(candidate, str) and candidate else None
        if resource_id is None:
            message = EmailMessage()
            message["To"] = self._email
            message["Subject"] = draft.title
            message["Message-ID"] = message_id
            message.set_content(
                "This test packet message is intentionally left as a draft.\n\n"
                + "\n\n".join(block.statement for block in draft.claim_blocks)
            )
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip("=")
            created = await self._post(
                f"{self._gmail_root}/users/me/drafts",
                json={"message": {"raw": raw}},
            )
            message_payload = created.get("message")
            if not isinstance(message_payload, dict):
                raise WorkspacePacketWriteError("Gmail draft omitted its message")
            resource_id = _required_string(message_payload, "id", "Gmail message ID")
        message_state = await self._get(
            f"{self._gmail_root}/users/me/messages/{quote(resource_id, safe='')}",
            params={"format": "minimal"},
        )
        revision = str(message_state.get("historyId") or resource_id)
        return MaterializedArtifact(
            artifact_id=draft.artifact_id,
            resource_id=resource_id,
            revision_id=revision,
            anchors={
                block.claim_id: f"workspace://gmail/{resource_id}#{block.slot}"
                for block in draft.claim_blocks
            },
        )

    async def _task(self, draft: PacketArtifactDraft, key: str) -> MaterializedArtifact:
        task_list_id = await self._task_list()
        marker = f"[veritas:{key[:16]}]"
        title = f"{marker} {draft.title}"
        listed = await self._get(
            f"{self._tasks_root}/lists/{quote(task_list_id, safe='')}/tasks",
            params={"showCompleted": "true", "showHidden": "true", "maxResults": 100},
        )
        items = listed.get("items")
        task: dict[str, Any] | None = None
        if isinstance(items, list):
            task = next(
                (
                    cast(dict[str, Any], item)
                    for item in items
                    if isinstance(item, dict) and item.get("title") == title
                ),
                None,
            )
        if task is None:
            task = await self._post(
                f"{self._tasks_root}/lists/{quote(task_list_id, safe='')}/tasks",
                json={
                    "title": title,
                    "notes": "\n\n".join(block.statement for block in draft.claim_blocks),
                },
            )
        resource_id = _required_string(task, "id", "Google Task ID")
        revision = _required_string(task, "etag", "Google Task ETag")
        return MaterializedArtifact(
            artifact_id=draft.artifact_id,
            resource_id=resource_id,
            container_id=task_list_id,
            revision_id=revision,
            anchors={
                block.claim_id: f"workspace://tasks/{resource_id}#{block.slot}"
                for block in draft.claim_blocks
            },
        )

    async def _task_list(self) -> str:
        listed = await self._get(f"{self._tasks_root}/users/@me/lists", params={"maxResults": 100})
        items = listed.get("items")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and item.get("title") == "Veritas":
                    return _required_string(item, "id", "Google Task list ID")
        created = await self._post(
            f"{self._tasks_root}/users/@me/lists",
            json={"title": "Veritas"},
        )
        return _required_string(created, "id", "Google Task list ID")

    async def _find_drive_file(self, key: str, mime_type: str) -> str | None:
        escaped_key = key.replace("'", "\\'")
        escaped_mime = mime_type.replace("'", "\\'")
        payload = await self._get(
            f"{self._drive_root}/files",
            params={
                "q": (
                    "trashed = false and "
                    f"mimeType = '{escaped_mime}' and "
                    f"appProperties has {{ key='veritasRequest' and value='{escaped_key}' }}"
                ),
                "fields": "files(id)",
                "pageSize": 2,
            },
        )
        files = payload.get("files")
        if not isinstance(files, list) or not files:
            return None
        if len(files) != 1 or not isinstance(files[0], dict):
            raise WorkspacePacketWriteError("Workspace idempotency key is ambiguous")
        return _required_string(files[0], "id", "Drive file ID")

    async def _mark_drive_file(self, file_id: str, key: str) -> None:
        await self._patch(
            f"{self._drive_root}/files/{quote(file_id, safe='')}",
            params={"fields": "id"},
            json={"appProperties": {"veritasRequest": key}},
        )

    async def _get(self, url: str, **kwargs: Any) -> dict[str, Any]:
        return await self._request("GET", url, **kwargs)

    async def _post(self, url: str, **kwargs: Any) -> dict[str, Any]:
        return await self._request("POST", url, **kwargs)

    async def _patch(self, url: str, **kwargs: Any) -> dict[str, Any]:
        return await self._request("PATCH", url, **kwargs)

    async def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        response = await self._client.request(
            method,
            url,
            headers={"Authorization": f"Bearer {self._token}"},
            **kwargs,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise WorkspacePacketWriteError(
                f"Workspace packet write failed with status {response.status_code}"
            ) from error
        try:
            payload = response.json()
        except ValueError as error:
            raise WorkspacePacketWriteError("Workspace packet response was not JSON") from error
        if not isinstance(payload, dict):
            raise WorkspacePacketWriteError("Workspace packet response must be an object")
        return cast(dict[str, Any], payload)


def _document_text(
    draft: PacketArtifactDraft,
) -> tuple[str, tuple[tuple[int, int], ...]]:
    text = f"{draft.title}\n\n"
    cursor = 1 + _utf16_length(text)
    ranges: list[tuple[int, int]] = []
    for block in draft.claim_blocks:
        label = f"{block.slot}\n"
        text += label
        cursor += _utf16_length(label)
        start = cursor
        text += block.statement
        cursor += _utf16_length(block.statement)
        ranges.append((start, cursor))
        text += "\n\n"
        cursor += 2
    return text, tuple(ranges)


def _slide_object_id(key: str, slot: str) -> str:
    return "v_" + hashlib.sha256(f"{key}:{slot}".encode()).hexdigest()[:24]


def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _required_string(payload: dict[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise WorkspacePacketWriteError(f"{label} is missing")
    return value
