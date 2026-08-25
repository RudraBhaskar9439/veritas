from datetime import UTC, datetime
from typing import Protocol

from veritas_runtime.changes.drive import DriveChangesPort
from veritas_runtime.changes.extractor import EvidenceExtractor
from veritas_runtime.changes.models import (
    DriveChange,
    DriveWatchStream,
    EvidenceCapture,
    EvidenceSnapshot,
    EvidenceSourceRegistration,
)
from veritas_runtime.changes.snapshots import ImmutableSnapshotService, SnapshotIntegrityError


class ChangeCursorConflict(RuntimeError):
    """Another worker advanced the Drive cursor; this attempt must be retried."""


class InvalidChangePage(RuntimeError):
    """A Drive change page did not provide a usable continuation cursor."""


class ChangeProcessingRepository(Protocol):
    async def get_stream(self, stream_id: str) -> DriveWatchStream | None: ...

    async def registrations_for_resources(
        self,
        subject: str,
        resource_ids: frozenset[str],
    ) -> tuple[EvidenceSourceRegistration, ...]: ...

    async def latest_snapshot(
        self,
        subject: str,
        packet_id: str,
        source_id: str,
    ) -> EvidenceSnapshot | None: ...

    async def operation_snapshots(
        self,
        operation_id: str,
        subject: str,
        stream_id: str,
    ) -> tuple[EvidenceSnapshot, ...] | None: ...

    async def commit_snapshots_and_cursor(
        self,
        stream_id: str,
        expected_page_token: str,
        next_page_token: str,
        snapshots: tuple[EvidenceSnapshot, ...],
        now: datetime,
        *,
        operation_id: str,
        batch_complete: bool,
    ) -> None: ...


class DriveChangeProcessor:
    def __init__(
        self,
        drive: DriveChangesPort,
        extractor: EvidenceExtractor,
        snapshots: ImmutableSnapshotService,
        repository: ChangeProcessingRepository,
    ) -> None:
        self._drive = drive
        self._extractor = extractor
        self._snapshots = snapshots
        self._repository = repository

    async def process_stream(
        self,
        stream_id: str,
        access_token: str,
        operation_id: str,
        now: datetime | None = None,
        *,
        expected_subject: str | None = None,
    ) -> tuple[EvidenceSnapshot, ...]:
        current_time = (now or datetime.now(UTC)).astimezone(UTC)
        stream = await self._repository.get_stream(stream_id)
        if stream is None:
            raise LookupError("Drive watch stream was not found")
        if expected_subject is not None and stream.subject != expected_subject:
            raise PermissionError("Drive watch stream belongs to another subject")
        replay = await self._repository.operation_snapshots(
            operation_id,
            stream.subject,
            stream.stream_id,
        )
        if replay is not None:
            return replay
        cursor = stream.page_token
        while True:
            page = await self._drive.list_changes(access_token, cursor)
            changes = _latest_change_per_resource(page.changes)
            registrations = await self._repository.registrations_for_resources(
                stream.subject,
                frozenset(change.file_id for change in changes),
            )
            changes_by_resource = {change.file_id: change for change in changes}
            page_snapshots: list[EvidenceSnapshot] = []
            for registration in registrations:
                change = changes_by_resource[registration.resource_id]
                capture = (
                    _deleted_capture(registration, change)
                    if change.removed
                    else await self._extractor.extract(access_token, registration)
                )
                previous = await self._repository.latest_snapshot(
                    registration.subject,
                    registration.packet_id,
                    registration.source_id,
                )
                result = await self._snapshots.capture(capture, previous, current_time)
                page_snapshots.append(result.snapshot)

            next_cursor = page.next_page_token or page.new_start_page_token
            if next_cursor is None:
                raise InvalidChangePage("Drive change page omitted its continuation cursor")
            if next_cursor == cursor and changes:
                raise InvalidChangePage("Drive change page did not advance its cursor")
            await self._repository.commit_snapshots_and_cursor(
                stream.stream_id,
                cursor,
                next_cursor,
                tuple(page_snapshots),
                current_time,
                operation_id=operation_id,
                batch_complete=page.next_page_token is None,
            )
            cursor = next_cursor
            if page.next_page_token is None:
                completed = await self._repository.operation_snapshots(
                    operation_id,
                    stream.subject,
                    stream.stream_id,
                )
                if completed is None:
                    raise SnapshotIntegrityError("Completed Drive batch could not be replayed")
                return completed


def _latest_change_per_resource(changes: tuple[DriveChange, ...]) -> tuple[DriveChange, ...]:
    latest: dict[str, DriveChange] = {}
    for change in changes:
        latest[change.file_id] = change
    return tuple(latest.values())


def _deleted_capture(
    registration: EvidenceSourceRegistration,
    change: DriveChange,
) -> EvidenceCapture:
    return EvidenceCapture(
        subject=registration.subject,
        packet_id=registration.packet_id,
        source_id=registration.source_id,
        resource_id=registration.resource_id,
        workspace_version=f"removed:{change.change_id}",
        mime_type="application/vnd.google-apps.unknown",
        evidence={registration.anchor: {"deleted": True}},
    )
