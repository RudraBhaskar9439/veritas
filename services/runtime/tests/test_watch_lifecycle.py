import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from change_support import FakeDriveChanges, MemoryWatchRepository
from veritas_runtime.changes.models import (
    DriveNotification,
    DriveWatchChannel,
    NotificationDisposition,
    WatchChannelState,
)
from veritas_runtime.changes.service import (
    DriveNotificationReceiver,
    DriveWatchCoordinator,
    UnknownWatchChannel,
    WatchChannelMismatch,
)
from veritas_runtime.changes.tokens import ChannelTokenCodec, InvalidChannelToken

NOW = datetime(2026, 8, 21, 1, 0, tzinfo=UTC)


def _notification(
    channel_id: str,
    *,
    message: int = 1,
    state: str = "sync",
    resource_id: str | None = None,
    at: datetime = NOW,
) -> DriveNotification:
    return DriveNotification(
        channel_id=channel_id,
        message_number=message,
        google_resource_id=resource_id or f"resource-{channel_id}",
        resource_state=state,
        resource_uri="https://www.googleapis.com/drive/v3/changes",
        received_at=at,
    )


def test_watch_reservation_handles_sync_before_google_watch_response() -> None:
    repository = MemoryWatchRepository()
    codec = ChannelTokenCodec(bytes(range(32)))
    receiver = DriveNotificationReceiver(repository, codec)

    async def early_sync(channel_id: str, token: str, _expiration: datetime) -> None:
        channel = repository.channels[channel_id]
        assert channel.state == WatchChannelState.PROVISIONING
        disposition = await receiver.receive(token, _notification(channel_id))
        assert disposition == NotificationDisposition.SYNCED

    drive = FakeDriveChanges(on_watch=early_sync)
    coordinator = DriveWatchCoordinator(drive, repository, codec, lambda: "channel-1")

    async def scenario() -> None:
        channel = await coordinator.start(
            "subject-1", "access-token", "https://app.test/drive-hook", NOW
        )
        assert channel.state == WatchChannelState.ACTIVE
        assert channel.sync_received is True
        assert channel.expiration == NOW + timedelta(days=6)
        assert repository.streams[channel.stream_id].page_token == "drive-page-1"
        assert (
            await coordinator.start("subject-1", "access-token", "https://app.test/drive-hook", NOW)
            == channel
        )
        assert len(drive.watch_calls) == 1

    asyncio.run(scenario())


def test_watch_renewal_overlaps_until_replacement_sync_then_stops_old() -> None:
    repository = MemoryWatchRepository()
    codec = ChannelTokenCodec(bytes(range(32)))
    drive = FakeDriveChanges()
    ids = iter(("channel-old", "channel-new"))
    coordinator = DriveWatchCoordinator(drive, repository, codec, lambda: next(ids))
    receiver = DriveNotificationReceiver(repository, codec)

    async def access_token_for(subject: str) -> str:
        assert subject == "subject-1"
        return "access-token"

    async def scenario() -> None:
        old = await coordinator.start(
            "subject-1", "access-token", "https://app.test/drive-hook", NOW
        )
        renewal_time = NOW + timedelta(days=5, hours=1)
        replacements = await coordinator.renew_due(
            access_token_for, "https://app.test/drive-hook", renewal_time
        )
        assert len(replacements) == 1
        replacement = replacements[0]
        assert replacement.replaces_channel_id == old.channel_id
        assert repository.channels[old.channel_id].state == WatchChannelState.RETIRING
        assert await coordinator.retire_replaced(access_token_for, renewal_time) == ()

        replacement_token = drive.watch_calls[1][4]
        assert (
            await receiver.receive(
                replacement_token,
                _notification(replacement.channel_id, at=renewal_time),
            )
            == NotificationDisposition.SYNCED
        )
        assert await coordinator.retire_replaced(access_token_for, renewal_time) == (
            old.channel_id,
        )
        assert repository.channels[old.channel_id].state == WatchChannelState.STOPPED
        assert drive.stop_calls == [("access-token", old.channel_id, f"resource-{old.channel_id}")]

    asyncio.run(scenario())


def test_failed_watch_is_marked_and_never_activated() -> None:
    repository = MemoryWatchRepository()
    codec = ChannelTokenCodec(bytes(range(32)))
    drive = FakeDriveChanges()
    drive.fail_watch = True
    coordinator = DriveWatchCoordinator(drive, repository, codec, lambda: "failed-channel")

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="Drive watch failed"):
            await coordinator.start("subject-1", "access", "https://app.test/drive-hook", NOW)
        assert repository.channels["failed-channel"].state == WatchChannelState.FAILED

    asyncio.run(scenario())


def test_watch_rejects_non_https_or_credentialed_webhook_urls() -> None:
    repository = MemoryWatchRepository()
    codec = ChannelTokenCodec(bytes(range(32)))
    coordinator = DriveWatchCoordinator(FakeDriveChanges(), repository, codec, lambda: "channel-1")

    async def scenario() -> None:
        for invalid in (
            "http://app.test/hook",
            "https://user:password@app.test/hook",
            "not-a-url",
        ):
            with pytest.raises(ValueError, match="HTTPS origin"):
                await coordinator.start("subject-1", "access", invalid, NOW)

    asyncio.run(scenario())


def test_notification_receiver_deduplicates_and_rejects_spoofing() -> None:
    repository = MemoryWatchRepository()
    codec = ChannelTokenCodec(bytes(range(32)))
    channel = DriveWatchChannel(
        channel_id="channel-1",
        stream_id="stream-1",
        state=WatchChannelState.ACTIVE,
        google_resource_id="resource-channel-1",
        expiration=NOW + timedelta(days=6),
        created_at=NOW,
        updated_at=NOW,
    )
    repository.channels[channel.channel_id] = channel
    receiver = DriveNotificationReceiver(repository, codec)
    token = codec.issue(channel.channel_id, channel.stream_id, channel.expiration)

    async def scenario() -> None:
        change = _notification("channel-1", message=2, state="change")
        assert await receiver.receive(token, change) == NotificationDisposition.ENQUEUED
        assert await receiver.receive(token, change) == NotificationDisposition.DUPLICATE
        assert len(repository.outbox) == 1

        unknown_state = _notification("channel-1", message=3, state="future-state")
        assert await receiver.receive(token, unknown_state) == NotificationDisposition.IGNORED
        assert ("channel-1", 3) not in repository.notifications

        with pytest.raises(WatchChannelMismatch, match="resource ID"):
            await receiver.receive(
                token,
                _notification("channel-1", message=4, state="change", resource_id="spoofed"),
            )
        with pytest.raises(InvalidChannelToken):
            await receiver.receive(
                token[:-1] + "x", _notification("channel-1", message=5, state="change")
            )
        with pytest.raises(UnknownWatchChannel):
            await receiver.receive(token, _notification("unknown", message=6, state="change"))

    asyncio.run(scenario())
