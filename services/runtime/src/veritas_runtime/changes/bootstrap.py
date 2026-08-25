import asyncio
import hashlib
from collections import defaultdict
from typing import Any, cast
from urllib.parse import quote

import httpx

from veritas_runtime.execution.service import WorkspaceSessionProvider
from veritas_runtime.packets.models import SourceKind, SourceSnapshot


class EvidenceBootstrapError(RuntimeError):
    """A real Google Workspace evidence source could not be materialized."""


class GoogleWorkspaceEvidenceBootstrapper:
    """Creates idempotent source Sheets and Docs before a packet is registered."""

    def __init__(
        self,
        access_token: str,
        client: httpx.AsyncClient,
        *,
        drive_root: str = "https://www.googleapis.com/drive/v3",
        sheets_root: str = "https://sheets.googleapis.com/v4",
        docs_root: str = "https://docs.googleapis.com/v1",
        version_settle_interval_seconds: float = 0.75,
        version_settle_attempts: int = 12,
        version_settle_observations: int = 6,
    ) -> None:
        if not access_token:
            raise ValueError("Workspace evidence bootstrap requires an access token")
        if (
            version_settle_interval_seconds < 0
            or version_settle_observations < 2
            or version_settle_attempts < version_settle_observations
        ):
            raise ValueError(
                "Drive version settling requires a valid interval and observation window"
            )
        self._token = access_token
        self._client = client
        self._drive_root = drive_root.rstrip("/")
        self._sheets_root = sheets_root.rstrip("/")
        self._docs_root = docs_root.rstrip("/")
        self._version_settle_interval_seconds = version_settle_interval_seconds
        self._version_settle_attempts = version_settle_attempts
        self._version_settle_observations = version_settle_observations

    async def materialize(
        self,
        request_id: str,
        sources: tuple[SourceSnapshot, ...],
    ) -> tuple[SourceSnapshot, ...]:
        if not request_id or not sources:
            raise EvidenceBootstrapError("Evidence request ID and sources are required")
        groups: dict[str, list[SourceSnapshot]] = defaultdict(list)
        for source in sources:
            groups[source.resource_id].append(source)

        resolved: dict[str, tuple[str, str]] = {}
        for logical_id, group in groups.items():
            kinds = {source.kind for source in group}
            if len(kinds) != 1:
                raise EvidenceBootstrapError("A source resource cannot mix Workspace kinds")
            kind = next(iter(kinds))
            key = hashlib.sha256(f"{request_id}:{logical_id}".encode()).hexdigest()
            if kind == SourceKind.GOOGLE_SHEET:
                resource_id, version = await self._sheet(tuple(group), key)
            elif kind == SourceKind.GOOGLE_DOC:
                resource_id, version = await self._document(tuple(group), key)
            else:
                raise EvidenceBootstrapError(f"Unsupported evidence source kind: {kind}")
            resolved[logical_id] = (resource_id, version)

        return tuple(
            source.model_copy(
                update={
                    "resource_id": resolved[source.resource_id][0],
                    "version": resolved[source.resource_id][1],
                }
            )
            for source in sources
        )

    async def _sheet(self, sources: tuple[SourceSnapshot, ...], key: str) -> tuple[str, str]:
        existing = await self._find_file(key, "application/vnd.google-apps.spreadsheet")
        if existing is not None:
            return existing, await self._drive_version(existing)
        sheet_names = {source.anchor.split("!", 1)[0].strip("'") for source in sources}
        if len(sheet_names) != 1 or any("!" not in source.anchor for source in sources):
            raise EvidenceBootstrapError("Sheet evidence must use one explicit sheet name")
        sheet_name = next(iter(sheet_names))
        title = _source_title(sources[0], "Veritas evidence")
        created = await self._request(
            "POST",
            f"{self._sheets_root}/spreadsheets",
            json={
                "properties": {"title": title},
                "sheets": [{"properties": {"title": sheet_name}}],
            },
        )
        resource_id = _required_string(created, "spreadsheetId", "Sheets spreadsheet ID")
        await self._request(
            "POST",
            f"{self._sheets_root}/spreadsheets/{quote(resource_id, safe='')}/values:batchUpdate",
            json={
                "valueInputOption": "RAW",
                "data": [
                    {"range": source.anchor, "values": [[source.value]]} for source in sources
                ],
            },
        )
        marked_version = await self._mark_file(resource_id, key)
        return resource_id, await self._settled_drive_version(resource_id, marked_version)

    async def _document(self, sources: tuple[SourceSnapshot, ...], key: str) -> tuple[str, str]:
        existing = await self._find_file(key, "application/vnd.google-apps.document")
        if existing is not None:
            return existing, await self._drive_version(existing)
        created = await self._request(
            "POST",
            f"{self._docs_root}/documents",
            json={"title": _source_title(sources[0], "Veritas evidence policy")},
        )
        resource_id = _required_string(created, "documentId", "Docs document ID")
        text, ranges = _document_text(sources)
        requests: list[dict[str, object]] = [
            {"insertText": {"location": {"index": 1}, "text": text}}
        ]
        requests.extend(
            {
                "createNamedRange": {
                    "name": source.anchor,
                    "range": {"startIndex": start, "endIndex": end},
                }
            }
            for source, (start, end) in zip(sources, ranges, strict=True)
        )
        await self._request(
            "POST",
            f"{self._docs_root}/documents/{quote(resource_id, safe='')}:batchUpdate",
            json={"requests": requests},
        )
        marked_version = await self._mark_file(resource_id, key)
        return resource_id, await self._settled_drive_version(resource_id, marked_version)

    async def _find_file(self, key: str, mime_type: str) -> str | None:
        escaped_key = key.replace("'", "\\'")
        payload = await self._request(
            "GET",
            f"{self._drive_root}/files",
            params={
                "q": (
                    "trashed = false and "
                    f"mimeType = '{mime_type}' and "
                    "appProperties has { key='veritasEvidenceRequest' "
                    f"and value='{escaped_key}' }}"
                ),
                "fields": "files(id)",
                "pageSize": 2,
            },
        )
        files = payload.get("files")
        if not isinstance(files, list) or not files:
            return None
        if len(files) != 1 or not isinstance(files[0], dict):
            raise EvidenceBootstrapError("Workspace evidence idempotency key is ambiguous")
        return _required_string(files[0], "id", "Drive evidence file ID")

    async def _mark_file(self, resource_id: str, key: str) -> str:
        payload = await self._request(
            "PATCH",
            f"{self._drive_root}/files/{quote(resource_id, safe='')}",
            params={"fields": "id,version"},
            json={"appProperties": {"veritasEvidenceRequest": key}},
        )
        version = payload.get("version")
        if not isinstance(version, (str, int)):
            raise EvidenceBootstrapError("Marked Drive evidence version is missing")
        return str(version)

    async def _drive_version(self, resource_id: str) -> str:
        payload = await self._request(
            "GET",
            f"{self._drive_root}/files/{quote(resource_id, safe='')}",
            params={"fields": "version"},
        )
        version = payload.get("version")
        if not isinstance(version, (str, int)):
            raise EvidenceBootstrapError("Drive evidence version is missing")
        return str(version)

    async def _settled_drive_version(self, resource_id: str, initial: str) -> str:
        """Wait for Workspace's asynchronous native-file commits to become observable.

        Sheets and Docs can acknowledge their content write before Drive publishes the
        final monotonically increasing file version. Returning that intermediate version
        would make an unchanged packet fail its own immutable baseline check.
        """

        previous = initial
        unchanged_observations = 0
        for _ in range(self._version_settle_attempts):
            await asyncio.sleep(self._version_settle_interval_seconds)
            current = await self._drive_version(resource_id)
            if current == previous:
                unchanged_observations += 1
                if unchanged_observations >= self._version_settle_observations:
                    return current
            else:
                unchanged_observations = 1
            previous = current
        raise EvidenceBootstrapError("Drive evidence version did not settle after creation")

    async def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        response = await self._client.request(
            method,
            url,
            headers={"Authorization": f"Bearer {self._token}"},
            **kwargs,
        )
        try:
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise EvidenceBootstrapError(
                f"Workspace evidence request failed with status {response.status_code}"
            ) from error
        if not isinstance(payload, dict):
            raise EvidenceBootstrapError("Workspace evidence response must be an object")
        return cast(dict[str, Any], payload)


