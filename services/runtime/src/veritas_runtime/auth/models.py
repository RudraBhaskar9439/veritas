from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str


@dataclass(frozen=True)
class OAuthTokenSet:
    access_token: str
    refresh_token: str | None
    expires_at: datetime
    scopes: tuple[str, ...]
    token_type: str = "Bearer"


@dataclass(frozen=True)
class WorkspaceCredentialRecord:
    subject: str
    email: str
    encrypted_payload: bytes
    key_resource: str
    scopes: tuple[str, ...]
    connected_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AuthorizationTicket:
    state: str
    code_verifier: str
    return_to: str
    issued_at: datetime


@dataclass(frozen=True)
class AuthorizationStart:
    authorization_url: str
    browser_ticket: str


@dataclass(frozen=True)
class ConnectedAccount:
    subject: str
    email: str
    return_to: str
    scopes: tuple[str, ...]
