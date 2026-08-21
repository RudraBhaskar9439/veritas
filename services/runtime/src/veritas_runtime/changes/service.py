from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlsplit
from uuid import uuid4

from veritas_runtime.changes.drive import DriveChangesPort
from veritas_runtime.changes.models import (
    DriveNotification,
    DriveWatchChannel,
    DriveWatchStream,
    NotificationDisposition,
    WatchChannelState,
)
from veritas_runtime.changes.tokens import ChannelTokenCodec

CHANNEL_LIFETIME = timedelta(days=6)
RENEWAL_WINDOW = timedelta(hours=24)
KNOWN_RESOURCE_STATES = frozenset({"sync", "add", "remove", "update", "trash", "untrash", "change"})


class UnknownWatchChannel(LookupError):
    """A webhook referenced a channel that Veritas did not provision."""


class WatchChannelMismatch(ValueError):
    """A webhook resource does not match the provisioned channel."""


class WatchLifecycleRepository(Protocol):
    async def get_stream_by_subject(self, subject: str) -> DriveWatchStream | None: ...

    async def get_stream(self, stream_id: str) -> DriveWatchStream | None: ...

    async def get_channel(self, channel_id: str) -> DriveWatchChannel | None: ...

    async def current_channel_for_stream(self, stream_id: str) -> DriveWatchChannel | None: ...

    async def get_or_create_stream(
        self,
        subject: str,
        page_token: str,
        now: datetime,
    ) -> DriveWatchStream: ...

    async def reserve_channel(self, channel: DriveWatchChannel) -> None: ...

    async def activate_channel(
        self,
        channel_id: str,
        google_resource_id: str,
        expiration: datetime,
        now: datetime,
    ) -> DriveWatchChannel: ...

    async def fail_channel(self, channel_id: str, now: datetime) -> None: ...

    async def active_channels_expiring_before(
        self, deadline: datetime
    ) -> tuple[DriveWatchChannel, ...]: ...

    async def mark_replaced(
        self,
        old_channel_id: str,
        new_channel_id: str,
        now: datetime,
    ) -> None: ...

    async def synced_replacements(self) -> tuple[DriveWatchChannel, ...]: ...

    async def mark_stopped(self, channel_id: str, now: datetime) -> None: ...


class NotificationRepository(Protocol):
    async def get_channel(self, channel_id: str) -> DriveWatchChannel | None: ...

    async def record_notification(
        self,
        notification: DriveNotification,
        enqueue: bool,
    ) -> bool: ...

    async def mark_synced(
        self,
        channel_id: str,
        google_resource_id: str,
        now: datetime,
    ) -> None: ...


AccessTokenProvider = Callable[[str], Awaitable[str]]
ChannelIdFactory = Callable[[], str]


