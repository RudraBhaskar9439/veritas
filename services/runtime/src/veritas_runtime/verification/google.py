import base64
import hashlib
import json
from email import policy
from email.parser import BytesParser
from typing import Any, cast
from urllib.parse import quote

import httpx

from veritas_runtime.packets.models import ArtifactKind, ArtifactRecord
from veritas_runtime.repairs.models import RepairStep
from veritas_runtime.verification.models import (
    ObservedStatement,
    ProtectedArtifactState,
)
from veritas_runtime.verification.service import VerificationReadError, anchor_set_hash


class WorkspaceVerificationReadError(VerificationReadError):
    """An independent Workspace read could not prove the requested state."""


class GoogleWorkspaceVerificationGateway:
    """Read-only adapter that never consumes execution mutation receipts as truth."""

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

    async def read_registered(
        self,
        access_token: str,
        artifact: ArtifactRecord,
        anchor: str,
        expected: str,
        previous: str,
    ) -> ObservedStatement:
        payload = await self._read_artifact(access_token, artifact)
        if artifact.kind == ArtifactKind.GOOGLE_DOC:
            part = _first_document_part(payload)
            statement = _doc_text(part, _single_named_range(part, _anchor_token(anchor)))
            revision = _required_string(payload, "revisionId", "Docs revision")
        elif artifact.kind == ArtifactKind.GOOGLE_SLIDES:
            statement = _slides_text(payload, _anchor_token(anchor))
            revision = _required_string(payload, "revisionId", "Slides revision")
        elif artifact.kind == ArtifactKind.GMAIL:
            raw = _required_string(payload, "raw", "Gmail raw message")
            message = BytesParser(policy=policy.default).parsebytes(_decode_base64url(raw))
            statement = _registered_statement(_plain_body(message), expected, previous)
            revision = str(
                payload.get("historyId") or payload.get("id") or artifact.base_revision_id
            )
        elif artifact.kind == ArtifactKind.GOOGLE_TASK:
            statement = _registered_statement(str(payload.get("notes") or ""), expected, previous)
            revision = _required_string(payload, "etag", "Tasks ETag")
        else:
            raise WorkspaceVerificationReadError(f"Unsupported artifact kind: {artifact.kind}")
        return ObservedStatement(
            resource_id=artifact.resource_id,
            revision_id=revision,
            statement=statement,
        )

    async def read_correction(
        self,
        access_token: str,
        step: RepairStep,
        external_id: str,
    ) -> ObservedStatement:
        response = await self._client.get(
            f"{self._gmail_root}/users/me/drafts/{quote(external_id, safe='')}",
            headers=_authorization(access_token),
            params={"format": "raw"},
        )
        payload = _draft_message(_response_object(response))
        raw = _required_string(payload, "raw", "Gmail correction raw message")
        message = BytesParser(policy=policy.default).parsebytes(_decode_base64url(raw))
        body = _plain_body(message)
        statement = _registered_statement(body, step.proposed_statement, step.before_statement)
        return ObservedStatement(
            resource_id=external_id,
            revision_id=str(payload.get("historyId") or payload.get("id") or external_id),
            statement=statement,
        )

    async def protected_state(
        self,
        access_token: str,
        artifact: ArtifactRecord,
        anchors: tuple[str, ...],
        registered_statements: tuple[str, ...],
    ) -> ProtectedArtifactState:
        if len(anchors) != len(registered_statements):
            raise WorkspaceVerificationReadError(
                "Protected-state anchors and statements do not align"
            )
        payload = await self._read_artifact(access_token, artifact)
        if artifact.kind == ArtifactKind.GOOGLE_DOC:
            part = _first_document_part(payload)
            ranges = tuple(_single_named_range(part, _anchor_token(anchor)) for anchor in anchors)
            protected = _doc_protected_text(part, ranges)
            revision = _required_string(payload, "revisionId", "Docs revision")
        elif artifact.kind == ArtifactKind.GOOGLE_SLIDES:
            protected = _slides_protected_text(
                payload, frozenset(_anchor_token(anchor) for anchor in anchors)
            )
            revision = _required_string(payload, "revisionId", "Slides revision")
        elif artifact.kind == ArtifactKind.GMAIL:
            raw = _required_string(payload, "raw", "Gmail raw message")
            message = BytesParser(policy=policy.default).parsebytes(_decode_base64url(raw))
            protected = _replace_registered(_plain_body(message), registered_statements)
            revision = str(
                payload.get("historyId") or payload.get("id") or artifact.base_revision_id
            )
        elif artifact.kind == ArtifactKind.GOOGLE_TASK:
            protected = _replace_registered(str(payload.get("notes") or ""), registered_statements)
            revision = _required_string(payload, "etag", "Tasks ETag")
        else:
            raise WorkspaceVerificationReadError(f"Unsupported artifact kind: {artifact.kind}")
        return ProtectedArtifactState(
            artifact_id=artifact.artifact_id,
            resource_id=artifact.resource_id,
            revision_id=revision,
            anchor_set_hash=anchor_set_hash(anchors),
            protected_content_hash=hashlib.sha256(protected.encode()).hexdigest(),
        )

    async def _read_artifact(self, access_token: str, artifact: ArtifactRecord) -> dict[str, Any]:
        headers = _authorization(access_token)
        if artifact.kind == ArtifactKind.GOOGLE_DOC:
            response = await self._client.get(
                f"{self._docs_root}/documents/{quote(artifact.resource_id, safe='')}",
                headers=headers,
                params={"includeTabsContent": "true"},
            )
        elif artifact.kind == ArtifactKind.GOOGLE_SLIDES:
            response = await self._client.get(
                f"{self._slides_root}/presentations/{quote(artifact.resource_id, safe='')}",
                headers=headers,
            )
        elif artifact.kind == ArtifactKind.GMAIL:
            if not artifact.container_id:
                raise WorkspaceVerificationReadError("Gmail artifact is missing its draft ID")
            response = await self._client.get(
                f"{self._gmail_root}/users/me/drafts/{quote(artifact.container_id, safe='')}",
                headers=headers,
                params={"format": "raw"},
            )
        elif artifact.kind == ArtifactKind.GOOGLE_TASK:
            if not artifact.container_id:
                raise WorkspaceVerificationReadError("Google Task is missing its task-list ID")
            response = await self._client.get(
                f"{self._tasks_root}/lists/{quote(artifact.container_id, safe='')}/tasks/"
                f"{quote(artifact.resource_id, safe='')}",
                headers=headers,
            )
        else:
            raise WorkspaceVerificationReadError(f"Unsupported artifact kind: {artifact.kind}")
        payload = _response_object(response)
        return _draft_message(payload) if artifact.kind == ArtifactKind.GMAIL else payload


