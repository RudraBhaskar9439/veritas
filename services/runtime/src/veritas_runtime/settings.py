from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed runtime configuration with safe defaults."""

    model_config = SettingsConfigDict(env_prefix="VERITAS_", case_sensitive=False, extra="ignore")

    environment: Literal["local", "test", "preview", "production"] = "local"
    version: str = "0.1.0"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    request_id_header: str = Field(default="X-Request-ID", min_length=1)
    database_url: SecretStr | None = None
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: SecretStr | None = None
    google_oauth_redirect_uri: str | None = None
    google_kms_credentials_key: str | None = None
    oauth_ticket_key: SecretStr | None = None
    drive_channel_token_key: SecretStr | None = None
    drive_webhook_url: str | None = None
    snapshot_bucket: str | None = None

    @property
    def google_auth_configured(self) -> bool:
        """Return true only when every production OAuth dependency is present."""

        return all(
            (
                self.database_url,
                self.google_oauth_client_id,
                self.google_oauth_client_secret,
                self.google_oauth_redirect_uri,
                self.google_kms_credentials_key,
                self.oauth_ticket_key,
            )
        )

    @property
    def drive_ingress_configured(self) -> bool:
        return bool(self.database_url and self.drive_channel_token_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
