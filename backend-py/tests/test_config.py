import os

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_defaults_match_ts_backend():
    settings = Settings(_env_file=None)
    assert settings.app_host == "127.0.0.1"
    assert settings.app_port == 4173
    assert settings.product_home_url == "http://localhost:3000/"
    assert settings.identity_mode == "anonymous"
    assert settings.max_text_file_bytes == 10 * 1024 * 1024
    assert settings.max_recording_file_bytes == 100 * 1024 * 1024
    assert settings.max_chat_attachment_bytes == 10 * 1024 * 1024
    assert settings.request_timeout_ms == 120_000
    assert settings.llm_url == "http://localhost:8000"
    assert settings.llm_model == "google/gemma-4"
    assert settings.llm_api_key is None
    assert settings.llm_deadline_ms == 120_000
    assert settings.llm_connect_timeout_ms == 5_000
    assert settings.llm_pool_timeout_ms == 5_000
    assert settings.llm_temperature == 0.1
    assert settings.llm_seed is None
    assert settings.llm_response_format_mode == "json_schema"
    assert settings.llm_insecure_tls is False


def test_megabyte_env_vars_are_converted_to_bytes(monkeypatch):
    monkeypatch.setenv("MAX_TEXT_FILE_MB", "5")
    settings = Settings(_env_file=None)
    assert settings.max_text_file_bytes == 5 * 1024 * 1024


def test_invalid_megabyte_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("MAX_TEXT_FILE_MB", "not-a-number")
    settings = Settings(_env_file=None)
    assert settings.max_text_file_bytes == 10 * 1024 * 1024


def test_llm_seed_parses_when_set(monkeypatch):
    monkeypatch.setenv("LLM_SEED", "42")
    settings = Settings(_env_file=None)
    assert settings.llm_seed == 42


def test_llm_deadline_parses_when_set(monkeypatch):
    monkeypatch.setenv("LLM_DEADLINE_MS", "45000")
    settings = Settings(_env_file=None)
    assert settings.llm_deadline_ms == 45_000


def test_llm_insecure_tls_true(monkeypatch):
    monkeypatch.setenv("LLM_TLS_INSECURE", "true")
    settings = Settings(_env_file=None)
    assert settings.llm_insecure_tls is True


def test_llm_seed_empty_string_falls_back_to_none(monkeypatch):
    # Regression: .env.example ships `LLM_SEED=` (empty) — this used to
    # crash Settings() with a pydantic ValidationError at startup.
    monkeypatch.setenv("LLM_SEED", "")
    settings = Settings(_env_file=None)
    assert settings.llm_seed is None


def test_llm_insecure_tls_rejects_non_true_truthy_strings(monkeypatch):
    # Parity with TS: backend/src/config/index.ts:43 does a strict
    # `=== "true"` check — "1"/"yes"/"on" must NOT enable insecure TLS,
    # unlike Pydantic's default bool coercion.
    monkeypatch.setenv("LLM_TLS_INSECURE", "1")
    settings = Settings(_env_file=None)
    assert settings.llm_insecure_tls is False


def test_llm_insecure_tls_true_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("LLM_TLS_INSECURE", "TRUE")
    settings = Settings(_env_file=None)
    assert settings.llm_insecure_tls is True


def test_identity_mode_parses_trusted_header(monkeypatch):
    monkeypatch.setenv("IDENTITY_MODE", "trusted_header")

    settings = Settings(_env_file=None)

    assert settings.identity_mode == "trusted_header"


def test_unknown_identity_mode_is_rejected(monkeypatch):
    monkeypatch.setenv("IDENTITY_MODE", "debug_header")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
