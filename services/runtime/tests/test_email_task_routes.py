import base64
import json
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from veritas_runtime.auth.sessions import SessionPrincipal
from veritas_runtime.email_tasks.models import (
    EmailTaskEligibleRoute,
    EmailTaskRegistrationResult,
    EmailTaskSetup,
    EmailTaskThreadBinding,
    EmailTaskThreadSource,
    EmailTaskWorkflow,
    EmailTaskWorkflowStatus,
    GmailPushNotification,
    GmailWatchStream,
)
from veritas_runtime.email_tasks.routes import create_email_task_router
from veritas_runtime.email_tasks.routes_ingress import create_gmail_webhook_router
from veritas_runtime.email_tasks.security import InvalidPubSubIdentity

NOW = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)


def _workflow() -> EmailTaskWorkflow:
    return EmailTaskWorkflow(
        workflow_id="workflow-1",
        subject="subject-1",
        mailbox_email="operator@example.com",
        authorized_sender="customer@example.com",
        routing_key="VX-A1B2C3D4E5F6",
        packet_id="packet-1",
        manifest_id="manifest-1",
        claim_id="claim-1",
        artifact_id="task-artifact-1",
        task_id="task-1",
        task_list_id="list-1",
        status=EmailTaskWorkflowStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )


class RecordingCoordinator:
    def __init__(self) -> None:
        self.registered: tuple[str, str, object] | None = None

    async def list(self, subject: str):  # type: ignore[no-untyped-def]
        assert subject == "subject-1"
        return (_workflow(),)

    async def setup(self, subject: str, mailbox_email: str, packet_id: str) -> EmailTaskSetup:
        assert (subject, mailbox_email, packet_id) == (
            "subject-1",
            "operator@example.com",
            "packet-1",
        )
        return EmailTaskSetup(
            packet_id=packet_id,
            mailbox_email=mailbox_email,
            routes=(
                EmailTaskEligibleRoute(
                    claim_id="claim-1",
                    claim_statement="Move the customer onboarding review to Friday.",
                    claim_risk="reversible",
                    artifact_id="task-artifact-1",
                    task_id="task-1",
                    task_list_id="list-1",
                ),
            ),
            workflows=(_workflow(),),
        )

    async def list_events(self, subject: str, packet_id: str):  # type: ignore[no-untyped-def]
        assert (subject, packet_id) == ("subject-1", "packet-1")
        return ()

    async def register(self, subject, mailbox_email, request):  # type: ignore[no-untyped-def]
        self.registered = (subject, mailbox_email, request)
        watch = GmailWatchStream(
            subject=subject,
            mailbox_email=mailbox_email,
            history_id="101",
            expiration=NOW + timedelta(days=6),
            created_at=NOW,
            updated_at=NOW,
        )
        return EmailTaskRegistrationResult(workflow=_workflow(), watch=watch, reused=False)

    async def pause(self, subject: str, workflow_id: str) -> EmailTaskWorkflow:
        assert (subject, workflow_id) == ("subject-1", "workflow-1")
        return _workflow().model_copy(update={"status": EmailTaskWorkflowStatus.PAUSED})

    async def start_conversation(self, subject: str, workflow_id: str) -> EmailTaskThreadBinding:
        assert (subject, workflow_id) == ("subject-1", "workflow-1")
        return EmailTaskThreadBinding(
            binding_id="binding-1",
            subject=subject,
            workflow_id=workflow_id,
            gmail_thread_id="thread-1",
            bootstrap_message_id="message-1",
            subject_line="Customer onboarding — customer update",
            source=EmailTaskThreadSource.COMPANY_STARTED,
            created_at=NOW,
            updated_at=NOW,
        )

    async def bind_unmatched(
        self, subject: str, request_id: str, workflow_id: str
    ) -> EmailTaskThreadBinding:
        assert (request_id, workflow_id) == ("request-1", "workflow-1")
        return await self.start_conversation(subject, workflow_id)


async def _principal() -> SessionPrincipal:
    return SessionPrincipal(subject="subject-1", email="operator@example.com", issued_at=NOW)


