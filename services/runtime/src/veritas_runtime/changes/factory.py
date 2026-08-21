from sqlalchemy.ext.asyncio import create_async_engine

from veritas_runtime.changes.database import SqlWatchRepository
from veritas_runtime.changes.service import DriveNotificationReceiver
from veritas_runtime.changes.tokens import ChannelTokenCodec
from veritas_runtime.settings import Settings


def build_drive_notification_receiver(
    settings: Settings,
) -> DriveNotificationReceiver | None:
    if not settings.drive_ingress_configured:
        return None
    assert settings.database_url is not None
    assert settings.drive_channel_token_key is not None
    engine = create_async_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
    return DriveNotificationReceiver(
        SqlWatchRepository(engine),
        ChannelTokenCodec.from_base64(settings.drive_channel_token_key.get_secret_value()),
    )
