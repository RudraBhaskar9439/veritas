import base64
import binascii
import hashlib
import hmac
import json
from datetime import UTC, datetime


class InvalidChannelToken(ValueError):
    """A Drive webhook token is invalid, expired, or bound to another channel."""


class ChannelTokenCodec:
    VERSION = "v1"

    def __init__(self, key: bytes) -> None:
        if len(key) < 32:
            raise ValueError("Channel token key must contain at least 32 bytes")
        self._key = key

    @classmethod
    def from_base64(cls, encoded_key: str) -> "ChannelTokenCodec":
        try:
            key = _decode(encoded_key)
        except (binascii.Error, ValueError) as error:
            raise ValueError("Channel token key must be URL-safe base64") from error
        return cls(key)

    def issue(self, channel_id: str, stream_id: str, expires_at: datetime) -> str:
        payload = _encode(
            json.dumps(
                {
                    "c": channel_id,
                    "e": int(expires_at.astimezone(UTC).timestamp()),
                    "s": stream_id,
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        )
        signature = _encode(hmac.digest(self._key, f"{self.VERSION}.{payload}".encode(), "sha256"))
        token = f"{self.VERSION}.{payload}.{signature}"
        if len(token) > 256:
            raise ValueError("Channel token exceeds the Google Drive 256-character limit")
        return token

    def verify(
        self,
        token: str,
        expected_channel_id: str,
        expected_stream_id: str,
        now: datetime,
    ) -> None:
        try:
            version, payload, supplied_signature = token.split(".", 2)
            expected_signature = _encode(
                hmac.digest(self._key, f"{version}.{payload}".encode(), "sha256")
            )
            if version != self.VERSION or not hmac.compare_digest(
                supplied_signature, expected_signature
            ):
                raise InvalidChannelToken("Channel token signature is invalid")
            decoded = json.loads(_decode(payload))
            channel_id = decoded["c"]
            stream_id = decoded["s"]
            expiration = int(decoded["e"])
        except InvalidChannelToken:
            raise
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise InvalidChannelToken("Channel token is malformed") from error
        if channel_id != expected_channel_id or stream_id != expected_stream_id:
            raise InvalidChannelToken("Channel token binding does not match")
        if int(now.astimezone(UTC).timestamp()) > expiration:
            raise InvalidChannelToken("Channel token has expired")


def channel_token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
