import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from veritas_runtime.auth.oauth import OAuthExchangeError
from veritas_runtime.email_tasks.models import (
    EmailTaskEligibleRoute,
    EmailTaskEvent,
    EmailTaskRegistrationResult,
    EmailTaskSetup,
    EmailTaskThreadBinding,
    EmailTaskThreadSource,
    EmailTaskUnmatchedRequest,
    EmailTaskWorkflow,
    EmailTaskWorkflowResult,
    EmailTaskWorkflowStatus,
    GmailConversationSeed,
    GmailWatchStream,
    RegisterEmailTaskWorkflowRequest,
)
from veritas_runtime.email_tasks.policy import normalize_email, workflow_routing_key
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
