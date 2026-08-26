import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import create_async_engine

from packet_support import (
    NOW,
    MemoryManifestRepository,
    RecordingArtifactWriter,
    load_generation_request,
)
from veritas_runtime.auth.database import metadata
from veritas_runtime.changes.database import registered_evidence_sources
from veritas_runtime.email_tasks.database import SqlEmailTaskWorkflowRepository
from veritas_runtime.email_tasks.models import (
    EmailTaskEvent,
    EmailTaskEventStatus,
    EmailTaskWorkflowStatus,
    GmailWatchStream,
    RegisterEmailTaskWorkflowRequest,
)
from veritas_runtime.email_tasks.policy import (
    InvalidEmailAddress,
    deterministic_risk_flags,
    normalize_email,
    routes_to_workflow,
)
from veritas_runtime.email_tasks.service import (
    EmailTaskRegistrationCoordinator,
    EmailTaskWorkflowError,
    EmailTaskWorkflowService,
    GmailWatchRenewalService,
)
from veritas_runtime.execution.service import WorkspaceSession
from veritas_runtime.packets.database import SqlManifestRepository
from veritas_runtime.packets.generator import DecisionPacketGenerator
from veritas_runtime.workspace.contracts import (
    REQUIRED_WORKSPACE_SCOPES,
    WorkspaceAuthorization,
)


class LatestManifest:
    def __init__(self, manifest) -> None:  # type: ignore[no-untyped-def]
        self.manifest = manifest

    async def latest_for_packet(self, packet_id: str):  # type: ignore[no-untyped-def]
        return self.manifest if self.manifest.packet_id == packet_id else None


class MemoryWorkflows:
    def __init__(self, *, owns_packet: bool = True) -> None:
        self.owns_packet = owns_packet
        self.records = {}
        self.watch = None

    async def packet_registered_for_subject(self, subject: str, packet_id: str) -> bool:
        return self.owns_packet and subject == "subject-1" and bool(packet_id)

    async def get_by_identity(self, subject: str, routing_key: str):  # type: ignore[no-untyped-def]
        return self.records.get((subject, routing_key))

    async def persist(self, workflow, input_digest):  # type: ignore[no-untyped-def]
        from veritas_runtime.email_tasks.models import EmailTaskWorkflowResult

        key = (workflow.subject, workflow.routing_key)
        existing = self.records.get(key)
        if existing is not None:
            return EmailTaskWorkflowResult(workflow=existing[0], reused=True)
        self.records[key] = (workflow, input_digest)
        return EmailTaskWorkflowResult(workflow=workflow, reused=False)

    async def list_for_subject(self, subject: str):  # type: ignore[no-untyped-def]
        return tuple(
            workflow
            for (workflow_subject, _), (workflow, _) in self.records.items()
            if workflow_subject == subject
        )

    async def list_events_for_subject(self, subject: str, packet_id: str):  # type: ignore[no-untyped-def]
        return ()

    async def pause_for_subject(self, subject, workflow_id, updated_at):  # type: ignore[no-untyped-def]
        for key, (workflow, digest) in self.records.items():
            if workflow.subject == subject and workflow.workflow_id == workflow_id:
                paused = workflow.model_copy(
                    update={
                        "status": EmailTaskWorkflowStatus.PAUSED,
                        "updated_at": updated_at,
                    }
                )
                self.records[key] = (paused, digest)
                return paused
        return None

    async def get_watch(self, subject: str):  # type: ignore[no-untyped-def]
        return self.watch if self.watch is not None and self.watch.subject == subject else None

    async def upsert_watch(self, stream):  # type: ignore[no-untyped-def]
        self.watch = stream
        return stream


async def _manifest():  # type: ignore[no-untyped-def]
    request_id, blueprint, sources = load_generation_request()
    return (
        await DecisionPacketGenerator(
            RecordingArtifactWriter(),
            MemoryManifestRepository(),
        ).generate(request_id, blueprint, sources, NOW)
    ).manifest


def _request(**updates: str) -> RegisterEmailTaskWorkflowRequest:
    return RegisterEmailTaskWorkflowRequest(
        packetId=updates.get("packet_id", "packet-q3-executive-review"),
        claimId=updates.get("claim_id", "claim-scale-acquisition"),
        artifactId=updates.get("artifact_id", "artifact-acquisition-task"),
        authorizedSender=updates.get("authorized_sender", "Customer@Example.com"),
    )


