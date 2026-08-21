import asyncio

import pytest
from google.api_core.exceptions import PreconditionFailed

from veritas_runtime.changes.snapshots import GcsSnapshotObjectStore, SnapshotIntegrityError


class FakeBlob:
    def __init__(self) -> None:
        self.metadata: dict[str, str] | None = None
        self.generation: int | None = None
        self.fail_precondition = False
        self.persisted_metadata: dict[str, str] | None = None
        self.uploads: list[tuple[bytes, dict[str, object]]] = []

    def upload_from_string(self, content: bytes, **kwargs: object) -> None:
        self.uploads.append((content, kwargs))
        if self.fail_precondition:
            raise PreconditionFailed("already exists")
        self.persisted_metadata = self.metadata
        self.generation = 7

    def reload(self) -> None:
        self.metadata = self.persisted_metadata
        self.generation = 7


class FakeBucket:
    def __init__(self, blob: FakeBlob) -> None:
        self._blob = blob

    def blob(self, _name: str) -> FakeBlob:
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
