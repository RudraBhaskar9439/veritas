import json
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    insert,
    select,
)
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from veritas_runtime.auth.database import metadata
from veritas_runtime.packets.generator import (
    IdempotencyConflict,
    PersistedManifest,
    manifest_checksum,
)
from veritas_runtime.packets.models import ClaimManifest, ManifestDraft

claim_manifests = Table(
    "claim_manifests",
    metadata,
    Column("manifest_id", String(255), primary_key=True),
    Column("packet_id", String(255), nullable=False),
    Column("version", Integer, nullable=False),
    Column("idempotency_key", String(512), nullable=False, unique=True),
    Column("input_digest", String(64), nullable=False),
    Column("checksum", String(64), nullable=False),
    Column("manifest_json", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("packet_id", "version", name="claim_manifests_packet_version_uq"),
)
Index("claim_manifests_packet_idx", claim_manifests.c.packet_id)


class SqlManifestRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get_by_idempotency_key(self, key: str) -> PersistedManifest | None:
        async with self._engine.connect() as connection:
            row = await _select_by_key(connection, key)
        return _persisted(row) if row is not None else None

    async def persist(
        self,
        draft: ManifestDraft,
        idempotency_key: str,
        input_digest: str,
        now: datetime,
    ) -> PersistedManifest:
        async with self._engine.begin() as connection:
            if self._engine.dialect.name == "postgresql":
                await connection.execute(
                    select(func.pg_advisory_xact_lock(func.hashtext(draft.packet_id)))
                )
            existing = await _select_by_key(connection, idempotency_key)
            if existing is not None:
                persisted = _persisted(existing)
                if persisted.input_digest != input_digest:
                    raise IdempotencyConflict(
                        "Generation request ID was reused with different inputs"
                    )
                return persisted

            current_version = await connection.scalar(
                select(func.max(claim_manifests.c.version)).where(
                    claim_manifests.c.packet_id == draft.packet_id
                )
            )
            version = int(current_version or 0) + 1
            manifest_id = f"manifest-{uuid5(NAMESPACE_URL, idempotency_key)}"
            manifest = ClaimManifest(
                manifest_id=manifest_id,
                packet_id=draft.packet_id,
                version=version,
                created_at=now.astimezone(UTC),
                sources=draft.sources,
                artifacts=draft.artifacts,
                claims=draft.claims,
            )
            checksum = manifest_checksum(manifest)
            await connection.execute(
                insert(claim_manifests).values(
                    manifest_id=manifest.manifest_id,
                    packet_id=manifest.packet_id,
                    version=manifest.version,
                    idempotency_key=idempotency_key,
                    input_digest=input_digest,
                    checksum=checksum,
                    manifest_json=manifest.model_dump_json(by_alias=True),
                    created_at=manifest.created_at,
                )
            )
        return PersistedManifest(manifest, checksum, input_digest)


async def _select_by_key(connection: AsyncConnection, key: str) -> dict[str, object] | None:
    row = (
        (
            await connection.execute(
                select(claim_manifests).where(claim_manifests.c.idempotency_key == key)
            )
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row is not None else None


def _persisted(row: dict[str, object]) -> PersistedManifest:
    raw_manifest = row["manifest_json"]
    if not isinstance(raw_manifest, str):
        raise TypeError("Stored manifest JSON must be text")
    manifest = ClaimManifest.model_validate(json.loads(raw_manifest))
    checksum = str(row["checksum"])
    if manifest_checksum(manifest) != checksum:
        raise ValueError("Stored manifest checksum mismatch")
    return PersistedManifest(
        manifest=manifest,
        checksum=checksum,
        input_digest=str(row["input_digest"]),
    )
