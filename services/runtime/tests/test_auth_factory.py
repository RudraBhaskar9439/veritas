import base64

import pytest
from pydantic import SecretStr

from veritas_runtime.auth.factory import build_google_connection_service
from veritas_runtime.settings import Settings


def _configured_settings(ticket_key: str | None = None) -> Settings:
    return Settings(
        environment="test",
        database_url=SecretStr("postgresql+asyncpg://veritas:secret@localhost/veritas"),
        google_oauth_client_id="client-id",
        google_oauth_client_secret=SecretStr("client-secret"),
        google_oauth_redirect_uri="https://veritas.test/api/v1/auth/google/callback",
        google_kms_credentials_key="projects/p/locations/l/keyRings/r/cryptoKeys/k",
        oauth_ticket_key=SecretStr(
            ticket_key or base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")
        ),
    )


def test_factory_fails_closed_until_every_dependency_is_configured() -> None:
    settings = Settings(environment="test", google_oauth_client_id="client-id")

    assert settings.google_auth_configured is False
    assert build_google_connection_service(settings) is None


def test_factory_builds_without_opening_external_connections() -> None:
    settings = _configured_settings()

    assert settings.google_auth_configured is True
    assert build_google_connection_service(settings) is not None
    assert "client-secret" not in repr(settings)


def test_factory_rejects_invalid_ticket_encryption_key() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        build_google_connection_service(_configured_settings("c2hvcnQ"))
