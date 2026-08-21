from veritas_runtime.app_factory import create_app
from veritas_runtime.operations.routes import create_worker_operations_router

app = create_app("agent-worker")
app.include_router(create_worker_operations_router(None))


@app.get("/api/v1/capabilities", tags=["system"])
async def capabilities() -> dict[str, object]:
    return {"service": "agent-worker", "executingRepairs": False}
