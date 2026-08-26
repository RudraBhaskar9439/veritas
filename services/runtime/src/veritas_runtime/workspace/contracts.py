from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

OPENID_SCOPES = (
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
)


class WorkspaceCapability(StrEnum):
    DRIVE_WATCH = "drive.watch"
    EVIDENCE_READ = "evidence.read"
    DOCS_REPAIR = "docs.repair"
    SLIDES_REPAIR = "slides.repair"
    GMAIL_CORRECTION_DRAFT = "gmail.correction-draft"
    GMAIL_INBOX_READ = "gmail.inbox-read"
    TASKS_REPAIR = "tasks.repair"


CAPABILITY_SCOPES: dict[WorkspaceCapability, frozenset[str]] = {
    WorkspaceCapability.DRIVE_WATCH: frozenset({"https://www.googleapis.com/auth/drive.file"}),
    WorkspaceCapability.EVIDENCE_READ: frozenset(
        {
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/spreadsheets",
        }
    ),
    WorkspaceCapability.DOCS_REPAIR: frozenset(
        {
            "https://www.googleapis.com/auth/documents",
            "https://www.googleapis.com/auth/drive.file",
        }
    ),
    WorkspaceCapability.SLIDES_REPAIR: frozenset(
        {
            "https://www.googleapis.com/auth/presentations",
            "https://www.googleapis.com/auth/drive.file",
        }
    ),
    WorkspaceCapability.GMAIL_CORRECTION_DRAFT: frozenset(
        {"https://www.googleapis.com/auth/gmail.compose"}
    ),
    WorkspaceCapability.GMAIL_INBOX_READ: frozenset(
        {"https://www.googleapis.com/auth/gmail.readonly"}
    ),
    WorkspaceCapability.TASKS_REPAIR: frozenset({"https://www.googleapis.com/auth/tasks"}),
}

REQUIRED_WORKSPACE_SCOPES = tuple(
    sorted(set(OPENID_SCOPES).union(*(set(scopes) for scopes in CAPABILITY_SCOPES.values())))
)


class MissingWorkspaceScope(PermissionError):
    pass


@dataclass(frozen=True)
class WorkspaceAuthorization:
    granted_scopes: frozenset[str]

    def allows(self, capability: WorkspaceCapability) -> bool:
        return CAPABILITY_SCOPES[capability].issubset(self.granted_scopes)

    def require(self, capability: WorkspaceCapability) -> None:
        missing = CAPABILITY_SCOPES[capability] - self.granted_scopes
        if missing:
            raise MissingWorkspaceScope(
                f"Capability {capability.value} is missing {len(missing)} required scope(s)"
            )


@dataclass(frozen=True)
class WorkspaceArtifactRef:
    artifact_id: str
    revision_id: str | None = None


@dataclass(frozen=True)
class WorkspaceSnapshot:
    artifact: WorkspaceArtifactRef
    mime_type: str
    content: bytes


@dataclass(frozen=True)
class WorkspaceMutation:
    artifact: WorkspaceArtifactRef
    request_id: str
    operations: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class WorkspaceMutationResult:
    artifact: WorkspaceArtifactRef
    new_revision_id: str


class DrivePort(Protocol):
    async def snapshot(self, artifact: WorkspaceArtifactRef) -> WorkspaceSnapshot: ...

    async def watch(self, artifact: WorkspaceArtifactRef, channel_id: str) -> datetime: ...


class DocsPort(Protocol):
    async def apply(self, mutation: WorkspaceMutation) -> WorkspaceMutationResult: ...


class SlidesPort(Protocol):
    async def apply(self, mutation: WorkspaceMutation) -> WorkspaceMutationResult: ...


class GmailPort(Protocol):
    async def create_correction_draft(
        self, mutation: WorkspaceMutation
    ) -> WorkspaceMutationResult: ...


class TasksPort(Protocol):
    async def apply(self, mutation: WorkspaceMutation) -> WorkspaceMutationResult: ...
