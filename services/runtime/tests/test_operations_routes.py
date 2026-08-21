import asyncio
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from operations_support import MemoryOperationRepository
from veritas_runtime.operations.models import OperationRequest
from veritas_runtime.operations.routes import (
    create_operations_router,
    create_worker_operations_router,
)
from veritas_runtime.operations.service import ReliableOperationService

NOW = datetime(2026, 8, 21, 10, 0, tzinfo=UTC)


async def subject_resolver(_request: Request) -> str:
    return "subject-1"


async def actor_resolver(_request: Request) -> str:
    return "operator@example.test"


def test_routes_fail_closed_without_configured_services() -> None:
    app = FastAPI()
    app.include_router(create_operations_router(None, None, None))
    app.include_router(create_worker_operations_router(None))
    client = TestClient(app)
    assert client.get("/api/v1/operations/capabilities").json() == {
        "deadLetterInspection": False,
        "auditedReplay": False,
    }
    assert client.get("/api/v1/operations/dead-letters").status_code == 503
    assert (
        client.post("/internal/v1/operations/tick", json={"workerId": "worker"}).status_code == 503
    )


def test_routes_list_and_replay_quarantined_operations() -> None:
    repository = MemoryOperationRepository()
    service = ReliableOperationService(repository, {})

    async def prepare() -> str:
        operation, _ = await service.enqueue(
            OperationRequest(
                subject="subject-1",
                kind="repair.execute",
                correlation_id="incident-042",
                idempotency_key="route-request",
                payload={},
            ),
            NOW,
        )
        await service.tick("worker-1", NOW)
        return operation.operation_id

    operation_id = asyncio.run(prepare())
    app = FastAPI()
    app.include_router(create_operations_router(service, subject_resolver, actor_resolver))
    app.include_router(create_worker_operations_router(service))
    client = TestClient(app)
    dead = client.get("/api/v1/operations/dead-letters")
    assert dead.status_code == 200 and dead.json()[0]["operationId"] == operation_id
    replay = client.post(
        f"/api/v1/operations/dead-letters/{operation_id}/replay",
        json={
            "requestId": "route-replay",
            "reason": "Operator corrected the dependency and reviewed the incident.",
        },
    )
    assert replay.status_code == 200
    assert replay.json()["operation"]["replayOf"] == operation_id
    assert "payload" not in replay.json()["operation"]
    tick = client.post("/internal/v1/operations/tick", json={"workerId": "worker-2"})
    assert tick.status_code == 200
