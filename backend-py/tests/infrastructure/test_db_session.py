from app.infrastructure.db.session import build_engine, build_sessionmaker


def test_build_engine_does_not_connect_eagerly():
    engine = build_engine("postgresql+asyncpg://user:pass@localhost:1/nonexistent")
    assert engine is not None


def test_build_sessionmaker_returns_factory():
    engine = build_engine("postgresql+asyncpg://user:pass@localhost:1/nonexistent")
    factory = build_sessionmaker(engine)
    session = factory()
    assert session is not None