def test_registration_is_manifest_bound_sender_bound_and_idempotent() -> None:
    async def scenario() -> None:
        manifest = await _manifest()
        workflows = MemoryWorkflows()
        service = EmailTaskWorkflowService(LatestManifest(manifest), workflows)  # type: ignore[arg-type]

        first = await service.register("subject-1", "Operator@Example.com", _request(), NOW)
        replay = await service.register("subject-1", "Operator@Example.com", _request(), NOW)

        assert first.reused is False
        assert replay.reused is True
        assert first.workflow.authorized_sender == "customer@example.com"
        assert first.workflow.mailbox_email == "operator@example.com"
        assert first.workflow.task_id == "workspace-artifact-acquisition-task"
        assert first.workflow.task_list_id == "workspace-task-list"
        assert routes_to_workflow(
            f"Please update delivery [{first.workflow.routing_key}]",
            first.workflow.routing_key,
        )
        assert routes_to_workflow("Unrelated customer email", first.workflow.routing_key) is False

        setup = await service.setup(
            "subject-1",
            "Operator@Example.com",
            manifest.packet_id,
        )
        assert setup.mailbox_email == "operator@example.com"
        assert setup.packet_id == manifest.packet_id
        assert [(route.claim_id, route.artifact_id) for route in setup.routes] == [
            ("claim-scale-acquisition", "artifact-acquisition-task")
        ]
        assert setup.routes[0].task_id == "workspace-artifact-acquisition-task"

    asyncio.run(scenario())


def test_registration_rejects_unowned_or_unregistered_task_routes() -> None:
    async def scenario() -> None:
        manifest = await _manifest()
        with pytest.raises(EmailTaskWorkflowError, match="not registered to this account"):
            await EmailTaskWorkflowService(
                LatestManifest(manifest),
                MemoryWorkflows(owns_packet=False),  # type: ignore[arg-type]
            ).register("subject-1", "operator@example.com", _request(), NOW)

        service = EmailTaskWorkflowService(
            LatestManifest(manifest),
            MemoryWorkflows(),  # type: ignore[arg-type]
        )
        with pytest.raises(EmailTaskWorkflowError, match="outside the registered claim lineage"):
            await service.register(
                "subject-1",
                "operator@example.com",
                _request(artifact_id="artifact-board-memo"),
                NOW,
            )

    asyncio.run(scenario())


def test_email_normalization_and_deterministic_risk_policy_fail_closed() -> None:
    assert normalize_email("Customer <CUSTOMER@Example.COM>") == "customer@example.com"
    with pytest.raises(InvalidEmailAddress):
        normalize_email("not-an-address")
    assert deterministic_risk_flags("Please update delivery", "Move installation to Friday") == ()
    assert deterministic_risk_flags(
        "Cancel and refund", "Delete the payment task and send bank credentials"
    ) == (
        "sensitive:bank",
        "sensitive:cancel",
        "sensitive:credential",
        "sensitive:delete",
        "sensitive:payment",
        "sensitive:refund",
    )


