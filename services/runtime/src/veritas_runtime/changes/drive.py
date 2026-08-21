import hashlib
from datetime import UTC, datetime
from typing import Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from veritas_runtime.changes.models import DriveChange, DriveChangePage, DriveWatchLease


class DriveChangeError(RuntimeError):
    """The Drive changes API returned an unusable response."""


class DriveChangesPort(Protocol):
    async def get_start_page_token(self, access_token: str) -> str: ...

    async def watch_changes(
        self,
        access_token: str,
        page_token: str,
        channel_id: str,
        address: str,
        channel_token: str,
        expiration: datetime,
    ) -> DriveWatchLease: ...

    async def list_changes(self, access_token: str, page_token: str) -> DriveChangePage: ...

    async def stop_channel(
        self,
        access_token: str,
        channel_id: str,
        google_resource_id: str,
    ) -> None: ...


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _StartToken(_ApiModel):
    startPageToken: str = Field(min_length=1)


class _WatchResponse(_ApiModel):
    id: str = Field(min_length=1)
    resourceId: str = Field(min_length=1)
    resourceUri: str = Field(min_length=1)
    expiration: str | None = None


class _DriveFile(_ApiModel):
    id: str | None = None
    mimeType: str | None = None
    version: str | int | None = None
    headRevisionId: str | None = None


class _Change(_ApiModel):
    fileId: str | None = None
    removed: bool = False
    time: datetime
    changeType: str
    file: _DriveFile | None = None


class _ChangeList(_ApiModel):
    changes: tuple[_Change, ...] = ()
    nextPageToken: str | None = None
    newStartPageToken: str | None = None


class GoogleDriveChangesClient:
    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        api_root: str = "https://www.googleapis.com/drive/v3",
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=20)
        self._api_root = api_root.rstrip("/")

    async def get_start_page_token(self, access_token: str) -> str:
        response = await self._client.get(
            f"{self._api_root}/changes/startPageToken",
            headers=_authorization(access_token),
            params={"supportsAllDrives": "true"},
        )
        return _validated(_StartToken, response).startPageToken

    async def watch_changes(
        self,
        access_token: str,
        page_token: str,
        channel_id: str,
        address: str,
        channel_token: str,
        expiration: datetime,
    ) -> DriveWatchLease:
        requested_expiration = expiration.astimezone(UTC)
        response = await self._client.post(
            f"{self._api_root}/changes/watch",
            headers=_authorization(access_token),
            params={"pageToken": page_token, "supportsAllDrives": "true"},
            json={
                "id": channel_id,
                "type": "web_hook",
                "address": address,
                "token": channel_token,
                "expiration": str(int(requested_expiration.timestamp() * 1000)),
            },
        )
        payload = _validated(_WatchResponse, response)
        if payload.id != channel_id:
            raise DriveChangeError("Drive returned a different watch channel ID")
        actual_expiration = (
            datetime.fromtimestamp(int(payload.expiration) / 1000, tz=UTC)
            if payload.expiration is not None
            else requested_expiration
        )
        return DriveWatchLease(
            channel_id=payload.id,
            google_resource_id=payload.resourceId,
            resource_uri=payload.resourceUri,
            expiration=actual_expiration,
        )

    async def list_changes(self, access_token: str, page_token: str) -> DriveChangePage:
        response = await self._client.get(
            f"{self._api_root}/changes",
            headers=_authorization(access_token),
            params={
                "pageToken": page_token,
                "includeItemsFromAllDrives": "true",
                "supportsAllDrives": "true",
                "fields": (
                    "changes(fileId,removed,time,changeType,"
                    "file(id,mimeType,version,headRevisionId)),"
                    "nextPageToken,newStartPageToken"
                ),
            },
        )
        payload = _validated(_ChangeList, response)
        changes = tuple(_drive_change(change) for change in payload.changes if change.fileId)
        return DriveChangePage(
            changes=changes,
            next_page_token=payload.nextPageToken,
            new_start_page_token=payload.newStartPageToken,
        )

    async def stop_channel(
        self,
        access_token: str,
        channel_id: str,
        google_resource_id: str,
    ) -> None:
        response = await self._client.post(
            f"{self._api_root}/channels/stop",
            headers=_authorization(access_token),
            json={"id": channel_id, "resourceId": google_resource_id},
        )
        if response.status_code >= 400:
            raise DriveChangeError(f"Drive API request failed with status {response.status_code}")


def _authorization(access_token: str) -> dict[str, str]:
    if not access_token:
        raise ValueError("Google access token is required")
    return {"Authorization": f"Bearer {access_token}"}


def _drive_change(change: _Change) -> DriveChange:
    if change.fileId is None:
        raise DriveChangeError("A file change is missing its file ID")
    version = (
        str(change.file.headRevisionId or change.file.version)
        if change.file and (change.file.headRevisionId or change.file.version)
        else None
    )
    identity = (
        f"{change.fileId}:{change.time.astimezone(UTC).isoformat()}:"
        f"{change.removed}:{version or ''}"
    )
    return DriveChange(
        change_id=hashlib.sha256(identity.encode()).hexdigest(),
        file_id=change.fileId,
        removed=change.removed,
        mime_type=change.file.mimeType if change.file else None,
        workspace_version=version,
    )


def _validated[ModelT: BaseModel](model: type[ModelT], response: httpx.Response) -> ModelT:
    try:
        response.raise_for_status()
        return model.model_validate(response.json())
    except (httpx.HTTPError, ValidationError, ValueError) as error:
        status = response.status_code
        raise DriveChangeError(f"Drive API response was invalid (status {status})") from error
