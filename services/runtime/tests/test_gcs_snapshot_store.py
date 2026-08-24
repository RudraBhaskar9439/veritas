import asyncio
import hashlib
from datetime import UTC, datetime

import pytest
from google.api_core.exceptions import PreconditionFailed

from veritas_runtime.changes.models import (
    DeltaKind,
    EvidenceSnapshot,
    StoredSnapshotObject,
)
from veritas_runtime.changes.snapshots import GcsSnapshotObjectStore, SnapshotIntegrityError


class FakeBlob:
    def __init__(self) -> None:
        self.metadata: dict[str, str] | None = None
        self.generation: int | None = None
        self.fail_precondition = False
        self.persisted_metadata: dict[str, str] | None = None
        self.uploads: list[tuple[bytes, dict[str, object]]] = []
        self.download = b"content"
        self.downloads: list[dict[str, object]] = []

    def upload_from_string(self, content: bytes, **kwargs: object) -> None:
        self.uploads.append((content, kwargs))
        if self.fail_precondition:
            raise PreconditionFailed("already exists")
        self.persisted_metadata = self.metadata
        self.generation = 7

    def reload(self) -> None:
        self.metadata = self.persisted_metadata
        self.generation = 7

    def download_as_bytes(self, **kwargs: object) -> bytes:
        self.downloads.append(kwargs)
        return self.download


class FakeBucket:
    def __init__(self, blob: FakeBlob) -> None:
        self._blob = blob

    def blob(self, _name: str, **_kwargs: object) -> FakeBlob:
        return self._blob


class FakeStorageClient:
    def __init__(self, blob: FakeBlob) -> None:
        self._bucket = FakeBucket(blob)

    def bucket(self, _name: str) -> FakeBucket:
        return self._bucket


def test_gcs_snapshot_store_uses_create_only_generation_precondition() -> None:
    blob = FakeBlob()
    store = GcsSnapshotObjectStore("snapshot-bucket", FakeStorageClient(blob))  # type: ignore[arg-type]

    async def scenario() -> None:
        stored = await store.put_once("evidence/object.json", b"content", "a" * 64)
        assert stored.generation == "7"
        assert stored.bucket == "snapshot-bucket"

    asyncio.run(scenario())
    assert blob.uploads[0][1]["if_generation_match"] == 0
    assert blob.uploads[0][1]["checksum"] == "crc32c"


def test_gcs_snapshot_store_reads_exact_generation_and_verifies_hash() -> None:
    blob = FakeBlob()
    store = GcsSnapshotObjectStore("bucket", FakeStorageClient(blob))  # type: ignore[arg-type]
    stored = EvidenceSnapshot(
        snapshot_id="snapshot-1",
        subject="subject-1",
        packet_id="packet-1",
        source_id="source-1",
        resource_id="resource-1",
        workspace_version="v1",
        content_hash=hashlib.sha256(b"content").hexdigest(),
        semantic_hash="b" * 64,
        storage=StoredSnapshotObject(
            bucket="bucket",
            object_name="evidence/object.json",
            generation="7",
        ),
        delta_kind=DeltaKind.MEANINGFUL,
        created_at=datetime(2026, 8, 24, 13, 0, tzinfo=UTC),
    )

    async def scenario() -> None:
        assert await store.read(stored) == b"content"
        blob.download = b"tampered"
        with pytest.raises(SnapshotIntegrityError, match="content hash"):
            await store.read(stored)

    asyncio.run(scenario())
    assert blob.downloads[0]["if_generation_match"] == 7
    assert blob.downloads[0]["checksum"] == "crc32c"


def test_gcs_snapshot_store_accepts_verified_replay_and_rejects_collision() -> None:
    blob = FakeBlob()
    blob.fail_precondition = True
    blob.persisted_metadata = {"sha256": "a" * 64}
    store = GcsSnapshotObjectStore("snapshot-bucket", FakeStorageClient(blob))  # type: ignore[arg-type]

    async def scenario() -> None:
        assert (
            await store.put_once("evidence/object.json", b"content", "a" * 64)
        ).generation == "7"
        blob.persisted_metadata = {"sha256": "b" * 64}
        with pytest.raises(SnapshotIntegrityError, match="content-address"):
            await store.put_once("evidence/object.json", b"content", "a" * 64)

    asyncio.run(scenario())
