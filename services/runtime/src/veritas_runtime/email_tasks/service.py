import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from veritas_runtime.auth.oauth import OAuthExchangeError
from veritas_runtime.email_tasks.google import EmailTaskPreconditionFailed
from veritas_runtime.email_tasks.models import (
    EmailTaskEligibleRoute,
    EmailTaskEvent,
    EmailTaskEventResult,
    EmailTaskEventStatus,
    EmailTaskRegistrationResult,
    EmailTaskReviewDecision,
    EmailTaskSetup,
    EmailTaskThreadBinding,
    EmailTaskThreadSource,
    EmailTaskUnmatchedRequest,
    EmailTaskWorkflow,
    EmailTaskWorkflowResult,
    EmailTaskWorkflowStatus,
    GmailConversationSeed,
    GmailWatchStream,
    GoogleTaskState,
    RegisterEmailTaskWorkflowRequest,
    ReviewEmailTaskEventRequest,
)
from veritas_runtime.email_tasks.policy import normalize_email, workflow_routing_key
from veritas_runtime.email_tasks.processor import managed_task_notes
from veritas_runtime.execution.service import WorkspaceSession
from veritas_runtime.execution.sessions import WorkspaceSessionUnavailable
from veritas_runtime.packets.generator import manifest_checksum
from veritas_runtime.packets.models import ArtifactKind, ClaimManifest
from veritas_runtime.workspace.contracts import MissingWorkspaceScope, WorkspaceCapability


class EmailTaskWorkflowError(RuntimeError):
    pass


class GmailWatchGateway(Protocol):
    async def start_watch(
        self,
        subject: str,
        mailbox_email: str,
        access_token: str,
        topic_name: str,
        now: datetime | None = None,
    ) -> GmailWatchStream: ...

    async def ensure_conversation(
        self,
        access_token: str,
        mailbox_email: str,
        customer_email: str,
        subject_line: str,
        body: str,
        message_id: str,
    ) -> GmailConversationSeed: ...

    async def get_task(
        self,
        access_token: str,
        task_list_id: str,
        task_id: str,
    ) -> GoogleTaskState: ...

    async def update_task(
        self,
        access_token: str,
        task_list_id: str,
        current: GoogleTaskState,
        title: str,
        notes: str,
    ) -> GoogleTaskState: ...


class EmailTaskWorkspaceSessionProvider(Protocol):
    async def get(self, subject: str) -> WorkspaceSession: ...


class EmailTaskManifestRepository(Protocol):
    async def latest_for_packet(self, packet_id: str) -> ClaimManifest | None: ...


class EmailTaskWorkflowRepository(Protocol):
    async def packet_registered_for_subject(self, subject: str, packet_id: str) -> bool: ...

    async def get_by_identity(
        self,
        subject: str,
        routing_key: str,
    ) -> EmailTaskWorkflow | None: ...

    async def persist(
        self,
        workflow: EmailTaskWorkflow,
        input_digest: str,
    ) -> EmailTaskWorkflowResult: ...

    async def list_for_subject(self, subject: str) -> tuple[EmailTaskWorkflow, ...]: ...

    async def get_by_workflow_id(
        self,
        subject: str,
        workflow_id: str,
    ) -> EmailTaskWorkflow | None: ...

    async def list_threads_for_subject(
        self,
        subject: str,
    ) -> tuple[EmailTaskThreadBinding, ...]: ...

    async def bind_thread(
        self,
        binding: EmailTaskThreadBinding,
    ) -> EmailTaskThreadBinding: ...

    async def list_unmatched_for_subject(
        self,
        subject: str,
    ) -> tuple[EmailTaskUnmatchedRequest, ...]: ...

    async def get_unmatched(
        self,
        subject: str,
        request_id: str,
    ) -> EmailTaskUnmatchedRequest | None: ...

    async def bind_unmatched(
        self,
        subject: str,
        request_id: str,
        workflow_id: str,
        updated_at: datetime,
    ) -> EmailTaskUnmatchedRequest | None: ...

    async def pause_for_subject(
        self,
        subject: str,
        workflow_id: str,
        updated_at: datetime,
    ) -> EmailTaskWorkflow | None: ...

    async def upsert_watch(self, stream: GmailWatchStream) -> GmailWatchStream: ...

    async def get_watch(self, subject: str) -> GmailWatchStream | None: ...

    async def list_events_for_subject(
        self,
        subject: str,
        packet_id: str,
    ) -> tuple[EmailTaskEvent, ...]: ...

    async def get_event_by_id(
        self,
        subject: str,
        event_id: str,
    ) -> EmailTaskEvent | None: ...

    async def claim_event_review(
        self,
        subject: str,
        event_id: str,
        decision: EmailTaskReviewDecision,
        request_id: str,
        reason: str,
        reviewed_by: str,
        reviewed_at: datetime,
    ) -> EmailTaskEventResult: ...

    async def finalize_event_review(
        self,
        event_id: str,
        request_id: str,
        status: EmailTaskEventStatus,
        task_revision: str | None,
        review_receipt_checksum: str,
        updated_at: datetime,
    ) -> EmailTaskEventResult: ...

    async def release_event_review(
        self,
        event_id: str,
        request_id: str,
        updated_at: datetime,
    ) -> EmailTaskEvent | None: ...


