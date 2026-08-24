from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from veritas_runtime.auth.database import SqlAuthRepository
from veritas_runtime.auth.oauth import GoogleOAuthConfig, GoogleOAuthGateway
from veritas_runtime.auth.service import GoogleConnectionService
from veritas_runtime.auth.storage import EncryptedCredentialVault, GoogleKmsCredentialCipher
from veritas_runtime.auth.tickets import AuthorizationTicketCodec
from veritas_runtime.settings import Settings
from veritas_runtime.workspace.contracts import REQUIRED_WORKSPACE_SCOPES


@dataclass(frozen=True)
class GoogleAuthComponents:
    service: GoogleConnectionService
    repository: SqlAuthRepository
    vault: EncryptedCredentialVault
    oauth: GoogleOAuthGateway


def build_google_auth_components(
    settings: Settings,
    engine: AsyncEngine | None = None,
) -> GoogleAuthComponents | None:
    if not settings.google_auth_configured:
        return None
    assert settings.google_oauth_client_id is not None
    assert settings.google_oauth_client_secret is not None
    assert settings.google_oauth_redirect_uri is not None
    assert settings.google_kms_credentials_key is not None
    assert settings.oauth_ticket_key is not None

    if engine is None:
        if settings.database_url is None:
            raise ValueError("A shared Cloud SQL engine is required")
        resolved_engine = create_async_engine(
            settings.database_url.get_secret_value(), pool_pre_ping=True
        )
    else:
        resolved_engine = engine
    repository = SqlAuthRepository(resolved_engine)
    cipher = GoogleKmsCredentialCipher(settings.google_kms_credentials_key)
    vault = EncryptedCredentialVault(cipher, repository)
    gateway = GoogleOAuthGateway(
        GoogleOAuthConfig(
            client_id=settings.google_oauth_client_id,
            client_secret=settings.google_oauth_client_secret.get_secret_value(),
            redirect_uri=settings.google_oauth_redirect_uri,
            scopes=REQUIRED_WORKSPACE_SCOPES,
        )
    )
    tickets = AuthorizationTicketCodec.from_base64(settings.oauth_ticket_key.get_secret_value())
    return GoogleAuthComponents(
        service=GoogleConnectionService(gateway, tickets, repository, vault),
        repository=repository,
        vault=vault,
        oauth=gateway,
    )


def build_google_connection_service(settings: Settings) -> GoogleConnectionService | None:
    components = build_google_auth_components(settings)
    return components.service if components is not None else None
