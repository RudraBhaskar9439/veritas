from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from veritas_runtime.packets.models import SourceKind

type JsonValue = bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None


class ChangeModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )


class WatchChannelState(StrEnum):
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    RETIRING = "retiring"
    STOPPED = "stopped"
    FAILED = "failed"


class DriveWatchStream(ChangeModel):
    stream_id: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    page_token: str = Field(min_length=1)
    created_at: datetime
    updated_at: datetime


class DriveWatchChannel(ChangeModel):
    channel_id: str = Field(min_length=1, max_length=64)
    stream_id: str = Field(min_length=1)
    state: WatchChannelState
    google_resource_id: str | None = None
    expiration: datetime
    replaces_channel_id: str | None = None
    sync_received: bool = False
    created_at: datetime
    updated_at: datetime


class DriveWatchLease(ChangeModel):
    channel_id: str = Field(min_length=1, max_length=64)
    google_resource_id: str = Field(min_length=1)
    resource_uri: str = Field(min_length=1)
    expiration: datetime


class DriveNotification(ChangeModel):
    channel_id: str = Field(min_length=1, max_length=64)
    message_number: int = Field(ge=1)
    google_resource_id: str = Field(min_length=1)
    resource_state: str = Field(min_length=1)
    resource_uri: str = Field(min_length=1)
    changed: tuple[str, ...] = ()
    received_at: datetime


class NotificationDisposition(StrEnum):
    SYNCED = "synced"
    ENQUEUED = "enqueued"
    DUPLICATE = "duplicate"
    IGNORED = "ignored"


class DriveChange(ChangeModel):
    change_id: str = Field(min_length=1)
    file_id: str = Field(min_length=1)
    removed: bool = False
    mime_type: str | None = None
    workspace_version: str | None = None


class DriveChangePage(ChangeModel):
    changes: tuple[DriveChange, ...]
    next_page_token: str | None = None
    new_start_page_token: str | None = None


class EvidenceCapture(ChangeModel):
    subject: str = Field(min_length=1)
    packet_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    workspace_version: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    evidence: dict[str, JsonValue] = Field(min_length=1)
    presentation: dict[str, JsonValue] = Field(default_factory=dict)


class EvidenceSourceRegistration(ChangeModel):
    subject: str = Field(min_length=1)
    packet_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    kind: SourceKind
    resource_id: str = Field(min_length=1)
    anchor: str = Field(min_length=1)
    registered_at: datetime


class DeltaKind(StrEnum):
    BASELINE = "baseline"
    DUPLICATE = "duplicate"
    COSMETIC = "cosmetic"
    MEANINGFUL = "meaningful"


class StoredSnapshotObject(ChangeModel):
    bucket: str = Field(min_length=1)
    object_name: str = Field(min_length=1)
    generation: str = Field(min_length=1)


class EvidenceSnapshot(ChangeModel):
    snapshot_id: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    packet_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    workspace_version: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    semantic_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    storage: StoredSnapshotObject
    delta_kind: DeltaKind
    created_at: datetime


class SnapshotCaptureResult(ChangeModel):
    snapshot: EvidenceSnapshot
    canonical_content: bytes = Field(exclude=True, repr=False)
