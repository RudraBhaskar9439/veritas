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
    cloud_sql_instance: str | None = None
    cloud_sql_database: str = "veritas"
    cloud_sql_user: str | None = None
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: SecretStr | None = None
    google_oauth_redirect_uri: str | None = None
    google_kms_credentials_key: str | None = None
    oauth_ticket_key: SecretStr | None = None
    application_session_key: SecretStr | None = None
    drive_channel_token_key: SecretStr | None = None
    drive_webhook_url: str | None = None
    gmail_pubsub_topic: str | None = None
    gmail_push_audience: str | None = None
    gmail_push_service_account_email: str | None = None
    snapshot_bucket: str | None = None
    google_cloud_project: str | None = None
    google_cloud_location: str = "global"
    gemini_model: str = "gemini-3.5-flash"
    max_request_bytes: int = Field(default=1_048_576, ge=1024, le=10_485_760)

    @property
    def google_auth_configured(self) -> bool:
        """Return true only when every production OAuth dependency is present."""

        return all(
            (
                self.database_configured,
                self.google_oauth_client_id,
                self.google_oauth_client_secret,
                self.google_oauth_redirect_uri,
                self.google_kms_credentials_key,
                self.oauth_ticket_key,
            )
        )

    @property
    def application_session_configured(self) -> bool:
        return self.application_session_key is not None

    @property
    def drive_ingress_configured(self) -> bool:
        return bool(self.database_configured and self.drive_channel_token_key)

    @property
    def gemini_configured(self) -> bool:
        return bool(self.google_cloud_project and self.google_cloud_location and self.gemini_model)

    @property
    def gmail_ingress_configured(self) -> bool:
        return bool(
            self.database_configured
            and self.gmail_push_audience
            and self.gmail_push_service_account_email
        )

    @property
    def database_configured(self) -> bool:
        return self.database_url is not None or all(
            (self.cloud_sql_instance, self.cloud_sql_database, self.cloud_sql_user)
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
