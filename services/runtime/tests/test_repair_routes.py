from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from repair_support import MemoryRepairRepository
from veritas_runtime.repairs.models import ApprovalActor, ApprovalActorKind
from veritas_runtime.repairs.routes import create_repair_router
from veritas_runtime.repairs.service import RepairPlanningService


async def subject_resolver(_request: Request) -> str:
    return "subject-1"


async def actor_resolver(_request: Request) -> ApprovalActor:
    return ApprovalActor(principal="human@example.test", kind=ApprovalActorKind.HUMAN)


def test_repair_routes_are_fail_closed_when_dependencies_are_absent() -> None:
    app = FastAPI()
    app.include_router(create_repair_router(None, None, None))
    client = TestClient(app)
    assert client.get("/api/v1/repairs/capabilities").json() == {
        "typedPlanning": False,
        "humanApprovals": False,
        "execution": False,
    }
    response = client.post(
        "/api/v1/packets/packet/repair-plans",
        json={"requestId": "request", "impactReportId": "impact"},
    )
    assert response.status_code == 503


def test_repair_routes_create_a_plan_and_capture_a_human_decision() -> None:
    repository = MemoryRepairRepository()
    app = FastAPI()
    app.include_router(
        create_repair_router(
            RepairPlanningService(repository),
            subject_resolver,
            actor_resolver,
        )
    )
    client = TestClient(app)
    packet_id = repository.context.manifest.packet_id
    response = client.post(
        f"/api/v1/packets/{packet_id}/repair-plans",
        json={
            "requestId": "repair-request-1",
            "impactReportId": repository.context.impact.report_id,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["plan"]["policySummary"] == {
        "autoExecuteSteps": 3,
        "approvalRequiredSteps": 4,
        "draftOnlySteps": 2,
        "blockedSteps": 0,
    }
    approval = body["approvals"][0]
    decision = client.post(
        f"/api/v1/repair-plans/{body['plan']['planId']}/approvals/{approval['approvalId']}",
        json={
            "requestId": "approval-request-1",
            "decision": "approve",
            "reason": "I reviewed the consequence and approve this repair.",
        },
    )
    assert decision.status_code == 200
    assert decision.json()["approval"]["status"] == "approved"
    assert decision.json()["approval"]["decidedBy"] == "human@example.test"
