import asyncio
from datetime import UTC, datetime

import pytest

from change_support import FakeDriveChanges, MemorySnapshotObjects
from veritas_runtime.changes.models import (
    DeltaKind,
    DriveChange,
    DriveChangePage,
    DriveWatchStream,
    EvidenceCapture,
    EvidenceSnapshot,
    EvidenceSourceRegistration,
)
from veritas_runtime.changes.processor import (
    ChangeCursorConflict,
    DriveChangeProcessor,
    InvalidChangePage,
)
from veritas_runtime.changes.snapshots import ImmutableSnapshotService
from veritas_runtime.packets.models import SourceKind

NOW = datetime(2026, 8, 21, 1, 0, tzinfo=UTC)


class MemoryProcessingRepository:
    def __init__(self) -> None:
        self.stream = DriveWatchStream(
            stream_id="stream-1",
            subject="subject-1",
            page_token="page-1",
            created_at=NOW,
            updated_at=NOW,
        )
        self.registrations = (
            EvidenceSourceRegistration(
                subject="subject-1",
                packet_id="packet-1",
                source_id="source-churn",
                kind=SourceKind.GOOGLE_SHEET,
                resource_id="sheet-1",
                anchor="Metrics!B17",
                registered_at=NOW,
            ),
            EvidenceSourceRegistration(
                subject="subject-1",
                packet_id="packet-1",
                source_id="source-policy",
                kind=SourceKind.GOOGLE_DOC,
                resource_id="doc-1",
                anchor="launch-date",
                registered_at=NOW,
            ),
        )
        self.snapshots: dict[tuple[str, str, str], EvidenceSnapshot] = {}
        self.operation_batches: dict[str, tuple[str, str, bool, tuple[EvidenceSnapshot, ...]]] = {}

    async def get_stream(self, stream_id: str) -> DriveWatchStream | None:
        return self.stream if stream_id == self.stream.stream_id else None

    async def registrations_for_resources(
        self, subject: str, resource_ids: frozenset[str]
    ) -> tuple[EvidenceSourceRegistration, ...]:
        return tuple(
            registration
            for registration in self.registrations
            if registration.subject == subject and registration.resource_id in resource_ids
        )

    async def latest_snapshot(
        self, subject: str, packet_id: str, source_id: str
    ) -> EvidenceSnapshot | None:
        return self.snapshots.get((subject, packet_id, source_id))

    async def operation_snapshots(
        self, operation_id: str, subject: str, stream_id: str
    ) -> tuple[EvidenceSnapshot, ...] | None:
        batch = self.operation_batches.get(operation_id)
        if batch is None:
            return None
        if batch[:2] != (subject, stream_id):
            raise RuntimeError("batch identity conflict")
        return batch[3] if batch[2] else None

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
    ) -> None:
        if stream_id != self.stream.stream_id or self.stream.page_token != expected_page_token:
            raise ChangeCursorConflict("cursor conflict")
        for snapshot in snapshots:
            self.snapshots[(snapshot.subject, snapshot.packet_id, snapshot.source_id)] = snapshot
        existing = self.operation_batches.get(operation_id)
        prior = () if existing is None else existing[3]
        indexed = {snapshot.snapshot_id: snapshot for snapshot in (*prior, *snapshots)}
        self.operation_batches[operation_id] = (
            self.stream.subject,
            stream_id,
            batch_complete,
            tuple(indexed.values()),
        )
        self.stream = self.stream.model_copy(
            update={"page_token": next_page_token, "updated_at": now}
        )


class FakeExtractor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def extract(
        self, access_token: str, registration: EvidenceSourceRegistration
    ) -> EvidenceCapture:
        assert access_token == "access"
        self.calls.append(registration.resource_id)
        return EvidenceCapture(
            subject=registration.subject,
            packet_id=registration.packet_id,
            source_id=registration.source_id,
            resource_id=registration.resource_id,
            workspace_version=f"version-{len(self.calls)}",
            mime_type="application/vnd.google-apps.spreadsheet",
            evidence={registration.anchor: 0.09},
        )


def test_change_processor_coalesces_pages_snapshots_registered_sources_and_deletions() -> None:
    repository = MemoryProcessingRepository()
    extractor = FakeExtractor()
    objects = MemorySnapshotObjects()
    drive = FakeDriveChanges()
    pages = {
        "page-1": DriveChangePage(
            changes=(
                DriveChange(change_id="1", file_id="sheet-1", workspace_version="1"),
                DriveChange(change_id="2", file_id="sheet-1", workspace_version="2"),
                DriveChange(change_id="3", file_id="unregistered"),
            ),
            next_page_token="page-2",
        ),
        "page-2": DriveChangePage(
            changes=(DriveChange(change_id="4", file_id="doc-1", removed=True),),
            new_start_page_token="page-3",
        ),
    }

    async def list_changes(_access: str, cursor: str) -> DriveChangePage:
        listed_cursors.append(cursor)
        return pages[cursor]

    listed_cursors: list[str] = []
    drive.list_changes = list_changes  # type: ignore[method-assign]
    processor = DriveChangeProcessor(
        drive,
        extractor,
        ImmutableSnapshotService(objects),
        repository,
    )

    async def scenario() -> None:
        snapshots = await processor.process_stream("stream-1", "access", "operation-1", NOW)
        assert len(snapshots) == 2
        assert all(snapshot.delta_kind == DeltaKind.BASELINE for snapshot in snapshots)
        assert extractor.calls == ["sheet-1"]
        assert repository.stream.page_token == "page-3"
        deleted = repository.snapshots[("subject-1", "packet-1", "source-policy")]
        assert deleted.workspace_version == "removed:4"
        replay = await processor.process_stream("stream-1", "access", "operation-1", NOW)
        assert replay == snapshots
        assert listed_cursors == ["page-1", "page-2"]

    asyncio.run(scenario())


def test_change_processor_rejects_missing_stream_and_nonadvancing_cursor() -> None:
    repository = MemoryProcessingRepository()
    drive = FakeDriveChanges()
    drive.change_page = DriveChangePage(changes=())
    processor = DriveChangeProcessor(
        drive,
        FakeExtractor(),
        ImmutableSnapshotService(MemorySnapshotObjects()),
        repository,
    )

    async def scenario() -> None:
        with pytest.raises(LookupError, match="not found"):
            await processor.process_stream("missing", "access", "operation-missing", NOW)
        with pytest.raises(PermissionError, match="another subject"):
            await processor.process_stream(
                "stream-1",
                "access",
                "operation-subject",
                NOW,
                expected_subject="subject-2",
            )
        with pytest.raises(InvalidChangePage, match="advance"):
            await processor.process_stream("stream-1", "access", "operation-invalid", NOW)

    asyncio.run(scenario())