def test_email_task_setup_and_registration_routes_are_authenticated_and_camel_cased() -> None:
    coordinator = RecordingCoordinator()
    app = FastAPI()
    app.include_router(create_email_task_router(coordinator, _principal))  # type: ignore[arg-type]
    client = TestClient(app)

    setup = client.get("/api/v1/email-task-workflows/setup?packetId=packet-1")
    assert setup.status_code == 200
    assert setup.json()["mailboxEmail"] == "operator@example.com"
    assert setup.json()["routes"][0]["taskId"] == "task-1"
    assert "subject" not in setup.json()["workflows"][0]

    created = client.post(
        "/api/v1/email-task-workflows",
        json={
            "packetId": "packet-1",
            "claimId": "claim-1",
            "artifactId": "task-artifact-1",
            "authorizedSender": "customer@example.com",
        },
    )
    assert created.status_code == 200
    assert "routingKey" not in created.json()["workflow"]
    assert coordinator.registered is not None
    assert coordinator.registered[0:2] == ("subject-1", "operator@example.com")

    conversation = client.post("/api/v1/email-task-workflows/workflow-1/conversation")
    assert conversation.status_code == 200
    assert conversation.json()["gmailThreadId"] == "thread-1"
    assert "subject" not in conversation.json()

    bound = client.post(
        "/api/v1/email-task-unmatched/request-1/bind",
        json={"workflowId": "workflow-1"},
    )
    assert bound.status_code == 200
    assert bound.json()["workflowId"] == "workflow-1"

    paused = client.delete("/api/v1/email-task-workflows/workflow-1")
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"


def test_email_task_routes_fail_closed_when_not_composed() -> None:
    app = FastAPI()
    app.include_router(create_email_task_router(None, None))
    client = TestClient(app)

    assert client.get("/api/v1/email-task-workflows/capabilities").json() == {
        "acceptingEmailTaskWorkflows": False
    }
    assert client.get("/api/v1/email-task-workflows").status_code == 503
    assert client.get("/api/v1/email-task-workflows/setup?packetId=packet-1").status_code == 503
    assert client.get("/api/v1/email-task-events?packetId=packet-1").status_code == 503
    assert client.post("/api/v1/email-task-workflows", json={}).status_code == 503
    assert client.post("/api/v1/email-task-workflows/workflow-1/conversation").status_code == 503
    assert (
        client.post(
            "/api/v1/email-task-unmatched/request-1/bind",
            json={"workflowId": "workflow-1"},
        ).status_code
        == 503
    )
    assert client.delete("/api/v1/email-task-workflows/workflow-1").status_code == 503


class RecordingVerifier:
    def __init__(self) -> None:
        self.authorization: str | None = None

    async def verify(self, authorization: str | None) -> None:
        self.authorization = authorization


class RecordingReceiver:
    def __init__(self) -> None:
        self.notifications: list[GmailPushNotification] = []

    async def receive(self, notification):  # type: ignore[no-untyped-def]
        self.notifications.append(notification)
        return True


def test_gmail_push_requires_identity_and_decodes_the_real_pubsub_contract() -> None:
    receiver = RecordingReceiver()
    verifier = RecordingVerifier()
    app = FastAPI()
    app.include_router(create_gmail_webhook_router(receiver, verifier))  # type: ignore[arg-type]
    data = base64.urlsafe_b64encode(
        json.dumps({"emailAddress": "operator@example.com", "historyId": 102}).encode()
    ).decode()

    response = TestClient(app).post(
        "/api/v1/integrations/gmail/notifications",
        headers={"Authorization": "Bearer signed-pubsub-token"},
        json={
            "message": {
                "messageId": "message-1",
                "publishTime": "2026-08-26T10:01:02Z",
                "data": data,
            }
        },
    )

    assert response.status_code == 204
    assert verifier.authorization == "Bearer signed-pubsub-token"
    assert receiver.notifications[0].mailbox_email == "operator@example.com"
    assert receiver.notifications[0].history_id == "102"


def test_gmail_push_fails_closed_without_composition_identity_or_valid_payload() -> None:
    closed = FastAPI()
    closed.include_router(create_gmail_webhook_router(None, None))
    closed_client = TestClient(closed)
    assert closed_client.get("/api/v1/integrations/gmail/capabilities").json() == {
        "acceptingGmailNotifications": False
    }
    assert (
        closed_client.post("/api/v1/integrations/gmail/notifications", json={}).status_code == 503
    )

    class RejectingVerifier:
        async def verify(self, authorization: str | None) -> None:
            raise InvalidPubSubIdentity("wrong push identity")

    receiver = RecordingReceiver()
    denied = FastAPI()
    denied.include_router(create_gmail_webhook_router(receiver, RejectingVerifier()))  # type: ignore[arg-type]
    assert (
        TestClient(denied)
        .post(
            "/api/v1/integrations/gmail/notifications",
            headers={"Authorization": "Bearer wrong"},
            json={},
        )
        .status_code
        == 401
    )

    invalid = FastAPI()
    invalid.include_router(create_gmail_webhook_router(receiver, RecordingVerifier()))  # type: ignore[arg-type]
    assert (
        TestClient(invalid)
        .post(
            "/api/v1/integrations/gmail/notifications",
            headers={"Authorization": "Bearer signed"},
            json={"message": {"messageId": "missing-data"}},
        )
        .status_code
        == 400
    )
