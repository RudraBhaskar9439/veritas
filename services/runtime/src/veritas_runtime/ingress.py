from veritas_runtime.app_factory import create_app
from veritas_runtime.changes.factory import build_drive_notification_receiver
from veritas_runtime.changes.routes import create_drive_webhook_router
from veritas_runtime.settings import get_settings

settings = get_settings()
receiver = build_drive_notification_receiver(settings)
app = create_app("event-ingress", settings)
app.include_router(create_drive_webhook_router(receiver))


@app.get("/api/v1/capabilities", tags=["system"])
async def capabilities() -> dict[str, object]:
    return {
        "service": "event-ingress",
        "acceptingWorkspaceEvents": receiver is not None,
    }
