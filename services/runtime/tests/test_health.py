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


def test_request_id_is_generated_and_security_headers_are_set(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.headers["X-Request-ID"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_request_id_is_propagated(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "request-test-123"})

    assert response.headers["X-Request-ID"] == "request-test-123"
