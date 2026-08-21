from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Response

from veritas_runtime.changes.models import DriveNotification
from veritas_runtime.changes.service import (
    DriveNotificationReceiver,
    UnknownWatchChannel,
    WatchChannelMismatch,
)
from veritas_runtime.changes.tokens import InvalidChannelToken


def create_drive_webhook_router(receiver: DriveNotificationReceiver | None) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/integrations/google-drive/capabilities", tags=["drive-changes"])
    async def capabilities() -> dict[str, bool]:
        return {"acceptingDriveNotifications": receiver is not None}

    @router.post(
        "/api/v1/integrations/google-drive/notifications",
        status_code=204,
        tags=["drive-changes"],
    )
    async def receive_notification(
        x_goog_channel_id: Annotated[str, Header(min_length=1, max_length=64)],
        x_goog_message_number: Annotated[int, Header(ge=1)],
        x_goog_resource_id: Annotated[str, Header(min_length=1)],
        x_goog_resource_state: Annotated[str, Header(min_length=1)],
        x_goog_resource_uri: Annotated[str, Header(min_length=1)],
        x_goog_channel_token: Annotated[str | None, Header()] = None,
        x_goog_changed: Annotated[str | None, Header()] = None,
    ) -> Response:
        if receiver is None:
            raise HTTPException(
                status_code=503, detail="Drive notification intake is not configured"
            )
        if x_goog_channel_token is None:
            raise HTTPException(status_code=401, detail="Drive channel token is required")
        notification = DriveNotification(
            channel_id=x_goog_channel_id,
            message_number=x_goog_message_number,
            google_resource_id=x_goog_resource_id,
            resource_state=x_goog_resource_state,
            resource_uri=x_goog_resource_uri,
            changed=tuple(
                part.strip() for part in (x_goog_changed or "").split(",") if part.strip()
            ),
            received_at=datetime.now(UTC),
        )
        try:
            await receiver.receive(x_goog_channel_token, notification)
        except InvalidChannelToken as error:
            raise HTTPException(status_code=401, detail="Invalid Drive channel token") from error
        except UnknownWatchChannel as error:
            raise HTTPException(status_code=404, detail="Unknown Drive watch channel") from error
        except WatchChannelMismatch as error:
            raise HTTPException(status_code=409, detail="Drive watch channel mismatch") from error
        return Response(status_code=204)

    return router
