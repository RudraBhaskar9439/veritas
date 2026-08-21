from typing import Any, Protocol, cast
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from veritas_runtime.changes.models import EvidenceCapture, EvidenceSourceRegistration, JsonValue
from veritas_runtime.packets.models import SourceKind


class EvidenceExtractionError(RuntimeError):
    """Registered evidence could not be read exactly from Google Workspace."""


class EvidenceExtractor(Protocol):
    async def extract(
        self,
        access_token: str,
        registration: EvidenceSourceRegistration,
    ) -> EvidenceCapture: ...


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _DriveVersion(_ApiModel):
    version: str | int = Field()


class _SheetValues(_ApiModel):
    values: list[list[JsonValue]] = []


class GoogleEvidenceExtractor:
    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        drive_root: str = "https://www.googleapis.com/drive/v3",
        sheets_root: str = "https://sheets.googleapis.com/v4",
        docs_root: str = "https://docs.googleapis.com/v1",
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=20)
        self._drive_root = drive_root.rstrip("/")
        self._sheets_root = sheets_root.rstrip("/")
        self._docs_root = docs_root.rstrip("/")

    async def extract(
        self,
        access_token: str,
        registration: EvidenceSourceRegistration,
    ) -> EvidenceCapture:
        version = await self._workspace_version(access_token, registration.resource_id)
        if registration.kind == SourceKind.GOOGLE_SHEET:
            value, presentation = await self._sheet_evidence(access_token, registration)
            mime_type = "application/vnd.google-apps.spreadsheet"
        elif registration.kind == SourceKind.GOOGLE_DOC:
            value, presentation = await self._doc_evidence(access_token, registration)
            mime_type = "application/vnd.google-apps.document"
        else:
            raise EvidenceExtractionError(f"Unsupported evidence source kind: {registration.kind}")
        return EvidenceCapture(
            subject=registration.subject,
            packet_id=registration.packet_id,
            source_id=registration.source_id,
            resource_id=registration.resource_id,
            workspace_version=version,
            mime_type=mime_type,
            evidence={registration.anchor: value},
            presentation={registration.anchor: presentation},
        )

    async def _workspace_version(self, access_token: str, resource_id: str) -> str:
        response = await self._client.get(
            f"{self._drive_root}/files/{quote(resource_id, safe='')}",
            headers=_authorization(access_token),
            params={"fields": "version", "supportsAllDrives": "true"},
        )
        return str(_validated(_DriveVersion, response).version)

    async def _sheet_evidence(
        self,
        access_token: str,
        registration: EvidenceSourceRegistration,
    ) -> tuple[JsonValue, dict[str, JsonValue]]:
        resource = quote(registration.resource_id, safe="")
        anchor = quote(registration.anchor, safe="")
        values_response = await self._client.get(
            f"{self._sheets_root}/spreadsheets/{resource}/values/{anchor}",
            headers=_authorization(access_token),
            params={
                "valueRenderOption": "UNFORMATTED_VALUE",
                "dateTimeRenderOption": "SERIAL_NUMBER",
            },
        )
        values = _validated(_SheetValues, values_response).values
        if not values or not values[0]:
            raise EvidenceExtractionError(
                f"Registered Sheets anchor {registration.anchor} is empty"
            )
        value = cast(
            JsonValue,
            values[0][0] if len(values) == 1 and len(values[0]) == 1 else values,
        )

        format_response = await self._client.get(
            f"{self._sheets_root}/spreadsheets/{resource}",
            headers=_authorization(access_token),
            params={
                "ranges": registration.anchor,
                "includeGridData": "true",
                "fields": (
                    "sheets(properties(sheetId,title),data(startRow,startColumn,"
                    "rowData(values(formattedValue,effectiveFormat,note))))"
                ),
            },
        )
        _raise_for_status(format_response)
        presentation = cast(dict[str, JsonValue], _json_object(format_response))
        return value, presentation

    async def _doc_evidence(
        self,
        access_token: str,
        registration: EvidenceSourceRegistration,
    ) -> tuple[JsonValue, dict[str, JsonValue]]:
        response = await self._client.get(
            f"{self._docs_root}/documents/{quote(registration.resource_id, safe='')}",
            headers=_authorization(access_token),
            params={
                "fields": (
                    "revisionId,namedRanges,body(content(startIndex,endIndex,paragraph("
                    "elements(startIndex,endIndex,textRun(content,textStyle)))))"
                )
            },
        )
        _raise_for_status(response)
        document = _json_object(response)
        start, end = _named_range(document, registration.anchor)
        text, styles = _text_in_range(document, start, end)
        if not text:
            raise EvidenceExtractionError(
                f"Registered Docs named range {registration.anchor} is empty"
            )
        return text, {"segments": styles}


