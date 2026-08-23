from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.config_route import router as config_router
from app.api.generate import router as generate_router
from app.api.health import router as health_router
from app.config import get_settings
from app.infrastructure.cache.redis_client import build_redis_client
from app.infrastructure.db.session import build_engine, build_sessionmaker


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine = build_engine(settings.database_url)
    app.state.db_sessionmaker = build_sessionmaker(engine)
    app.state.redis = build_redis_client(settings.redis_url)
    yield
    try:
        await app.state.redis.aclose()
    finally:
        # Must run even if closing Redis fails, or a flaky Redis on
        # shutdown leaks the SQLAlchemy engine's connection pool on every
        # restart/redeploy.
        await engine.dispose()


app = FastAPI(title="ujm-service backend-py", lifespan=lifespan)

app.include_router(health_router)
app.include_router(config_router)
app.include_router(generate_router)
