from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed runtime configuration with safe defaults."""

    model_config = SettingsConfigDict(env_prefix="VERITAS_", case_sensitive=False, extra="ignore")

    environment: Literal["local", "test", "preview", "production"] = "local"
    version: str = "0.1.0"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    request_id_header: str = Field(default="X-Request-ID", min_length=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
