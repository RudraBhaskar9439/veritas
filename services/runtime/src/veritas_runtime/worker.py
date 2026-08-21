from veritas_runtime.app_factory import create_app

app = create_app("agent-worker")


@app.get("/api/v1/capabilities", tags=["system"])
async def capabilities() -> dict[str, object]:
    return {"service": "agent-worker", "executingRepairs": False}
