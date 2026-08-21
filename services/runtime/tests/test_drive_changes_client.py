import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from veritas_runtime.changes.drive import DriveChangeError, GoogleDriveChangesClient

NOW = datetime(2026, 8, 21, 1, 0, tzinfo=UTC)


def test_drive_client_uses_change_cursor_watch_and_stop_contracts() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/changes/startPageToken"):
            return httpx.Response(200, json={"startPageToken": "page-1"})
        if request.url.path.endswith("/changes/watch"):
            body = __import__("json").loads(request.content)
            return httpx.Response(
                200,
                json={
                    "id": body["id"],
                    "resourceId": "drive-resource-1",
                    "resourceUri": "https://www.googleapis.com/drive/v3/changes",
                    "expiration": body["expiration"],
                },
            )
        if request.url.path.endswith("/changes"):
            return httpx.Response(
                200,
                json={
                    "changes": [
                        {
                            "fileId": "sheet-1",
                            "time": "2026-08-21T01:00:00Z",
                            "changeType": "file",
                            "file": {
                                "id": "sheet-1",
                                "mimeType": "application/vnd.google-apps.spreadsheet",
                                "version": "42",
                            },
                        },
                        {
                            "fileId": "gone-1",
                            "removed": True,
                            "time": "2026-08-21T01:01:00Z",
                            "changeType": "file",
                        },
                        {
                            "driveId": "shared-drive-1",
                            "time": "2026-08-21T01:02:00Z",
                            "changeType": "drive",
                        },
                    ],
                    "newStartPageToken": "page-2",
                },
            )
        if request.url.path.endswith("/channels/stop"):
            return httpx.Response(204)
        return httpx.Response(404)

    async def scenario() -> None:
        http = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://www.googleapis.com"
        )
        client = GoogleDriveChangesClient(http)
        assert await client.get_start_page_token("access") == "page-1"
        expiration = NOW + timedelta(days=6)
        lease = await client.watch_changes(
            "access", "page-1", "channel-1", "https://app.test/hook", "signed", expiration
        )
        assert lease.google_resource_id == "drive-resource-1"
        assert lease.expiration == expiration
        page = await client.list_changes("access", "page-1")
        assert page.new_start_page_token == "page-2"
        assert page.changes[0].workspace_version == "42"
        assert page.changes[1].removed is True
        await client.stop_channel("access", "channel-1", "drive-resource-1")
        await http.aclose()

    asyncio.run(scenario())
    assert all(request.headers["Authorization"] == "Bearer access" for request in requests)
    assert "pageToken=page-1" in str(requests[1].url)


def test_drive_client_rejects_http_schema_channel_and_auth_failures() -> None:
    responses = iter(
        [
            httpx.Response(500, json={"error": "down"}),
            httpx.Response(200, json={"wrong": "shape"}),
            httpx.Response(
                200,
                json={
                    "id": "different-channel",
                    "resourceId": "resource",
                    "resourceUri": "https://drive.test",
                },
            ),
        ]
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return next(responses)

    async def scenario() -> None:
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = GoogleDriveChangesClient(http, "https://drive.test/v3")
        with pytest.raises(DriveChangeError, match="status 500"):
            await client.get_start_page_token("access")
        with pytest.raises(DriveChangeError, match="invalid"):
            await client.get_start_page_token("access")
        with pytest.raises(DriveChangeError, match="different watch channel"):
            await client.watch_changes(
                "access",
                "page",
                "channel",
                "https://app.test/hook",
                "token",
                NOW + timedelta(days=6),
            )
        with pytest.raises(ValueError, match="access token"):
            await client.get_start_page_token("")
        await http.aclose()

    asyncio.run(scenario())
