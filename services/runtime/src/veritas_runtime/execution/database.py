import hashlib
import json
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Table,
    Text,
    insert,
    select,
    update,
)
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from veritas_runtime.auth.database import metadata
from veritas_runtime.execution.models import (
    RepairRun,
    RepairRunStatus,
    StepExecutionRecord,
)
from veritas_runtime.execution.service import ExecutionContext
from veritas_runtime.repairs.database import repair_approvals, repair_plans
from veritas_runtime.repairs.models import ApprovalRecord, ApprovalStatus, RepairPlan
from veritas_runtime.repairs.service import repair_plan_checksum

repair_runs = Table(
    "repair_runs",
    metadata,
    Column("run_id", String(255), primary_key=True),
    Column("subject", String(255), nullable=False),
    Column("plan_id", String(255), ForeignKey("repair_plans.plan_id"), nullable=False),
    Column("packet_id", String(255), nullable=False),
    Column("idempotency_key", String(1024), nullable=False, unique=True),
    Column("status", String(32), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
Index("repair_runs_plan_idx", repair_runs.c.subject, repair_runs.c.plan_id)

repair_run_steps = Table(
    "repair_run_steps",
    metadata,
    Column("run_id", String(255), ForeignKey("repair_runs.run_id"), primary_key=True),
    Column("step_id", String(255), primary_key=True),
    Column("status", String(32), nullable=False),
    Column("record_json", Text, nullable=False),
    Column("checksum", String(64), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

repair_run_step_events = Table(
    "repair_run_step_events",
    metadata,
    Column("event_id", String(255), primary_key=True),
    Column("run_id", String(255), ForeignKey("repair_runs.run_id"), nullable=False),
    Column("step_id", String(255), nullable=False),
    Column("status", String(32), nullable=False),
    Column("record_json", Text, nullable=False),
    Column("checksum", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("repair_run_step_events_run_idx", repair_run_step_events.c.run_id)


class SqlExecutionRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def load_context(self, subject: str, plan_id: str) -> ExecutionContext:
        async with self._engine.connect() as connection:
            plan_row = (
                (
                    await connection.execute(
                        select(repair_plans).where(
                            repair_plans.c.subject == subject,
                            repair_plans.c.plan_id == plan_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if plan_row is None:
                raise LookupError("Repair plan was not found")
            plan = _plan(plan_row)
            approval_rows = (
                (
                    await connection.execute(
                        select(repair_approvals)
                        .where(repair_approvals.c.plan_id == plan_id)
                        .order_by(repair_approvals.c.approval_id)
                    )
                )
                .mappings()
                .all()
            )
        return ExecutionContext(plan, tuple(_approval(row) for row in approval_rows))

    async def get_by_idempotency_key(self, key: str) -> RepairRun | None:
        async with self._engine.connect() as connection:
            row = await _run_by_key(connection, key)
            return await _run(connection, row) if row is not None else None

    async def start(
        self,
        subject: str,
        plan: RepairPlan,
        idempotency_key: str,
        now: datetime,
    ) -> RepairRun:
        async with self._engine.begin() as connection:
            existing = await _run_by_key(connection, idempotency_key)
            if existing is not None:
                if existing["subject"] != subject or existing["plan_id"] != plan.plan_id:
                    raise ValueError("Execution request ID conflicts with another repair plan")
                return await _run(connection, existing)
            run_id = f"run-{uuid5(NAMESPACE_URL, idempotency_key)}"
            await connection.execute(
                insert(repair_runs).values(
                    run_id=run_id,
                    subject=subject,
                    plan_id=plan.plan_id,
                    packet_id=plan.packet_id,
                    idempotency_key=idempotency_key,
                    status=RepairRunStatus.RUNNING.value,
                    created_at=now,
                    updated_at=now,
                )
            )
            row = await _run_by_key(connection, idempotency_key)
            if row is None:
                raise RuntimeError("Persisted repair run was not found")
            return await _run(connection, row)

    async def record_step(
        self,
        run: RepairRun,
        record: StepExecutionRecord,
        now: datetime,
    ) -> RepairRun:
        checksum = _record_checksum(record)
        payload = record.model_dump_json(by_alias=True)
        async with self._engine.begin() as connection:
            run_row = await _run_by_id(connection, run.run_id)
            if run_row is None:
                raise LookupError("Repair run was not found")
            existing = (
                (
                    await connection.execute(
                        select(repair_run_steps).where(
                            repair_run_steps.c.run_id == run.run_id,
                            repair_run_steps.c.step_id == record.step_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            values = {
                "status": record.status.value,
                "record_json": payload,
                "checksum": checksum,
                "updated_at": now,
            }
            if existing is None:
                await connection.execute(
                    insert(repair_run_steps).values(
                        run_id=run.run_id,
                        step_id=record.step_id,
                        **values,
                    )
                )
            else:
                await connection.execute(
                    update(repair_run_steps)
                    .where(
                        repair_run_steps.c.run_id == run.run_id,
                        repair_run_steps.c.step_id == record.step_id,
                    )
                    .values(**values)
                )
            await connection.execute(
                insert(repair_run_step_events).values(
                    event_id=f"run-event-{uuid4()}",
                    run_id=run.run_id,
                    step_id=record.step_id,
                    status=record.status.value,
                    record_json=payload,
                    checksum=checksum,
                    created_at=now,
                )
            )
            await connection.execute(
                update(repair_runs)
                .where(repair_runs.c.run_id == run.run_id)
                .values(status=RepairRunStatus.RUNNING.value, updated_at=now)
            )
            updated = await _run_by_id(connection, run.run_id)
            if updated is None:
                raise RuntimeError("Updated repair run was not found")
            return await _run(connection, updated)

    async def finish(
        self,
        run: RepairRun,
        status: RepairRunStatus,
        now: datetime,
    ) -> RepairRun:
        async with self._engine.begin() as connection:
            result = await connection.execute(
                update(repair_runs)
                .where(repair_runs.c.run_id == run.run_id)
                .values(status=status.value, updated_at=now)
            )
            if result.rowcount != 1:
                raise LookupError("Repair run was not found")
            updated = await _run_by_id(connection, run.run_id)
            if updated is None:
                raise RuntimeError("Finished repair run was not found")
            return await _run(connection, updated)


async def _run_by_key(connection: AsyncConnection, key: str) -> RowMapping | None:
    return (
        (await connection.execute(select(repair_runs).where(repair_runs.c.idempotency_key == key)))
        .mappings()
        .one_or_none()
    )


async def _run_by_id(connection: AsyncConnection, run_id: str) -> RowMapping | None:
    return (
        (await connection.execute(select(repair_runs).where(repair_runs.c.run_id == run_id)))
        .mappings()
        .one_or_none()
    )


async def _run(connection: AsyncConnection, row: RowMapping) -> RepairRun:
    step_rows = (
        (
            await connection.execute(
                select(repair_run_steps)
                .where(repair_run_steps.c.run_id == row["run_id"])
                .order_by(repair_run_steps.c.step_id)
            )
        )
        .mappings()
        .all()
    )
    steps = tuple(_step(step_row) for step_row in step_rows)
    created_at = _timestamp(row["created_at"])
    updated_at = _timestamp(row["updated_at"])
    return RepairRun(
        run_id=str(row["run_id"]),
        plan_id=str(row["plan_id"]),
        packet_id=str(row["packet_id"]),
        status=RepairRunStatus(str(row["status"])),
        created_at=created_at,
        updated_at=updated_at,
        steps=steps,
    )


def _step(row: RowMapping) -> StepExecutionRecord:
    record = StepExecutionRecord.model_validate(json.loads(str(row["record_json"])))
    if _record_checksum(record) != str(row["checksum"]):
        raise ValueError("Stored execution step checksum mismatch")
    return record


def _record_checksum(record: StepExecutionRecord) -> str:
    canonical = json.dumps(
        record.model_dump(mode="json", by_alias=True),
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _plan(row: RowMapping) -> RepairPlan:
    plan = RepairPlan.model_validate(json.loads(str(row["plan_json"])))
    if repair_plan_checksum(plan) != str(row["checksum"]):
        raise ValueError("Stored repair plan checksum mismatch")
    return plan


def _approval(row: RowMapping) -> ApprovalRecord:
    decided_at = row["decided_at"]
    return ApprovalRecord(
        approval_id=str(row["approval_id"]),
        plan_id=str(row["plan_id"]),
        claim_id=str(row["claim_id"]),
        status=ApprovalStatus(str(row["status"])),
        decided_by=str(row["decided_by"]) if row["decided_by"] is not None else None,
        reason=str(row["reason"]) if row["reason"] is not None else None,
        decided_at=_timestamp(decided_at) if isinstance(decided_at, datetime) else None,
    )


def _timestamp(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("Stored execution timestamp is invalid")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
