import base64
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx

from veritas_runtime.auth.models import GoogleIdentity, OAuthTokenSet

GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"


class OAuthExchangeError(RuntimeError):
    """A safe, non-secret-bearing OAuth failure."""


class GoogleOAuthPort(Protocol):
    def authorization_url(self, state: str, code_verifier: str) -> str: ...

    async def exchange_code(self, code: str, code_verifier: str) -> OAuthTokenSet: ...

    async def fetch_identity(self, access_token: str) -> GoogleIdentity: ...

    async def refresh_access_token(self, refresh_token: str) -> OAuthTokenSet: ...


@dataclass(frozen=True)
class GoogleOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: tuple[str, ...]


class GoogleOAuthGateway:
    def __init__(
        self,
        config: GoogleOAuthConfig,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._client = client

    def authorization_url(self, state: str, code_verifier: str) -> str:
        parameters = {
            "access_type": "offline",
            "client_id": self._config.client_id,
            "code_challenge": _pkce_challenge(code_verifier),
            "code_challenge_method": "S256",
            "include_granted_scopes": "true",
            "prompt": "consent select_account",
            "redirect_uri": self._config.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self._config.scopes),
            "state": state,
        }
        return f"{GOOGLE_AUTHORIZATION_ENDPOINT}?{urlencode(parameters)}"

    async def exchange_code(self, code: str, code_verifier: str) -> OAuthTokenSet:
        response = await self._request(
            "POST",
            GOOGLE_TOKEN_ENDPOINT,
            data={
                "client_id": self._config.client_id,
                "client_secret": self._config.client_secret,
                "code": code,
                "code_verifier": code_verifier,
                "grant_type": "authorization_code",
                "redirect_uri": self._config.redirect_uri,
            },
        )
        payload = _safe_json(response)
        if response.is_error:
            raise OAuthExchangeError("Google rejected the authorization code")

        access_token = _required_string(payload, "access_token")
        token_type = _required_string(payload, "token_type")
        if token_type.casefold() != "bearer":
            raise OAuthExchangeError("Google returned an unsupported token type")
        expires_in = payload.get("expires_in")
        if not isinstance(expires_in, int) or expires_in <= 0:
            raise OAuthExchangeError("Google returned an invalid token lifetime")
        refresh_token = payload.get("refresh_token")
        if refresh_token is not None and not isinstance(refresh_token, str):
            raise OAuthExchangeError("Google returned an invalid refresh token")

        raw_scopes = payload.get("scope", " ".join(self._config.scopes))
        if not isinstance(raw_scopes, str):
            raise OAuthExchangeError("Google returned invalid granted scopes")
        granted_scopes = tuple(sorted(set(raw_scopes.split())))
        if not set(self._config.scopes).issubset(granted_scopes):
            raise OAuthExchangeError("Google did not grant every required capability")

        return OAuthTokenSet(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
            scopes=granted_scopes,
            token_type="Bearer",
        )

    async def fetch_identity(self, access_token: str) -> GoogleIdentity:
        response = await self._request(
            "GET",
            GOOGLE_USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        payload = _safe_json(response)
        if response.is_error:
            raise OAuthExchangeError("Google identity verification failed")
        if payload.get("email_verified") is not True:
            raise OAuthExchangeError("Google account email is not verified")
        return GoogleIdentity(
            subject=_required_string(payload, "sub"),
            email=_required_string(payload, "email"),
        )

    async def refresh_access_token(self, refresh_token: str) -> OAuthTokenSet:
        if not refresh_token:
            raise OAuthExchangeError("Google refresh token is missing")
        response = await self._request(
            "POST",
            GOOGLE_TOKEN_ENDPOINT,
            data={
                "client_id": self._config.client_id,
                "client_secret": self._config.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        payload = _safe_json(response)
        if response.is_error:
            raise OAuthExchangeError("Google rejected the refresh token")
        access_token = _required_string(payload, "access_token")
        token_type = _required_string(payload, "token_type")
        if token_type.casefold() != "bearer":
            raise OAuthExchangeError("Google returned an unsupported token type")
        expires_in = payload.get("expires_in")
        if not isinstance(expires_in, int) or expires_in <= 0:
            raise OAuthExchangeError("Google returned an invalid token lifetime")
        raw_scopes = payload.get("scope", " ".join(self._config.scopes))
        if not isinstance(raw_scopes, str):
            raise OAuthExchangeError("Google returned invalid granted scopes")
        granted_scopes = tuple(sorted(set(raw_scopes.split())))
        if not set(self._config.scopes).issubset(granted_scopes):
            raise OAuthExchangeError("Google refresh omitted a required capability")
        rotated_refresh_token = payload.get("refresh_token")
        if rotated_refresh_token is not None and not isinstance(rotated_refresh_token, str):
            raise OAuthExchangeError("Google returned an invalid refresh token")
        return OAuthTokenSet(
            access_token=access_token,
            refresh_token=rotated_refresh_token or refresh_token,
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
            scopes=granted_scopes,
            token_type="Bearer",
        )

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self._client is not None:
            return await self._client.request(method, url, **kwargs)
        async with httpx.AsyncClient(timeout=10) as client:
            return await client.request(method, url, **kwargs)


def _pkce_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _safe_json(response: httpx.Response) -> Mapping[str, object]:
    try:
        payload = response.json()
    except ValueError as error:
        raise OAuthExchangeError("Google returned an invalid OAuth response") from error
    if not isinstance(payload, dict):
        raise OAuthExchangeError("Google returned an invalid OAuth response")
    return payload


def _required_string(payload: Mapping[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise OAuthExchangeError(f"Google OAuth response omitted {field}")
    return value
