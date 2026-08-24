from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from veritas_runtime.app_factory import create_app
from veritas_runtime.settings import Settings


@pytest.fixture
def app() -> Iterator[FastAPI]:
    yield create_app(
        "test-service",
        Settings(environment="test", version="test-version"),
    )


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_liveness_contract(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "test-service",
        "version": "test-version",
    }


def test_readiness_contract(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "service": "test-service",
        "environment": "test",
        "checks": {"configuration": "ok"},
    }


def test_readiness_fails_closed_when_runtime_composition_is_missing() -> None:
    unconfigured = create_app("worker", Settings(environment="test"))
    unconfigured.state.configuration_ready = False

    response = TestClient(unconfigured).get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "service": "worker",
        "environment": "test",
        "checks": {"configuration": "missing"},
    }


def test_request_id_is_generated_and_security_headers_are_set(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.headers["X-Request-ID"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Permissions-Policy"]
    assert response.headers["Content-Security-Policy"]


def test_request_id_is_propagated(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "request-test-123"})

    assert response.headers["X-Request-ID"] == "request-test-123"


def test_unsafe_request_id_is_replaced_and_oversized_request_is_rejected(
    client: TestClient,
) -> None:
    unsafe = client.get("/health/live", headers={"X-Request-ID": "unsafe\nvalue"})
    assert unsafe.headers["X-Request-ID"] != "unsafe\nvalue"
    oversized = client.post(
        "/missing",
        headers={"Content-Length": "2000000", "X-Request-ID": "large-request"},
    )
    assert oversized.status_code == 413
    assert oversized.json() == {
        "error": "request_too_large",
        "requestId": "large-request",
    }


def test_preview_responses_enable_hsts() -> None:
    preview = create_app("preview-service", Settings(environment="preview"))
    response = TestClient(preview).get("/health/live")
    assert response.headers["Strict-Transport-Security"].startswith("max-age=31536000")
