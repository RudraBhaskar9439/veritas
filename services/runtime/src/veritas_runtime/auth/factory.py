from sqlalchemy.ext.asyncio import create_async_engine

from veritas_runtime.auth.database import SqlAuthRepository
from veritas_runtime.auth.oauth import GoogleOAuthConfig, GoogleOAuthGateway
from veritas_runtime.auth.service import GoogleConnectionService
from veritas_runtime.auth.storage import EncryptedCredentialVault, GoogleKmsCredentialCipher
from veritas_runtime.auth.tickets import AuthorizationTicketCodec
from veritas_runtime.settings import Settings
from veritas_runtime.workspace.contracts import REQUIRED_WORKSPACE_SCOPES


def build_google_connection_service(settings: Settings) -> GoogleConnectionService | None:
    if not settings.google_auth_configured:
        return None
    assert settings.database_url is not None
    assert settings.google_oauth_client_id is not None
    assert settings.google_oauth_client_secret is not None
    assert settings.google_oauth_redirect_uri is not None
    assert settings.google_kms_credentials_key is not None
    assert settings.oauth_ticket_key is not None

    engine = create_async_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
    repository = SqlAuthRepository(engine)
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
    return GoogleConnectionService(gateway, tickets, repository, vault)
