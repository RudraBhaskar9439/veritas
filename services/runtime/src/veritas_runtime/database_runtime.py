from dataclasses import dataclass
from typing import Any, Protocol, cast

from google.cloud.sql.connector import (
    IPTypes,
    create_async_connector,
)
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from veritas_runtime.settings import Settings


class AsyncCloudSqlConnector(Protocol):
    async def connect_async(
        self,
        instance_connection_string: str,
        driver: str,
        **kwargs: Any,
    ) -> Any: ...

    async def close_async(self) -> None: ...


class CloudSqlIamConnectionFactory:
    def __init__(self, instance: str, database: str, user: str) -> None:
        if not all((instance, database, user)):
            raise ValueError("Cloud SQL IAM connection settings are incomplete")
        self._instance = instance
        self._database = database
        self._user = user
        self._connector: AsyncCloudSqlConnector | None = None

    async def connect(self) -> Any:
        if self._connector is None:
            self._connector = cast(
                AsyncCloudSqlConnector,
                await create_async_connector(
                    ip_type=IPTypes.PUBLIC,
                    enable_iam_auth=True,
                    refresh_strategy="LAZY",
                ),
            )
        return await self._connector.connect_async(
            self._instance,
            "asyncpg",
            user=self._user,
            db=self._database,
            enable_iam_auth=True,
            statement_cache_size=0,
        )

    async def close(self) -> None:
        if self._connector is not None:
            await self._connector.close_async()
            self._connector = None


@dataclass(frozen=True)
class DatabaseRuntime:
    engine: AsyncEngine
    cloud_sql: CloudSqlIamConnectionFactory | None = None

    async def close(self) -> None:
        await self.engine.dispose()
        if self.cloud_sql is not None:
            await self.cloud_sql.close()


def build_database_runtime(settings: Settings) -> DatabaseRuntime | None:
    if settings.database_url is not None:
        return DatabaseRuntime(
            create_async_engine(
                settings.database_url.get_secret_value(),
                pool_pre_ping=True,
                pool_recycle=1_800,
            )
        )
    if not settings.database_configured:
        return None
    assert settings.cloud_sql_instance is not None
    assert settings.cloud_sql_user is not None
    cloud_sql = CloudSqlIamConnectionFactory(
        settings.cloud_sql_instance,
        settings.cloud_sql_database,
        settings.cloud_sql_user,
    )
    return DatabaseRuntime(
        create_async_engine(
            "postgresql+asyncpg://",
            async_creator=cloud_sql.connect,
            pool_pre_ping=True,
            pool_recycle=1_800,
        ),
        cloud_sql,
    )
