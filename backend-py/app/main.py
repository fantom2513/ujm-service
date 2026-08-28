import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.chat import router as chat_router
from app.api.config_route import router as config_router
from app.api.generate import router as generate_router
from app.api.health import router as health_router
from app.api.schemas import ApiError
from app.config import get_settings
from app.infrastructure.cache.redis_client import build_redis_client
from app.infrastructure.db.session import build_engine, build_sessionmaker

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine = build_engine(settings)
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
app.include_router(chat_router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Fail-safe error boundary: full detail (with traceback) is only ever
    # logged server-side — the client gets a generic, registry-style error,
    # never the raw exception text.
    logger.exception("Unhandled exception while handling %s %s", request.method, request.url.path)
    error = ApiError(code="internal-error", message="Внутренняя ошибка сервера")
    return JSONResponse(
        status_code=500,
        content={"ok": False, "error": error.model_dump(by_alias=True, exclude_none=True)},
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
