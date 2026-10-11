"""Application configuration models."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed, environment-backed settings for the service."""

    model_config = SettingsConfigDict(
        env_prefix="TRANSCRIPTION_",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Volga Transcription Service"
    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    model_size: str = "base"
    device: str = "cpu"
    compute_type: str = "int8"
    max_upload_size_mb: int = Field(default=500, ge=1)
    temp_dir: str | None = None


settings = Settings()
