from veritas_runtime.app_factory import create_app

app = create_app("control-api")


@app.get("/api/v1", tags=["system"])
async def service_root() -> dict[str, str]:
    return {"service": "control-api", "status": "available"}
