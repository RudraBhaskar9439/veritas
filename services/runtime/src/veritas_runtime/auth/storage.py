import json
from datetime import UTC, datetime
from typing import Protocol, cast

from google.cloud import kms_v1

from veritas_runtime.auth.models import GoogleIdentity, OAuthTokenSet, WorkspaceCredentialRecord


class CredentialIntegrityError(RuntimeError):
    """Raised when encrypted credentials do not match their storage identity."""


class CredentialCipher(Protocol):
    key_resource: str

    async def encrypt(self, plaintext: bytes) -> bytes: ...

    async def decrypt(self, ciphertext: bytes) -> bytes: ...


class CredentialRepository(Protocol):
    async def upsert(self, record: WorkspaceCredentialRecord) -> None: ...

    async def get(self, subject: str) -> WorkspaceCredentialRecord | None: ...

    async def delete(self, subject: str) -> None: ...


class KmsAsyncClient(Protocol):
    async def encrypt(self, request: dict[str, object]) -> object: ...

    async def decrypt(self, request: dict[str, object]) -> object: ...


class GoogleKmsCredentialCipher:
    """Encrypt small OAuth token envelopes directly with a non-exportable Cloud KMS key."""

    def __init__(self, key_resource: str, client: KmsAsyncClient | None = None) -> None:
        self.key_resource = key_resource
        self._client = client

    def _resolved_client(self) -> KmsAsyncClient:
        if self._client is None:
            self._client = cast(KmsAsyncClient, kms_v1.KeyManagementServiceAsyncClient())
        return self._client

    async def encrypt(self, plaintext: bytes) -> bytes:
        if len(plaintext) > 65_536:
            raise ValueError("Credential payload exceeds the Cloud KMS limit")
        response = await self._resolved_client().encrypt(
            request={"name": self.key_resource, "plaintext": plaintext}
        )
        ciphertext = getattr(response, "ciphertext", None)
        if not isinstance(ciphertext, bytes):
            raise CredentialIntegrityError("Cloud KMS returned no ciphertext")
        return ciphertext

    async def decrypt(self, ciphertext: bytes) -> bytes:
        response = await self._resolved_client().decrypt(
            request={"name": self.key_resource, "ciphertext": ciphertext}
        )
        plaintext = getattr(response, "plaintext", None)
        if not isinstance(plaintext, bytes):
            raise CredentialIntegrityError("Cloud KMS returned no plaintext")
        return plaintext


class EncryptedCredentialVault:
    def __init__(self, cipher: CredentialCipher, repository: CredentialRepository) -> None:
        self._cipher = cipher
        self._repository = repository

    async def store(self, identity: GoogleIdentity, tokens: OAuthTokenSet) -> None:
        if not tokens.refresh_token:
            raise CredentialIntegrityError("Offline access requires a refresh token")
        now = datetime.now(UTC)
        plaintext = json.dumps(
            {
                "access_token": tokens.access_token,
                "email": identity.email,
                "expires_at": tokens.expires_at.astimezone(UTC).isoformat(),
                "key_resource": self._cipher.key_resource,
                "refresh_token": tokens.refresh_token,
                "scopes": sorted(tokens.scopes),
                "subject": identity.subject,
                "token_type": tokens.token_type,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        encrypted_payload = await self._cipher.encrypt(plaintext)
        existing = await self._repository.get(identity.subject)
        await self._repository.upsert(
            WorkspaceCredentialRecord(
                subject=identity.subject,
                email=identity.email,
                encrypted_payload=encrypted_payload,
                key_resource=self._cipher.key_resource,
                scopes=tuple(sorted(tokens.scopes)),
                connected_at=existing.connected_at if existing else now,
                updated_at=now,
            )
        )

    async def load(self, subject: str) -> tuple[GoogleIdentity, OAuthTokenSet] | None:
        record = await self._repository.get(subject)
        if record is None:
            return None
        if record.key_resource != self._cipher.key_resource:
            raise CredentialIntegrityError("Credential key resource mismatch")
        try:
            payload = json.loads(await self._cipher.decrypt(record.encrypted_payload))
            identity = GoogleIdentity(
                subject=str(payload["subject"]),
                email=str(payload["email"]),
            )
            tokens = OAuthTokenSet(
                access_token=str(payload["access_token"]),
                refresh_token=str(payload["refresh_token"]),
                expires_at=datetime.fromisoformat(str(payload["expires_at"])).astimezone(UTC),
                scopes=tuple(str(scope) for scope in payload["scopes"]),
                token_type=str(payload["token_type"]),
            )
            envelope_key_resource = str(payload["key_resource"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise CredentialIntegrityError("Credential envelope is invalid") from error
        if (
            identity.subject != record.subject
            or identity.email != record.email
            or tokens.scopes != record.scopes
            or envelope_key_resource != record.key_resource
        ):
            raise CredentialIntegrityError("Credential envelope does not match its record")
        return identity, tokens

    async def delete(self, subject: str) -> None:
        await self._repository.delete(subject)
