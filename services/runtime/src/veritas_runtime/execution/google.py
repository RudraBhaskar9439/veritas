import base64
import hashlib
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from typing import Any, cast
from urllib.parse import quote

import httpx

from veritas_runtime.execution.models import ArtifactState, MutationReceipt
from veritas_runtime.packets.models import ArtifactKind
from veritas_runtime.repairs.models import RepairOperation, RepairStep
from veritas_runtime.workspace.contracts import WorkspaceCapability


class WorkspaceExecutionError(RuntimeError):
    """A Workspace artifact could not be read or mutated safely."""


class WorkspacePreconditionFailed(WorkspaceExecutionError):
    """The artifact changed after it was read and must be merged again."""


class GoogleWorkspaceRepairGateway:
    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        docs_root: str = "https://docs.googleapis.com/v1",
        slides_root: str = "https://slides.googleapis.com/v1",
        gmail_root: str = "https://gmail.googleapis.com/gmail/v1",
        tasks_root: str = "https://tasks.googleapis.com/tasks/v1",
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=20)
        self._docs_root = docs_root.rstrip("/")
        self._slides_root = slides_root.rstrip("/")
        self._gmail_root = gmail_root.rstrip("/")
        self._tasks_root = tasks_root.rstrip("/")

    def capability(self, step: RepairStep) -> WorkspaceCapability:
        return {
            ArtifactKind.GOOGLE_DOC: WorkspaceCapability.DOCS_REPAIR,
            ArtifactKind.GOOGLE_SLIDES: WorkspaceCapability.SLIDES_REPAIR,
            ArtifactKind.GMAIL: WorkspaceCapability.GMAIL_CORRECTION_DRAFT,
            ArtifactKind.GOOGLE_TASK: WorkspaceCapability.TASKS_REPAIR,
        }[step.artifact_kind]

    async def read(self, access_token: str, step: RepairStep) -> ArtifactState:
        if step.artifact_kind == ArtifactKind.GOOGLE_DOC:
            return await self._read_doc(access_token, step)
        if step.artifact_kind == ArtifactKind.GOOGLE_SLIDES:
            return await self._read_slides(access_token, step)
        if step.artifact_kind == ArtifactKind.GMAIL:
            return await self._read_gmail(access_token, step)
        if step.artifact_kind == ArtifactKind.GOOGLE_TASK:
            return await self._read_task(access_token, step)
        raise WorkspaceExecutionError(f"Unsupported artifact kind: {step.artifact_kind}")

    async def apply(
        self,
        access_token: str,
        step: RepairStep,
        current: ArtifactState,
    ) -> MutationReceipt:
        if step.artifact_kind == ArtifactKind.GOOGLE_DOC:
            return await self._apply_doc(access_token, step, current)
        if step.artifact_kind == ArtifactKind.GOOGLE_SLIDES:
            return await self._apply_slides(access_token, step, current)
        if step.artifact_kind == ArtifactKind.GMAIL:
            return await self._create_correction_draft(access_token, step, current)
        if step.artifact_kind == ArtifactKind.GOOGLE_TASK:
            return await self._apply_task(access_token, step, current)
        raise WorkspaceExecutionError(f"Unsupported artifact kind: {step.artifact_kind}")

    async def _read_doc(self, token: str, step: RepairStep) -> ArtifactState:
        response = await self._client.get(
            f"{self._docs_root}/documents/{quote(step.resource_id, safe='')}",
            headers=_authorization(token),
            params={"includeTabsContent": "true"},
        )
        document = _response_object(response)
        revision = _required_string(document, "revisionId", "Docs revision")
        anchor = _anchor_token(step.anchor)
        part = _first_document_part(document)
        text_range = _single_named_range(part, anchor)
        statement = _doc_text(part, text_range)
        if not statement:
            raise WorkspaceExecutionError("Docs registered anchor is empty")
        return ArtifactState(
            resource_id=step.resource_id,
            revision_id=revision,
            anchor=step.anchor,
            statement=statement,
            write_context={"range": text_range, "name": anchor},
        )

    async def _apply_doc(
        self, token: str, step: RepairStep, current: ArtifactState
    ) -> MutationReceipt:
        text_range = _context_object(current, "range")
        start = text_range.get("startIndex")
        if not isinstance(start, int):
            raise WorkspaceExecutionError("Docs write range lacks a start index")
        location = {
            key: text_range[key]
            for key in ("segmentId", "tabId")
            if isinstance(text_range.get(key), str)
        }
        location["index"] = start
        recreated_range = dict(text_range)
        recreated_range["endIndex"] = start + _utf16_length(step.proposed_statement)
        body = {
            "requests": [
                {"deleteContentRange": {"range": text_range}},
                {
                    "insertText": {
                        "location": location,
                        "text": step.proposed_statement,
                    }
                },
                {
                    "createNamedRange": {
                        "name": _context_string(current, "name"),
                        "range": recreated_range,
                    }
                },
            ],
            "writeControl": {"requiredRevisionId": current.revision_id},
        }
        response = await self._client.post(
            f"{self._docs_root}/documents/{quote(step.resource_id, safe='')}:batchUpdate",
            headers=_authorization(token),
            json=body,
        )
        payload = _response_object(response, precondition_statuses={400, 409, 412})
        write_control = payload.get("writeControl")
        revision = (
            write_control.get("requiredRevisionId") if isinstance(write_control, dict) else None
        )
        return MutationReceipt(
            resource_id=step.resource_id,
            revision_id=revision if isinstance(revision, str) else current.revision_id,
        )

    async def _read_slides(self, token: str, step: RepairStep) -> ArtifactState:
        response = await self._client.get(
            f"{self._slides_root}/presentations/{quote(step.resource_id, safe='')}",
            headers=_authorization(token),
        )
        presentation = _response_object(response)
        revision = _required_string(presentation, "revisionId", "Slides revision")
        object_id = _anchor_token(step.anchor)
        statement = _slides_text(presentation, object_id)
        return ArtifactState(
            resource_id=step.resource_id,
            revision_id=revision,
            anchor=step.anchor,
            statement=statement,
            write_context={"objectId": object_id},
        )

    async def _apply_slides(
        self, token: str, step: RepairStep, current: ArtifactState
    ) -> MutationReceipt:
        object_id = _context_string(current, "objectId")
        response = await self._client.post(
            f"{self._slides_root}/presentations/{quote(step.resource_id, safe='')}:batchUpdate",
            headers=_authorization(token),
            json={
                "requests": [
                    {"deleteText": {"objectId": object_id, "textRange": {"type": "ALL"}}},
                    {
                        "insertText": {
                            "objectId": object_id,
                            "insertionIndex": 0,
                            "text": step.proposed_statement,
                        }
                    },
                ],
                "writeControl": {"requiredRevisionId": current.revision_id},
            },
        )
        payload = _response_object(response, precondition_statuses={400, 409, 412})
        control = payload.get("writeControl")
        revision = control.get("requiredRevisionId") if isinstance(control, dict) else None
        return MutationReceipt(
            resource_id=step.resource_id,
            revision_id=revision if isinstance(revision, str) else current.revision_id,
        )

    async def _read_gmail(self, token: str, step: RepairStep) -> ArtifactState:
        if not step.container_id:
            raise WorkspaceExecutionError("Gmail artifact is missing its draft ID")
        response = await self._client.get(
            f"{self._gmail_root}/users/me/drafts/{quote(step.container_id, safe='')}",
            headers=_authorization(token),
            params={"format": "raw"},
        )
        payload = _draft_message(_response_object(response))
        raw = _required_string(payload, "raw", "Gmail raw message")
        message = BytesParser(policy=policy.default).parsebytes(_decode_base64url(raw))
        body = _plain_body(message)
        statement = _registered_statement(body, step)
        return ArtifactState(
            resource_id=step.resource_id,
            revision_id=str(payload.get("historyId") or payload.get("id") or step.base_revision_id),
            anchor=step.anchor,
            statement=statement,
            write_context={
                "to": str(message.get("To", "")),
                "cc": str(message.get("Cc", "")),
                "subject": str(message.get("Subject", "Decision Packet update")),
                "messageId": str(message.get("Message-ID", "")),
            },
        )

    async def _create_correction_draft(
        self, token: str, step: RepairStep, current: ArtifactState
    ) -> MutationReceipt:
        if step.operation != RepairOperation.CREATE_CORRECTION_DRAFT:
            raise WorkspaceExecutionError("Gmail execution is correction-draft-only")
        message_id = _deterministic_message_id(step.execution_key)
        existing = await self._client.get(
            f"{self._gmail_root}/users/me/drafts",
            headers=_authorization(token),
            params={"q": f"in:drafts rfc822msgid:{message_id}", "maxResults": 1},
        )
        existing_payload = _response_object(existing)
        drafts = existing_payload.get("drafts")
        if isinstance(drafts, list) and drafts and isinstance(drafts[0], dict):
            existing_id = drafts[0].get("id")
            if isinstance(existing_id, str) and existing_id:
                return MutationReceipt(
                    resource_id=step.resource_id,
                    revision_id=existing_id,
                    external_id=existing_id,
                    recovered=True,
                )
        draft = EmailMessage()
        recipient = _context_string(current, "to")
        if not recipient:
            raise WorkspaceExecutionError("Original Gmail message has no recipient")
        draft["To"] = recipient
        cc = _context_string(current, "cc")
        if cc:
            draft["Cc"] = cc
        original_subject = _context_string(current, "subject")
        draft["Subject"] = f"Correction: {original_subject}"
        draft["Message-ID"] = message_id
        original_message_id = _context_string(current, "messageId")
        if original_message_id:
            draft["In-Reply-To"] = original_message_id
            draft["References"] = original_message_id
        draft.set_content(
            "Correction to the previously shared decision packet:\n\n"
            f"Previously: {step.before_statement}\n"
            f"Corrected: {step.proposed_statement}\n\n"
            "This correction was prepared by Veritas and has not been sent."
        )
        encoded = base64.urlsafe_b64encode(draft.as_bytes()).decode().rstrip("=")
        response = await self._client.post(
            f"{self._gmail_root}/users/me/drafts",
            headers=_authorization(token),
            json={"message": {"raw": encoded}},
        )
        payload = _response_object(response)
        draft_id = _required_string(payload, "id", "Gmail draft ID")
        message_payload = payload.get("message")
        if not isinstance(message_payload, dict):
            raise WorkspaceExecutionError("Gmail correction draft omitted its message")
        return MutationReceipt(
            resource_id=step.resource_id,
            revision_id=draft_id,
            external_id=draft_id,
        )

    async def _read_task(self, token: str, step: RepairStep) -> ArtifactState:
        task_list = _task_list(step)
        response = await self._client.get(
            f"{self._tasks_root}/lists/{quote(task_list, safe='')}/tasks/"
            f"{quote(step.resource_id, safe='')}",
            headers=_authorization(token),
        )
        payload = _response_object(response)
        notes = str(payload.get("notes") or "")
        return ArtifactState(
            resource_id=step.resource_id,
            revision_id=_required_string(payload, "etag", "Tasks ETag"),
            anchor=step.anchor,
            statement=_registered_statement(notes, step),
            write_context={"notes": notes},
        )

    async def _apply_task(
        self, token: str, step: RepairStep, current: ArtifactState
    ) -> MutationReceipt:
        notes = _context_string(current, "notes")
        if notes.count(step.before_statement) != 1:
            raise WorkspaceExecutionError("Task registered statement is not uniquely replaceable")
        updated_notes = notes.replace(step.before_statement, step.proposed_statement, 1)
        response = await self._client.patch(
            f"{self._tasks_root}/lists/{quote(_task_list(step), safe='')}/tasks/"
            f"{quote(step.resource_id, safe='')}",
            headers={**_authorization(token), "If-Match": current.revision_id},
            json={"notes": updated_notes},
        )
        payload = _response_object(response, precondition_statuses={409, 412})
        return MutationReceipt(
            resource_id=step.resource_id,
            revision_id=_required_string(payload, "etag", "Updated Tasks ETag"),
        )


