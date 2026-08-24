from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from veritas_runtime.changes.database import SqlWatchRepository
from veritas_runtime.changes.service import DriveNotificationReceiver
from veritas_runtime.changes.tokens import ChannelTokenCodec
from veritas_runtime.settings import Settings


def build_drive_notification_receiver(
    settings: Settings,
    engine: AsyncEngine | None = None,
) -> DriveNotificationReceiver | None:
    if not settings.drive_ingress_configured:
        return None
    assert settings.drive_channel_token_key is not None
    if engine is None:
        if settings.database_url is None:
            raise ValueError("A shared Cloud SQL engine is required")
        resolved_engine = create_async_engine(
            settings.database_url.get_secret_value(), pool_pre_ping=True
        )
    else:
        resolved_engine = engine
    return DriveNotificationReceiver(
        SqlWatchRepository(resolved_engine),
        ChannelTokenCodec.from_base64(settings.drive_channel_token_key.get_secret_value()),
    )
