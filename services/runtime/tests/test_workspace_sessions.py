import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from veritas_runtime.auth.models import GoogleIdentity, OAuthTokenSet
from veritas_runtime.execution.sessions import (
    EncryptedWorkspaceSessionProvider,
    WorkspaceSessionUnavailable,
)

NOW = datetime(2026, 8, 24, 13, 0, tzinfo=UTC)


class MemoryVault:
    def __init__(self, stored: tuple[GoogleIdentity, OAuthTokenSet] | None) -> None:
        self.stored = stored
        self.store_calls = 0

    async def load(self, subject: str) -> tuple[GoogleIdentity, OAuthTokenSet] | None:
        del subject
        return self.stored

    async def store(self, identity: GoogleIdentity, tokens: OAuthTokenSet) -> None:
        self.store_calls += 1
        self.stored = (identity, tokens)


class RecordingRefresher:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def refresh_access_token(self, refresh_token: str) -> OAuthTokenSet:
        self.calls.append(refresh_token)
        return OAuthTokenSet(
            access_token="refreshed-access",
            refresh_token=refresh_token,
            expires_at=NOW + timedelta(hours=1),
            scopes=("scope-a", "scope-b"),
        )


def _tokens(expires_at: datetime, refresh_token: str | None = "refresh-secret") -> OAuthTokenSet:
    return OAuthTokenSet(
        access_token="stored-access",
        refresh_token=refresh_token,
        expires_at=expires_at,
        scopes=("scope-a",),
    )


def test_workspace_session_reuses_fresh_encrypted_token() -> None:
    vault = MemoryVault(
        (GoogleIdentity("subject-1", "owner@example.test"), _tokens(NOW + timedelta(hours=1)))
    )
    refresher = RecordingRefresher()

    session = asyncio.run(
        EncryptedWorkspaceSessionProvider(vault, refresher, clock=lambda: NOW).get("subject-1")
    )

    assert session.access_token == "stored-access"
    assert session.authorization.granted_scopes == frozenset({"scope-a"})
    assert refresher.calls == []
    assert vault.store_calls == 0


def test_workspace_session_refreshes_and_reencrypts_expiring_token() -> None:
    vault = MemoryVault(
        (GoogleIdentity("subject-1", "owner@example.test"), _tokens(NOW + timedelta(seconds=30)))
    )
    refresher = RecordingRefresher()

    session = asyncio.run(
        EncryptedWorkspaceSessionProvider(vault, refresher, clock=lambda: NOW).get("subject-1")
    )

    assert session.access_token == "refreshed-access"
    assert refresher.calls == ["refresh-secret"]
    assert vault.store_calls == 1


def test_workspace_session_fails_closed_without_matching_authorization() -> None:
    async def scenario() -> None:
        refresher = RecordingRefresher()
        missing = EncryptedWorkspaceSessionProvider(MemoryVault(None), refresher, clock=lambda: NOW)
        with pytest.raises(WorkspaceSessionUnavailable, match="not connected"):
            await missing.get("subject-1")

        expired = EncryptedWorkspaceSessionProvider(
            MemoryVault(
                (
                    GoogleIdentity("subject-1", "owner@example.test"),
                    _tokens(NOW - timedelta(minutes=1), refresh_token=None),
                )
            ),
            refresher,
            clock=lambda: NOW,
        )
        with pytest.raises(WorkspaceSessionUnavailable, match="expired"):
            await expired.get("subject-1")

        mismatch = EncryptedWorkspaceSessionProvider(
            MemoryVault(
                (
                    GoogleIdentity("different-subject", "owner@example.test"),
                    _tokens(NOW + timedelta(hours=1)),
                )
            ),
            refresher,
            clock=lambda: NOW,
        )
        with pytest.raises(WorkspaceSessionUnavailable, match="does not match"):
            await mismatch.get("subject-1")

    asyncio.run(scenario())