class EmailTaskWorkflowService:
    """Registers sender and Gmail-thread authority through a Claim Manifest edge."""

    def __init__(
        self,
        manifests: EmailTaskManifestRepository,
        workflows: EmailTaskWorkflowRepository,
    ) -> None:
        self._manifests = manifests
        self._workflows = workflows

    async def register(
        self,
        subject: str,
        mailbox_email: str,
        request: RegisterEmailTaskWorkflowRequest,
        now: datetime | None = None,
    ) -> EmailTaskWorkflowResult:
        if not await self._workflows.packet_registered_for_subject(subject, request.packet_id):
            raise EmailTaskWorkflowError("The decision packet is not registered to this account")
        manifest = await self._manifests.latest_for_packet(request.packet_id)
        if manifest is None:
            raise EmailTaskWorkflowError("The registered Claim Manifest was not found")
        claim = next((item for item in manifest.claims if item.claim_id == request.claim_id), None)
        artifact = next(
            (item for item in manifest.artifacts if item.artifact_id == request.artifact_id),
            None,
        )
        if claim is None or artifact is None:
            raise EmailTaskWorkflowError("The requested claim-to-artifact route is not registered")
        if not any(anchor.artifact_id == artifact.artifact_id for anchor in claim.artifact_anchors):
            raise EmailTaskWorkflowError(
                "The requested task is outside the registered claim lineage"
            )
        if artifact.kind != ArtifactKind.GOOGLE_TASK or not artifact.container_id:
            raise EmailTaskWorkflowError(
                "The registered artifact is not an addressable Google Task"
            )

        sender = normalize_email(request.authorized_sender)
        mailbox = normalize_email(mailbox_email)
        routing_key = workflow_routing_key(
            subject,
            manifest.packet_id,
            claim.claim_id,
            artifact.artifact_id,
            sender,
        )
        identity = f"{subject}:{routing_key}"
        instant = (now or datetime.now(UTC)).astimezone(UTC)
        workflow = EmailTaskWorkflow(
            workflow_id=f"email-task-{uuid5(NAMESPACE_URL, identity)}",
            subject=subject,
            mailbox_email=mailbox,
            authorized_sender=sender,
            routing_key=routing_key,
            packet_id=manifest.packet_id,
            manifest_id=manifest.manifest_id,
            claim_id=claim.claim_id,
            artifact_id=artifact.artifact_id,
            task_id=artifact.resource_id,
            task_list_id=artifact.container_id,
            status=EmailTaskWorkflowStatus.ACTIVE,
            created_at=instant,
            updated_at=instant,
        )
        digest = hashlib.sha256(
            json.dumps(
                {
                    "workflow": {
                        **workflow.model_dump(mode="json", by_alias=True),
                        "routingKey": workflow.routing_key,
                    },
                    "manifestChecksum": manifest_checksum(manifest),
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return await self._workflows.persist(workflow, digest)

    async def list(self, subject: str) -> tuple[EmailTaskWorkflow, ...]:
        return await self._workflows.list_for_subject(subject)

    async def get(self, subject: str, workflow_id: str) -> EmailTaskWorkflow:
        workflow = await self._workflows.get_by_workflow_id(subject, workflow_id)
        if workflow is None:
            raise EmailTaskWorkflowError("The email-task workflow was not found")
        return workflow

    async def conversation_copy(
        self,
        subject: str,
        workflow: EmailTaskWorkflow,
    ) -> tuple[str, str]:
        if not await self._workflows.packet_registered_for_subject(subject, workflow.packet_id):
            raise EmailTaskWorkflowError("The decision packet is not registered to this account")
        manifest = await self._manifests.latest_for_packet(workflow.packet_id)
        if manifest is None or manifest.manifest_id != workflow.manifest_id:
            raise EmailTaskWorkflowError("The registered Claim Manifest was not found")
        claim = next(
            (item for item in manifest.claims if item.claim_id == workflow.claim_id),
            None,
        )
        if claim is None:
            raise EmailTaskWorkflowError("The registered customer conversation lost its claim")
        title = _human_task_title(claim.statement)
        return (
            f"{title} — customer update",
            (
                f"Hi,\n\nPlease reply to this conversation whenever anything changes for "
                f"“{title}”. Your reply will reach the responsible team and update only the "
                "tracked action connected to this conversation.\n\nThanks"
            ),
        )

    async def list_events(
        self,
        subject: str,
        packet_id: str,
    ) -> tuple[EmailTaskEvent, ...]:
        if not await self._workflows.packet_registered_for_subject(subject, packet_id):
            raise EmailTaskWorkflowError("The decision packet is not registered to this account")
        return await self._workflows.list_events_for_subject(subject, packet_id)

    async def pause(
        self,
        subject: str,
        workflow_id: str,
        now: datetime | None = None,
    ) -> EmailTaskWorkflow:
        paused = await self._workflows.pause_for_subject(
            subject,
            workflow_id,
            (now or datetime.now(UTC)).astimezone(UTC),
        )
        if paused is None:
            raise EmailTaskWorkflowError("The email-task workflow was not found")
        return paused

    async def setup(
        self,
        subject: str,
        mailbox_email: str,
        packet_id: str,
    ) -> EmailTaskSetup:
        if not await self._workflows.packet_registered_for_subject(subject, packet_id):
            raise EmailTaskWorkflowError("The decision packet is not registered to this account")
        manifest = await self._manifests.latest_for_packet(packet_id)
        if manifest is None:
            raise EmailTaskWorkflowError("The registered Claim Manifest was not found")
        task_artifacts = {
            artifact.artifact_id: artifact
            for artifact in manifest.artifacts
            if artifact.kind == ArtifactKind.GOOGLE_TASK and artifact.container_id
        }
        routes = tuple(
            EmailTaskEligibleRoute(
                claim_id=claim.claim_id,
                claim_statement=claim.statement,
                claim_risk=claim.risk.value,
                artifact_id=anchor.artifact_id,
                task_id=task_artifacts[anchor.artifact_id].resource_id,
                task_list_id=task_artifacts[anchor.artifact_id].container_id or "",
            )
            for claim in manifest.claims
            for anchor in claim.artifact_anchors
            if anchor.artifact_id in task_artifacts
        )
        return EmailTaskSetup(
            packet_id=manifest.packet_id,
            mailbox_email=normalize_email(mailbox_email),
            routes=routes,
            workflows=await self.list(subject),
            threads=await self._workflows.list_threads_for_subject(subject),
            unmatched_requests=await self._workflows.list_unmatched_for_subject(subject),
        )


def _human_task_title(statement: str) -> str:
    concise = statement.strip().rstrip(".!?")
    for prefix in ("The company should ", "We should ", "Please "):
        if concise.casefold().startswith(prefix.casefold()):
            concise = concise[len(prefix) :].strip()
            break
    if not concise:
        return "Tracked customer action"
    return concise[0].upper() + concise[1:]


class EmailTaskRegistrationCoordinator:
    def __init__(
        self,
        workflows: EmailTaskWorkflowService,
        repository: EmailTaskWorkflowRepository,
        sessions: EmailTaskWorkspaceSessionProvider,
        gmail: GmailWatchGateway,
        topic_name: str,
    ) -> None:
        if not topic_name.startswith("projects/") or "/topics/" not in topic_name:
            raise ValueError("A fully-qualified Gmail Pub/Sub topic is required")
        self._workflows = workflows
        self._repository = repository
        self._sessions = sessions
        self._gmail = gmail
        self._topic_name = topic_name

    async def register(
        self,
        subject: str,
        mailbox_email: str,
        request: RegisterEmailTaskWorkflowRequest,
        now: datetime | None = None,
    ) -> EmailTaskRegistrationResult:
        try:
            session = await self._sessions.get(subject)
        except (OAuthExchangeError, WorkspaceSessionUnavailable) as error:
            raise EmailTaskWorkflowError(
                "Reconnect Google Workspace to authorize Gmail inbox monitoring and Tasks"
            ) from error
        try:
            session.authorization.require(WorkspaceCapability.GMAIL_INBOX_READ)
            session.authorization.require(WorkspaceCapability.TASKS_REPAIR)
        except MissingWorkspaceScope as error:
            raise EmailTaskWorkflowError(
                "Reconnect Google Workspace to authorize Gmail inbox monitoring and Tasks"
            ) from error
        result = await self._workflows.register(subject, mailbox_email, request, now)
        watch = await self._gmail.start_watch(
            subject,
            mailbox_email,
            session.access_token,
            self._topic_name,
            now,
        )
        stored = await self._repository.upsert_watch(watch)
        return EmailTaskRegistrationResult(
            workflow=result.workflow,
            watch=stored,
            reused=result.reused,
        )

    async def list(self, subject: str) -> tuple[EmailTaskWorkflow, ...]:
        return await self._workflows.list(subject)

    async def list_events(
        self,
        subject: str,
        packet_id: str,
    ) -> tuple[EmailTaskEvent, ...]:
        return await self._workflows.list_events(subject, packet_id)

    async def review_event(
        self,
        subject: str,
        reviewer: str,
        event_id: str,
        request: ReviewEmailTaskEventRequest,
        now: datetime | None = None,
    ) -> EmailTaskEventResult:
        instant = (now or datetime.now(UTC)).astimezone(UTC)
        event = await self._repository.get_event_by_id(subject, event_id)
        if event is None:
            raise EmailTaskWorkflowError("The escalated email request was not found")
        if event.review_request_id == request.request_id:
            if event.review_decision != request.decision:
                raise EmailTaskWorkflowError(
                    "Review request identity was reused with another decision"
                )
            if event.status in {EmailTaskEventStatus.APPLIED, EmailTaskEventStatus.REJECTED}:
                return EmailTaskEventResult(event=event, reused=True)
        elif event.status != EmailTaskEventStatus.ESCALATED:
            raise EmailTaskWorkflowError("The email request has already been resolved")

        workflow = await self._workflows.get(subject, event.workflow_id)
        reviewer_email = normalize_email(reviewer)
        try:
            session = await self._sessions.get(subject)
            session.authorization.require(WorkspaceCapability.TASKS_REPAIR)
        except (OAuthExchangeError, WorkspaceSessionUnavailable, MissingWorkspaceScope) as error:
            raise EmailTaskWorkflowError(
                "Reconnect Google Workspace before reviewing this customer request"
            ) from error

        current: GoogleTaskState | None = None
        if request.decision == EmailTaskReviewDecision.APPROVE:
            if not event.proposed_title or not event.proposed_note:
                raise EmailTaskWorkflowError(
                    "This escalated request has no bounded task update to approve"
                )
            current = await self._gmail.get_task(
                session.access_token,
                workflow.task_list_id,
                workflow.task_id,
            )

        try:
            claimed = await self._repository.claim_event_review(
                subject,
                event_id,
                request.decision,
                request.request_id,
                request.reason,
                reviewer_email,
                instant,
            )
        except ValueError as error:
            raise EmailTaskWorkflowError(str(error)) from error

        if claimed.event.status in {
            EmailTaskEventStatus.APPLIED,
            EmailTaskEventStatus.REJECTED,
        }:
            return EmailTaskEventResult(event=claimed.event, reused=True)

        if request.decision == EmailTaskReviewDecision.REJECT:
            return await self._finalize_review(
                claimed.event,
                EmailTaskEventStatus.REJECTED,
                None,
                instant,
            )

        if current is None or not claimed.event.proposed_title or not claimed.event.proposed_note:
            await self._repository.release_event_review(event_id, request.request_id, instant)
            raise EmailTaskWorkflowError("The approved task update is incomplete")
        if claimed.event.event_id in current.notes:
            return await self._finalize_review(
                claimed.event,
                EmailTaskEventStatus.APPLIED,
                current.etag,
                instant,
            )

        notes = managed_task_notes(
            current.notes,
            claimed.event.event_id,
            claimed.event.sender,
            claimed.event.gmail_message_id,
            claimed.event.proposed_note,
        )
        try:
            updated = await self._gmail.update_task(
                session.access_token,
                workflow.task_list_id,
                current,
                claimed.event.proposed_title,
                notes,
            )
        except EmailTaskPreconditionFailed as error:
            refreshed = await self._gmail.get_task(
                session.access_token,
                workflow.task_list_id,
                workflow.task_id,
            )
            if claimed.event.event_id in refreshed.notes:
                return await self._finalize_review(
                    claimed.event,
                    EmailTaskEventStatus.APPLIED,
                    refreshed.etag,
                    instant,
                )
            await self._repository.release_event_review(event_id, request.request_id, instant)
            raise EmailTaskWorkflowError(
                "The Google Task changed during review. No customer update was overwritten."
            ) from error
        return await self._finalize_review(
            claimed.event,
            EmailTaskEventStatus.APPLIED,
            updated.etag,
            instant,
        )

    async def _finalize_review(
        self,
        event: EmailTaskEvent,
        status: EmailTaskEventStatus,
        task_revision: str | None,
        instant: datetime,
    ) -> EmailTaskEventResult:
        if (
            event.review_decision is None
            or event.review_request_id is None
            or event.review_reason is None
            or event.reviewed_by is None
            or event.reviewed_at is None
        ):
            raise EmailTaskWorkflowError("The email review authority receipt is incomplete")
        checksum = _review_checksum(event, status, task_revision)
        try:
            return await self._repository.finalize_event_review(
                event.event_id,
                event.review_request_id,
                status,
                task_revision,
                checksum,
                instant,
            )
        except ValueError as error:
            raise EmailTaskWorkflowError(str(error)) from error

    async def start_conversation(
        self,
        subject: str,
        workflow_id: str,
        now: datetime | None = None,
    ) -> EmailTaskThreadBinding:
        instant = (now or datetime.now(UTC)).astimezone(UTC)
        workflow = await self._workflows.get(subject, workflow_id)
        if workflow.status != EmailTaskWorkflowStatus.ACTIVE:
            raise EmailTaskWorkflowError("The email-task workflow is paused")
        existing = tuple(
            thread
            for thread in await self._repository.list_threads_for_subject(subject)
            if thread.workflow_id == workflow.workflow_id
            and thread.source == EmailTaskThreadSource.COMPANY_STARTED
        )
        if existing:
            return existing[0]
        watch = await self._repository.get_watch(subject)
        if watch is None or watch.expiration <= instant:
            raise EmailTaskWorkflowError(
                "Reconnect Google Workspace before starting the customer conversation"
            )
        try:
            session = await self._sessions.get(subject)
            session.authorization.require(WorkspaceCapability.GMAIL_CORRECTION_DRAFT)
            session.authorization.require(WorkspaceCapability.GMAIL_INBOX_READ)
        except (OAuthExchangeError, WorkspaceSessionUnavailable, MissingWorkspaceScope) as error:
            raise EmailTaskWorkflowError(
                "Reconnect Google Workspace before starting the customer conversation"
            ) from error
        subject_line, body = await self._workflows.conversation_copy(subject, workflow)
        seed = await self._gmail.ensure_conversation(
            session.access_token,
            workflow.mailbox_email,
            workflow.authorized_sender,
            subject_line,
            body,
            f"<{workflow.workflow_id}@veritas-agent.invalid>",
        )
        binding = EmailTaskThreadBinding(
            binding_id=f"email-thread-{uuid5(NAMESPACE_URL, f'{subject}:{seed.gmail_thread_id}')}",
            subject=subject,
            workflow_id=workflow.workflow_id,
            gmail_thread_id=seed.gmail_thread_id,
            bootstrap_message_id=seed.gmail_message_id,
            subject_line=subject_line,
            source=EmailTaskThreadSource.COMPANY_STARTED,
            created_at=instant,
            updated_at=instant,
        )
        try:
            return await self._repository.bind_thread(binding)
        except ValueError as error:
            raise EmailTaskWorkflowError(str(error)) from error

    async def bind_unmatched(
        self,
        subject: str,
        request_id: str,
        workflow_id: str,
        now: datetime | None = None,
    ) -> EmailTaskThreadBinding:
        instant = (now or datetime.now(UTC)).astimezone(UTC)
        request = await self._repository.get_unmatched(subject, request_id)
        workflow = await self._workflows.get(subject, workflow_id)
        if request is None:
            raise EmailTaskWorkflowError("The unmatched customer request was not found")
        if workflow.status != EmailTaskWorkflowStatus.ACTIVE:
            raise EmailTaskWorkflowError("The selected email-task workflow is paused")
        if workflow_id not in request.candidate_workflow_ids:
            raise EmailTaskWorkflowError("The selected task is not authorized for this sender")
        binding_identity = f"{subject}:{request.gmail_thread_id}"
        binding = EmailTaskThreadBinding(
            binding_id=f"email-thread-{uuid5(NAMESPACE_URL, binding_identity)}",
            subject=subject,
            workflow_id=workflow_id,
            gmail_thread_id=request.gmail_thread_id,
            bootstrap_message_id=None,
            subject_line=request.subject_line,
            source=EmailTaskThreadSource.OPERATOR_BOUND,
            created_at=instant,
            updated_at=instant,
        )
        try:
            stored = await self._repository.bind_thread(binding)
            bound = await self._repository.bind_unmatched(
                subject,
                request_id,
                workflow_id,
                instant,
            )
        except ValueError as error:
            raise EmailTaskWorkflowError(str(error)) from error
        if bound is None:
            raise EmailTaskWorkflowError("The unmatched customer request was not found")
        return stored

    async def pause(self, subject: str, workflow_id: str) -> EmailTaskWorkflow:
        return await self._workflows.pause(subject, workflow_id)

    async def setup(
        self,
        subject: str,
        mailbox_email: str,
        packet_id: str,
    ) -> EmailTaskSetup:
        setup = await self._workflows.setup(subject, mailbox_email, packet_id)
        watch = await self._repository.get_watch(subject)
        if watch is None or watch.expiration <= datetime.now(UTC):
            return setup.model_copy(update={"workflows": ()})
        return setup


def _review_checksum(
    event: EmailTaskEvent,
    status: EmailTaskEventStatus,
    task_revision: str | None,
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "eventReceipt": event.receipt_checksum,
                "decision": event.review_decision.value if event.review_decision else None,
                "requestId": event.review_request_id,
                "reason": event.review_reason,
                "reviewedBy": event.reviewed_by,
                "reviewedAt": (
                    event.reviewed_at.astimezone(UTC).isoformat()
                    if event.reviewed_at is not None
                    else None
                ),
                "result": status.value,
                "taskRevision": task_revision,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


class GmailWatchRenewalRepository(Protocol):
    async def expiring_watches(
        self,
        before: datetime,
        limit: int,
    ) -> tuple[GmailWatchStream, ...]: ...

    async def upsert_watch(self, stream: GmailWatchStream) -> GmailWatchStream: ...


class GmailWatchRenewalService:
    """Renews short-lived Gmail watches before their seven-day expiry boundary."""

    def __init__(
        self,
        repository: GmailWatchRenewalRepository,
        sessions: EmailTaskWorkspaceSessionProvider,
        gmail: GmailWatchGateway,
        topic_name: str,
        *,
        renewal_window: timedelta = timedelta(days=1),
        batch_size: int = 25,
    ) -> None:
        if not topic_name.startswith("projects/") or "/topics/" not in topic_name:
            raise ValueError("A fully-qualified Gmail Pub/Sub topic is required")
        if renewal_window <= timedelta(0) or renewal_window > timedelta(days=3):
            raise ValueError("Gmail watch renewal window must be within three days")
        if batch_size < 1 or batch_size > 100:
            raise ValueError("Gmail watch renewal batch size is invalid")
        self._repository = repository
        self._sessions = sessions
        self._gmail = gmail
        self._topic_name = topic_name
        self._renewal_window = renewal_window
        self._batch_size = batch_size

    async def renew(self, now: datetime | None = None) -> int:
        instant = (now or datetime.now(UTC)).astimezone(UTC)
        streams = await self._repository.expiring_watches(
            instant + self._renewal_window,
            self._batch_size,
        )
        renewed = 0
        for stream in streams:
            session = await self._sessions.get(stream.subject)
            session.authorization.require(WorkspaceCapability.GMAIL_INBOX_READ)
            next_stream = await self._gmail.start_watch(
                stream.subject,
                stream.mailbox_email,
                session.access_token,
                self._topic_name,
                instant,
            )
            await self._repository.upsert_watch(next_stream)
            renewed += 1
        return renewed
