from fastapi.testclient import TestClient

from veritas_runtime.api import app as api_app
from veritas_runtime.ingress import app as ingress_app
from veritas_runtime.worker import app as worker_app


def test_control_api_role() -> None:
    response = TestClient(api_app).get("/api/v1")
    assert response.status_code == 200
    assert response.json()["service"] == "control-api"


def test_ingress_fails_closed_until_event_phase() -> None:
    response = TestClient(ingress_app).get("/api/v1/capabilities")
    assert response.status_code == 200
    assert response.json()["acceptingWorkspaceEvents"] is False


def test_worker_exposes_reliability_contract_but_fails_closed_until_configured() -> None:
    response = TestClient(worker_app).get("/api/v1/capabilities")
    assert response.status_code == 200
    assert response.json()["executingRepairs"] is False
    reliability = TestClient(worker_app).get("/internal/v1/operations/capabilities")
    assert reliability.json() == {
        "durableLeases": False,
        "boundedRetries": False,
        "deadLetters": False,
    }
