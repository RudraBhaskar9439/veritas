from veritas_runtime.app_factory import create_app
from veritas_runtime.operations.routes import create_worker_operations_router
from veritas_runtime.settings import get_settings
from veritas_runtime.worker_runtime import build_worker_components

settings = get_settings()
components = build_worker_components(settings)
app = create_app("agent-worker", settings)
app.state.configuration_ready = components is not None
app.include_router(create_worker_operations_router(components.service if components else None))
if components is not None:
    app.router.add_event_handler("shutdown", components.close)


@app.get("/api/v1/capabilities", tags=["system"])
async def capabilities() -> dict[str, object]:
    return {
        "service": "agent-worker",
        "processingDriveChanges": components is not None,
        "durableOperations": components is not None,
        "executingRepairs": components is not None,
        "independentVerification": components is not None,
    }
