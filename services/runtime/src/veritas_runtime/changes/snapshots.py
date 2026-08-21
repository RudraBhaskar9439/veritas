import asyncio
import hashlib
from datetime import UTC, datetime
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from google.api_core.exceptions import PreconditionFailed
from google.cloud.storage.client import Client  # type: ignore[import-untyped]

from veritas_runtime.changes.models import (
    EvidenceCapture,
    EvidenceSnapshot,
    SnapshotCaptureResult,
    StoredSnapshotObject,
)
from veritas_runtime.changes.semantic import (
    canonical_capture,
    classify_delta,
    content_hash,
    semantic_hash,
)


class SnapshotIntegrityError(RuntimeError):
    """An immutable snapshot object does not match its content address."""


class SnapshotObjectStore(Protocol):
    async def put_once(
        self,
        object_name: str,
        content: bytes,
        sha256: str,
    ) -> StoredSnapshotObject: ...


class ImmutableSnapshotService:
    def __init__(self, objects: SnapshotObjectStore) -> None:
        self._objects = objects

    async def capture(
        self,
        capture: EvidenceCapture,
        previous: EvidenceSnapshot | None,
        now: datetime | None = None,
    ) -> SnapshotCaptureResult:
        if previous is not None and (
            previous.subject != capture.subject
            or previous.packet_id != capture.packet_id
            or previous.source_id != capture.source_id
            or previous.resource_id != capture.resource_id
        ):
            raise SnapshotIntegrityError("Previous snapshot belongs to different evidence")
        canonical = canonical_capture(capture)
        exact_hash = content_hash(capture)
        if hashlib.sha256(canonical).hexdigest() != exact_hash:
            raise SnapshotIntegrityError("Canonical snapshot hash is inconsistent")
        meaning_hash = semantic_hash(capture)
        object_name = _object_name(capture, exact_hash)
        stored = await self._objects.put_once(object_name, canonical, exact_hash)
        created_at = (now or datetime.now(UTC)).astimezone(UTC)
        snapshot = EvidenceSnapshot(
            snapshot_id=(
                "snapshot-"
                + str(
                    uuid5(
                        NAMESPACE_URL,
                        (f"{capture.subject}:{capture.packet_id}:{capture.source_id}:{exact_hash}"),
                    )
                )
            ),
            subject=capture.subject,
            packet_id=capture.packet_id,
            source_id=capture.source_id,
            resource_id=capture.resource_id,
            workspace_version=capture.workspace_version,
            content_hash=exact_hash,
            semantic_hash=meaning_hash,
            storage=stored,
            delta_kind=classify_delta(exact_hash, meaning_hash, previous),
            created_at=created_at,
        )
        return SnapshotCaptureResult(snapshot=snapshot, canonical_content=canonical)


class GcsSnapshotObjectStore:
    def __init__(self, bucket_name: str, client: Client | None = None) -> None:
        if not bucket_name:
            raise ValueError("Snapshot bucket name is required")
        self._bucket_name = bucket_name
        self._client = client or Client()

    async def put_once(
        self,
        object_name: str,
        content: bytes,
        sha256: str,
    ) -> StoredSnapshotObject:
        return await asyncio.to_thread(self._put_once, object_name, content, sha256)

    def _put_once(
        self,
        object_name: str,
        content: bytes,
        sha256: str,
    ) -> StoredSnapshotObject:
        blob = self._client.bucket(self._bucket_name).blob(object_name)
        blob.metadata = {"sha256": sha256}
        try:
            blob.upload_from_string(
                content,
                content_type="application/json",
                if_generation_match=0,
                checksum="crc32c",
            )
        except PreconditionFailed:
            blob.reload()
            if not blob.metadata or blob.metadata.get("sha256") != sha256:
                raise SnapshotIntegrityError(
                    "Existing snapshot object failed content-address verification"
                ) from None
        if blob.generation is None:
            blob.reload()
        if blob.generation is None:
            raise SnapshotIntegrityError("Cloud Storage returned no object generation")
        return StoredSnapshotObject(
            bucket=self._bucket_name,
            object_name=object_name,
            generation=str(blob.generation),
        )


def _object_name(capture: EvidenceCapture, exact_hash: str) -> str:
    subject_partition = hashlib.sha256(capture.subject.encode()).hexdigest()[:24]
    packet_partition = hashlib.sha256(capture.packet_id.encode()).hexdigest()[:24]
    resource_partition = hashlib.sha256(capture.resource_id.encode()).hexdigest()[:24]
    return (
        f"evidence/v1/{subject_partition}/{packet_partition}/{resource_partition}/{exact_hash}.json"
    )
