import asyncio

import pytest
from pydantic import SecretStr

import veritas_runtime.database_runtime as database_runtime
from veritas_runtime.database_runtime import (
    CloudSqlIamConnectionFactory,
    build_database_runtime,
)
from veritas_runtime.settings import Settings


class FakeConnector:
    def __init__(self) -> None:
        self.connect_calls: list[tuple[str, str, dict[str, object]]] = []
        self.closed = False

    async def connect_async(self, instance: str, driver: str, **kwargs: object) -> object:
        self.connect_calls.append((instance, driver, kwargs))
        return object()

    async def close_async(self) -> None:
        self.closed = True


def test_database_runtime_prefers_explicit_url_for_local_and_test() -> None:
    runtime = build_database_runtime(
        Settings(database_url=SecretStr("sqlite+aiosqlite:///:memory:"))
    )

    assert runtime is not None
    assert runtime.cloud_sql is None
    assert build_database_runtime(Settings()) is None
    asyncio.run(runtime.close())


def test_cloud_sql_runtime_uses_lazy_automatic_iam_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector()

    async def create_connector(**kwargs: object) -> FakeConnector:
        assert kwargs["enable_iam_auth"] is True
        assert kwargs["refresh_strategy"] == "LAZY"
        return connector

    monkeypatch.setattr(database_runtime, "create_async_connector", create_connector)
    factory = CloudSqlIamConnectionFactory(
        "project:us-central1:instance",
        "veritas",
        "service@project.iam",
    )

    async def scenario() -> None:
        await factory.connect()
        await factory.connect()
        await factory.close()

    asyncio.run(scenario())
    assert len(connector.connect_calls) == 2
    instance, driver, kwargs = connector.connect_calls[0]
    assert instance == "project:us-central1:instance"
    assert driver == "asyncpg"
    assert kwargs == {
        "user": "service@project.iam",
        "db": "veritas",
        "enable_iam_auth": True,
        "statement_cache_size": 0,
    }
    assert connector.closed is True


def test_cloud_sql_runtime_builds_without_opening_a_connection() -> None:
    runtime = build_database_runtime(
        Settings(
            cloud_sql_instance="project:us-central1:instance",
            cloud_sql_database="veritas",
            cloud_sql_user="service@project.iam",
        )
    )

    assert runtime is not None
    assert runtime.cloud_sql is not None
    asyncio.run(runtime.close())


def test_cloud_sql_factory_rejects_incomplete_identity() -> None:
    with pytest.raises(ValueError, match="incomplete"):
        CloudSqlIamConnectionFactory("", "veritas", "service@project.iam")
