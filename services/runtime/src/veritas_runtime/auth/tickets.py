import base64
import json
from datetime import UTC, datetime, timedelta

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from veritas_runtime.auth.models import AuthorizationTicket

TICKET_VERSION = "v1"
TICKET_AAD = b"veritas:google-oauth-ticket:v1"


class InvalidAuthorizationTicket(ValueError):
    """Raised when a browser authorization ticket cannot be trusted."""


class AuthorizationTicketCodec:
    def __init__(self, key: bytes, ttl: timedelta = timedelta(minutes=10)) -> None:
        if len(key) != 32:
            raise ValueError("OAuth ticket key must contain exactly 32 bytes")
        self._cipher = AESGCM(key)
        self._ttl = ttl

    @classmethod
    def from_base64(cls, encoded_key: str) -> "AuthorizationTicketCodec":
        try:
            key = base64.b64decode(
                _pad_base64(encoded_key),
                altchars=b"-_",
                validate=True,
            )
        except ValueError as error:
            raise ValueError("OAuth ticket key must be URL-safe base64") from error
        return cls(key)

    def encode(self, ticket: AuthorizationTicket, nonce: bytes) -> str:
        if len(nonce) != 12:
            raise ValueError("OAuth ticket nonce must contain exactly 12 bytes")
        payload = json.dumps(
            {
                "state": ticket.state,
                "code_verifier": ticket.code_verifier,
                "return_to": ticket.return_to,
                "issued_at": ticket.issued_at.astimezone(UTC).isoformat(),
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        encrypted = nonce + self._cipher.encrypt(nonce, payload, TICKET_AAD)
        return f"{TICKET_VERSION}.{_encode_base64(encrypted)}"

    def decode(self, encoded_ticket: str, now: datetime) -> AuthorizationTicket:
        try:
            version, encoded_payload = encoded_ticket.split(".", maxsplit=1)
            if version != TICKET_VERSION:
                raise InvalidAuthorizationTicket("Unsupported OAuth ticket version")
            encrypted = base64.urlsafe_b64decode(_pad_base64(encoded_payload))
            nonce, ciphertext = encrypted[:12], encrypted[12:]
            payload = json.loads(self._cipher.decrypt(nonce, ciphertext, TICKET_AAD))
            ticket = AuthorizationTicket(
                state=str(payload["state"]),
                code_verifier=str(payload["code_verifier"]),
                return_to=str(payload["return_to"]),
                issued_at=datetime.fromisoformat(str(payload["issued_at"])).astimezone(UTC),
            )
        except (InvalidTag, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            if isinstance(error, InvalidAuthorizationTicket):
                raise
            raise InvalidAuthorizationTicket("Invalid OAuth browser ticket") from error

        resolved_now = now.astimezone(UTC)
        if ticket.issued_at > resolved_now + timedelta(minutes=1):
            raise InvalidAuthorizationTicket("OAuth browser ticket was issued in the future")
        if resolved_now - ticket.issued_at > self._ttl:
            raise InvalidAuthorizationTicket("OAuth browser ticket has expired")
        return ticket


def _encode_base64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _pad_base64(value: str) -> str:
    return value + "=" * (-len(value) % 4)
