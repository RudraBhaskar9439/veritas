from fastapi import FastAPI
from fastapi.testclient import TestClient

from packet_support import (
    MemoryManifestRepository,
    RecordingArtifactWriter,
    load_generation_request,
)
from veritas_runtime.packets.generator import DecisionPacketGenerator
from veritas_runtime.packets.routes import create_packet_router


def _payload() -> dict[str, object]:
    request_id, blueprint, sources = load_generation_request()
    return {
        "requestId": request_id,
        "blueprint": blueprint.model_dump(mode="json", by_alias=True),
        "sources": [source.model_dump(mode="json", by_alias=True) for source in sources],
    }


def _app(generator: DecisionPacketGenerator | None) -> FastAPI:
    app = FastAPI()
    app.include_router(create_packet_router(generator))
    return app


def test_packet_routes_fail_closed_without_workspace_configuration() -> None:
    client = TestClient(_app(None))
    assert client.get("/api/v1/packets/capabilities").json() == {"liveWorkspaceGeneration": False}
    response = client.post("/api/v1/packets", json=_payload())
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_packet_routes_generate_replay_and_reject_conflicting_request() -> None:
    generator = DecisionPacketGenerator(RecordingArtifactWriter(), MemoryManifestRepository())
    client = TestClient(_app(generator))
    payload = _payload()

    assert client.get("/api/v1/packets/capabilities").json() == {"liveWorkspaceGeneration": True}
    generated = client.post("/api/v1/packets", json=payload)
    assert generated.status_code == 200
    assert generated.json()["reused"] is False
    replay = client.post("/api/v1/packets", json=payload)
    assert replay.status_code == 200
    assert replay.json()["reused"] is True

    conflicting = _payload()
    conflicting["sources"][0]["value"] = 0.09  # type: ignore[index]
    response = client.post("/api/v1/packets", json=conflicting)
    assert response.status_code == 409


def test_packet_route_maps_generation_errors_to_bad_request() -> None:
    generator = DecisionPacketGenerator(RecordingArtifactWriter(), MemoryManifestRepository())
    client = TestClient(_app(generator))
    payload = _payload()
    payload["requestId"] = ""
    response = client.post("/api/v1/packets", json=payload)
    assert response.status_code == 400
    assert "request ID" in response.json()["detail"]
