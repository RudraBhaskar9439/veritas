from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, Response

from veritas_runtime.email_tasks.notifications import (
    GmailNotificationError,
    GmailNotificationReceiver,
    decode_pubsub_push,
)
from veritas_runtime.email_tasks.security import InvalidPubSubIdentity, PubSubIdentityVerifier


def create_gmail_webhook_router(
    receiver: GmailNotificationReceiver | None,
    verifier: PubSubIdentityVerifier | None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/integrations/gmail/capabilities", tags=["gmail-events"])
    async def capabilities() -> dict[str, bool]:
        return {"acceptingGmailNotifications": receiver is not None and verifier is not None}

    @router.post(
        "/api/v1/integrations/gmail/notifications",
        status_code=204,
        tags=["gmail-events"],
    )
    async def receive_notification(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ) -> Response:
        if receiver is None or verifier is None:
            raise HTTPException(
                status_code=503,
                detail="Gmail notification intake is not configured",
            )
        try:
            await verifier.verify(authorization)
        except InvalidPubSubIdentity as error:
            raise HTTPException(status_code=401, detail=str(error)) from error
        try:
            notification = decode_pubsub_push(await request.json())
        except (GmailNotificationError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        await receiver.receive(notification)
        return Response(status_code=204)

    return router
