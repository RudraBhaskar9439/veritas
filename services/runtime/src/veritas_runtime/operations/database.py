import hashlib
import json
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Table,
    Text,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from veritas_runtime.auth.database import metadata
from veritas_runtime.changes.database import (
    drive_change_operation_snapshots,
    evidence_snapshots,
)
from veritas_runtime.operations.models import (
    DeadLetterSummary,
    Operation,
    OperationRequest,
    OperationStatus,
)
from veritas_runtime.operations.service import OperationIdempotencyConflict, payload_hash

operations = Table(
    "operations",
    metadata,
    Column("operation_id", String(255), primary_key=True),
    Column("subject", String(255), nullable=False),
    Column("kind", String(80), nullable=False),
    Column("correlation_id", String(128), nullable=False),
    Column("idempotency_key", String(512), nullable=False, unique=True),
    Column("payload_json", Text, nullable=False),
    Column("payload_hash", String(64), nullable=False),
    Column("status", String(32), nullable=False),
    Column("attempt", Integer, nullable=False),
    Column("max_attempts", Integer, nullable=False),
    Column("available_at", DateTime(timezone=True), nullable=False),
    Column("lease_owner", String(128), nullable=True),
    Column("lease_expires_at", DateTime(timezone=True), nullable=True),
    Column("last_error_code", String(80), nullable=True),
    Column("diagnostic_fingerprint", String(64), nullable=True),
    Column("replay_of", String(255), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
Index("operations_claim_idx", operations.c.status, operations.c.available_at)
Index("operations_dead_letter_idx", operations.c.subject, operations.c.status)

operation_events = Table(
    "operation_events",
    metadata,
    Column("event_id", String(255), primary_key=True),
    Column("operation_id", String(255), nullable=False),
    Column("event_type", String(80), nullable=False),
    Column("actor", String(255), nullable=False),
    Column("event_json", Text, nullable=False),
    Column("checksum", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index(
    "operation_events_operation_idx",
    operation_events.c.operation_id,
    operation_events.c.created_at,
)


class SqlOperationRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def enqueue(self, request: OperationRequest, now: datetime) -> tuple[Operation, bool]:
        digest = payload_hash(request.payload)
        async with self._engine.begin() as connection:
            existing = await _by_idempotency(connection, request.idempotency_key)
            if existing is not None:
                _require_same_request(existing, request, digest)
                return _operation(existing), True
            operation_identity = f"{request.subject}:{request.idempotency_key}"
            operation_id = f"op-{uuid5(NAMESPACE_URL, operation_identity)}"
            values = {
                "operation_id": operation_id,
                "subject": request.subject,
                "kind": request.kind,
                "correlation_id": request.correlation_id,
                "idempotency_key": request.idempotency_key,
                "payload_json": _canonical(request.payload),
                "payload_hash": digest,
                "status": OperationStatus.QUEUED.value,
                "attempt": 0,
                "max_attempts": request.max_attempts,
                "available_at": now,
                "lease_owner": None,
                "lease_expires_at": None,
                "last_error_code": None,
                "diagnostic_fingerprint": None,
                "replay_of": None,
                "created_at": now,
                "updated_at": now,
            }
            await connection.execute(insert(operations).values(**values))
            await _event(connection, operation_id, "enqueued", "system", {}, now)
            return _operation(values), False

    async def recover_expired(self, now: datetime) -> int:
        async with self._engine.begin() as connection:
            rows = (
                (
                    await connection.execute(
                        select(operations.c.operation_id).where(
                            operations.c.status == OperationStatus.RUNNING.value,
                            operations.c.lease_expires_at <= now,
                        )
                    )
                )
                .scalars()
                .all()
            )
            if not rows:
                return 0
            await connection.execute(
                update(operations)
                .where(operations.c.operation_id.in_(rows))
                .values(
                    status=OperationStatus.QUEUED.value,
                    available_at=now,
                    lease_owner=None,
                    lease_expires_at=None,
                    last_error_code="worker_lease_expired",
                    updated_at=now,
                )
            )
            for operation_id in rows:
                await _event(
                    connection,
                    str(operation_id),
                    "lease_recovered",
                    "system",
                    {"errorCode": "worker_lease_expired"},
                    now,
                )
            return len(rows)

    async def claim(
        self, worker_id: str, now: datetime, lease_expires_at: datetime
    ) -> Operation | None:
        async with self._engine.begin() as connection:
            row = (
                (
                    await connection.execute(
                        select(operations)
                        .where(
                            or_(
                                operations.c.status == OperationStatus.QUEUED.value,
                                operations.c.status == OperationStatus.RETRY_WAIT.value,
                            ),
                            operations.c.available_at <= now,
                        )
                        .order_by(operations.c.available_at, operations.c.created_at)
                        .limit(1)
                        .with_for_update(skip_locked=True)
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            await connection.execute(
                update(operations)
                .where(
                    operations.c.operation_id == row["operation_id"],
                    operations.c.status == row["status"],
                )
                .values(
                    status=OperationStatus.RUNNING.value,
                    attempt=int(row["attempt"]) + 1,
                    lease_owner=worker_id,
                    lease_expires_at=lease_expires_at,
                    updated_at=now,
                )
            )
            claimed = await _by_id(connection, str(row["operation_id"]))
            if claimed is None:
                raise RuntimeError("Claimed operation disappeared")
            await _event(
                connection,
                str(row["operation_id"]),
                "claimed",
                worker_id,
                {"attempt": int(claimed["attempt"])},
                now,
            )
            return _operation(claimed)

    async def succeed(self, operation: Operation, worker_id: str, now: datetime) -> Operation:
        return await self._transition(
            operation,
            worker_id,
            OperationStatus.SUCCEEDED,
            now,
            "succeeded",
        )

    async def retry(
        self,
        operation: Operation,
        worker_id: str,
        error_code: str,
        diagnostic_fingerprint: str,
        available_at: datetime,
        now: datetime,
    ) -> Operation:
        return await self._transition(
            operation,
            worker_id,
            OperationStatus.RETRY_WAIT,
            now,
            "retry_scheduled",
            available_at=available_at,
            error_code=error_code,
            diagnostic_fingerprint=diagnostic_fingerprint,
        )

    async def dead_letter(
        self,
        operation: Operation,
        worker_id: str,
        error_code: str,
        diagnostic_fingerprint: str,
        now: datetime,
    ) -> Operation:
        return await self._transition(
            operation,
            worker_id,
            OperationStatus.DEAD_LETTER,
            now,
            "dead_lettered",
            error_code=error_code,
            diagnostic_fingerprint=diagnostic_fingerprint,
        )

    async def list_dead_letters(self, subject: str) -> tuple[DeadLetterSummary, ...]:
        async with self._engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        select(operations)
                        .where(
                            operations.c.subject == subject,
                            operations.c.status == OperationStatus.DEAD_LETTER.value,
                        )
                        .order_by(operations.c.updated_at.desc())
                    )
                )
                .mappings()
                .all()
            )
            operation_ids = tuple(str(row["operation_id"]) for row in rows)
            packet_rows = (
                (
                    await connection.execute(
                        select(
                            drive_change_operation_snapshots.c.operation_id,
                            evidence_snapshots.c.packet_id,
                        )
                        .select_from(
                            drive_change_operation_snapshots.join(
                                evidence_snapshots,
                                evidence_snapshots.c.snapshot_id
                                == drive_change_operation_snapshots.c.snapshot_id,
                            )
                        )
                        .where(
                            drive_change_operation_snapshots.c.operation_id.in_(operation_ids)
                        )
                        .distinct()
                    )
                )
                .mappings()
                .all()
                if operation_ids
                else ()
            )
        packet_ids: dict[str, set[str]] = {}
        for row in packet_rows:
            packet_ids.setdefault(str(row["operation_id"]), set()).add(str(row["packet_id"]))
        return tuple(
            _dead_letter(row, tuple(sorted(packet_ids.get(str(row["operation_id"]), ()))))
            for row in rows
        )

    async def replay(
        self,
        subject: str,
        operation_id: str,
        request_id: str,
        actor: str,
        reason: str,
        now: datetime,
    ) -> tuple[Operation, bool]:
        idempotency_key = f"{subject}:replay:{operation_id}:{request_id}"
        async with self._engine.begin() as connection:
            original = await _by_id(connection, operation_id)
            if (
                original is None
                or original["subject"] != subject
                or original["status"] != OperationStatus.DEAD_LETTER.value
            ):
                raise LookupError("Dead-lettered operation was not found")
            existing = await _by_idempotency(connection, idempotency_key)
            if existing is not None:
                if existing["replay_of"] != operation_id:
                    raise OperationIdempotencyConflict(
                        "Replay request conflicts with another operation"
                    )
                return _operation(existing), True
            replay_id = f"op-{uuid5(NAMESPACE_URL, idempotency_key)}"
            replay_payload = json.loads(str(original["payload_json"]))
            replay_payload.setdefault("__veritasReplayRootOperationId", operation_id)
            replay_payload_json = _canonical(replay_payload)
            values = {
                "operation_id": replay_id,
                "subject": subject,
                "kind": original["kind"],
                "correlation_id": original["correlation_id"],
                "idempotency_key": idempotency_key,
                "payload_json": replay_payload_json,
                "payload_hash": hashlib.sha256(replay_payload_json.encode()).hexdigest(),
                "status": OperationStatus.QUEUED.value,
                "attempt": 0,
                "max_attempts": original["max_attempts"],
                "available_at": now,
                "lease_owner": None,
                "lease_expires_at": None,
                "last_error_code": None,
                "diagnostic_fingerprint": None,
                "replay_of": operation_id,
                "created_at": now,
                "updated_at": now,
            }
            await connection.execute(insert(operations).values(**values))
            await _event(
                connection,
                replay_id,
                "replayed",
                actor,
                {"replayOf": operation_id, "reason": reason},
                now,
            )
            return _operation(values), False

    async def _transition(
        self,
        operation: Operation,
        worker_id: str,
        status: OperationStatus,
        now: datetime,
        event_type: str,
        *,
        available_at: datetime | None = None,
        error_code: str | None = None,
        diagnostic_fingerprint: str | None = None,
    ) -> Operation:
        values = {
            "status": status.value,
            "available_at": available_at or operation.available_at,
            "lease_owner": None,
            "lease_expires_at": None,
            "last_error_code": error_code,
            "diagnostic_fingerprint": diagnostic_fingerprint,
            "updated_at": now,
        }
        async with self._engine.begin() as connection:
            result = await connection.execute(
                update(operations)
                .where(
                    operations.c.operation_id == operation.operation_id,
                    operations.c.status == OperationStatus.RUNNING.value,
                    operations.c.lease_owner == worker_id,
                )
                .values(**values)
            )
            if result.rowcount != 1:
                raise RuntimeError("Operation lease was lost before transition")
            await _event(
                connection,
                operation.operation_id,
                event_type,
                worker_id,
                {
                    "attempt": operation.attempt,
                    "errorCode": error_code,
                    "diagnosticFingerprint": diagnostic_fingerprint,
                },
                now,
            )
            row = await _by_id(connection, operation.operation_id)
            if row is None:
                raise RuntimeError("Transitioned operation disappeared")
            return _operation(row)


async def _by_id(connection: AsyncConnection, operation_id: str) -> RowMapping | None:
    return (
        (
            await connection.execute(
                select(operations).where(operations.c.operation_id == operation_id)
            )
        )
        .mappings()
        .one_or_none()
    )


async def _by_idempotency(connection: AsyncConnection, key: str) -> RowMapping | None:
    return (
        (await connection.execute(select(operations).where(operations.c.idempotency_key == key)))
        .mappings()
        .one_or_none()
    )


async def _event(
    connection: AsyncConnection,
    operation_id: str,
    event_type: str,
    actor: str,
    detail: dict[str, object],
    now: datetime,
) -> None:
    payload = _canonical(detail)
    await connection.execute(
        insert(operation_events).values(
            event_id=f"operation-event-{uuid4()}",
            operation_id=operation_id,
            event_type=event_type,
            actor=actor,
            event_json=payload,
            checksum=hashlib.sha256(payload.encode()).hexdigest(),
            created_at=now,
        )
    )


def _operation(row: RowMapping | dict[str, object]) -> Operation:
    return Operation(
        operation_id=str(row["operation_id"]),
        subject=str(row["subject"]),
        kind=str(row["kind"]),
        correlation_id=str(row["correlation_id"]),
        idempotency_key=str(row["idempotency_key"]),
        payload=json.loads(str(row["payload_json"])),
        payload_hash=str(row["payload_hash"]),
        status=OperationStatus(str(row["status"])),
        attempt=int(str(row["attempt"])),
        max_attempts=int(str(row["max_attempts"])),
        available_at=_timestamp(row["available_at"]),
        lease_owner=str(row["lease_owner"]) if row["lease_owner"] is not None else None,
        lease_expires_at=_optional_timestamp(row["lease_expires_at"]),
        last_error_code=(
            str(row["last_error_code"]) if row["last_error_code"] is not None else None
        ),
        diagnostic_fingerprint=(
            str(row["diagnostic_fingerprint"])
            if row["diagnostic_fingerprint"] is not None
            else None
        ),
        replay_of=str(row["replay_of"]) if row["replay_of"] is not None else None,
        created_at=_timestamp(row["created_at"]),
        updated_at=_timestamp(row["updated_at"]),
    )


def _dead_letter(row: RowMapping, packet_ids: tuple[str, ...] = ()) -> DeadLetterSummary:
    return DeadLetterSummary(
        operation_id=str(row["operation_id"]),
        kind=str(row["kind"]),
        correlation_id=str(row["correlation_id"]),
        attempt=int(str(row["attempt"])),
        max_attempts=int(str(row["max_attempts"])),
        error_code=str(row["last_error_code"]),
        diagnostic_fingerprint=str(row["diagnostic_fingerprint"]),
        replay_of=str(row["replay_of"]) if row["replay_of"] is not None else None,
        packet_ids=packet_ids,
        updated_at=_timestamp(row["updated_at"]),
    )


def _require_same_request(row: RowMapping, request: OperationRequest, digest: str) -> None:
    if (
        row["subject"] != request.subject
        or row["kind"] != request.kind
        or row["payload_hash"] != digest
    ):
        raise OperationIdempotencyConflict("Operation request ID was reused with different work")


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _optional_timestamp(value: object) -> datetime | None:
    return _timestamp(value) if value is not None else None


def _timestamp(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("Stored operation timestamp is invalid")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
