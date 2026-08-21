import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from veritas_runtime.auth.database import AuthorizationAttemptStore
from veritas_runtime.auth.models import (
    AuthorizationStart,
    AuthorizationTicket,
    ConnectedAccount,
)
from veritas_runtime.auth.oauth import GoogleOAuthPort
from veritas_runtime.auth.storage import EncryptedCredentialVault
from veritas_runtime.auth.tickets import AuthorizationTicketCodec, InvalidAuthorizationTicket


class InvalidAuthorizationAttempt(ValueError):
    """Raised for invalid, expired, or replayed OAuth callbacks."""


class GoogleConnectionService:
    def __init__(
        self,
        oauth: GoogleOAuthPort,
        tickets: AuthorizationTicketCodec,
        attempts: AuthorizationAttemptStore,
        vault: EncryptedCredentialVault,
        ticket_ttl: timedelta = timedelta(minutes=10),
    ) -> None:
        self._oauth = oauth
        self._tickets = tickets
        self._attempts = attempts
        self._vault = vault
        self._ticket_ttl = ticket_ttl

    async def start(self, return_to: str, now: datetime | None = None) -> AuthorizationStart:
        _validate_return_to(return_to)
        issued_at = (now or datetime.now(UTC)).astimezone(UTC)
        state = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        await self._attempts.issue(_state_hash(state), issued_at + self._ticket_ttl)
        browser_ticket = self._tickets.encode(
            AuthorizationTicket(
                state=state,
                code_verifier=code_verifier,
                return_to=return_to,
                issued_at=issued_at,
            ),
            nonce=secrets.token_bytes(12),
        )
        return AuthorizationStart(
            authorization_url=self._oauth.authorization_url(state, code_verifier),
            browser_ticket=browser_ticket,
        )

    async def complete(
        self,
        code: str,
        state: str,
        browser_ticket: str,
        now: datetime | None = None,
    ) -> ConnectedAccount:
        resolved_now = (now or datetime.now(UTC)).astimezone(UTC)
        ticket = await self._consume_ticket(state, browser_ticket, resolved_now)

        tokens = await self._oauth.exchange_code(code, ticket.code_verifier)
        identity = await self._oauth.fetch_identity(tokens.access_token)
        await self._vault.store(identity, tokens)
        return ConnectedAccount(
            subject=identity.subject,
            email=identity.email,
            return_to=ticket.return_to,
            scopes=tokens.scopes,
        )

    async def cancel(
        self,
        state: str,
        browser_ticket: str,
        now: datetime | None = None,
    ) -> str:
        resolved_now = (now or datetime.now(UTC)).astimezone(UTC)
        ticket = await self._consume_ticket(state, browser_ticket, resolved_now)
        return ticket.return_to

    async def _consume_ticket(
        self,
        state: str,
        browser_ticket: str,
        now: datetime,
    ) -> AuthorizationTicket:
        try:
            ticket = self._tickets.decode(browser_ticket, now)
        except InvalidAuthorizationTicket as error:
            raise InvalidAuthorizationAttempt("OAuth browser ticket is invalid") from error
        if not hmac.compare_digest(ticket.state, state):
            raise InvalidAuthorizationAttempt("OAuth state does not match")
        if not await self._attempts.consume(_state_hash(state), now):
            raise InvalidAuthorizationAttempt("OAuth attempt expired or was already consumed")
        return ticket


def _state_hash(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def _validate_return_to(return_to: str) -> None:
    parsed = urlsplit(return_to)
    if not return_to.startswith("/") or return_to.startswith("//"):
        raise ValueError("OAuth return path must be application-relative")
    if parsed.scheme or parsed.netloc:
        raise ValueError("OAuth return path must not contain an origin")
