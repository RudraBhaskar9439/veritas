from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    and_,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from sqlalchemy.sql.base import Executable

from veritas_runtime.auth.database import metadata
from veritas_runtime.changes.models import (
    DeltaKind,
    DriveNotification,
    DriveNotificationOutboxEvent,
    DriveWatchChannel,
    DriveWatchStream,
    EvidenceSnapshot,
    EvidenceSourceRegistration,
    StoredSnapshotObject,
    WatchChannelState,
)
from veritas_runtime.changes.processor import ChangeCursorConflict
from veritas_runtime.changes.service import WatchChannelMismatch
from veritas_runtime.changes.snapshots import SnapshotIntegrityError
from veritas_runtime.packets.models import SourceKind

drive_watch_streams = Table(
    "drive_watch_streams",
    metadata,
    Column("stream_id", String(255), primary_key=True),
    Column("subject", String(255), nullable=False, unique=True),
    Column("page_token", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

drive_watch_channels = Table(
    "drive_watch_channels",
    metadata,
    Column("channel_id", String(64), primary_key=True),
    Column(
        "stream_id",
        String(255),
        ForeignKey("drive_watch_streams.stream_id"),
        nullable=False,
    ),
    Column("state", String(32), nullable=False),
    Column("google_resource_id", String(255), nullable=True),
    Column("expiration", DateTime(timezone=True), nullable=False),
    Column("replaces_channel_id", String(64), nullable=True),
    Column("sync_received", Boolean, nullable=False, default=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
Index(
    "drive_watch_channels_renewal_idx",
    drive_watch_channels.c.state,
    drive_watch_channels.c.expiration,
)

drive_notifications = Table(
    "drive_notifications",
    metadata,
    Column(
        "channel_id",
        String(64),
        ForeignKey("drive_watch_channels.channel_id"),
        primary_key=True,
    ),
    Column("message_number", BigInteger, primary_key=True),
    Column("google_resource_id", String(255), nullable=False),
    Column("resource_state", String(64), nullable=False),
    Column("resource_uri", Text, nullable=False),
    Column("changed", Text, nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
)

drive_notification_outbox = Table(
    "drive_notification_outbox",
    metadata,
    Column("event_id", String(255), primary_key=True),
    Column("channel_id", String(64), nullable=False),
    Column("message_number", BigInteger, nullable=False),
    Column("status", String(32), nullable=False),
    Column("attempts", Integer, nullable=False, default=0),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("drive_notification_outbox_pending_idx", drive_notification_outbox.c.status)

registered_evidence_sources = Table(
    "registered_evidence_sources",
    metadata,
    Column("subject", String(255), primary_key=True),
    Column("packet_id", String(255), primary_key=True),
    Column("source_id", String(255), primary_key=True),
    Column("kind", String(32), nullable=False),
    Column("resource_id", String(255), nullable=False),
    Column("anchor", Text, nullable=False),
    Column("registered_at", DateTime(timezone=True), nullable=False),
)
Index(
    "registered_evidence_sources_resource_idx",
    registered_evidence_sources.c.subject,
    registered_evidence_sources.c.resource_id,
)

evidence_snapshots = Table(
    "evidence_snapshots",
    metadata,
    Column("snapshot_id", String(255), primary_key=True),
    Column("subject", String(255), nullable=False),
    Column("packet_id", String(255), nullable=False),
    Column("source_id", String(255), nullable=False),
    Column("resource_id", String(255), nullable=False),
    Column("workspace_version", String(255), nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column("semantic_hash", String(64), nullable=False),
    Column("bucket", String(255), nullable=False),
    Column("object_name", Text, nullable=False),
    Column("object_generation", String(64), nullable=False),
    Column("delta_kind", String(32), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "subject",
        "packet_id",
        "source_id",
        "workspace_version",
        name="evidence_snapshots_source_version_uq",
    ),
    UniqueConstraint(
        "subject",
        "packet_id",
        "source_id",
        "content_hash",
        name="evidence_snapshots_source_content_uq",
    ),
)
Index(
    "evidence_snapshots_source_created_idx",
    evidence_snapshots.c.subject,
    evidence_snapshots.c.packet_id,
    evidence_snapshots.c.source_id,
    evidence_snapshots.c.created_at,
)


class SqlWatchRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get_stream_by_subject(self, subject: str) -> DriveWatchStream | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        select(drive_watch_streams).where(drive_watch_streams.c.subject == subject)
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _stream(row) if row is not None else None

    async def get_stream(self, stream_id: str) -> DriveWatchStream | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        select(drive_watch_streams).where(
                            drive_watch_streams.c.stream_id == stream_id
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _stream(row) if row is not None else None

    async def get_or_create_stream(
        self,
        subject: str,
        page_token: str,
        now: datetime,
    ) -> DriveWatchStream:
        stream_id = f"drive-stream-{uuid5(NAMESPACE_URL, subject)}"
        values = {
            "stream_id": stream_id,
            "subject": subject,
            "page_token": page_token,
            "created_at": now,
            "updated_at": now,
        }
        async with self._engine.begin() as connection:
            await connection.execute(
                _insert_do_nothing(
                    connection,
                    drive_watch_streams,
                    values,
                    (drive_watch_streams.c.subject,),
                )
            )
            row = (
                (
                    await connection.execute(
                        select(drive_watch_streams).where(drive_watch_streams.c.subject == subject)
                    )
                )
                .mappings()
                .one()
            )
        return _stream(row)

    async def reserve_channel(self, channel: DriveWatchChannel) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                insert(drive_watch_channels).values(
                    channel_id=channel.channel_id,
                    stream_id=channel.stream_id,
                    state=channel.state.value,
                    google_resource_id=channel.google_resource_id,
                    expiration=channel.expiration,
                    replaces_channel_id=channel.replaces_channel_id,
                    sync_received=channel.sync_received,
                    created_at=channel.created_at,
                    updated_at=channel.updated_at,
                )
            )

    async def activate_channel(
        self,
        channel_id: str,
        google_resource_id: str,
        expiration: datetime,
        now: datetime,
    ) -> DriveWatchChannel:
        async with self._engine.begin() as connection:
            row = await _channel_row(connection, channel_id)
            if row is None:
                raise LookupError("Reserved watch channel is missing")
            early_resource_id = row["google_resource_id"]
            if early_resource_id is not None and early_resource_id != google_resource_id:
                raise WatchChannelMismatch("Early sync resource ID does not match watch response")
            await connection.execute(
                update(drive_watch_channels)
                .where(drive_watch_channels.c.channel_id == channel_id)
                .values(
                    state=WatchChannelState.ACTIVE.value,
                    google_resource_id=google_resource_id,
                    expiration=expiration,
                    updated_at=now,
                )
            )
            activated = await _channel_row(connection, channel_id)
        if activated is None:
            raise LookupError("Activated watch channel is missing")
        return _channel(activated)

    async def fail_channel(self, channel_id: str, now: datetime) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                update(drive_watch_channels)
                .where(drive_watch_channels.c.channel_id == channel_id)
                .values(state=WatchChannelState.FAILED.value, updated_at=now)
            )

    async def active_channels_expiring_before(
        self, deadline: datetime
    ) -> tuple[DriveWatchChannel, ...]:
        async with self._engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        select(drive_watch_channels).where(
                            drive_watch_channels.c.state == WatchChannelState.ACTIVE.value,
                            drive_watch_channels.c.expiration <= deadline,
                        )
                    )
                )
                .mappings()
                .all()
            )
        return tuple(_channel(row) for row in rows)

    async def mark_replaced(
        self,
        old_channel_id: str,
        new_channel_id: str,
        now: datetime,
    ) -> None:
        async with self._engine.begin() as connection:
            replacement = await _channel_row(connection, new_channel_id)
            if replacement is None or replacement["replaces_channel_id"] != old_channel_id:
                raise WatchChannelMismatch("Replacement channel binding is invalid")
            result = await connection.execute(
                update(drive_watch_channels)
                .where(
                    drive_watch_channels.c.channel_id == old_channel_id,
                    drive_watch_channels.c.state == WatchChannelState.ACTIVE.value,
                )
                .values(state=WatchChannelState.RETIRING.value, updated_at=now)
            )
            if result.rowcount != 1:
                raise WatchChannelMismatch("Old watch channel is not active")

    async def synced_replacements(self) -> tuple[DriveWatchChannel, ...]:
        old = drive_watch_channels.alias("old_channel")
        async with self._engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        select(drive_watch_channels)
                        .join(
                            old,
                            and_(
                                drive_watch_channels.c.replaces_channel_id == old.c.channel_id,
                                old.c.state == WatchChannelState.RETIRING.value,
                            ),
                        )
                        .where(
                            drive_watch_channels.c.state == WatchChannelState.ACTIVE.value,
                            drive_watch_channels.c.sync_received.is_(True),
                        )
                    )
                )
                .mappings()
                .all()
            )
        return tuple(_channel(row) for row in rows)

    async def mark_stopped(self, channel_id: str, now: datetime) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                update(drive_watch_channels)
                .where(drive_watch_channels.c.channel_id == channel_id)
                .values(state=WatchChannelState.STOPPED.value, updated_at=now)
            )

    async def get_channel(self, channel_id: str) -> DriveWatchChannel | None:
        async with self._engine.connect() as connection:
            row = await _channel_row(connection, channel_id)
        return _channel(row) if row is not None else None

    async def current_channel_for_stream(self, stream_id: str) -> DriveWatchChannel | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        select(drive_watch_channels)
                        .where(
                            drive_watch_channels.c.stream_id == stream_id,
                            drive_watch_channels.c.state.in_(
                                (
                                    WatchChannelState.ACTIVE.value,
                                    WatchChannelState.PROVISIONING.value,
                                )
                            ),
                        )
                        .order_by(drive_watch_channels.c.created_at.desc())
                        .limit(1)
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _channel(row) if row is not None else None

    async def record_notification(
        self,
        notification: DriveNotification,
        enqueue: bool,
    ) -> bool:
        values = {
            "channel_id": notification.channel_id,
            "message_number": notification.message_number,
            "google_resource_id": notification.google_resource_id,
            "resource_state": notification.resource_state,
            "resource_uri": notification.resource_uri,
            "changed": "\n".join(notification.changed),
            "received_at": notification.received_at,
        }
        async with self._engine.begin() as connection:
            result = await connection.execute(
                _insert_do_nothing(
                    connection,
                    drive_notifications,
                    values,
                    (
                        drive_notifications.c.channel_id,
                        drive_notifications.c.message_number,
                    ),
                )
            )
            if result.rowcount != 1:
                return False
            if enqueue:
                await connection.execute(
                    insert(drive_notification_outbox).values(
                        event_id=(
                            f"drive-notification:{notification.channel_id}:"
                            f"{notification.message_number}"
                        ),
                        channel_id=notification.channel_id,
                        message_number=notification.message_number,
                        status="pending",
                        attempts=0,
                        created_at=notification.received_at,
                    )
                )
        return True

    async def mark_synced(
        self,
        channel_id: str,
        google_resource_id: str,
        now: datetime,
    ) -> None:
        async with self._engine.begin() as connection:
            row = await _channel_row(connection, channel_id)
            if row is None:
                raise LookupError("Watch channel disappeared during sync")
            current_resource_id = row["google_resource_id"]
            if current_resource_id is not None and current_resource_id != google_resource_id:
                raise WatchChannelMismatch("Sync resource ID does not match watch channel")
            await connection.execute(
                update(drive_watch_channels)
                .where(drive_watch_channels.c.channel_id == channel_id)
                .values(
                    google_resource_id=google_resource_id,
                    sync_received=True,
                    updated_at=now,
                )
            )

    async def pending_notification_events(
        self,
        limit: int = 100,
    ) -> tuple[DriveNotificationOutboxEvent, ...]:
        if limit < 1 or limit > 500:
            raise ValueError("Outbox batch size must be between 1 and 500")
        async with self._engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        select(
                            drive_notification_outbox,
                            drive_watch_channels.c.stream_id,
                            drive_watch_streams.c.subject,
                        )
                        .join(
                            drive_watch_channels,
                            drive_watch_channels.c.channel_id
                            == drive_notification_outbox.c.channel_id,
                        )
                        .join(
                            drive_watch_streams,
                            drive_watch_streams.c.stream_id == drive_watch_channels.c.stream_id,
                        )
                        .where(drive_notification_outbox.c.status == "pending")
                        .order_by(drive_notification_outbox.c.created_at)
                        .limit(limit)
                    )
                )
                .mappings()
                .all()
            )
        return tuple(
            DriveNotificationOutboxEvent(
                event_id=str(row["event_id"]),
                stream_id=str(row["stream_id"]),
                subject=str(row["subject"]),
                channel_id=str(row["channel_id"]),
                message_number=int(row["message_number"]),
                attempts=int(row["attempts"]),
                created_at=_utc_datetime(row["created_at"]),
            )
            for row in rows
        )

    async def mark_notification_dispatched(self, event_id: str) -> bool:
        async with self._engine.begin() as connection:
            result = await connection.execute(
                update(drive_notification_outbox)
                .where(
                    drive_notification_outbox.c.event_id == event_id,
                    drive_notification_outbox.c.status == "pending",
                )
                .values(
                    status="published",
                    attempts=drive_notification_outbox.c.attempts + 1,
                )
            )
        return result.rowcount == 1

    async def register_sources(
        self,
        registrations: tuple[EvidenceSourceRegistration, ...],
    ) -> None:
        async with self._engine.begin() as connection:
            for registration in registrations:
                existing = (
                    (
                        await connection.execute(
                            select(registered_evidence_sources).where(
                                registered_evidence_sources.c.subject == registration.subject,
                                registered_evidence_sources.c.packet_id == registration.packet_id,
                                registered_evidence_sources.c.source_id == registration.source_id,
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    if (
                        existing["kind"] != registration.kind.value
                        or existing["resource_id"] != registration.resource_id
                        or existing["anchor"] != registration.anchor
                    ):
                        raise SnapshotIntegrityError(
                            "Registered evidence identity cannot be rebound"
                        )
                    continue
                await connection.execute(
                    insert(registered_evidence_sources).values(
                        subject=registration.subject,
                        packet_id=registration.packet_id,
                        source_id=registration.source_id,
                        kind=registration.kind.value,
                        resource_id=registration.resource_id,
                        anchor=registration.anchor,
                        registered_at=registration.registered_at,
                    )
                )

    async def registrations_for_resources(
        self,
        subject: str,
        resource_ids: frozenset[str],
    ) -> tuple[EvidenceSourceRegistration, ...]:
        if not resource_ids:
            return ()
        async with self._engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        select(registered_evidence_sources).where(
                            registered_evidence_sources.c.subject == subject,
                            registered_evidence_sources.c.resource_id.in_(resource_ids),
                        )
                    )
                )
                .mappings()
                .all()
            )
        return tuple(
            EvidenceSourceRegistration(
                subject=row["subject"],
                packet_id=row["packet_id"],
                source_id=row["source_id"],
                kind=SourceKind(row["kind"]),
                resource_id=row["resource_id"],
                anchor=row["anchor"],
                registered_at=_utc_datetime(row["registered_at"]),
            )
            for row in rows
        )

    async def latest_snapshot(
        self,
        subject: str,
        packet_id: str,
        source_id: str,
    ) -> EvidenceSnapshot | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        select(evidence_snapshots)
                        .where(
                            evidence_snapshots.c.subject == subject,
                            evidence_snapshots.c.packet_id == packet_id,
                            evidence_snapshots.c.source_id == source_id,
                        )
                        .order_by(evidence_snapshots.c.created_at.desc())
                        .limit(1)
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _snapshot(row) if row is not None else None

    async def commit_snapshots_and_cursor(
        self,
        stream_id: str,
        expected_page_token: str,
        next_page_token: str,
        snapshots: tuple[EvidenceSnapshot, ...],
        now: datetime,
    ) -> None:
        async with self._engine.begin() as connection:
            if self._engine.dialect.name == "postgresql":
                await connection.execute(
                    select(func.pg_advisory_xact_lock(func.hashtext(stream_id)))
                )
            stream = (
                (
                    await connection.execute(
                        select(drive_watch_streams).where(
                            drive_watch_streams.c.stream_id == stream_id
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if stream is None:
                raise LookupError("Drive watch stream was not found")
            if stream["page_token"] != expected_page_token:
                raise ChangeCursorConflict("Drive cursor was advanced by another worker")

            for snapshot in snapshots:
                existing = (
                    (
                        await connection.execute(
                            select(evidence_snapshots).where(
                                evidence_snapshots.c.subject == snapshot.subject,
                                evidence_snapshots.c.packet_id == snapshot.packet_id,
                                evidence_snapshots.c.source_id == snapshot.source_id,
                                (
                                    evidence_snapshots.c.workspace_version
                                    == snapshot.workspace_version
                                )
                                | (evidence_snapshots.c.content_hash == snapshot.content_hash),
                            )
                        )
                    )
                    .mappings()
                    .first()
                )
                if existing is not None:
                    if (
                        existing["content_hash"] != snapshot.content_hash
                        or existing["semantic_hash"] != snapshot.semantic_hash
                        or existing["object_name"] != snapshot.storage.object_name
                        or existing["object_generation"] != snapshot.storage.generation
                    ):
                        raise SnapshotIntegrityError(
                            "Persisted snapshot identity conflicts with immutable content"
                        )
                    continue
                await connection.execute(
                    insert(evidence_snapshots).values(
                        snapshot_id=snapshot.snapshot_id,
                        subject=snapshot.subject,
                        packet_id=snapshot.packet_id,
                        source_id=snapshot.source_id,
                        resource_id=snapshot.resource_id,
                        workspace_version=snapshot.workspace_version,
                        content_hash=snapshot.content_hash,
                        semantic_hash=snapshot.semantic_hash,
                        bucket=snapshot.storage.bucket,
                        object_name=snapshot.storage.object_name,
                        object_generation=snapshot.storage.generation,
                        delta_kind=snapshot.delta_kind.value,
                        created_at=snapshot.created_at,
                    )
                )
            result = await connection.execute(
                update(drive_watch_streams)
                .where(
                    drive_watch_streams.c.stream_id == stream_id,
                    drive_watch_streams.c.page_token == expected_page_token,
                )
                .values(page_token=next_page_token, updated_at=now)
            )
            if result.rowcount != 1:
                raise ChangeCursorConflict("Drive cursor was advanced by another worker")


async def _channel_row(
    connection: AsyncConnection,
    channel_id: str,
) -> RowMapping | None:
    return (
        (
            await connection.execute(
                select(drive_watch_channels).where(drive_watch_channels.c.channel_id == channel_id)
            )
        )
        .mappings()
        .one_or_none()
    )


def _stream(row: RowMapping) -> DriveWatchStream:
    return DriveWatchStream(
        stream_id=row["stream_id"],
        subject=row["subject"],
        page_token=row["page_token"],
        created_at=_utc_datetime(row["created_at"]),
        updated_at=_utc_datetime(row["updated_at"]),
    )


def _channel(row: RowMapping) -> DriveWatchChannel:
    return DriveWatchChannel(
        channel_id=row["channel_id"],
        stream_id=row["stream_id"],
        state=WatchChannelState(row["state"]),
        google_resource_id=row["google_resource_id"],
        expiration=_utc_datetime(row["expiration"]),
        replaces_channel_id=row["replaces_channel_id"],
        sync_received=row["sync_received"],
        created_at=_utc_datetime(row["created_at"]),
        updated_at=_utc_datetime(row["updated_at"]),
    )


def _snapshot(row: RowMapping) -> EvidenceSnapshot:
    return EvidenceSnapshot(
        snapshot_id=row["snapshot_id"],
        subject=row["subject"],
        packet_id=row["packet_id"],
        source_id=row["source_id"],
        resource_id=row["resource_id"],
        workspace_version=row["workspace_version"],
        content_hash=row["content_hash"],
        semantic_hash=row["semantic_hash"],
        storage=StoredSnapshotObject(
            bucket=row["bucket"],
            object_name=row["object_name"],
            generation=row["object_generation"],
        ),
        delta_kind=DeltaKind(row["delta_kind"]),
        created_at=_utc_datetime(row["created_at"]),
    )


def _utc_datetime(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _insert_do_nothing(
    connection: AsyncConnection,
    table: Table,
    values: dict[str, object],
    index_elements: tuple[Column[object], ...],
) -> Executable:
    if connection.dialect.name == "sqlite":
        sqlite_statement = sqlite_insert(table).values(**values)
        return sqlite_statement.on_conflict_do_nothing(index_elements=index_elements)
    postgres_statement = postgres_insert(table).values(**values)
    return postgres_statement.on_conflict_do_nothing(index_elements=index_elements)
