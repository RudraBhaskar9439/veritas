import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

SESSION_VERSION = "v1"


class InvalidApplicationSession(ValueError):
    """Raised when a browser session cannot be authenticated."""


@dataclass(frozen=True)
class SessionPrincipal:
    subject: str
    email: str
    issued_at: datetime


class ApplicationSessionCodec:
    """Signs short-lived browser identities without exposing Google tokens."""

    def __init__(self, key: bytes, ttl: timedelta = timedelta(hours=12)) -> None:
        if len(key) != 32:
            raise ValueError("Application session key must contain exactly 32 bytes")
        if ttl <= timedelta(0) or ttl > timedelta(days=7):
            raise ValueError("Application session TTL must be between zero and seven days")
        self._key = key
        self._ttl = ttl

    @classmethod
    def from_base64(cls, encoded_key: str) -> "ApplicationSessionCodec":
        try:
            key = _decode_base64(encoded_key)
        except ValueError as error:
            raise ValueError("Application session key must be URL-safe base64") from error
        return cls(key)

    def encode(self, principal: SessionPrincipal) -> str:
        if not principal.subject or not principal.email:
            raise ValueError("Application session principal is incomplete")
        payload = json.dumps(
            {
                "email": principal.email,
                "issued_at": principal.issued_at.astimezone(UTC).isoformat(),
                "subject": principal.subject,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        encoded_payload = _encode_base64(payload)
        signature = hmac.new(
            self._key,
            f"{SESSION_VERSION}.{encoded_payload}".encode(),
            hashlib.sha256,
        ).digest()
        return f"{SESSION_VERSION}.{encoded_payload}.{_encode_base64(signature)}"

    def decode(self, encoded: str, now: datetime | None = None) -> SessionPrincipal:
        try:
            version, encoded_payload, encoded_signature = encoded.split(".", maxsplit=2)
            if version != SESSION_VERSION:
                raise InvalidApplicationSession("Unsupported application session version")
            signature = _decode_base64(encoded_signature)
            expected = hmac.new(
                self._key,
                f"{version}.{encoded_payload}".encode(),
                hashlib.sha256,
            ).digest()
            if not hmac.compare_digest(signature, expected):
                raise InvalidApplicationSession("Application session signature is invalid")
            payload = json.loads(_decode_base64(encoded_payload))
            principal = SessionPrincipal(
                subject=str(payload["subject"]),
                email=str(payload["email"]),
                issued_at=datetime.fromisoformat(str(payload["issued_at"])).astimezone(UTC),
            )
        except (
            ValueError,
            KeyError,
            TypeError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as error:
            if isinstance(error, InvalidApplicationSession):
                raise
            raise InvalidApplicationSession("Application session is invalid") from error
        if not principal.subject or not principal.email:
            raise InvalidApplicationSession("Application session principal is incomplete")
        resolved_now = (now or datetime.now(UTC)).astimezone(UTC)
        if principal.issued_at > resolved_now + timedelta(minutes=1):
            raise InvalidApplicationSession("Application session was issued in the future")
        if resolved_now - principal.issued_at > self._ttl:
            raise InvalidApplicationSession("Application session has expired")
        return principal


def _encode_base64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode_base64(value: str) -> bytes:
    decoded = base64.b64decode(
        _pad_base64(value),
        altchars=b"-_",
        validate=True,
    )
    if _encode_base64(decoded) != value:
        raise ValueError("Base64 value is not canonical")
    return decoded


def _pad_base64(value: str) -> str:
    return value + "=" * (-len(value) % 4)
