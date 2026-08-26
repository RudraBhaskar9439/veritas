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
    EmailTaskWorkflow,
    EmailTaskWorkflowResult,
    EmailTaskWorkflowStatus,
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
    """Registers a sender-to-task route only through an existing Claim Manifest edge."""

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
                    "workflow": workflow.model_dump(mode="json", by_alias=True),
                    "manifestChecksum": manifest_checksum(manifest),
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return await self._workflows.persist(workflow, digest)

    async def list(self, subject: str) -> tuple[EmailTaskWorkflow, ...]:
        return await self._workflows.list_for_subject(subject)

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
        )


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