def _authorization(token: str) -> dict[str, str]:
    if not token:
        raise ValueError("Google access token is required")
    return {"Authorization": f"Bearer {token}"}


def _response_object(
    response: httpx.Response,
    precondition_statuses: set[int] | None = None,
) -> dict[str, Any]:
    if response.status_code in (precondition_statuses or set()):
        raise WorkspacePreconditionFailed(
            f"Workspace revision precondition failed with status {response.status_code}"
        )
    try:
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise WorkspaceExecutionError(
            f"Workspace request failed with status {response.status_code}"
        ) from error
    try:
        payload = response.json()
    except ValueError as error:
        raise WorkspaceExecutionError("Workspace response was not JSON") from error
    if not isinstance(payload, dict):
        raise WorkspaceExecutionError("Workspace response must be an object")
    return cast(dict[str, Any], payload)


def _required_string(payload: dict[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise WorkspaceExecutionError(f"{label} is missing")
    return value


def _anchor_token(anchor: str) -> str:
    token = anchor.rsplit("#", 1)[-1]
    if not token:
        raise WorkspaceExecutionError("Registered anchor is invalid")
    return token


def _first_document_part(document: dict[str, Any]) -> dict[str, Any]:
    tabs = document.get("tabs")
    if isinstance(tabs, list) and tabs and isinstance(tabs[0], dict):
        part = tabs[0].get("documentTab")
        if isinstance(part, dict):
            return cast(dict[str, Any], part)
    return document


def _single_named_range(part: dict[str, Any], name: str) -> dict[str, Any]:
    groups = part.get("namedRanges")
    group = groups.get(name) if isinstance(groups, dict) else None
    definitions = group.get("namedRanges") if isinstance(group, dict) else None
    ranges = (
        definitions[0].get("ranges")
        if isinstance(definitions, list)
        and len(definitions) == 1
        and isinstance(definitions[0], dict)
        else None
    )
    if not isinstance(ranges, list) or len(ranges) != 1 or not isinstance(ranges[0], dict):
        raise WorkspaceExecutionError(
            f"Docs named range {name} must resolve to one registered span"
        )
    text_range = cast(dict[str, Any], ranges[0])
    start = text_range.get("startIndex")
    end = text_range.get("endIndex")
    if not isinstance(start, int) or not isinstance(end, int) or start >= end:
        raise WorkspaceExecutionError("Docs registered range has invalid indexes")
    return text_range


def _doc_text(part: dict[str, Any], text_range: dict[str, Any]) -> str:
    start = cast(int, text_range["startIndex"])
    end = cast(int, text_range["endIndex"])
    body = part.get("body")
    content = body.get("content") if isinstance(body, dict) else None
    if not isinstance(content, list):
        raise WorkspaceExecutionError("Docs response has no body content")
    fragments: list[str] = []
    for structural in content:
        paragraph = structural.get("paragraph") if isinstance(structural, dict) else None
        elements = paragraph.get("elements") if isinstance(paragraph, dict) else None
        if not isinstance(elements, list):
            continue
        for element in elements:
            if not isinstance(element, dict):
                continue
            element_start = element.get("startIndex")
            element_end = element.get("endIndex")
            text_run = element.get("textRun")
            text = text_run.get("content") if isinstance(text_run, dict) else None
            if not isinstance(element_start, int) or not isinstance(element_end, int):
                continue
            if not isinstance(text, str):
                continue
            overlap_start = max(start, element_start)
            overlap_end = min(end, element_end)
            if overlap_start < overlap_end:
                fragments.append(text[overlap_start - element_start : overlap_end - element_start])
    return "".join(fragments)


def _slides_text(presentation: dict[str, Any], object_id: str) -> str:
    slides = presentation.get("slides")
    if not isinstance(slides, list):
        raise WorkspaceExecutionError("Slides response has no slides")
    for slide in slides:
        elements = slide.get("pageElements") if isinstance(slide, dict) else None
        if not isinstance(elements, list):
            continue
        for element in elements:
            if not isinstance(element, dict) or element.get("objectId") != object_id:
                continue
            shape = element.get("shape")
            text = shape.get("text") if isinstance(shape, dict) else None
            text_elements = text.get("textElements") if isinstance(text, dict) else None
            if not isinstance(text_elements, list):
                break
            fragments = [
                run["textRun"]["content"]
                for run in text_elements
                if isinstance(run, dict)
                and isinstance(run.get("textRun"), dict)
                and isinstance(run["textRun"].get("content"), str)
            ]
            statement = "".join(fragments)
            # Google Slides materializes a paragraph terminator after inserted shape text.
            # It is structural API output, not part of the registered claim statement.
            if statement.endswith("\n"):
                statement = statement[:-1]
            if statement:
                return statement
    raise WorkspaceExecutionError(f"Slides registered shape {object_id} was not found")


def _decode_base64url(raw: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except ValueError as error:
        raise WorkspaceExecutionError("Gmail raw message encoding is invalid") from error


def _plain_body(message: EmailMessage) -> str:
    body = message.get_body(preferencelist=("plain",))
    content = message.get_content() if body is None else body.get_content()
    if not isinstance(content, str):
        raise WorkspaceExecutionError("Gmail message has no text body")
    return content


def _registered_statement(content: str, step: RepairStep) -> str:
    if content.count(step.proposed_statement) == 1:
        return step.proposed_statement
    if content.count(step.before_statement) == 1:
        return step.before_statement
    raise WorkspaceExecutionError("Registered statement is missing or ambiguous")


def _context_string(current: ArtifactState, key: str) -> str:
    value = current.write_context.get(key)
    if not isinstance(value, str):
        raise WorkspaceExecutionError(f"Workspace write context lacks {key}")
    return value


def _context_object(current: ArtifactState, key: str) -> dict[str, Any]:
    value = current.write_context.get(key)
    if not isinstance(value, dict):
        raise WorkspaceExecutionError(f"Workspace write context lacks {key}")
    return cast(dict[str, Any], value)


def _task_list(step: RepairStep) -> str:
    if not step.container_id:
        raise WorkspaceExecutionError("Google Task repair requires a registered task list ID")
    return step.container_id


def _draft_message(payload: dict[str, Any]) -> dict[str, Any]:
    message = payload.get("message")
    if not isinstance(message, dict):
        raise WorkspaceExecutionError("Gmail draft omitted its message")
    return cast(dict[str, Any], message)


def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _deterministic_message_id(execution_key: str) -> str:
    digest = hashlib.sha256(execution_key.encode()).hexdigest()[:32]
    return f"<veritas-{digest}@veritas.invalid>"
