import pytest

from veritas_runtime.workspace.contracts import (
    CAPABILITY_SCOPES,
    REQUIRED_WORKSPACE_SCOPES,
    MissingWorkspaceScope,
    WorkspaceAuthorization,
    WorkspaceCapability,
)


def test_complete_scope_set_authorizes_every_registered_capability() -> None:
    authorization = WorkspaceAuthorization(frozenset(REQUIRED_WORKSPACE_SCOPES))

    assert set(CAPABILITY_SCOPES) == set(WorkspaceCapability)
    assert all(authorization.allows(capability) for capability in WorkspaceCapability)
    for capability in WorkspaceCapability:
        authorization.require(capability)


def test_missing_scope_fails_closed_without_revealing_scope_value() -> None:
    authorization = WorkspaceAuthorization(frozenset())

    assert authorization.allows(WorkspaceCapability.GMAIL_CORRECTION_DRAFT) is False
    with pytest.raises(MissingWorkspaceScope) as raised:
        authorization.require(WorkspaceCapability.GMAIL_CORRECTION_DRAFT)

    assert "gmail.compose" not in str(raised.value)
    assert "1 required scope" in str(raised.value)


def test_scope_contract_uses_compose_not_full_mailbox_access() -> None:
    assert "https://www.googleapis.com/auth/gmail.compose" in REQUIRED_WORKSPACE_SCOPES
    assert "https://mail.google.com/" not in REQUIRED_WORKSPACE_SCOPES
    assert "https://www.googleapis.com/auth/drive" not in REQUIRED_WORKSPACE_SCOPES
