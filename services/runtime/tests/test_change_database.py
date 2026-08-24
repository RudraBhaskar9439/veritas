import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from change_support import FakeDriveChanges, MemorySnapshotObjects
from veritas_runtime.auth.database import metadata
from veritas_runtime.changes.database import (
    SqlWatchRepository,
    drive_notification_outbox,
    drive_notifications,
)
from veritas_runtime.changes.models import (
    DriveNotification,
    EvidenceCapture,
    EvidenceSourceRegistration,
    NotificationDisposition,
)
from veritas_runtime.changes.processor import ChangeCursorConflict
from veritas_runtime.changes.service import DriveNotificationReceiver, DriveWatchCoordinator
from veritas_runtime.changes.snapshots import ImmutableSnapshotService, SnapshotIntegrityError
from veritas_runtime.changes.tokens import ChannelTokenCodec
from veritas_runtime.packets.models import SourceKind

NOW = datetime(2026, 8, 21, 1, 0, tzinfo=UTC)


def test_sql_watch_repository_persists_overlap_sync_and_atomic_outbox_dedup() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        repository = SqlWatchRepository(engine)
        codec = ChannelTokenCodec(bytes(range(32)))
        drive = FakeDriveChanges()
        ids = iter(("channel-old", "channel-new"))
        coordinator = DriveWatchCoordinator(drive, repository, codec, lambda: next(ids))
        receiver = DriveNotificationReceiver(repository, codec)

        old = await coordinator.start("subject-1", "access", "https://app.test/drive-hook", NOW)
        old_token = drive.watch_calls[0][4]
        notification = DriveNotification(
            channel_id=old.channel_id,
            message_number=2,
            google_resource_id="resource-channel-old",
            resource_state="change",
            resource_uri="https://drive.test/changes",
            changed=("content",),
            received_at=NOW,
        )
        assert await receiver.receive(old_token, notification) == NotificationDisposition.ENQUEUED
        assert await receiver.receive(old_token, notification) == NotificationDisposition.DUPLICATE

        async with engine.connect() as connection:
            notification_count = await connection.scalar(
                select(func.count()).select_from(drive_notifications)
            )
            outbox_count = await connection.scalar(
                select(func.count()).select_from(drive_notification_outbox)
            )
        assert notification_count == 1
        assert outbox_count == 1
        pending = await repository.pending_notification_events()
        assert len(pending) == 1
        assert pending[0].event_id == f"drive-notification:{old.channel_id}:2"
        assert pending[0].stream_id == old.stream_id
        assert pending[0].subject == "subject-1"
        assert await repository.mark_notification_dispatched(pending[0].event_id) is True
        assert await repository.mark_notification_dispatched(pending[0].event_id) is False
        assert await repository.pending_notification_events() == ()
        with pytest.raises(ValueError, match="batch size"):
            await repository.pending_notification_events(0)

        renewal_time = NOW + timedelta(days=5, hours=1)

        async def token_for(_subject: str) -> str:
            return "access"

        replacement = (
            await coordinator.renew_due(token_for, "https://app.test/drive-hook", renewal_time)
        )[0]
        replacement_token = drive.watch_calls[1][4]
        sync = notification.model_copy(
            update={
                "channel_id": replacement.channel_id,
                "message_number": 1,
                "google_resource_id": "resource-channel-new",
                "resource_state": "sync",
                "received_at": renewal_time,
            }
        )
        assert await receiver.receive(replacement_token, sync) == NotificationDisposition.SYNCED
        assert await coordinator.retire_replaced(token_for, renewal_time) == (old.channel_id,)

        registration = EvidenceSourceRegistration(
            subject="subject-1",
            packet_id="packet-1",
            source_id="source-1",
            kind=SourceKind.GOOGLE_SHEET,
            resource_id="sheet-1",
            anchor="Metrics!B17",
            registered_at=NOW,
        )
        await repository.register_sources((registration,))
        await repository.register_sources((registration,))
        with pytest.raises(SnapshotIntegrityError, match="cannot be rebound"):
            await repository.register_sources(
                (registration.model_copy(update={"resource_id": "other-sheet"}),)
            )
        assert await repository.registrations_for_resources(
            "subject-1", frozenset({"sheet-1"})
        ) == (registration,)
        assert await repository.registrations_for_resources("subject-1", frozenset()) == ()

        capture = EvidenceCapture(
            subject="subject-1",
            packet_id="packet-1",
            source_id="source-1",
            resource_id="sheet-1",
            workspace_version="sheet-v1",
            mime_type="application/vnd.google-apps.spreadsheet",
            evidence={"Metrics!B17": 0.04},
        )
        snapshot = (
            await ImmutableSnapshotService(MemorySnapshotObjects()).capture(capture, None, NOW)
        ).snapshot
        stream = await repository.get_stream(old.stream_id)
        assert stream is not None
        await repository.commit_snapshots_and_cursor(
            stream.stream_id, stream.page_token, "drive-page-2", (snapshot,), NOW
        )
        assert await repository.latest_snapshot("subject-1", "packet-1", "source-1") == snapshot
        with pytest.raises(ChangeCursorConflict, match="another worker"):
            await repository.commit_snapshots_and_cursor(
                stream.stream_id, stream.page_token, "drive-page-3", (snapshot,), NOW
            )
        await engine.dispose()

    asyncio.run(scenario())
