import base64
from datetime import UTC, datetime, timedelta

import pytest

from veritas_runtime.auth.sessions import (
    ApplicationSessionCodec,
    InvalidApplicationSession,
    SessionPrincipal,
)

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
KEY = bytes(range(32))


def _principal(issued_at: datetime = NOW) -> SessionPrincipal:
    return SessionPrincipal(
        subject="subject-1",
        email="owner@example.test",
        issued_at=issued_at,
    )


def test_application_session_round_trip_and_base64_constructor() -> None:
    encoded_key = base64.urlsafe_b64encode(KEY).decode().rstrip("=")
    codec = ApplicationSessionCodec.from_base64(encoded_key)

    encoded = codec.encode(_principal())

    assert encoded.startswith("v1.")
    assert codec.decode(encoded, NOW + timedelta(minutes=1)) == _principal()


def test_application_session_rejects_tampering_expiry_and_future_issuance() -> None:
    codec = ApplicationSessionCodec(KEY)
    encoded = codec.encode(_principal())
    tampered = encoded[:-1] + ("A" if encoded[-1] != "A" else "B")

    with pytest.raises(InvalidApplicationSession):
        codec.decode(tampered, NOW)
    with pytest.raises(InvalidApplicationSession, match="expired"):
        codec.decode(encoded, NOW + timedelta(hours=13))

    future = codec.encode(_principal(NOW + timedelta(minutes=2)))
    with pytest.raises(InvalidApplicationSession, match="future"):
        codec.decode(future, NOW)


def test_application_session_rejects_malformed_values_and_invalid_keys() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        ApplicationSessionCodec(b"short")
    with pytest.raises(ValueError, match="base64"):
        ApplicationSessionCodec.from_base64("not valid base64!")
    with pytest.raises(InvalidApplicationSession):
        ApplicationSessionCodec(KEY).decode("v2.invalid.value", NOW)
