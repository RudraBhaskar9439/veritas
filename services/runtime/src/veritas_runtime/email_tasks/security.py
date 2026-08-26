import asyncio
from typing import Protocol

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token


class InvalidPubSubIdentity(PermissionError):
    pass


class PubSubIdentityVerifier(Protocol):
    async def verify(self, authorization: str | None) -> None: ...


class GooglePubSubIdentityVerifier:
    def __init__(self, audience: str, service_account_email: str) -> None:
        if not audience.startswith("https://") or "@" not in service_account_email:
            raise ValueError("Pub/Sub OIDC verification configuration is invalid")
        self._audience = audience
        self._service_account_email = service_account_email.lower()

    async def verify(self, authorization: str | None) -> None:
        if not authorization or not authorization.startswith("Bearer "):
            raise InvalidPubSubIdentity("Pub/Sub bearer identity is required")
        token = authorization.removeprefix("Bearer ").strip()
        try:
            claims = await asyncio.to_thread(
                id_token.verify_oauth2_token,
                token,
                GoogleAuthRequest(),
                self._audience,
            )
        except Exception as error:
            raise InvalidPubSubIdentity("Pub/Sub bearer identity is invalid") from error
        email = claims.get("email") if isinstance(claims, dict) else None
        verified = claims.get("email_verified") if isinstance(claims, dict) else None
        if (
            not isinstance(email, str)
            or email.lower() != self._service_account_email
            or not verified
        ):
            raise InvalidPubSubIdentity("Pub/Sub service identity is not authorized")