def test_sql_repository_persists_only_subject_owned_workflows() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        request_id, blueprint, sources = load_generation_request()
        manifests = SqlManifestRepository(engine)
        manifest = (
            await DecisionPacketGenerator(RecordingArtifactWriter(), manifests).generate(
                request_id,
                blueprint,
                sources,
                NOW,
            )
        ).manifest
        async with engine.begin() as connection:
            await connection.execute(
                insert(registered_evidence_sources).values(
                    subject="subject-1",
                    packet_id=manifest.packet_id,
                    source_id=manifest.sources[0].source_id,
                    kind=manifest.sources[0].kind.value,
                    resource_id=manifest.sources[0].resource_id,
                    anchor=manifest.sources[0].anchor,
                    registered_at=NOW,
                )
            )
        workflows = SqlEmailTaskWorkflowRepository(engine)
        service = EmailTaskWorkflowService(manifests, workflows)
        created = await service.register(
            "subject-1",
            "operator@example.com",
            _request(packet_id=manifest.packet_id),
            NOW,
        )
        loaded = await workflows.get_by_identity("subject-1", created.workflow.routing_key)
        assert loaded == created.workflow
        assert await workflows.active_for_mailbox("operator@example.com") == (created.workflow,)
        assert await workflows.list_for_subject("subject-1") == (created.workflow,)
        assert await workflows.subject_for_mailbox("operator@example.com") == "subject-1"
        assert (await manifests.latest_for_packet(manifest.packet_id)) == manifest

        watch = GmailWatchStream(
            subject="subject-1",
            mailbox_email="operator@example.com",
            history_id="10",
            expiration=NOW + timedelta(hours=2),
            created_at=NOW,
            updated_at=NOW,
        )
        stored_watch = await workflows.upsert_watch(watch)
        assert stored_watch.history_id == "10"
        assert stored_watch.mailbox_email == "operator@example.com"
        assert (await workflows.get_watch("subject-1")).history_id == "10"  # type: ignore[union-attr]
        assert [
            item.history_id for item in await workflows.expiring_watches(NOW + timedelta(days=1), 5)
        ] == ["10"]
        renewed = watch.model_copy(
            update={
                "history_id": "20",
                "expiration": NOW + timedelta(days=7),
                "updated_at": NOW + timedelta(minutes=1),
            }
        )
        assert (await workflows.upsert_watch(renewed)).history_id == "20"
        assert await workflows.expiring_watches(NOW + timedelta(days=1), 5) == ()
        assert await workflows.advance_history(
            "subject-1",
            "20",
            "21",
            NOW + timedelta(minutes=2),
        )
        assert not await workflows.advance_history(
            "subject-1",
            "20",
            "22",
            NOW + timedelta(minutes=3),
        )

        event = EmailTaskEvent(
            event_id="event-1",
            workflow_id=created.workflow.workflow_id,
            gmail_message_id="message-1",
            gmail_thread_id="thread-1",
            history_id="21",
            sender="customer@example.com",
            recipient="operator@example.com",
            subject_line=f"Move delivery [{created.workflow.routing_key}]",
            body_hash="b" * 64,
            proposed_title="Move customer delivery to Friday",
            proposed_note="Customer confirmed Friday delivery.",
            status=EmailTaskEventStatus.APPLIED,
            rationale="The authorized customer requested a clear scheduling update.",
            risk_flags=(),
            task_revision="task-v2",
            receipt_checksum="a" * 64,
            received_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
        stored_event = await workflows.persist_event(event)
        assert stored_event.reused is False
        assert (await workflows.persist_event(event)).reused is True
        assert await workflows.get_event(created.workflow.workflow_id, "message-1") == event
        assert await workflows.list_events_for_subject("subject-1", manifest.packet_id) == (event,)
        with pytest.raises(ValueError, match="different evidence"):
            await workflows.persist_event(event.model_copy(update={"receipt_checksum": "c" * 64}))

        paused = await workflows.pause_for_subject(
            "subject-1",
            created.workflow.workflow_id,
            NOW + timedelta(minutes=4),
        )
        assert paused is not None
        assert paused.status == EmailTaskWorkflowStatus.PAUSED
        assert await workflows.get_by_identity("subject-1", created.workflow.routing_key) is None
        assert await workflows.active_for_mailbox("operator@example.com") == ()
        assert await workflows.subject_for_mailbox("operator@example.com") is None
        assert await workflows.pause_for_subject("subject-1", "missing", NOW) is None
        await engine.dispose()

    asyncio.run(scenario())


def test_gmail_watch_is_renewed_before_expiry_with_the_same_mailbox_identity() -> None:
    expiring = GmailWatchStream(
        subject="subject-1",
        mailbox_email="operator@example.com",
        history_id="100",
        expiration=NOW + timedelta(hours=3),
        created_at=NOW - timedelta(days=6),
        updated_at=NOW - timedelta(days=6),
    )

    class Watches:
        stored = expiring

        async def expiring_watches(self, before, limit):  # type: ignore[no-untyped-def]
            assert before == NOW + timedelta(days=1)
            assert limit == 25
            return (self.stored,)

        async def upsert_watch(self, stream):  # type: ignore[no-untyped-def]
            self.stored = stream
            return stream

    class Sessions:
        async def get(self, subject: str) -> WorkspaceSession:
            assert subject == "subject-1"
            return WorkspaceSession(
                access_token="access-token",
                authorization=WorkspaceAuthorization(frozenset(REQUIRED_WORKSPACE_SCOPES)),
                email="operator@example.com",
            )

    class Gmail:
        async def start_watch(
            self,
            subject,
            mailbox_email,
            access_token,
            topic_name,
            now=None,
        ):  # type: ignore[no-untyped-def]
            assert (subject, mailbox_email, access_token) == (
                "subject-1",
                "operator@example.com",
                "access-token",
            )
            assert topic_name == "projects/project-1/topics/gmail-events"
            return expiring.model_copy(
                update={
                    "history_id": "200",
                    "expiration": NOW + timedelta(days=7),
                    "updated_at": now,
                }
            )

    async def scenario() -> None:
        watches = Watches()
        service = GmailWatchRenewalService(
            watches,
            Sessions(),
            Gmail(),
            "projects/project-1/topics/gmail-events",
        )
        assert await service.renew(NOW) == 1
        assert watches.stored.history_id == "200"
        assert watches.stored.expiration == NOW + timedelta(days=7)

    asyncio.run(scenario())


def test_registration_coordinator_checks_scopes_starts_watch_and_hides_expired_streams() -> None:
    class Sessions:
        def __init__(self, scopes=frozenset(REQUIRED_WORKSPACE_SCOPES)) -> None:  # type: ignore[no-untyped-def]
            self.scopes = scopes

        async def get(self, subject: str) -> WorkspaceSession:
            return WorkspaceSession(
                access_token=f"token-for-{subject}",
                authorization=WorkspaceAuthorization(self.scopes),
                email="operator@example.com",
            )

    class Gmail:
        async def start_watch(
            self,
            subject,
            mailbox_email,
            access_token,
            topic_name,
            now=None,
        ):  # type: ignore[no-untyped-def]
            assert access_token == f"token-for-{subject}"
            assert topic_name == "projects/project-1/topics/gmail-events"
            return GmailWatchStream(
                subject=subject,
                mailbox_email=mailbox_email,
                history_id="101",
                expiration=(now or NOW) + timedelta(days=7),
                created_at=now or NOW,
                updated_at=now or NOW,
            )

    async def scenario() -> None:
        manifest = await _manifest()
        repository = MemoryWorkflows()
        workflows = EmailTaskWorkflowService(LatestManifest(manifest), repository)  # type: ignore[arg-type]
        coordinator = EmailTaskRegistrationCoordinator(
            workflows,
            repository,  # type: ignore[arg-type]
            Sessions(),
            Gmail(),
            "projects/project-1/topics/gmail-events",
        )
        created = await coordinator.register(
            "subject-1",
            "operator@example.com",
            _request(),
            NOW,
        )
        assert created.watch.history_id == "101"
        assert (await coordinator.list("subject-1"))[0] == created.workflow
        assert await coordinator.list_events("subject-1", manifest.packet_id) == ()
        assert (
            await coordinator.setup("subject-1", "operator@example.com", manifest.packet_id)
        ).workflows == (created.workflow,)
        paused = await coordinator.pause("subject-1", created.workflow.workflow_id)
        assert paused.status == EmailTaskWorkflowStatus.PAUSED

        repository.watch = created.watch.model_copy(
            update={"expiration": NOW - timedelta(minutes=1)}
        )
        assert (
            await coordinator.setup("subject-1", "operator@example.com", manifest.packet_id)
        ).workflows == ()

        no_scopes = EmailTaskRegistrationCoordinator(
            EmailTaskWorkflowService(LatestManifest(manifest), MemoryWorkflows()),  # type: ignore[arg-type]
            MemoryWorkflows(),  # type: ignore[arg-type]
            Sessions(frozenset()),
            Gmail(),
            "projects/project-1/topics/gmail-events",
        )
        with pytest.raises(EmailTaskWorkflowError, match="Reconnect Google Workspace"):
            await no_scopes.register(
                "subject-1",
                "operator@example.com",
                _request(),
                NOW,
            )

    with pytest.raises(ValueError, match="fully-qualified"):
        EmailTaskRegistrationCoordinator(  # type: ignore[arg-type]
            object(),
            object(),
            object(),
            object(),
            "not-a-topic",
        )
    asyncio.run(scenario())
