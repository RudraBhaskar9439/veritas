from collections.abc import Awaitable, Callable
from time import perf_counter

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from veritas_runtime.security import security_headers, trusted_request_id
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
        started_at = perf_counter()
        request_id = trusted_request_id(request.headers.get(resolved.request_id_header))
        request.state.request_id = request_id
        content_length = request.headers.get("content-length")
        response: Response
        if content_length is not None and (
            not content_length.isdigit() or int(content_length) > resolved.max_request_bytes
        ):
            response = JSONResponse(
                status_code=413,
                content={"error": "request_too_large", "requestId": request_id},
            )
        else:
            response = await call_next(request)
        response.headers[resolved.request_id_header] = request_id
        for header, value in security_headers(
            transport_secure=resolved.environment in {"preview", "production"}
        ).items():
            response.headers[header] = value
        await logger.ainfo(
            "request.completed",
            service=service_name,
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round((perf_counter() - started_at) * 1000, 2),
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
    async def readiness() -> Response:
        configured = bool(getattr(app.state, "configuration_ready", True))
        payload = {
            "status": "ready" if configured else "not_ready",
            "service": service_name,
            "environment": resolved.environment,
            "checks": {"configuration": "ok" if configured else "missing"},
        }
        return JSONResponse(status_code=200 if configured else 503, content=payload)

    return app
