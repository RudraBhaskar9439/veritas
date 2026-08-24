import asyncio
import base64
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from veritas_runtime.auth.models import GoogleIdentity, OAuthTokenSet, WorkspaceCredentialRecord
from veritas_runtime.auth.routes import (
    LOCAL_COOKIE_NAME,
    LOCAL_SESSION_COOKIE_NAME,
    PRODUCTION_COOKIE_NAME,
    create_google_auth_router,
)
from veritas_runtime.auth.service import GoogleConnectionService, InvalidAuthorizationAttempt
from veritas_runtime.auth.sessions import ApplicationSessionCodec
from veritas_runtime.auth.storage import EncryptedCredentialVault
from veritas_runtime.auth.tickets import AuthorizationTicketCodec

NOW = datetime(2026, 8, 21, 2, 0, tzinfo=UTC)


class FakeOAuth:
    def __init__(self) -> None:
        self.exchange_calls = 0
        self.last_verifier: str | None = None

    def authorization_url(self, state: str, code_verifier: str) -> str:
        self.last_verifier = code_verifier
        return f"https://accounts.example.test/authorize?{urlencode({'state': state})}"

    async def exchange_code(self, code: str, code_verifier: str) -> OAuthTokenSet:
        self.exchange_calls += 1
        assert code == "google-code"
        assert code_verifier == self.last_verifier
        return OAuthTokenSet(
            access_token="access-secret",
            refresh_token="refresh-secret",
            expires_at=NOW + timedelta(hours=1),
            scopes=("openid", "scope-a"),
        )

    async def fetch_identity(self, access_token: str) -> GoogleIdentity:
        assert access_token == "access-secret"
        return GoogleIdentity("subject-1", "owner@example.test")


class MemoryAttempts:
    def __init__(self) -> None:
        self.unused: dict[str, datetime] = {}

    async def issue(self, state_hash: str, expires_at: datetime) -> None:
        self.unused[state_hash] = expires_at

    async def consume(self, state_hash: str, now: datetime) -> bool:
        expiry = self.unused.pop(state_hash, None)
        return expiry is not None and expiry >= now


class MemoryCredentials:
    def __init__(self) -> None:
        self.records: dict[str, WorkspaceCredentialRecord] = {}

    async def upsert(self, record: WorkspaceCredentialRecord) -> None:
        self.records[record.subject] = record

    async def get(self, subject: str) -> WorkspaceCredentialRecord | None:
        return self.records.get(subject)

    async def delete(self, subject: str) -> None:
        self.records.pop(subject, None)


class TestCipher:
    key_resource = "test-key"

    async def encrypt(self, plaintext: bytes) -> bytes:
        return b"cipher:" + base64.urlsafe_b64encode(plaintext)

    async def decrypt(self, ciphertext: bytes) -> bytes:
        return base64.urlsafe_b64decode(ciphertext.removeprefix(b"cipher:"))


def _service() -> tuple[GoogleConnectionService, FakeOAuth, MemoryCredentials]:
    oauth = FakeOAuth()
    credentials = MemoryCredentials()
    return (
        GoogleConnectionService(
            oauth,
            AuthorizationTicketCodec(bytes(range(32))),
            MemoryAttempts(),
            EncryptedCredentialVault(TestCipher(), credentials),
        ),
        oauth,
        credentials,
    )


def _state(authorization_url: str) -> str:
    return parse_qs(urlsplit(authorization_url).query)["state"][0]


def test_connection_service_completes_once_and_stores_encrypted_tokens() -> None:
    service, oauth, credentials = _service()

    async def scenario() -> None:
        start = await service.start("/integrations/google?tab=workspace", NOW)
        state = _state(start.authorization_url)
        account = await service.complete("google-code", state, start.browser_ticket, NOW)

        assert account.subject == "subject-1"
        assert account.return_to == "/integrations/google?tab=workspace"
        record = credentials.records[account.subject]
        assert b"access-secret" not in record.encrypted_payload

        with pytest.raises(InvalidAuthorizationAttempt, match="already consumed"):
            await service.complete("google-code", state, start.browser_ticket, NOW)

    asyncio.run(scenario())
    assert oauth.exchange_calls == 1


def test_connection_service_cancels_and_consumes_denied_attempt() -> None:
    service, oauth, _ = _service()

    async def scenario() -> None:
        start = await service.start("/integrations/google", NOW)
        state = _state(start.authorization_url)
        assert await service.cancel(state, start.browser_ticket, NOW) == "/integrations/google"
        with pytest.raises(InvalidAuthorizationAttempt, match="already consumed"):
            await service.cancel(state, start.browser_ticket, NOW)

    asyncio.run(scenario())
    assert oauth.exchange_calls == 0


