import os

from app.config import Settings


def test_defaults_match_ts_backend():
    settings = Settings(_env_file=None)
    assert settings.app_host == "127.0.0.1"
    assert settings.app_port == 4173
    assert settings.product_home_url == "http://localhost:3000/"
    assert settings.max_text_file_bytes == 10 * 1024 * 1024
    assert settings.max_recording_file_bytes == 100 * 1024 * 1024
    assert settings.max_chat_attachment_bytes == 10 * 1024 * 1024
    assert settings.request_timeout_ms == 120_000
    assert settings.llm_url == "http://localhost:8000"
    assert settings.llm_model == "google/gemma-4"
    assert settings.llm_api_key is None
    assert settings.llm_timeout_ms == 120_000
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


def test_llm_insecure_tls_true(monkeypatch):
    monkeypatch.setenv("LLM_TLS_INSECURE", "true")
    settings = Settings(_env_file=None)
    assert settings.llm_insecure_tls is True
