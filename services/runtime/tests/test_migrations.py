import asyncio
from pathlib import Path

import pytest

from veritas_runtime.migrations import (
    Migration,
    _connect,
    apply_migrations,
    discover_migrations,
    migration_directory,
)
from veritas_runtime.settings import Settings


class FakeMigrationConnection:
    def __init__(self, recorded: dict[str, str] | None = None) -> None:
        self.recorded = recorded or {}
        self.executed: list[tuple[str, tuple[object, ...]]] = []

    async def execute(self, query: str, *args: object) -> str:
        self.executed.append((query, args))
        return "OK"

    async def fetchval(self, query: str, *args: object) -> object:
        del query
        return self.recorded.get(str(args[0]))

    async def close(self) -> None:
        return None


def test_discovers_migrations_in_lexical_order(tmp_path: Path) -> None:
    (tmp_path / "0002_second.sql").write_text("CREATE TABLE second(id INT);", encoding="utf-8")
    (tmp_path / "0001_first.sql").write_text(
        "BEGIN; CREATE TABLE first(id INT); COMMIT;",
        encoding="utf-8",
    )

    migrations = discover_migrations(tmp_path)

    assert [item.name for item in migrations] == ["0001_first.sql", "0002_second.sql"]
    assert all(len(item.checksum) == 64 for item in migrations)


def test_discovery_rejects_empty_or_malformed_sets(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="no migrations"):
        discover_migrations(tmp_path)

    (tmp_path / "not-versioned.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(RuntimeError, match="invalid migration filename"):
        discover_migrations(tmp_path)


def test_packaged_migrations_and_database_configuration_are_required() -> None:
    assert (migration_directory() / "0014_thread_bound_email_routing.sql").is_file()

    with pytest.raises(RuntimeError, match="database configuration is required"):
        asyncio.run(_connect(Settings()))


def test_applies_each_pending_migration_with_ledger_in_same_transaction() -> None:
    migration = Migration("0001_first.sql", "a" * 64, "BEGIN; CREATE TABLE first(id INT); COMMIT;")
    connection = FakeMigrationConnection()

    applied = asyncio.run(apply_migrations(connection, (migration,)))

    assert applied == ("0001_first.sql",)
    script = connection.executed[-2][0]
    assert script.startswith("BEGIN;\nCREATE TABLE first(id INT);")
    assert "INSERT INTO veritas_schema_migrations" in script
    assert script.endswith("COMMIT;")
    assert "pg_advisory_unlock" in connection.executed[-1][0]


def test_replay_skips_matching_migration() -> None:
    migration = Migration("0001_first.sql", "a" * 64, "SELECT 1;")
    connection = FakeMigrationConnection({migration.name: migration.checksum})

    assert asyncio.run(apply_migrations(connection, (migration,))) == ()
    assert not any(
        "INSERT INTO veritas_schema_migrations" in query for query, _ in connection.executed
    )


def test_checksum_drift_fails_closed_and_releases_lock() -> None:
    migration = Migration("0001_first.sql", "a" * 64, "SELECT 1;")
    connection = FakeMigrationConnection({migration.name: "b" * 64})

    with pytest.raises(RuntimeError, match="checksum mismatch"):
        asyncio.run(apply_migrations(connection, (migration,)))

    assert "pg_advisory_unlock" in connection.executed[-1][0]
