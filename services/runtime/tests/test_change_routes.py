from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from change_support import MemoryWatchRepository
from veritas_runtime.changes.models import DriveWatchChannel, WatchChannelState
from veritas_runtime.changes.routes import create_drive_webhook_router
from veritas_runtime.changes.service import DriveNotificationReceiver
from veritas_runtime.changes.tokens import ChannelTokenCodec

NOW = datetime.now(UTC)


def _app(receiver: DriveNotificationReceiver | None) -> FastAPI:
    app = FastAPI()
    app.include_router(create_drive_webhook_router(receiver))
    return app


def _headers(token: str | None = None) -> dict[str, str]:
    headers = {
        "X-Goog-Channel-ID": "channel-1",
        "X-Goog-Message-Number": "2",
        "X-Goog-Resource-ID": "resource-1",
        "X-Goog-Resource-State": "change",
        "X-Goog-Resource-URI": "https://drive.test/changes",
        "X-Goog-Changed": "content, permissions",
    }
    if token is not None:
        headers["X-Goog-Channel-Token"] = token
    return headers


def test_drive_webhook_route_fails_closed_when_unconfigured_or_unsigned() -> None:
    client = TestClient(_app(None))
    assert client.get("/api/v1/integrations/google-drive/capabilities").json() == {
        "acceptingDriveNotifications": False
    }
    assert (
        client.post(
            "/api/v1/integrations/google-drive/notifications", headers=_headers()
        ).status_code
        == 503
    )

    repository = MemoryWatchRepository()
    codec = ChannelTokenCodec(bytes(range(32)))
    configured = TestClient(_app(DriveNotificationReceiver(repository, codec)))
    assert (
        configured.post(
            "/api/v1/integrations/google-drive/notifications", headers=_headers()
        ).status_code
        == 401
    )


def test_drive_webhook_route_accepts_once_and_rejects_bad_token() -> None:
    repository = MemoryWatchRepository()
    codec = ChannelTokenCodec(bytes(range(32)))
    channel = DriveWatchChannel(
        channel_id="channel-1",
        stream_id="stream-1",
        state=WatchChannelState.ACTIVE,
        google_resource_id="resource-1",
        expiration=NOW + timedelta(days=6),
        created_at=NOW,
        updated_at=NOW,
    )
    repository.channels[channel.channel_id] = channel
    token = codec.issue(channel.channel_id, channel.stream_id, channel.expiration)
    client = TestClient(_app(DriveNotificationReceiver(repository, codec)))

    accepted = client.post(
        "/api/v1/integrations/google-drive/notifications", headers=_headers(token)
    )
    assert accepted.status_code == 204
    assert repository.outbox[0].changed == ("content", "permissions")
    assert (
        client.post(
            "/api/v1/integrations/google-drive/notifications", headers=_headers(token)
        ).status_code
        == 204
    )
    assert len(repository.outbox) == 1
    assert (
        client.post(
            "/api/v1/integrations/google-drive/notifications", headers=_headers("invalid")
        ).status_code
        == 401
    )
