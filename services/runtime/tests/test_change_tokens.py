from datetime import UTC, datetime, timedelta

import pytest

from veritas_runtime.changes.tokens import (
    ChannelTokenCodec,
    InvalidChannelToken,
    channel_token_fingerprint,
)

NOW = datetime(2026, 8, 21, 1, 0, tzinfo=UTC)


def test_channel_tokens_are_bound_expiring_and_fingerprintable() -> None:
    codec = ChannelTokenCodec(bytes(range(32)))
    token = codec.issue("channel-1", "stream-1", NOW + timedelta(days=6))
    codec.verify(token, "channel-1", "stream-1", NOW)
    assert len(token) <= 256
    assert len(channel_token_fingerprint(token)) == 64

    with pytest.raises(InvalidChannelToken, match="binding"):
        codec.verify(token, "channel-2", "stream-1", NOW)
    with pytest.raises(InvalidChannelToken, match="expired"):
        codec.verify(token, "channel-1", "stream-1", NOW + timedelta(days=7))


def test_channel_tokens_reject_tampering_malformed_values_and_weak_keys() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        ChannelTokenCodec(b"weak")

    codec = ChannelTokenCodec(bytes(range(32)))
    token = codec.issue("channel-1", "stream-1", NOW + timedelta(days=6))
    with pytest.raises(InvalidChannelToken, match="signature"):
        codec.verify(token[:-1] + ("A" if token[-1] != "A" else "B"), "channel-1", "stream-1", NOW)
    with pytest.raises(InvalidChannelToken, match="malformed"):
        codec.verify("not-a-token", "channel-1", "stream-1", NOW)
    with pytest.raises(ValueError, match="256-character"):
        codec.issue("c" * 200, "s" * 200, NOW + timedelta(days=6))