class WorkspaceEvidenceBootstrapService:
    def __init__(
        self,
        sessions: WorkspaceSessionProvider,
        http: httpx.AsyncClient,
        *,
        version_settle_interval_seconds: float = 0.75,
        version_settle_attempts: int = 12,
        version_settle_observations: int = 6,
    ) -> None:
        self._sessions = sessions
        self._http = http
        self._version_settle_interval_seconds = version_settle_interval_seconds
        self._version_settle_attempts = version_settle_attempts
        self._version_settle_observations = version_settle_observations

    async def bootstrap_for_subject(
        self,
        subject: str,
        request_id: str,
        sources: tuple[SourceSnapshot, ...],
    ) -> tuple[SourceSnapshot, ...]:
        session = await self._sessions.get(subject)
        return await GoogleWorkspaceEvidenceBootstrapper(
            session.access_token,
            self._http,
            version_settle_interval_seconds=self._version_settle_interval_seconds,
            version_settle_attempts=self._version_settle_attempts,
            version_settle_observations=self._version_settle_observations,
        ).materialize(f"{subject}:{request_id}", sources)


def _source_title(source: SourceSnapshot, fallback: str) -> str:
    title = source.context.get("title")
    return title if isinstance(title, str) and title.strip() else fallback


def _document_text(
    sources: tuple[SourceSnapshot, ...],
) -> tuple[str, tuple[tuple[int, int], ...]]:
    text = "Veritas registered evidence\n\n"
    cursor = 1 + _utf16_length(text)
    ranges: list[tuple[int, int]] = []
    for source in sources:
        label = f"{source.anchor}\n"
        text += label
        cursor += _utf16_length(label)
        value = str(source.value)
        start = cursor
        text += value
        cursor += _utf16_length(value)
        ranges.append((start, cursor))
        text += "\n\n"
        cursor += 2
    return text, tuple(ranges)


def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _required_string(payload: dict[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise EvidenceBootstrapError(f"{label} is missing")
    return value
