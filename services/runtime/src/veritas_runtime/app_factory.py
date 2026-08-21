from collections.abc import Awaitable, Callable
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from veritas_runtime.settings import Settings, get_settings

logger = structlog.get_logger()


def create_app(service_name: str, settings: Settings | None = None) -> FastAPI:
    """Create a service app with identical health and request-correlation contracts."""

    resolved = settings or get_settings()
    app = FastAPI(
        title=f"Veritas {service_name}",
        version=resolved.version,
        docs_url=None if resolved.environment == "production" else "/docs",
        redoc_url=None,
    )
    app.state.service_name = service_name
    app.state.settings = resolved

    @app.middleware("http")
    async def request_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get(resolved.request_id_header) or str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[resolved.request_id_header] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        await logger.ainfo(
            "request.completed",
            service=service_name,
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
        )
        return response

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, error: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        await logger.aexception(
            "request.failed",
            service=service_name,
            request_id=request_id,
            error_type=type(error).__name__,
        )
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "requestId": request_id},
        )

    @app.get("/health/live", tags=["health"])
    async def liveness() -> dict[str, str]:
        return {"status": "ok", "service": service_name, "version": resolved.version}

    @app.get("/health/ready", tags=["health"])
    async def readiness() -> dict[str, object]:
        return {
            "status": "ready",
            "service": service_name,
            "environment": resolved.environment,
            "checks": {"configuration": "ok"},
        }

    return app
