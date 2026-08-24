from veritas_runtime.app_factory import create_app
from veritas_runtime.changes.factory import build_drive_notification_receiver
from veritas_runtime.changes.routes import create_drive_webhook_router
from veritas_runtime.database_runtime import build_database_runtime
from veritas_runtime.settings import get_settings

settings = get_settings()
database = build_database_runtime(settings)
receiver = build_drive_notification_receiver(
    settings,
    database.engine if database is not None else None,
)
app = create_app("event-ingress", settings)
app.state.configuration_ready = receiver is not None
app.include_router(create_drive_webhook_router(receiver))
if database is not None:
    app.router.add_event_handler("shutdown", database.close)


@app.get("/api/v1/capabilities", tags=["system"])
async def capabilities() -> dict[str, object]:
    return {
        "service": "event-ingress",
        "acceptingWorkspaceEvents": receiver is not None,
    }