def _draft_message(payload: dict[str, Any]) -> dict[str, Any]:
    message = payload.get("message")
    if not isinstance(message, dict):
        raise WorkspaceVerificationReadError("Gmail draft omitted its message")
    return cast(dict[str, Any], message)


def _authorization(token: str) -> dict[str, str]:
    if not token:
        raise ValueError("Google access token is required")
    return {"Authorization": f"Bearer {token}"}


def _response_object(response: httpx.Response) -> dict[str, Any]:
    try:
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise WorkspaceVerificationReadError(
            f"Workspace verification read failed with status {response.status_code}"
        ) from error
    try:
        payload = response.json()
    except ValueError as error:
        raise WorkspaceVerificationReadError(
            "Workspace verification response was not JSON"
        ) from error
    if not isinstance(payload, dict):
        raise WorkspaceVerificationReadError("Workspace verification response must be an object")
    return cast(dict[str, Any], payload)


def _required_string(payload: dict[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise WorkspaceVerificationReadError(f"{label} is missing")
    return value


def _anchor_token(anchor: str) -> str:
    token = anchor.rsplit("#", 1)[-1]
    if not token:
        raise WorkspaceVerificationReadError("Registered anchor is invalid")
    return token


def _first_document_part(document: dict[str, Any]) -> dict[str, Any]:
    tabs = document.get("tabs")
    if isinstance(tabs, list) and tabs and isinstance(tabs[0], dict):
        part = tabs[0].get("documentTab")
        if isinstance(part, dict):
            return cast(dict[str, Any], part)
    return document


def _single_named_range(part: dict[str, Any], name: str) -> dict[str, Any]:
    named_ranges = part.get("namedRanges")
    entry = named_ranges.get(name) if isinstance(named_ranges, dict) else None
    ranges = entry.get("namedRanges") if isinstance(entry, dict) else None
    if not isinstance(ranges, list) or len(ranges) != 1 or not isinstance(ranges[0], dict):
        raise WorkspaceVerificationReadError(
            f"Docs anchor {name} must resolve to exactly one named range"
        )
    text_range = ranges[0].get("ranges")
    if (
        not isinstance(text_range, list)
        or len(text_range) != 1
        or not isinstance(text_range[0], dict)
    ):
        raise WorkspaceVerificationReadError(
            f"Docs anchor {name} must contain exactly one text range"
        )
    return cast(dict[str, Any], text_range[0])


def _doc_text(part: dict[str, Any], text_range: dict[str, Any]) -> str:
    start = text_range.get("startIndex")
    end = text_range.get("endIndex")
    if not isinstance(start, int) or not isinstance(end, int) or start >= end:
        raise WorkspaceVerificationReadError("Docs named range has invalid indexes")
    pieces: list[str] = []
    for element in _structural_elements(part):
        text_run = element.get("textRun")
        content = text_run.get("content") if isinstance(text_run, dict) else None
        element_start = element.get("startIndex")
        element_end = element.get("endIndex")
        if (
            isinstance(content, str)
            and isinstance(element_start, int)
            and isinstance(element_end, int)
            and element_end > start
            and element_start < end
        ):
            left = max(start, element_start) - element_start
            right = min(end, element_end) - element_start
            pieces.append(_slice_utf16(content, left, right))
    statement = "".join(pieces)
    if not statement:
        raise WorkspaceVerificationReadError("Docs registered anchor is empty")
    return statement


def _doc_protected_text(part: dict[str, Any], ranges: tuple[dict[str, Any], ...]) -> str:
    intervals: list[tuple[int, int]] = []
    for text_range in ranges:
        start = text_range.get("startIndex")
        end = text_range.get("endIndex")
        if not isinstance(start, int) or not isinstance(end, int) or start >= end:
            raise WorkspaceVerificationReadError("Docs protected range has invalid indexes")
        intervals.append((start, end))
    pieces: list[tuple[int, str]] = []
    for element in _structural_elements(part):
        text_run = element.get("textRun")
        content = text_run.get("content") if isinstance(text_run, dict) else None
        start = element.get("startIndex")
        end = element.get("endIndex")
        if not isinstance(content, str) or not isinstance(start, int) or not isinstance(end, int):
            continue
        fragments = [(start, end, content)]
        for excluded_start, excluded_end in intervals:
            next_fragments: list[tuple[int, int, str]] = []
            for fragment_start, fragment_end, fragment_text in fragments:
                if excluded_end <= fragment_start or excluded_start >= fragment_end:
                    next_fragments.append((fragment_start, fragment_end, fragment_text))
                    continue
                left_end = max(fragment_start, min(excluded_start, fragment_end))
                right_start = min(fragment_end, max(excluded_end, fragment_start))
                if fragment_start < left_end:
                    next_fragments.append(
                        (
                            fragment_start,
                            left_end,
                            _slice_utf16(fragment_text, 0, left_end - fragment_start),
                        )
                    )
                if right_start < fragment_end:
                    next_fragments.append(
                        (
                            right_start,
                            fragment_end,
                            _slice_utf16(
                                fragment_text,
                                right_start - fragment_start,
                                fragment_end - fragment_start,
                            ),
                        )
                    )
            fragments = next_fragments
        pieces.extend((fragment_start, text) for fragment_start, _, text in fragments)
    return json.dumps(
        [text for _, text in sorted(pieces)],
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _structural_elements(part: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    def walk(value: object) -> None:
        if isinstance(value, dict):
            if "textRun" in value and "startIndex" in value and "endIndex" in value:
                result.append(cast(dict[str, Any], value))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(part.get("body", {}).get("content") if isinstance(part.get("body"), dict) else [])
    return result


def _slice_utf16(value: str, start_units: int, end_units: int) -> str:
    encoded = value.encode("utf-16-le")
    return encoded[start_units * 2 : end_units * 2].decode("utf-16-le")


def _slides_text(presentation: dict[str, Any], object_id: str) -> str:
    for element in _slide_elements(presentation):
        if element.get("objectId") == object_id:
            statement = _shape_text(element)
            if statement:
                return statement
            raise WorkspaceVerificationReadError("Slides registered shape is empty")
    raise WorkspaceVerificationReadError(f"Slides registered shape {object_id} was not found")


def _slides_protected_text(
    presentation: dict[str, Any], registered_object_ids: frozenset[str]
) -> str:
    entries: list[tuple[str, str]] = []
    found: set[str] = set()
    for element in _slide_elements(presentation):
        object_id = element.get("objectId")
        if not isinstance(object_id, str):
            continue
        if object_id in registered_object_ids:
            found.add(object_id)
            continue
        entries.append((object_id, _shape_text(element)))
    if found != set(registered_object_ids):
        raise WorkspaceVerificationReadError("A protected Slides anchor is missing")
    return json.dumps(sorted(entries), separators=(",", ":"), ensure_ascii=False)


def _slide_elements(presentation: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    slides = presentation.get("slides")
    if not isinstance(slides, list):
        return result
    for slide in slides:
        elements = slide.get("pageElements") if isinstance(slide, dict) else None
        if isinstance(elements, list):
            result.extend(element for element in elements if isinstance(element, dict))
    return result


def _shape_text(element: dict[str, Any]) -> str:
    shape = element.get("shape")
    text = shape.get("text") if isinstance(shape, dict) else None
    elements = text.get("textElements") if isinstance(text, dict) else None
    if not isinstance(elements, list):
        return ""
    statement = "".join(
        run.get("content", "")
        for item in elements
        if isinstance(item, dict)
        for run in [item.get("textRun")]
        if isinstance(run, dict) and isinstance(run.get("content"), str)
    )
    # Slides exposes the structural paragraph terminator as text even though it
    # is not part of the inserted claim. Remove exactly that terminator; any
    # additional whitespace remains observable verification evidence.
    return statement[:-1] if statement.endswith("\n") else statement


def _registered_statement(body: str, expected: str, previous: str) -> str:
    if expected and expected in body:
        return expected
    if previous and previous in body:
        return previous
    return body.strip() or "Registered statement is missing."


def _replace_registered(value: str, statements: tuple[str, ...]) -> str:
    protected = value
    for index, statement in enumerate(statements):
        if protected.count(statement) != 1:
            raise WorkspaceVerificationReadError(
                "A registered statement is not uniquely present in the protected artifact"
            )
        protected = protected.replace(statement, f"{{{{REGISTERED:{index}}}}}", 1)
    return protected


def _decode_base64url(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except ValueError as error:
        raise WorkspaceVerificationReadError("Gmail raw message is not base64url") from error


def _plain_body(message: Any) -> str:
    if message.is_multipart():
        for part in message.walk():
            if (
                part.get_content_type() == "text/plain"
                and part.get_content_disposition() != "attachment"
            ):
                return str(part.get_content())
        raise WorkspaceVerificationReadError("Gmail message has no plain-text body")
    return str(message.get_content())
