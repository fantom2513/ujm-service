from app.config import Settings
from app.infrastructure.db.session import build_engine, build_sessionmaker


def _settings(**overrides) -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://user:pass@localhost:1/nonexistent",
        **overrides,
    )


def test_build_engine_does_not_connect_eagerly():
    engine = build_engine(_settings())
    assert engine is not None


def test_build_sessionmaker_returns_factory():
    engine = build_engine(_settings())
    factory = build_sessionmaker(engine)
    session = factory()
    assert session is not None


def test_build_engine_passes_pool_settings_from_settings_to_create_async_engine(monkeypatch):
    captured = {}

    def fake_create_async_engine(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return "fake-engine"

    monkeypatch.setattr(
        "app.infrastructure.db.session.create_async_engine", fake_create_async_engine
    )

    settings = _settings(
        db_pool_size=7,
        db_max_overflow=3,
        db_pool_timeout=9,
        db_statement_timeout_ms=12_345,
        db_idle_in_transaction_timeout_ms=54_321,
    )

    engine = build_engine(settings)

    assert engine == "fake-engine"
    assert captured["url"] == settings.database_url
    assert captured["pool_size"] == 7
    assert captured["max_overflow"] == 3
    assert captured["pool_timeout"] == 9

    server_settings = captured["connect_args"]["server_settings"]
    assert server_settings["statement_timeout"] == "12345"
    assert server_settings["idle_in_transaction_session_timeout"] == "54321"
    assert server_settings["tcp_keepalives_idle"] == "60"
    assert server_settings["tcp_keepalives_interval"] == "10"
    assert server_settings["tcp_keepalives_count"] == "5"
