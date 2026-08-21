import base64

import pytest
from pydantic import SecretStr

from veritas_runtime.changes.factory import build_drive_notification_receiver
from veritas_runtime.settings import Settings


def test_drive_ingress_factory_fails_closed_until_database_and_key_exist() -> None:
    settings = Settings(environment="test", drive_channel_token_key=SecretStr("key"))
    assert settings.drive_ingress_configured is False
    assert build_drive_notification_receiver(settings) is None


def test_drive_ingress_factory_builds_without_opening_database_connection() -> None:
    settings = Settings(
        environment="test",
        database_url=SecretStr("postgresql+asyncpg://veritas:secret@localhost/veritas"),
        drive_channel_token_key=SecretStr(
            base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")
        ),
    )
    assert settings.drive_ingress_configured is True
    assert build_drive_notification_receiver(settings) is not None


def test_drive_ingress_factory_rejects_weak_channel_key() -> None:
    settings = Settings(
        environment="test",
        database_url=SecretStr("postgresql+asyncpg://veritas:secret@localhost/veritas"),
        drive_channel_token_key=SecretStr("c2hvcnQ"),
    )
    with pytest.raises(ValueError, match="32 bytes"):
        build_drive_notification_receiver(settings)
