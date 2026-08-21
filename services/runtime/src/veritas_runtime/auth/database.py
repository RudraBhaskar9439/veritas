from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import Column, DateTime, LargeBinary, MetaData, String, Table, delete, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from veritas_runtime.auth.models import WorkspaceCredentialRecord

metadata = MetaData()

workspace_credentials = Table(
    "workspace_credentials",
    metadata,
    Column("subject", String(255), primary_key=True),
    Column("email", String(320), nullable=False),
    Column("encrypted_payload", LargeBinary, nullable=False),
    Column("key_resource", String(1024), nullable=False),
    Column("scopes", String, nullable=False),
    Column("connected_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

oauth_authorization_attempts = Table(
    "oauth_authorization_attempts",
    metadata,
    Column("state_hash", String(64), primary_key=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


class AuthorizationAttemptStore(Protocol):
    async def issue(self, state_hash: str, expires_at: datetime) -> None: ...

    async def consume(self, state_hash: str, now: datetime) -> bool: ...


class SqlAuthRepository:
    """PostgreSQL credential and one-time OAuth attempt persistence."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def upsert(self, record: WorkspaceCredentialRecord) -> None:
        values = {
            "subject": record.subject,
            "email": record.email,
            "encrypted_payload": record.encrypted_payload,
            "key_resource": record.key_resource,
            "scopes": "\n".join(record.scopes),
            "connected_at": record.connected_at,
            "updated_at": record.updated_at,
        }
        async with self._engine.begin() as connection:
            if self._engine.dialect.name == "sqlite":
                sqlite_statement = sqlite_insert(workspace_credentials).values(**values)
                sqlite_statement = sqlite_statement.on_conflict_do_update(
                    index_elements=[workspace_credentials.c.subject],
                    set_={
                        "email": sqlite_statement.excluded.email,
                        "encrypted_payload": sqlite_statement.excluded.encrypted_payload,
                        "key_resource": sqlite_statement.excluded.key_resource,
                        "scopes": sqlite_statement.excluded.scopes,
                        "updated_at": sqlite_statement.excluded.updated_at,
                    },
                )
                await connection.execute(sqlite_statement)
            else:
                postgres_statement = postgres_insert(workspace_credentials).values(**values)
                postgres_statement = postgres_statement.on_conflict_do_update(
                    index_elements=[workspace_credentials.c.subject],
                    set_={
                        "email": postgres_statement.excluded.email,
                        "encrypted_payload": postgres_statement.excluded.encrypted_payload,
                        "key_resource": postgres_statement.excluded.key_resource,
                        "scopes": postgres_statement.excluded.scopes,
                        "updated_at": postgres_statement.excluded.updated_at,
                    },
                )
                await connection.execute(postgres_statement)

    async def get(self, subject: str) -> WorkspaceCredentialRecord | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        select(workspace_credentials).where(
                            workspace_credentials.c.subject == subject
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return WorkspaceCredentialRecord(
            subject=row["subject"],
            email=row["email"],
            encrypted_payload=row["encrypted_payload"],
            key_resource=row["key_resource"],
            scopes=tuple(row["scopes"].splitlines()),
            connected_at=row["connected_at"],
            updated_at=row["updated_at"],
        )

    async def delete(self, subject: str) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                delete(workspace_credentials).where(workspace_credentials.c.subject == subject)
            )

    async def issue(self, state_hash: str, expires_at: datetime) -> None:
        async with self._engine.begin() as connection:
            values = {
                "state_hash": state_hash,
                "expires_at": expires_at,
                "created_at": datetime.now(UTC),
            }
            if self._engine.dialect.name == "sqlite":
                sqlite_statement = sqlite_insert(oauth_authorization_attempts).values(**values)
                sqlite_statement = sqlite_statement.on_conflict_do_nothing(
                    index_elements=[oauth_authorization_attempts.c.state_hash]
                )
                result = await connection.execute(sqlite_statement)
            else:
                postgres_statement = postgres_insert(oauth_authorization_attempts).values(**values)
                postgres_statement = postgres_statement.on_conflict_do_nothing(
                    index_elements=[oauth_authorization_attempts.c.state_hash]
                )
                result = await connection.execute(postgres_statement)
        if result.rowcount != 1:
            raise RuntimeError("OAuth authorization state collision")

    async def consume(self, state_hash: str, now: datetime) -> bool:
        statement = (
            delete(oauth_authorization_attempts)
            .where(
                oauth_authorization_attempts.c.state_hash == state_hash,
                oauth_authorization_attempts.c.expires_at >= now,
            )
            .returning(oauth_authorization_attempts.c.state_hash)
        )
        async with self._engine.begin() as connection:
            result = await connection.execute(statement)
        return result.scalar_one_or_none() is not None