def _named_range(document: dict[str, Any], name: str) -> tuple[int, int]:
    named_ranges = document.get("namedRanges")
    if not isinstance(named_ranges, dict):
        raise EvidenceExtractionError(f"Docs named range {name} was not found")
    group = named_ranges.get(name)
    if not isinstance(group, dict):
        raise EvidenceExtractionError(f"Docs named range {name} was not found")
    definitions = group.get("namedRanges")
    if not isinstance(definitions, list) or len(definitions) != 1:
        raise EvidenceExtractionError(f"Docs named range {name} must resolve to exactly one range")
    definition = definitions[0]
    if not isinstance(definition, dict) or not isinstance(definition.get("ranges"), list):
        raise EvidenceExtractionError(f"Docs named range {name} has invalid ranges")
    ranges = definition["ranges"]
    if len(ranges) != 1 or not isinstance(ranges[0], dict):
        raise EvidenceExtractionError(f"Docs named range {name} must contain exactly one text span")
    start = ranges[0].get("startIndex")
    end = ranges[0].get("endIndex")
    if not isinstance(start, int) or not isinstance(end, int) or start >= end:
        raise EvidenceExtractionError(f"Docs named range {name} has invalid indexes")
    return start, end


def _text_in_range(
    document: dict[str, Any],
    start: int,
    end: int,
) -> tuple[str, list[JsonValue]]:
    body = document.get("body")
    content = body.get("content") if isinstance(body, dict) else None
    if not isinstance(content, list):
        raise EvidenceExtractionError("Docs response has no body content")
    fragments: list[str] = []
    styles: list[JsonValue] = []
    for structural_element in content:
        if not isinstance(structural_element, dict):
            continue
        paragraph = structural_element.get("paragraph")
        elements = paragraph.get("elements") if isinstance(paragraph, dict) else None
        if not isinstance(elements, list):
            continue
        for element in elements:
            if not isinstance(element, dict):
                continue
            element_start = element.get("startIndex")
            element_end = element.get("endIndex")
            text_run = element.get("textRun")
            if (
                not isinstance(element_start, int)
                or not isinstance(element_end, int)
                or not isinstance(text_run, dict)
                or not isinstance(text_run.get("content"), str)
            ):
                continue
            overlap_start = max(start, element_start)
            overlap_end = min(end, element_end)
            if overlap_start >= overlap_end:
                continue
            text = text_run["content"]
            fragments.append(text[overlap_start - element_start : overlap_end - element_start])
            styles.append(
                {
                    "start": overlap_start,
                    "end": overlap_end,
                    "textStyle": text_run.get("textStyle", {}),
                }
            )
    return "".join(fragments), styles


def _authorization(access_token: str) -> dict[str, str]:
    if not access_token:
        raise ValueError("Google access token is required")
    return {"Authorization": f"Bearer {access_token}"}


def _raise_for_status(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise EvidenceExtractionError(
            f"Workspace evidence request failed with status {response.status_code}"
        ) from error


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as error:
        raise EvidenceExtractionError("Workspace evidence response was not JSON") from error
    if not isinstance(payload, dict):
        raise EvidenceExtractionError("Workspace evidence response must be an object")
    return cast(dict[str, Any], payload)


def _validated[ModelT: BaseModel](model: type[ModelT], response: httpx.Response) -> ModelT:
    _raise_for_status(response)
    try:
        return model.model_validate(response.json())
    except (ValidationError, ValueError) as error:
        raise EvidenceExtractionError("Workspace evidence response was invalid") from error
