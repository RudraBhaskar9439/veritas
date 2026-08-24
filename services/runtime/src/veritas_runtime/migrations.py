"""Checksum-pinned, single-writer PostgreSQL schema migration entrypoint."""

import asyncio
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import asyncpg  # type: ignore[import-untyped]

from veritas_runtime.database_runtime import CloudSqlIamConnectionFactory
from veritas_runtime.settings import Settings

_MIGRATION_NAME = re.compile(r"^\d{4}_[a-z0-9_]+\.sql$")
_ADVISORY_LOCK_ID = 8_642_021_576_274_901
_LEDGER_SQL = """
CREATE TABLE IF NOT EXISTS veritas_schema_migrations (
    name TEXT PRIMARY KEY,
    checksum CHAR(64) NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


class MigrationConnection(Protocol):
    async def execute(self, query: str, *args: object) -> str: ...

    async def fetchval(self, query: str, *args: object) -> object: ...

    async def close(self) -> None: ...


@dataclass(frozen=True)
class Migration:
    name: str
    checksum: str
    sql: str


def discover_migrations(directory: Path) -> tuple[Migration, ...]:
    migrations: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        if not _MIGRATION_NAME.fullmatch(path.name):
            raise RuntimeError(f"invalid migration filename: {path.name}")
        sql = path.read_text(encoding="utf-8")
        migrations.append(
            Migration(
                name=path.name,
                checksum=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
                sql=sql,
            )
        )
    if not migrations:
        raise RuntimeError(f"no migrations found in {directory}")
    return tuple(migrations)


def _transaction_body(sql: str) -> str:
    body = sql.strip()
    body = re.sub(r"^BEGIN\s*;\s*", "", body, count=1, flags=re.IGNORECASE)
    body = re.sub(r"\s*COMMIT\s*;\s*$", "", body, count=1, flags=re.IGNORECASE)
    return body.rstrip(";\n ") + ";"


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


async def apply_migrations(
    connection: MigrationConnection,
    migrations: tuple[Migration, ...],
) -> tuple[str, ...]:
    """Apply pending migrations under one session lock and reject checksum drift."""

    await connection.execute("SELECT pg_advisory_lock($1)", _ADVISORY_LOCK_ID)
    applied: list[str] = []
    try:
        await connection.execute(_LEDGER_SQL)
        for migration in migrations:
            recorded = await connection.fetchval(
                "SELECT checksum FROM veritas_schema_migrations WHERE name = $1",
                migration.name,
            )
            if recorded is not None:
                if str(recorded) != migration.checksum:
                    raise RuntimeError(f"migration checksum mismatch: {migration.name}")
                continue
            script = "\n".join(
                (
                    "BEGIN;",
                    _transaction_body(migration.sql),
                    (
                        "INSERT INTO veritas_schema_migrations(name, checksum) VALUES "
                        f"({_literal(migration.name)}, {_literal(migration.checksum)});"
                    ),
                    "COMMIT;",
                )
            )
            await connection.execute(script)
            applied.append(migration.name)
    finally:
        await connection.execute("SELECT pg_advisory_unlock($1)", _ADVISORY_LOCK_ID)
    return tuple(applied)


def migration_directory() -> Path:
    return Path(__file__).resolve().parents[2] / "migrations"


async def _connect(
    settings: Settings,
) -> tuple[MigrationConnection, CloudSqlIamConnectionFactory | None]:
    if settings.database_url is not None:
        dsn = settings.database_url.get_secret_value().replace(
            "postgresql+asyncpg://", "postgresql://", 1
        )
        return await asyncpg.connect(dsn), None
    if not settings.database_configured:
        raise RuntimeError("database configuration is required for migrations")
    assert settings.cloud_sql_instance is not None
    assert settings.cloud_sql_user is not None
    cloud_sql = CloudSqlIamConnectionFactory(
        settings.cloud_sql_instance,
        settings.cloud_sql_database,
        settings.cloud_sql_user,
    )
    return await cloud_sql.connect(), cloud_sql


async def run() -> None:
    settings = Settings()
    connection, cloud_sql = await _connect(settings)
    try:
        applied = await apply_migrations(connection, discover_migrations(migration_directory()))
        print(f"Veritas schema is current; applied {len(applied)} migration(s).")
    finally:
        await connection.close()
        if cloud_sql is not None:
            await cloud_sql.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
