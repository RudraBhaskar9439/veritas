import base64
from datetime import UTC, datetime, timedelta

import pytest

from veritas_runtime.auth.models import AuthorizationTicket
from veritas_runtime.auth.tickets import AuthorizationTicketCodec, InvalidAuthorizationTicket

NOW = datetime(2026, 8, 21, 2, 0, tzinfo=UTC)
KEY = bytes(range(32))
NONCE = bytes(range(12))


def _ticket(issued_at: datetime = NOW) -> AuthorizationTicket:
    return AuthorizationTicket(
        state="state-value",
        code_verifier="verifier-value",
        return_to="/integrations/google",
        issued_at=issued_at,
    )


def test_ticket_round_trip_and_base64_key_constructor() -> None:
    encoded_key = base64.urlsafe_b64encode(KEY).decode().rstrip("=")
    codec = AuthorizationTicketCodec.from_base64(encoded_key)

    encoded = codec.encode(_ticket(), NONCE)

    assert encoded.startswith("v1.")
    assert "verifier-value" not in encoded
    assert codec.decode(encoded, NOW + timedelta(minutes=1)) == _ticket()


@pytest.mark.parametrize(
    "encoded",
    [
        "v2.invalid",
        "v1.not-base64!",
        "v1.YWJj",
    ],
)
def test_ticket_rejects_untrusted_payloads(encoded: str) -> None:
    with pytest.raises(InvalidAuthorizationTicket):
        AuthorizationTicketCodec(KEY).decode(encoded, NOW)


def test_ticket_rejects_tampering_expiry_and_future_issuance() -> None:
    codec = AuthorizationTicketCodec(KEY)
    encoded = codec.encode(_ticket(), NONCE)
    tampered = encoded[:-1] + ("A" if encoded[-1] != "A" else "B")

    with pytest.raises(InvalidAuthorizationTicket):
        codec.decode(tampered, NOW)
    with pytest.raises(InvalidAuthorizationTicket, match="expired"):
        codec.decode(encoded, NOW + timedelta(minutes=11))

    future = codec.encode(_ticket(NOW + timedelta(minutes=2)), NONCE)
    with pytest.raises(InvalidAuthorizationTicket, match="future"):
        codec.decode(future, NOW)


def test_ticket_rejects_invalid_key_and_nonce_lengths() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        AuthorizationTicketCodec(b"short")
    with pytest.raises(ValueError, match="base64"):
        AuthorizationTicketCodec.from_base64("not valid base64!")
    with pytest.raises(ValueError, match="12 bytes"):
        AuthorizationTicketCodec(KEY).encode(_ticket(), b"short")
