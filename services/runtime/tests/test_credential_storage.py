import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from veritas_runtime.auth.database import SqlAuthRepository, metadata
from veritas_runtime.auth.models import GoogleIdentity, OAuthTokenSet, WorkspaceCredentialRecord
from veritas_runtime.auth.storage import (
    CredentialIntegrityError,
    EncryptedCredentialVault,
    GoogleKmsCredentialCipher,
)

NOW = datetime(2026, 8, 21, 2, 0, tzinfo=UTC)


class MemoryRepository:
    def __init__(self) -> None:
        self.records: dict[str, WorkspaceCredentialRecord] = {}

    async def upsert(self, record: WorkspaceCredentialRecord) -> None:
        self.records[record.subject] = record

    async def get(self, subject: str) -> WorkspaceCredentialRecord | None:
        return self.records.get(subject)

    async def delete(self, subject: str) -> None:
        self.records.pop(subject, None)


class ReversingCipher:
    key_resource = "kms/test/key"

    async def encrypt(self, plaintext: bytes) -> bytes:
        return b"encrypted:" + plaintext[::-1]

    async def decrypt(self, ciphertext: bytes) -> bytes:
        return ciphertext.removeprefix(b"encrypted:")[::-1]


def _tokens(refresh_token: str | None = "refresh-secret") -> OAuthTokenSet:
    return OAuthTokenSet(
        access_token="access-secret",
        refresh_token=refresh_token,
        expires_at=NOW + timedelta(hours=1),
        scopes=("openid", "scope-a"),
    )


def test_vault_persists_only_ciphertext_and_round_trips() -> None:
    repository = MemoryRepository()
    vault = EncryptedCredentialVault(ReversingCipher(), repository)
    identity = GoogleIdentity("subject-1", "owner@example.test")

    async def scenario() -> None:
        await vault.store(identity, _tokens())
        stored = repository.records[identity.subject]
        assert b"access-secret" not in stored.encrypted_payload
        assert b"refresh-secret" not in stored.encrypted_payload
        assert stored.key_resource == "kms/test/key"
        assert await vault.load(identity.subject) == (identity, _tokens())

        connected_at = stored.connected_at
        await vault.store(identity, _tokens("rotated-refresh"))
        assert repository.records[identity.subject].connected_at == connected_at
        await vault.delete(identity.subject)
        assert await vault.load(identity.subject) is None

    asyncio.run(scenario())


def test_vault_requires_offline_token_and_detects_record_swaps() -> None:
    repository = MemoryRepository()
    vault = EncryptedCredentialVault(ReversingCipher(), repository)
    identity = GoogleIdentity("subject-1", "owner@example.test")

    async def scenario() -> None:
        with pytest.raises(CredentialIntegrityError, match="refresh token"):
            await vault.store(identity, _tokens(None))
        await vault.store(identity, _tokens())
        record = repository.records[identity.subject]

        repository.records[identity.subject] = replace(record, email="attacker@example.test")
        with pytest.raises(CredentialIntegrityError, match="does not match"):
            await vault.load(identity.subject)

        repository.records[identity.subject] = replace(record, key_resource="kms/other/key")
        with pytest.raises(CredentialIntegrityError, match="key resource"):
            await vault.load(identity.subject)

        payload = json.loads(await ReversingCipher().decrypt(record.encrypted_payload))
        payload["key_resource"] = "kms/other/key"
        swapped_payload = await ReversingCipher().encrypt(json.dumps(payload).encode())
        repository.records[identity.subject] = replace(
            record,
            encrypted_payload=swapped_payload,
        )
        with pytest.raises(CredentialIntegrityError, match="does not match"):
            await vault.load(identity.subject)

        repository.records[identity.subject] = replace(record, encrypted_payload=b"encrypted:bad")
        with pytest.raises(CredentialIntegrityError, match="invalid"):
            await vault.load(identity.subject)

    asyncio.run(scenario())


class FakeKmsClient:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, object]]] = []

    async def encrypt(self, request: dict[str, object]) -> object:
        self.requests.append(("encrypt", request))
        return SimpleNamespace(ciphertext=b"kms-ciphertext")

    async def decrypt(self, request: dict[str, object]) -> object:
        self.requests.append(("decrypt", request))
        return SimpleNamespace(plaintext=b"kms-plaintext")


def test_google_kms_cipher_uses_named_key_and_enforces_payload_limit() -> None:
    client = FakeKmsClient()
    cipher = GoogleKmsCredentialCipher("projects/p/locations/l/keyRings/r/cryptoKeys/k", client)

    async def scenario() -> None:
        assert await cipher.encrypt(b"plain") == b"kms-ciphertext"
        assert await cipher.decrypt(b"cipher") == b"kms-plaintext"
        with pytest.raises(ValueError, match="KMS limit"):
            await cipher.encrypt(b"x" * 65_537)

    asyncio.run(scenario())
    assert client.requests[0][1]["plaintext"] == b"plain"
    assert client.requests[1][1]["ciphertext"] == b"cipher"


def test_google_kms_cipher_rejects_empty_responses() -> None:
    class EmptyClient(FakeKmsClient):
        async def encrypt(self, request: dict[str, object]) -> object:
            return SimpleNamespace(ciphertext=None)

        async def decrypt(self, request: dict[str, object]) -> object:
            return SimpleNamespace(plaintext=None)

    async def scenario() -> None:
        cipher = GoogleKmsCredentialCipher("key", EmptyClient())
        with pytest.raises(CredentialIntegrityError, match="no ciphertext"):
            await cipher.encrypt(b"plain")
        with pytest.raises(CredentialIntegrityError, match="no plaintext"):
            await cipher.decrypt(b"cipher")

    asyncio.run(scenario())


def test_sql_repository_upserts_credentials_and_consumes_state_once() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        repository = SqlAuthRepository(engine)
        record = WorkspaceCredentialRecord(
            subject="subject-1",
            email="owner@example.test",
            encrypted_payload=b"ciphertext",
            key_resource="kms/key",
            scopes=("openid", "scope-a"),
            connected_at=NOW,
            updated_at=NOW,
        )
        await repository.upsert(record)
        assert (await repository.get(record.subject)).encrypted_payload == b"ciphertext"  # type: ignore[union-attr]

        updated = replace(
            record, encrypted_payload=b"new-ciphertext", updated_at=NOW + timedelta(minutes=1)
        )
        await repository.upsert(updated)
        assert (await repository.get(record.subject)).encrypted_payload == b"new-ciphertext"  # type: ignore[union-attr]
        assert await repository.get("missing") is None

        await repository.issue("a" * 64, NOW + timedelta(minutes=10))
        with pytest.raises(RuntimeError, match="collision"):
            await repository.issue("a" * 64, NOW + timedelta(minutes=10))
        assert await repository.consume("a" * 64, NOW) is True
        assert await repository.consume("a" * 64, NOW) is False

        await repository.issue("b" * 64, NOW - timedelta(seconds=1))
        assert await repository.consume("b" * 64, NOW) is False
        await repository.delete(record.subject)
        assert await repository.get(record.subject) is None
        await engine.dispose()

    asyncio.run(scenario())