class DriveWatchCoordinator:
    def __init__(
        self,
        drive: DriveChangesPort,
        repository: WatchLifecycleRepository,
        tokens: ChannelTokenCodec,
        channel_ids: ChannelIdFactory | None = None,
    ) -> None:
        self._drive = drive
        self._repository = repository
        self._tokens = tokens
        self._channel_ids = channel_ids or (lambda: str(uuid4()))

    async def start(
        self,
        subject: str,
        access_token: str,
        webhook_url: str,
        now: datetime | None = None,
    ) -> DriveWatchChannel:
        current_time = (now or datetime.now(UTC)).astimezone(UTC)
        stream = await self._repository.get_stream_by_subject(subject)
        if stream is None:
            page_token = await self._drive.get_start_page_token(access_token)
            stream = await self._repository.get_or_create_stream(subject, page_token, current_time)
        current_channel = await self._repository.current_channel_for_stream(stream.stream_id)
        if current_channel is not None:
            return current_channel
        return await self._provision(
            stream,
            access_token,
            webhook_url,
            current_time,
            replaces_channel_id=None,
        )

    async def renew_due(
        self,
        access_token_for: AccessTokenProvider,
        webhook_url: str,
        now: datetime | None = None,
    ) -> tuple[DriveWatchChannel, ...]:
        current_time = (now or datetime.now(UTC)).astimezone(UTC)
        due = await self._repository.active_channels_expiring_before(current_time + RENEWAL_WINDOW)
        renewed: list[DriveWatchChannel] = []
        for old_channel in due:
            stream = await self._repository.get_stream(old_channel.stream_id)
            if stream is None:
                raise UnknownWatchChannel("Watch stream disappeared during renewal")
            access_token = await access_token_for(stream.subject)
            replacement = await self._provision(
                stream,
                access_token,
                webhook_url,
                current_time,
                replaces_channel_id=old_channel.channel_id,
            )
            await self._repository.mark_replaced(
                old_channel.channel_id, replacement.channel_id, current_time
            )
            renewed.append(replacement)
        return tuple(renewed)

    async def retire_replaced(
        self,
        access_token_for: AccessTokenProvider,
        now: datetime | None = None,
    ) -> tuple[str, ...]:
        current_time = (now or datetime.now(UTC)).astimezone(UTC)
        retired: list[str] = []
        for replacement in await self._repository.synced_replacements():
            old_id = replacement.replaces_channel_id
            if old_id is None:
                continue
            old_channel = await self._repository.get_channel(old_id)
            if old_channel is None or old_channel.google_resource_id is None:
                raise UnknownWatchChannel("Replaced channel is missing its Drive resource ID")
            stream = await self._repository.get_stream(replacement.stream_id)
            if stream is None:
                raise UnknownWatchChannel("Watch stream disappeared during retirement")
            await self._drive.stop_channel(
                await access_token_for(stream.subject),
                old_id,
                old_channel.google_resource_id,
            )
            await self._repository.mark_stopped(old_id, current_time)
            retired.append(old_id)
        return tuple(retired)

    async def _provision(
        self,
        stream: DriveWatchStream,
        access_token: str,
        webhook_url: str,
        now: datetime,
        replaces_channel_id: str | None,
    ) -> DriveWatchChannel:
        _require_https_webhook(webhook_url)
        requested_expiration = now + CHANNEL_LIFETIME
        channel = DriveWatchChannel(
            channel_id=self._channel_ids(),
            stream_id=stream.stream_id,
            state=WatchChannelState.PROVISIONING,
            expiration=requested_expiration,
            replaces_channel_id=replaces_channel_id,
            created_at=now,
            updated_at=now,
        )
        await self._repository.reserve_channel(channel)
        token = self._tokens.issue(channel.channel_id, stream.stream_id, requested_expiration)
        try:
            lease = await self._drive.watch_changes(
                access_token,
                stream.page_token,
                channel.channel_id,
                webhook_url,
                token,
                requested_expiration,
            )
            return await self._repository.activate_channel(
                channel.channel_id,
                lease.google_resource_id,
                lease.expiration,
                now,
            )
        except Exception:
            await self._repository.fail_channel(channel.channel_id, now)
            raise


class DriveNotificationReceiver:
    def __init__(
        self,
        repository: NotificationRepository,
        tokens: ChannelTokenCodec,
    ) -> None:
        self._repository = repository
        self._tokens = tokens

    async def receive(
        self,
        token: str,
        notification: DriveNotification,
    ) -> NotificationDisposition:
        channel = await self._repository.get_channel(notification.channel_id)
        if channel is None or channel.state in {
            WatchChannelState.STOPPED,
            WatchChannelState.FAILED,
        }:
            raise UnknownWatchChannel("Watch channel is unknown or inactive")
        self._tokens.verify(
            token,
            expected_channel_id=channel.channel_id,
            expected_stream_id=channel.stream_id,
            now=notification.received_at,
        )
        if (
            channel.google_resource_id is not None
            and channel.google_resource_id != notification.google_resource_id
        ):
            raise WatchChannelMismatch("Drive resource ID does not match the channel")

        if notification.resource_state not in KNOWN_RESOURCE_STATES:
            return NotificationDisposition.IGNORED
        enqueue = notification.resource_state != "sync"
        accepted = await self._repository.record_notification(notification, enqueue=enqueue)
        if not accepted:
            return NotificationDisposition.DUPLICATE
        if notification.resource_state == "sync":
            await self._repository.mark_synced(
                notification.channel_id,
                notification.google_resource_id,
                notification.received_at,
            )
            return NotificationDisposition.SYNCED
        return NotificationDisposition.ENQUEUED


def _require_https_webhook(webhook_url: str) -> None:
    parsed = urlsplit(webhook_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Drive webhook URL must be an HTTPS origin without credentials")