def test_connection_service_rejects_state_tampering_and_unsafe_return_path() -> None:
    service, oauth, _ = _service()

    async def scenario() -> None:
        for unsafe in ("https://attacker.test", "//attacker.test/path"):
            with pytest.raises(ValueError, match="application-relative"):
                await service.start(unsafe, NOW)

        start = await service.start("/safe", NOW)
        with pytest.raises(InvalidAuthorizationAttempt, match="does not match"):
            await service.complete("google-code", "attacker-state", start.browser_ticket, NOW)
        assert oauth.exchange_calls == 0

        account = await service.complete(
            "google-code", _state(start.authorization_url), start.browser_ticket, NOW
        )
        assert account.return_to == "/safe"

        expired = await service.start("/safe", NOW)
        with pytest.raises(InvalidAuthorizationAttempt, match="ticket is invalid"):
            await service.complete(
                "google-code",
                _state(expired.authorization_url),
                expired.browser_ticket,
                NOW + timedelta(minutes=11),
            )

    asyncio.run(scenario())


def _app(
    service: GoogleConnectionService | None,
    secure_cookie: bool = False,
    session_codec: ApplicationSessionCodec | None = None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(
        create_google_auth_router(
            service,
            secure_cookie=secure_cookie,
            session_codec=session_codec,
        )
    )
    return app


def test_routes_fail_closed_when_unconfigured() -> None:
    client = TestClient(_app(None))

    configuration = client.get("/api/v1/integrations/google/configuration")
    assert configuration.status_code == 200
    assert configuration.json()["configured"] is False
    assert configuration.json()["scopeCount"] > 0
    assert client.get("/api/v1/auth/google/start").status_code == 503
    assert (
        client.get("/api/v1/auth/google/callback", params={"code": "c", "state": "s"}).status_code
        == 503
    )


def test_routes_set_hardened_cookie_and_complete_callback() -> None:
    service, _, credentials = _service()
    client = TestClient(_app(service))

    start = client.get(
        "/api/v1/auth/google/start",
        params={"returnTo": "/command-center?incident=123"},
        follow_redirects=False,
    )
    assert start.status_code == 307
    assert start.headers["Cache-Control"] == "no-store"
    assert "HttpOnly" in start.headers["set-cookie"]
    assert "SameSite=lax" in start.headers["set-cookie"]
    assert "Secure" not in start.headers["set-cookie"]
    state = _state(start.headers["location"])

    callback = client.get(
        "/api/v1/auth/google/callback",
        params={"code": "google-code", "state": state},
        follow_redirects=False,
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == "/command-center?incident=123&google=connected"
    assert "subject-1" in credentials.records
    assert client.cookies.get(LOCAL_COOKIE_NAME) is None


def test_routes_issue_authenticated_session_and_logout() -> None:
    service, _, _ = _service()
    client = TestClient(_app(service, session_codec=ApplicationSessionCodec(bytes(range(32)))))
    start = client.get("/api/v1/auth/google/start", follow_redirects=False)
    state = _state(start.headers["location"])

    callback = client.get(
        "/api/v1/auth/google/callback",
        params={"code": "google-code", "state": state},
        follow_redirects=False,
    )

    assert callback.status_code == 303
    assert client.cookies.get(LOCAL_SESSION_COOKIE_NAME) is not None
    session = client.get("/api/v1/auth/session")
    assert session.status_code == 200
    assert session.json() == {"subject": "subject-1", "email": "owner@example.test"}

    logout = client.post("/api/v1/auth/logout")
    assert logout.status_code == 204
    assert client.cookies.get(LOCAL_SESSION_COOKIE_NAME) is None
    assert client.get("/api/v1/auth/session").status_code == 401


def test_routes_reject_bad_inputs_and_production_cookie_is_host_only() -> None:
    service, _, _ = _service()
    client = TestClient(_app(service))
    assert (
        client.get(
            "/api/v1/auth/google/start",
            params={"returnTo": "https://attacker.test"},
            follow_redirects=False,
        ).status_code
        == 400
    )
    assert (
        client.get(
            "/api/v1/auth/google/callback",
            params={"code": "google-code", "state": "state"},
        ).status_code
        == 400
    )

    secure_client = TestClient(_app(service, secure_cookie=True), base_url="https://veritas.test")
    response = secure_client.get("/api/v1/auth/google/start", follow_redirects=False)
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{PRODUCTION_COOKIE_NAME}=")
    assert "Secure" in cookie
    assert "HttpOnly" in cookie


def test_routes_handle_consent_denial_without_leaving_a_replayable_cookie() -> None:
    service, oauth, credentials = _service()
    client = TestClient(_app(service))
    start = client.get("/api/v1/auth/google/start", follow_redirects=False)
    state = _state(start.headers["location"])

    denied = client.get(
        "/api/v1/auth/google/callback",
        params={"error": "access_denied", "state": state},
        follow_redirects=False,
    )

    assert denied.status_code == 303
    assert denied.headers["location"] == "/integrations/google?google=denied"
    assert client.cookies.get(LOCAL_COOKIE_NAME) is None
    assert oauth.exchange_calls == 0
    assert credentials.records == {}


def test_routes_clear_ticket_when_callback_is_incomplete() -> None:
    service, _, _ = _service()
    client = TestClient(_app(service))
    start = client.get("/api/v1/auth/google/start", follow_redirects=False)
    state = _state(start.headers["location"])

    incomplete = client.get(
        "/api/v1/auth/google/callback",
        params={"state": state},
        follow_redirects=False,
    )

    assert incomplete.status_code == 400
    assert incomplete.headers["Cache-Control"] == "no-store"
    assert client.cookies.get(LOCAL_COOKIE_NAME) is None
