import asyncio
import hashlib
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from veritas_runtime.auth.oauth import (
    GOOGLE_AUTHORIZATION_ENDPOINT,
    GOOGLE_TOKEN_ENDPOINT,
    GOOGLE_USERINFO_ENDPOINT,
    GoogleOAuthConfig,
    GoogleOAuthGateway,
    OAuthExchangeError,
)

SCOPES = ("openid", "scope-a", "scope-b")
CONFIG = GoogleOAuthConfig(
    client_id="client-id",
    client_secret="client-secret",
    redirect_uri="https://api.example.test/api/v1/auth/google/callback",
    scopes=SCOPES,
)


def test_authorization_url_uses_offline_pkce_and_exact_scopes() -> None:
    verifier = "a" * 64
    url = GoogleOAuthGateway(CONFIG).authorization_url("csrf-state", verifier)
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == GOOGLE_AUTHORIZATION_ENDPOINT
    assert query["state"] == ["csrf-state"]
    assert query["access_type"] == ["offline"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["include_granted_scopes"] == ["true"]
    assert query["prompt"] == ["consent select_account"]
    assert query["scope"] == [" ".join(SCOPES)]
    expected_challenge = (
        __import__("base64")
        .urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    assert query["code_challenge"] == [expected_challenge]


def test_code_exchange_and_verified_identity() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if str(request.url) == GOOGLE_TOKEN_ENDPOINT:
            return httpx.Response(
                200,
                json={
                    "access_token": "access-secret",
                    "refresh_token": "refresh-secret",
                    "expires_in": 3600,
                    "scope": "scope-b openid scope-a",
                    "token_type": "Bearer",
                },
            )
        assert str(request.url) == GOOGLE_USERINFO_ENDPOINT
        return httpx.Response(
            200,
            json={"sub": "google-subject", "email": "owner@example.test", "email_verified": True},
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            gateway = GoogleOAuthGateway(CONFIG, client)
            tokens = await gateway.exchange_code("authorization-code", "pkce-verifier")
            identity = await gateway.fetch_identity(tokens.access_token)

        assert tokens.refresh_token == "refresh-secret"
        assert tokens.scopes == ("openid", "scope-a", "scope-b")
        assert identity.subject == "google-subject"
        assert identity.email == "owner@example.test"

    asyncio.run(scenario())
    assert len(seen) == 2
    assert seen[1].headers["Authorization"] == "Bearer access-secret"
    assert b"client-secret" in seen[0].content
    assert b"pkce-verifier" in seen[0].content


def test_refresh_rotates_access_token_and_preserves_refresh_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == GOOGLE_TOKEN_ENDPOINT
        assert b"grant_type=refresh_token" in request.content
        assert b"refresh_token=refresh-secret" in request.content
        return httpx.Response(
            200,
            json={
                "access_token": "refreshed-access",
                "expires_in": 3600,
                "scope": "scope-b openid scope-a",
                "token_type": "Bearer",
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            tokens = await GoogleOAuthGateway(CONFIG, client).refresh_access_token("refresh-secret")
        assert tokens.access_token == "refreshed-access"
        assert tokens.refresh_token == "refresh-secret"
        assert tokens.scopes == ("openid", "scope-a", "scope-b")

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"error": "invalid_grant"}, "rejected"),
        ({"access_token": "a", "expires_in": 1, "token_type": "MAC"}, "token type"),
        ({"access_token": "a", "expires_in": 0, "token_type": "Bearer"}, "lifetime"),
        (
            {"access_token": "a", "expires_in": 1, "token_type": "Bearer", "scope": "openid"},
            "required capability",
        ),
        (
            {"access_token": "a", "expires_in": 1, "token_type": "Bearer", "scope": 42},
            "granted scopes",
        ),
        (
            {
                "access_token": "a",
                "expires_in": 1,
                "token_type": "Bearer",
                "refresh_token": 42,
            },
            "refresh token",
        ),
    ],
)
def test_code_exchange_fails_closed(payload: dict[str, object], message: str) -> None:
    status = 400 if "error" in payload else 200

    async def scenario() -> None:
        transport = httpx.MockTransport(lambda _: httpx.Response(status, json=payload))
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(OAuthExchangeError, match=message):
                await GoogleOAuthGateway(CONFIG, client).exchange_code("code", "verifier")

    asyncio.run(scenario())


def test_invalid_json_and_unverified_identity_are_rejected() -> None:
    responses = iter(
        [
            httpx.Response(200, content=b"not-json"),
            httpx.Response(200, json={"sub": "s", "email": "e", "email_verified": False}),
        ]
    )

    async def scenario() -> None:
        transport = httpx.MockTransport(lambda _: next(responses))
        async with httpx.AsyncClient(transport=transport) as client:
            gateway = GoogleOAuthGateway(CONFIG, client)
            with pytest.raises(OAuthExchangeError, match="invalid OAuth response"):
                await gateway.exchange_code("code", "verifier")
            with pytest.raises(OAuthExchangeError, match="not verified"):
                await gateway.fetch_identity("access")

    asyncio.run(scenario())
