from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from veritas_runtime.auth.models import GoogleIdentity, OAuthTokenSet
from veritas_runtime.execution.service import WorkspaceSession
from veritas_runtime.workspace.contracts import WorkspaceAuthorization


class AccessTokenRefresher(Protocol):
    async def refresh_access_token(self, refresh_token: str) -> OAuthTokenSet: ...


class WorkspaceCredentialVault(Protocol):
    async def load(self, subject: str) -> tuple[GoogleIdentity, OAuthTokenSet] | None: ...

    async def store(self, identity: GoogleIdentity, tokens: OAuthTokenSet) -> None: ...


class WorkspaceSessionUnavailable(PermissionError):
    """Raised when no usable Google Workspace authorization exists."""


class EncryptedWorkspaceSessionProvider:
    """Loads KMS-protected credentials and refreshes short-lived access tokens."""

    def __init__(
        self,
        vault: WorkspaceCredentialVault,
        refresher: AccessTokenRefresher,
        *,
        clock: Callable[[], datetime] | None = None,
        refresh_window: timedelta = timedelta(minutes=2),
    ) -> None:
        if refresh_window < timedelta(0) or refresh_window > timedelta(minutes=15):
            raise ValueError("Workspace token refresh window is invalid")
        self._vault = vault
        self._refresher = refresher
        self._clock = clock or (lambda: datetime.now(UTC))
        self._refresh_window = refresh_window

    async def get(self, subject: str) -> WorkspaceSession:
        if not subject:
            raise WorkspaceSessionUnavailable("Workspace subject is required")
        stored = await self._vault.load(subject)
        if stored is None:
            raise WorkspaceSessionUnavailable("Google Workspace is not connected")
        identity, tokens = stored
        if identity.subject != subject:
            raise WorkspaceSessionUnavailable("Google Workspace identity does not match")
        now = self._clock().astimezone(UTC)
        if tokens.expires_at.astimezone(UTC) <= now + self._refresh_window:
            if not tokens.refresh_token:
                raise WorkspaceSessionUnavailable("Google Workspace authorization has expired")
            tokens = await self._refresher.refresh_access_token(tokens.refresh_token)
            await self._vault.store(identity, tokens)
        return WorkspaceSession(
            access_token=tokens.access_token,
            authorization=WorkspaceAuthorization(frozenset(tokens.scopes)),
            email=identity.email,
        )
