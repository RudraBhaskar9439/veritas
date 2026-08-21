from veritas_runtime.app_factory import create_app

app = create_app("event-ingress")


@app.get("/api/v1/capabilities", tags=["system"])
async def capabilities() -> dict[str, object]:
    return {"service": "event-ingress", "acceptingWorkspaceEvents": False}
