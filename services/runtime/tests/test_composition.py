import asyncio
import base64
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from pydantic import SecretStr
from starlette.requests import Request

import veritas_runtime.composition as composition
from veritas_runtime.auth.sessions import ApplicationSessionCodec, SessionPrincipal
from veritas_runtime.composition import (
    approval_actor_resolver,
    build_api_components,
    operation_actor_resolver,
    session_principal_resolver,
    subject_resolver,
)
from veritas_runtime.repairs.models import ApprovalActorKind
from veritas_runtime.settings import Settings


def _key() -> str:
    return base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url=SecretStr("sqlite+aiosqlite:///:memory:"),
        google_oauth_client_id="client-id",
        google_oauth_client_secret=SecretStr("client-secret"),
        google_oauth_redirect_uri="https://veritas.test/api/v1/auth/google/callback",
        google_kms_credentials_key="projects/p/locations/l/keyRings/r/cryptoKeys/k",
        oauth_ticket_key=SecretStr(_key()),
        application_session_key=SecretStr(_key()),
        snapshot_bucket="snapshot-bucket",
    )


class MemorySnapshots:
    async def read(self, _snapshot: object) -> bytes:
        return b"{}"


def _request(cookie: str | None) -> Request:
    headers = [] if cookie is None else [(b"cookie", f"veritas_session={cookie}".encode())]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "query_string": b"",
            "server": ("test", 443),
            "client": ("test", 1),
            "scheme": "https",
        }
    )


def test_composition_fails_closed_until_every_runtime_dependency_exists() -> None:
    assert build_api_components(Settings()) is None


def test_composition_builds_all_existing_production_services_without_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(composition, "GcsSnapshotObjectStore", lambda _bucket: MemorySnapshots())

    components = build_api_components(_settings())

    assert components is not None
    assert components.auth.service is not None
    assert components.packets is not None
    assert components.impact is not None
    assert components.repairs is not None
    assert components.execution is not None
    assert components.verification is not None
    assert components.operations is not None
    asyncio.run(components.close())


def test_session_resolvers_derive_subject_and_human_actor_from_signed_cookie() -> None:
    codec = ApplicationSessionCodec(bytes(range(32)))
    encoded = codec.encode(
        SessionPrincipal(
            subject="subject-1",
            email="owner@example.test",
            issued_at=datetime.now(UTC),
        )
    )
    request = _request(encoded)

    async def scenario() -> None:
        principal = await session_principal_resolver(codec, secure_cookie=False)(request)
        assert principal.subject == "subject-1"
        assert await subject_resolver(codec, secure_cookie=False)(request) == "subject-1"
        approval = await approval_actor_resolver(codec, secure_cookie=False)(request)
        assert approval.kind == ApprovalActorKind.HUMAN
        assert approval.principal == "owner@example.test"
        assert (
            await operation_actor_resolver(codec, secure_cookie=False)(request)
            == "owner@example.test"
        )

        with pytest.raises(HTTPException) as missing:
            await session_principal_resolver(codec, secure_cookie=False)(_request(None))
        assert missing.value.status_code == 401

        with pytest.raises(HTTPException) as tampered:
            await session_principal_resolver(codec, secure_cookie=False)(
                _request(encoded[:-1] + "x")
            )
        assert tampered.value.status_code == 401

    asyncio.run(scenario())
