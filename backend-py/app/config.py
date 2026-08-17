from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ResponseFormatMode = Literal["json_schema", "json_object", "none"]


def _megabytes_env_to_bytes(raw: str | None, fallback_mb: int) -> int:
    if raw is None:
        return fallback_mb * 1024 * 1024
    try:
        parsed = float(raw)
    except ValueError:
        return fallback_mb * 1024 * 1024
    if parsed <= 0:
        return fallback_mb * 1024 * 1024
    return int(parsed * 1024 * 1024)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_host: str = "127.0.0.1"
    app_port: int = 4173
    product_home_url: str = "http://localhost:3000/"

    max_text_file_mb: str | None = None
    max_recording_file_mb: str | None = None
    max_chat_attachment_mb: str | None = None
    request_timeout_ms: int = 120_000

    llm_url: str = "http://localhost:8000"
    llm_model: str = "google/gemma-4"
    llm_api_key: str | None = None
    llm_timeout_ms: int = 120_000
    llm_temperature: float = 0.1
    llm_seed: int | None = None
    llm_response_format_mode: ResponseFormatMode = "json_schema"
    llm_insecure_tls: bool = Field(default=False, validation_alias="LLM_TLS_INSECURE")

    database_url: str = "postgresql+asyncpg://uxarch:uxarch@localhost:5432/uxarch"
    redis_url: str = "redis://localhost:6379/2"
    redis_key_prefix: str = "uxarch:"

    @property
    def max_text_file_bytes(self) -> int:
        return _megabytes_env_to_bytes(self.max_text_file_mb, 10)

    @property
    def max_recording_file_bytes(self) -> int:
        return _megabytes_env_to_bytes(self.max_recording_file_mb, 100)

    @property
    def max_chat_attachment_bytes(self) -> int:
        return _megabytes_env_to_bytes(self.max_chat_attachment_mb, 10)


@lru_cache
def get_settings() -> Settings:
    return Settings()
