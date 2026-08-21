from collections.abc import Awaitable, Callable
from datetime import datetime

from veritas_runtime.changes.models import (
    DriveChangePage,
    DriveNotification,
    DriveWatchChannel,
    DriveWatchLease,
    DriveWatchStream,
    StoredSnapshotObject,
    WatchChannelState,
)
from veritas_runtime.changes.service import WatchChannelMismatch


class MemoryWatchRepository:
    def __init__(self) -> None:
        self.streams: dict[str, DriveWatchStream] = {}
        self.channels: dict[str, DriveWatchChannel] = {}
        self.notifications: set[tuple[str, int]] = set()
        self.outbox: list[DriveNotification] = []

    async def get_stream_by_subject(self, subject: str) -> DriveWatchStream | None:
        return next((stream for stream in self.streams.values() if stream.subject == subject), None)

    async def get_stream(self, stream_id: str) -> DriveWatchStream | None:
        return self.streams.get(stream_id)

    async def get_or_create_stream(
        self,
        subject: str,
        page_token: str,
        now: datetime,
    ) -> DriveWatchStream:
        existing = await self.get_stream_by_subject(subject)
        if existing is not None:
            return existing
        stream = DriveWatchStream(
            stream_id=f"stream-{subject}",
            subject=subject,
            page_token=page_token,
            created_at=now,
            updated_at=now,
        )
        self.streams[stream.stream_id] = stream
        return stream

    async def reserve_channel(self, channel: DriveWatchChannel) -> None:
        if channel.channel_id in self.channels:
            raise RuntimeError("channel collision")
        self.channels[channel.channel_id] = channel

    async def activate_channel(
        self,
        channel_id: str,
        google_resource_id: str,
        expiration: datetime,
        now: datetime,
    ) -> DriveWatchChannel:
        channel = self.channels[channel_id]
        if (
            channel.google_resource_id is not None
            and channel.google_resource_id != google_resource_id
        ):
            raise WatchChannelMismatch("early resource mismatch")
        active = channel.model_copy(
            update={
                "state": WatchChannelState.ACTIVE,
                "google_resource_id": google_resource_id,
                "expiration": expiration,
                "updated_at": now,
            }
        )
        self.channels[channel_id] = active
        return active

    async def fail_channel(self, channel_id: str, now: datetime) -> None:
        channel = self.channels[channel_id]
        self.channels[channel_id] = channel.model_copy(
            update={"state": WatchChannelState.FAILED, "updated_at": now}
        )

    async def active_channels_expiring_before(
        self, deadline: datetime
    ) -> tuple[DriveWatchChannel, ...]:
        return tuple(
            channel
            for channel in self.channels.values()
            if channel.state == WatchChannelState.ACTIVE and channel.expiration <= deadline
        )

    async def mark_replaced(
        self,
        old_channel_id: str,
        new_channel_id: str,
        now: datetime,
    ) -> None:
        old = self.channels[old_channel_id]
        new = self.channels[new_channel_id]
        if old.state != WatchChannelState.ACTIVE or new.replaces_channel_id != old_channel_id:
            raise WatchChannelMismatch("invalid replacement")
        self.channels[old_channel_id] = old.model_copy(
            update={"state": WatchChannelState.RETIRING, "updated_at": now}
        )

    async def synced_replacements(self) -> tuple[DriveWatchChannel, ...]:
        return tuple(
            channel
            for channel in self.channels.values()
            if channel.state == WatchChannelState.ACTIVE
            and channel.sync_received
            and channel.replaces_channel_id is not None
            and self.channels[channel.replaces_channel_id].state == WatchChannelState.RETIRING
        )

    async def mark_stopped(self, channel_id: str, now: datetime) -> None:
        channel = self.channels[channel_id]
        self.channels[channel_id] = channel.model_copy(
            update={"state": WatchChannelState.STOPPED, "updated_at": now}
        )

    async def get_channel(self, channel_id: str) -> DriveWatchChannel | None:
        return self.channels.get(channel_id)

    async def current_channel_for_stream(self, stream_id: str) -> DriveWatchChannel | None:
        current = [
            channel
            for channel in self.channels.values()
            if channel.stream_id == stream_id
            and channel.state in {WatchChannelState.ACTIVE, WatchChannelState.PROVISIONING}
        ]
        return max(current, key=lambda channel: channel.created_at) if current else None

    async def record_notification(
        self,
        notification: DriveNotification,
        enqueue: bool,
    ) -> bool:
        key = (notification.channel_id, notification.message_number)
        if key in self.notifications:
            return False
        self.notifications.add(key)
        if enqueue:
            self.outbox.append(notification)
        return True

    async def mark_synced(
        self,
        channel_id: str,
        google_resource_id: str,
        now: datetime,
    ) -> None:
        channel = self.channels[channel_id]
        if (
            channel.google_resource_id is not None
            and channel.google_resource_id != google_resource_id
        ):
            raise WatchChannelMismatch("sync resource mismatch")
        self.channels[channel_id] = channel.model_copy(
            update={
                "google_resource_id": google_resource_id,
                "sync_received": True,
                "updated_at": now,
            }
        )


WatchCallback = Callable[[str, str, datetime], Awaitable[None]]


class FakeDriveChanges:
    def __init__(self, on_watch: WatchCallback | None = None) -> None:
        self.start_page_token = "drive-page-1"
        self.watch_calls: list[tuple[str, str, str, str, str, datetime]] = []
        self.stop_calls: list[tuple[str, str, str]] = []
        self.on_watch = on_watch
        self.fail_watch = False
        self.change_page = DriveChangePage(changes=(), new_start_page_token="drive-page-2")

    async def get_start_page_token(self, access_token: str) -> str:
        assert access_token
        return self.start_page_token

    async def watch_changes(
        self,
        access_token: str,
        page_token: str,
        channel_id: str,
        address: str,
        channel_token: str,
        expiration: datetime,
    ) -> DriveWatchLease:
        self.watch_calls.append(
            (access_token, page_token, channel_id, address, channel_token, expiration)
        )
        if self.on_watch is not None:
            await self.on_watch(channel_id, channel_token, expiration)
        if self.fail_watch:
            raise RuntimeError("Drive watch failed")
        return DriveWatchLease(
            channel_id=channel_id,
            google_resource_id=f"resource-{channel_id}",
            resource_uri=f"https://drive.example.test/changes/{channel_id}",
            expiration=expiration,
        )

    async def list_changes(self, access_token: str, page_token: str) -> DriveChangePage:
        assert access_token and page_token
        return self.change_page

    async def stop_channel(
        self,
        access_token: str,
        channel_id: str,
        google_resource_id: str,
    ) -> None:
        self.stop_calls.append((access_token, channel_id, google_resource_id))


class MemorySnapshotObjects:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str, str]] = {}
        self.calls = 0

    async def put_once(
        self,
        object_name: str,
        content: bytes,
        sha256: str,
    ) -> StoredSnapshotObject:
        self.calls += 1
        existing = self.objects.get(object_name)
        if existing is not None and existing[:2] != (content, sha256):
            raise RuntimeError("content-address collision")
        generation = existing[2] if existing is not None else str(len(self.objects) + 1)
        self.objects[object_name] = (content, sha256, generation)
        return StoredSnapshotObject(
            bucket="test-snapshots",
            object_name=object_name,
            generation=generation,
        )
