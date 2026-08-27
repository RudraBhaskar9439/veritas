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
from veritas_runtime.email_tasks.google import EmailTaskPreconditionFailed
from veritas_runtime.email_tasks.models import (
    EmailTaskEvent,
    EmailTaskEventResult,
    EmailTaskEventStatus,
    EmailTaskReviewDecision,
    EmailTaskThreadBinding,
    EmailTaskThreadSource,
    EmailTaskUnmatchedRequest,
    EmailTaskUnmatchedStatus,
    EmailTaskWorkflowStatus,
    GmailConversationSeed,
    GmailWatchStream,
    GoogleTaskState,
    RegisterEmailTaskWorkflowRequest,
    ReviewEmailTaskEventRequest,
)
from veritas_runtime.email_tasks.policy import (
    InvalidEmailAddress,
    deterministic_risk_flags,
    normalize_email,
)
from veritas_runtime.email_tasks.service import (
    EmailTaskRegistrationCoordinator,
    EmailTaskWorkflowError,
    EmailTaskWorkflowService,
    GmailWatchRenewalService,
)
from veritas_runtime.execution.service import WorkspaceSession
from veritas_runtime.execution.sessions import WorkspaceSessionUnavailable
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
        self.threads = {}
        self.unmatched = {}
        self.events = {}

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

    async def get_by_workflow_id(self, subject, workflow_id):  # type: ignore[no-untyped-def]
        return next(
            (
                workflow
                for (workflow_subject, _), (workflow, _) in self.records.items()
                if workflow_subject == subject and workflow.workflow_id == workflow_id
            ),
            None,
        )

    async def list_threads_for_subject(self, subject):  # type: ignore[no-untyped-def]
        return tuple(thread for thread in self.threads.values() if thread.subject == subject)

    async def bind_thread(self, thread):  # type: ignore[no-untyped-def]
        existing = self.threads.get((thread.subject, thread.gmail_thread_id))
        if existing is not None and existing.workflow_id != thread.workflow_id:
            raise ValueError("A Gmail thread is already bound to another workflow")
        self.threads[(thread.subject, thread.gmail_thread_id)] = thread
        return existing or thread

    async def list_unmatched_for_subject(self, subject):  # type: ignore[no-untyped-def]
        return tuple(request for request in self.unmatched.values() if request.subject == subject)

    async def get_unmatched(self, subject, request_id):  # type: ignore[no-untyped-def]
        request = self.unmatched.get(request_id)
        return request if request is not None and request.subject == subject else None

    async def bind_unmatched(self, subject, request_id, workflow_id, updated_at):  # type: ignore[no-untyped-def]
        request = await self.get_unmatched(subject, request_id)
        if request is None:
            return None
        if workflow_id not in request.candidate_workflow_ids:
            raise ValueError("The selected workflow is not authorized for this sender")
        bound = request.model_copy(
            update={
                "status": EmailTaskUnmatchedStatus.BOUND,
                "bound_workflow_id": workflow_id,
                "updated_at": updated_at,
            }
        )
        self.unmatched[request_id] = bound
        return bound

    async def list_events_for_subject(self, subject: str, packet_id: str):  # type: ignore[no-untyped-def]
        workflows = {
            workflow.workflow_id
            for (workflow_subject, _), (workflow, _) in self.records.items()
            if workflow_subject == subject and workflow.packet_id == packet_id
        }
        return tuple(event for event in self.events.values() if event.workflow_id in workflows)

    async def get_event_by_id(self, subject, event_id):  # type: ignore[no-untyped-def]
        event = self.events.get(event_id)
        if event is None:
            return None
        workflow = await self.get_by_workflow_id(subject, event.workflow_id)
        return event if workflow is not None else None

    async def claim_event_review(
        self,
        subject,
        event_id,
        decision,
        request_id,
        reason,
        reviewed_by,
        reviewed_at,
    ):  # type: ignore[no-untyped-def]
        event = await self.get_event_by_id(subject, event_id)
        if event is None:
            raise ValueError("The escalated email request was not found")
        if event.review_request_id == request_id:
            return EmailTaskEventResult(event=event, reused=True)
        if event.status != EmailTaskEventStatus.ESCALATED:
            raise ValueError("The email request has already been resolved")
        claimed = event.model_copy(
            update={
                "status": EmailTaskEventStatus.REVIEWING,
                "review_decision": decision,
                "review_request_id": request_id,
                "review_reason": reason,
                "reviewed_by": reviewed_by,
                "reviewed_at": reviewed_at,
                "updated_at": reviewed_at,
            }
        )
        self.events[event_id] = claimed
        return EmailTaskEventResult(event=claimed, reused=False)

    async def finalize_event_review(
        self,
        event_id,
        request_id,
        status,
        task_revision,
        review_receipt_checksum,
        updated_at,
    ):  # type: ignore[no-untyped-def]
        event = self.events[event_id]
        if event.review_request_id != request_id:
            raise ValueError("Another operator owns this email review")
        if event.status == status and event.review_receipt_checksum:
            return EmailTaskEventResult(event=event, reused=True)
        resolved = event.model_copy(
            update={
                "status": status,
                "task_revision": task_revision,
                "review_receipt_checksum": review_receipt_checksum,
                "updated_at": updated_at,
            }
        )
        self.events[event_id] = resolved
        return EmailTaskEventResult(event=resolved, reused=False)

    async def release_event_review(self, event_id, request_id, updated_at):  # type: ignore[no-untyped-def]
        event = self.events.get(event_id)
        if event is None or event.review_request_id != request_id:
            return event
        released = event.model_copy(
            update={
                "status": EmailTaskEventStatus.ESCALATED,
                "review_decision": None,
                "review_request_id": None,
                "review_reason": None,
                "reviewed_by": None,
                "reviewed_at": None,
                "updated_at": updated_at,
            }
        )
        self.events[event_id] = released
        return released

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
        assert first.workflow.routing_key.startswith("VX-")

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
        assert await workflows.active_for_sender("subject-1", "customer@example.com") == (
            created.workflow,
        )
        assert await workflows.list_for_subject("subject-1") == (created.workflow,)
        assert (
            await workflows.get_by_workflow_id("subject-1", created.workflow.workflow_id)
        ) == created.workflow
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

        thread = EmailTaskThreadBinding(
            binding_id="binding-1",
            subject="subject-1",
            workflow_id=created.workflow.workflow_id,
            gmail_thread_id="thread-1",
            bootstrap_message_id="seed-1",
            subject_line="Increase acquisition spend — customer update",
            source=EmailTaskThreadSource.COMPANY_STARTED,
            created_at=NOW,
            updated_at=NOW,
        )
        assert await workflows.bind_thread(thread) == thread
        assert await workflows.bind_thread(thread) == thread
        assert await workflows.get_by_thread("subject-1", "thread-1") == created.workflow
        assert await workflows.list_threads_for_subject("subject-1") == (thread,)

        unmatched = EmailTaskUnmatchedRequest(
            request_id="unmatched-1",
            subject="subject-1",
            gmail_message_id="message-unmatched",
            gmail_thread_id="thread-new",
            mailbox_email="operator@example.com",
            sender="customer@example.com",
            recipient="operator@example.com",
            subject_line="A separate acquisition request",
            body_hash="d" * 64,
            candidate_workflow_ids=(created.workflow.workflow_id,),
            status=EmailTaskUnmatchedStatus.PENDING,
            bound_workflow_id=None,
            receipt_checksum="e" * 64,
            received_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
        assert await workflows.persist_unmatched(unmatched) == unmatched
        assert await workflows.persist_unmatched(unmatched) == unmatched
        with pytest.raises(ValueError, match="different evidence"):
            await workflows.persist_unmatched(unmatched.model_copy(update={"body_hash": "c" * 64}))
        assert await workflows.get_unmatched("subject-1", "unmatched-1") == unmatched
        assert await workflows.list_unmatched_for_subject("subject-1") == (unmatched,)
        bound_unmatched = await workflows.bind_unmatched(
            "subject-1",
            "unmatched-1",
            created.workflow.workflow_id,
            NOW + timedelta(minutes=3),
        )
        assert bound_unmatched is not None
        assert bound_unmatched.status == EmailTaskUnmatchedStatus.BOUND

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

        escalated_event = event.model_copy(
            update={
                "event_id": "event-review-1",
                "gmail_message_id": "message-review-1",
                "status": EmailTaskEventStatus.ESCALATED,
                "task_revision": None,
                "receipt_checksum": "f" * 64,
            }
        )
        assert (await workflows.persist_event(escalated_event)).reused is False
        assert (
            await workflows.get_event_by_id("subject-1", escalated_event.event_id)
        ) == escalated_event
        claimed = await workflows.claim_event_review(
            "subject-1",
            escalated_event.event_id,
            EmailTaskReviewDecision.APPROVE,
            "review-request-1",
            "Approved after checking the current task and customer request.",
            "operator@example.com",
            NOW + timedelta(minutes=4),
        )
        assert claimed.event.status == EmailTaskEventStatus.REVIEWING
        assert (
            await workflows.claim_event_review(
                "subject-1",
                escalated_event.event_id,
                EmailTaskReviewDecision.APPROVE,
                "review-request-1",
                "Approved after checking the current task and customer request.",
                "operator@example.com",
                NOW + timedelta(minutes=4),
            )
        ).reused is True
        resolved = await workflows.finalize_event_review(
            escalated_event.event_id,
            "review-request-1",
            EmailTaskEventStatus.APPLIED,
            "task-v3",
            "1" * 64,
            NOW + timedelta(minutes=5),
        )
        assert resolved.event.status == EmailTaskEventStatus.APPLIED
        assert resolved.event.review_receipt_checksum == "1" * 64
        assert (
            await workflows.finalize_event_review(
                escalated_event.event_id,
                "review-request-1",
                EmailTaskEventStatus.APPLIED,
                "task-v3",
                "1" * 64,
                NOW + timedelta(minutes=5),
            )
        ).reused is True
        with pytest.raises(ValueError, match="another decision"):
            await workflows.claim_event_review(
                "subject-1",
                escalated_event.event_id,
                EmailTaskReviewDecision.REJECT,
                "review-request-1",
                "Rejected after reviewing the customer request again.",
                "operator@example.com",
                NOW,
            )
        with pytest.raises(ValueError, match="already been resolved"):
            await workflows.claim_event_review(
                "subject-1",
                escalated_event.event_id,
                EmailTaskReviewDecision.APPROVE,
                "review-request-2",
                "Approved after reviewing the customer request again.",
                "operator@example.com",
                NOW,
            )
        with pytest.raises(ValueError, match="only finish"):
            await workflows.finalize_event_review(
                escalated_event.event_id,
                "review-request-1",
                EmailTaskEventStatus.ESCALATED,
                None,
                "2" * 64,
                NOW,
            )
        with pytest.raises(ValueError, match="not found"):
            await workflows.finalize_event_review(
                "missing-email-event",
                "review-request-1",
                EmailTaskEventStatus.REJECTED,
                None,
                "2" * 64,
                NOW,
            )

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
        def __init__(self) -> None:
            self.task = GoogleTaskState(
                task_id="workspace-artifact-acquisition-task",
                title="Increase acquisition spend",
                notes="Owner: growth team",
                etag="task-v1",
            )
            self.updates = 0

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

        async def ensure_conversation(
            self,
            access_token,
            mailbox_email,
            customer_email,
            subject_line,
            body,
            message_id,
        ):  # type: ignore[no-untyped-def]
            assert access_token == "token-for-subject-1"
            assert (mailbox_email, customer_email) == (
                "operator@example.com",
                "customer@example.com",
            )
            assert "VX-" not in subject_line
            assert "reply to this conversation" in body
            assert message_id.endswith("@veritas-agent.invalid>")
            return GmailConversationSeed(
                gmail_message_id="seed-message-1",
                gmail_thread_id="gmail-thread-1",
            )

        async def get_task(self, access_token, task_list_id, task_id):  # type: ignore[no-untyped-def]
            assert access_token == "token-for-subject-1"
            assert (task_list_id, task_id) == (
                "workspace-task-list",
                "workspace-artifact-acquisition-task",
            )
            return self.task

        async def update_task(
            self,
            access_token,
            task_list_id,
            current,
            title,
            notes,
        ):  # type: ignore[no-untyped-def]
            assert access_token == "token-for-subject-1"
            assert task_list_id == "workspace-task-list"
            assert current.etag == self.task.etag
            self.updates += 1
            self.task = GoogleTaskState(
                task_id=current.task_id,
                title=title,
                notes=notes,
                etag=f"task-v{self.updates + 1}",
            )
            return self.task

    async def scenario() -> None:
        manifest = await _manifest()
        repository = MemoryWorkflows()
        workflows = EmailTaskWorkflowService(LatestManifest(manifest), repository)  # type: ignore[arg-type]
        gmail = Gmail()
        coordinator = EmailTaskRegistrationCoordinator(
            workflows,
            repository,  # type: ignore[arg-type]
            Sessions(),
            gmail,
            "projects/project-1/topics/gmail-events",
        )
        created = await coordinator.register(
            "subject-1",
            "operator@example.com",
            _request(),
            NOW,
        )
        assert created.watch.history_id == "101"
        thread = await coordinator.start_conversation(
            "subject-1", created.workflow.workflow_id, NOW
        )
        assert thread.gmail_thread_id == "gmail-thread-1"
        assert thread.source == EmailTaskThreadSource.COMPANY_STARTED
        assert (
            await coordinator.start_conversation("subject-1", created.workflow.workflow_id, NOW)
        ) == thread
        assert (await coordinator.list("subject-1"))[0] == created.workflow
        assert await coordinator.list_events("subject-1", manifest.packet_id) == ()
        assert (
            await coordinator.setup("subject-1", "operator@example.com", manifest.packet_id)
        ).workflows == (created.workflow,)

        escalated = EmailTaskEvent(
            event_id="email-event-review-1",
            workflow_id=created.workflow.workflow_id,
            gmail_message_id="customer-message-review-1",
            gmail_thread_id="gmail-thread-1",
            history_id="102",
            sender="customer@example.com",
            recipient="operator@example.com",
            subject_line="Re: Increase acquisition spend — customer update",
            body_hash="b" * 64,
            proposed_title="Decrease acquisition spend by 10%",
            proposed_note="Customer requested a 10% decrease from the quoted acquisition spend.",
            status=EmailTaskEventStatus.ESCALATED,
            rationale="The customer reversed the registered acquisition recommendation.",
            risk_flags=("decision_reversal",),
            task_revision=None,
            receipt_checksum="c" * 64,
            received_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
        repository.events[escalated.event_id] = escalated
        approval = ReviewEmailTaskEventRequest(
            request_id="approval-request-1",
            decision=EmailTaskReviewDecision.APPROVE,
            reason="Approved after reviewing the customer request and current task.",
        )
        applied = await coordinator.review_event(
            "subject-1",
            "operator@example.com",
            escalated.event_id,
            approval,
            NOW + timedelta(minutes=1),
        )
        assert applied.reused is False
        assert applied.event.status == EmailTaskEventStatus.APPLIED
        assert applied.event.reviewed_by == "operator@example.com"
        assert applied.event.review_decision == EmailTaskReviewDecision.APPROVE
        assert applied.event.task_revision == "task-v2"
        assert applied.event.review_receipt_checksum is not None
        assert gmail.task.title == "Decrease acquisition spend by 10%"
        assert "Owner: growth team" in gmail.task.notes
        assert escalated.event_id in gmail.task.notes
        assert (
            await coordinator.review_event(
                "subject-1",
                "operator@example.com",
                escalated.event_id,
                approval,
                NOW + timedelta(minutes=2),
            )
        ).reused is True
        assert gmail.updates == 1

        rejected_event = escalated.model_copy(
            update={
                "event_id": "email-event-review-2",
                "gmail_message_id": "customer-message-review-2",
                "receipt_checksum": "d" * 64,
            }
        )
        repository.events[rejected_event.event_id] = rejected_event
        rejected = await coordinator.review_event(
            "subject-1",
            "operator@example.com",
            rejected_event.event_id,
            ReviewEmailTaskEventRequest(
                request_id="rejection-request-1",
                decision=EmailTaskReviewDecision.REJECT,
                reason="Rejected because the company is retaining the approved plan.",
            ),
            NOW + timedelta(minutes=3),
        )
        assert rejected.event.status == EmailTaskEventStatus.REJECTED
        assert rejected.event.task_revision is None
        assert gmail.updates == 1

        with pytest.raises(EmailTaskWorkflowError, match="not found"):
            await coordinator.review_event(
                "subject-1",
                "operator@example.com",
                "missing-email-event",
                approval,
                NOW,
            )
        with pytest.raises(EmailTaskWorkflowError, match="another decision"):
            await coordinator.review_event(
                "subject-1",
                "operator@example.com",
                escalated.event_id,
                ReviewEmailTaskEventRequest(
                    request_id=approval.request_id,
                    decision=EmailTaskReviewDecision.REJECT,
                    reason="Rejected after a second review of the customer request.",
                ),
                NOW,
            )
        with pytest.raises(EmailTaskWorkflowError, match="already been resolved"):
            await coordinator.review_event(
                "subject-1",
                "operator@example.com",
                rejected_event.event_id,
                ReviewEmailTaskEventRequest(
                    request_id="another-review-request",
                    decision=EmailTaskReviewDecision.REJECT,
                    reason="Rejected after a second review of the customer request.",
                ),
                NOW,
            )

        no_proposal = escalated.model_copy(
            update={
                "event_id": "email-event-no-proposal",
                "gmail_message_id": "customer-message-no-proposal",
                "proposed_title": None,
                "proposed_note": None,
                "receipt_checksum": "2" * 64,
            }
        )
        repository.events[no_proposal.event_id] = no_proposal
        with pytest.raises(EmailTaskWorkflowError, match="no bounded task update"):
            await coordinator.review_event(
                "subject-1",
                "operator@example.com",
                no_proposal.event_id,
                ReviewEmailTaskEventRequest(
                    request_id="no-proposal-request",
                    decision=EmailTaskReviewDecision.APPROVE,
                    reason="Approved after reviewing the ambiguous customer request.",
                ),
                NOW,
            )

        missing_review_scopes = EmailTaskRegistrationCoordinator(
            workflows,
            repository,  # type: ignore[arg-type]
            Sessions(frozenset()),
            Gmail(),
            "projects/project-1/topics/gmail-events",
        )
        with pytest.raises(EmailTaskWorkflowError, match="Reconnect Google Workspace"):
            await missing_review_scopes.review_event(
                "subject-1",
                "operator@example.com",
                no_proposal.event_id,
                ReviewEmailTaskEventRequest(
                    request_id="missing-scope-request",
                    decision=EmailTaskReviewDecision.REJECT,
                    reason="Rejected after reviewing the customer request and current task.",
                ),
                NOW,
            )

        conflict_event = escalated.model_copy(
            update={
                "event_id": "email-event-conflict",
                "gmail_message_id": "customer-message-conflict",
                "receipt_checksum": "3" * 64,
            }
        )
        repository.events[conflict_event.event_id] = conflict_event

        class ConflictGmail(Gmail):
            async def update_task(
                self,
                access_token,
                task_list_id,
                current,
                title,
                notes,
            ):  # type: ignore[no-untyped-def]
                del access_token, task_list_id, current, title, notes
                raise EmailTaskPreconditionFailed("concurrent human edit")

        conflict_coordinator = EmailTaskRegistrationCoordinator(
            workflows,
            repository,  # type: ignore[arg-type]
            Sessions(),
            ConflictGmail(),
            "projects/project-1/topics/gmail-events",
        )
        with pytest.raises(EmailTaskWorkflowError, match="changed during review"):
            await conflict_coordinator.review_event(
                "subject-1",
                "operator@example.com",
                conflict_event.event_id,
                ReviewEmailTaskEventRequest(
                    request_id="conflict-review-request",
                    decision=EmailTaskReviewDecision.APPROVE,
                    reason="Approved after checking the customer request and current task.",
                ),
                NOW,
            )
        assert repository.events[conflict_event.event_id].status == EmailTaskEventStatus.ESCALATED
        assert repository.events[conflict_event.event_id].review_request_id is None

        recovery_event = escalated.model_copy(
            update={
                "event_id": "email-event-recovery",
                "gmail_message_id": "customer-message-recovery",
                "receipt_checksum": "4" * 64,
            }
        )
        repository.events[recovery_event.event_id] = recovery_event
        recovery_gmail = Gmail()
        recovery_gmail.task = recovery_gmail.task.model_copy(
            update={
                "title": recovery_event.proposed_title,
                "notes": f"Owner: growth team\n{recovery_event.event_id}",
                "etag": "task-recovered",
            }
        )
        recovered = await EmailTaskRegistrationCoordinator(
            workflows,
            repository,  # type: ignore[arg-type]
            Sessions(),
            recovery_gmail,
            "projects/project-1/topics/gmail-events",
        ).review_event(
            "subject-1",
            "operator@example.com",
            recovery_event.event_id,
            ReviewEmailTaskEventRequest(
                request_id="recovery-review-request",
                decision=EmailTaskReviewDecision.APPROVE,
                reason="Approved after checking the recovered customer task update.",
            ),
            NOW,
        )
        assert recovered.event.status == EmailTaskEventStatus.APPLIED
        assert recovered.event.task_revision == "task-recovered"
        assert recovery_gmail.updates == 0

        unmatched = EmailTaskUnmatchedRequest(
            request_id="unmatched-bind-1",
            subject="subject-1",
            gmail_message_id="customer-message-1",
            gmail_thread_id="customer-started-thread-1",
            mailbox_email="operator@example.com",
            sender="customer@example.com",
            recipient="operator@example.com",
            subject_line="Please revise our acquisition plan",
            body_hash="f" * 64,
            candidate_workflow_ids=(created.workflow.workflow_id,),
            status=EmailTaskUnmatchedStatus.PENDING,
            bound_workflow_id=None,
            receipt_checksum="a" * 64,
            received_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
        repository.unmatched[unmatched.request_id] = unmatched
        operator_bound = await coordinator.bind_unmatched(
            "subject-1",
            unmatched.request_id,
            created.workflow.workflow_id,
            NOW + timedelta(minutes=1),
        )
        assert operator_bound.gmail_thread_id == "customer-started-thread-1"
        assert operator_bound.source == EmailTaskThreadSource.OPERATOR_BOUND
        assert repository.unmatched[unmatched.request_id].status == EmailTaskUnmatchedStatus.BOUND
        assert (
            repository.unmatched[unmatched.request_id].bound_workflow_id
            == created.workflow.workflow_id
        )

        alternate = await coordinator.register(
            "subject-1",
            "operator@example.com",
            _request(authorized_sender="other-customer@example.com"),
            NOW,
        )
        with pytest.raises(EmailTaskWorkflowError, match="not found"):
            await coordinator.bind_unmatched(
                "subject-1",
                "missing-request",
                created.workflow.workflow_id,
                NOW,
            )
        with pytest.raises(EmailTaskWorkflowError, match="not authorized"):
            await coordinator.bind_unmatched(
                "subject-1",
                unmatched.request_id,
                alternate.workflow.workflow_id,
                NOW,
            )

        missing_conversation_scopes = EmailTaskRegistrationCoordinator(
            workflows,
            repository,  # type: ignore[arg-type]
            Sessions(frozenset()),
            Gmail(),
            "projects/project-1/topics/gmail-events",
        )
        with pytest.raises(EmailTaskWorkflowError, match="Reconnect Google Workspace"):
            await missing_conversation_scopes.start_conversation(
                "subject-1", alternate.workflow.workflow_id, NOW
            )

        paused = await coordinator.pause("subject-1", created.workflow.workflow_id)
        assert paused.status == EmailTaskWorkflowStatus.PAUSED
        with pytest.raises(EmailTaskWorkflowError, match="paused"):
            await coordinator.start_conversation("subject-1", created.workflow.workflow_id, NOW)
        with pytest.raises(EmailTaskWorkflowError, match="paused"):
            await coordinator.bind_unmatched(
                "subject-1",
                unmatched.request_id,
                created.workflow.workflow_id,
                NOW,
            )

        repository.watch = created.watch.model_copy(
            update={"expiration": NOW - timedelta(minutes=1)}
        )
        with pytest.raises(EmailTaskWorkflowError, match="Reconnect Google Workspace"):
            await coordinator.start_conversation("subject-1", alternate.workflow.workflow_id, NOW)
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

        class DisconnectedSessions:
            async def get(self, subject: str) -> WorkspaceSession:
                raise WorkspaceSessionUnavailable("authorization must be refreshed")

        disconnected = EmailTaskRegistrationCoordinator(
            EmailTaskWorkflowService(LatestManifest(manifest), MemoryWorkflows()),  # type: ignore[arg-type]
            MemoryWorkflows(),  # type: ignore[arg-type]
            DisconnectedSessions(),
            Gmail(),
            "projects/project-1/topics/gmail-events",
        )
        with pytest.raises(EmailTaskWorkflowError, match="Reconnect Google Workspace"):
            await disconnected.register(
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
