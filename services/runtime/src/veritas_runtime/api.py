from veritas_runtime.app_factory import create_app
from veritas_runtime.auth.factory import build_google_connection_service
from veritas_runtime.auth.routes import create_google_auth_router
from veritas_runtime.settings import get_settings

settings = get_settings()
app = create_app("control-api", settings)
app.include_router(
    create_google_auth_router(
        build_google_connection_service(settings),
        secure_cookie=settings.environment in {"preview", "production"},
    )
)


@app.get("/api/v1", tags=["system"])
async def service_root() -> dict[str, str]:
    return {"service": "control-api", "status": "available"}
