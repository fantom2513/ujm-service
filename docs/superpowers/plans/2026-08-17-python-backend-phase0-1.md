# Python Backend — Фаза 0 + Фаза 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заложить новый сервис `backend-py` (Python 3.12 + FastAPI) — каркас проекта, конфиг, Postgres/Redis-подключение, Docker/CI-обвязку (Фаза 0), и добиться полного паритета с TS-бэком по LLM-инфраструктуре и `POST /api/generate` (Фаза 1), не трогая работающий `backend/` (TS) и не меняя прод/тест docker-compose до cutover.

**Architecture:** Слоистая структура из дизайн-спеки (`docs/superpowers/specs/2026-07-10-python-backend-infra-design.md`): `api/` (роутеры + Pydantic-схемы) → `domain/` (mermaid-валидация, guard) → `infrastructure/llm|db|cache/` (порты клиентов) → `services/files|links|recordings|openai/` (парсеры + промпт-логика). LLM-клиент, retry/fallback-цепочка, mermaid-валидатор и `/generate`-guard переносятся из `backend/src/infrastructure/llm/*.ts`, `backend/src/services/mermaid/index.ts`, `backend/src/server/generateGuard.ts` **1:1** — те же коды ошибок, та же логика retry/fallback, те же тест-кейсы (портированные на pytest). Postgres/Redis в Фазе 0 — только ленивое подключение (engine/pool создаются, но не используются ни одним эндпоинтом) под будущую Фазу 2.

**Tech Stack:** Python 3.12, FastAPI (async), uv (package manager + venv), SQLAlchemy 2.0 async + asyncpg (Postgres), redis.asyncio (Redis), httpx (исходящие LLM-запросы), pypdf + python-docx (извлечение текста), pytest + pytest-asyncio (тесты).

**Не входит в этот план:** `POST /api/chat` (Фаза 2 — сессии/история), кэш LLM-ответов и заготовка auth (Фаза 3), реальный Jira/Confluence и XLSX (Фаза 4), cutover (Фаза 5), RabbitMQ/Whisper (Фаза 6). Прод/тест `docker-compose.*.yaml` и `.gitlab-ci.yml`'s `build-*`/`deploy-*` джобы не меняются — `backend-py` живёт рядом, не заменяя `backend/`.

---

## Файловая структура (новые файлы)

```
backend-py/
  pyproject.toml
  .python-version                         # "3.12"
  Dockerfile
  .dockerignore
  app/
    __init__.py
    main.py                               # FastAPI() + lifespan (DB/Redis pool open/close) + роутеры
    config.py                             # Settings (pydantic-settings), паритет с backend/src/config/index.ts
    api/
      __init__.py
      schemas.py                          # CamelModel база + ApiError, DiagramResult, SourceContext, FileMeta
      health.py                           # GET /api/health
      config_route.py                     # GET /api/config
      generate.py                         # POST /api/generate
    domain/
      __init__.py
      mermaid.py                          # validate_mermaid
      generate_guard.py                   # required_source_error
    infrastructure/
      __init__.py
      llm/
        __init__.py
        errors.py                         # LLMError, LLMErrorCode
        client.py                         # inline_refs/strip_think_tags/extract_mermaid/extract_json + VLLMClient
        retry.py                          # execute_with_retry, complete_json_with_fallback
      db/
        __init__.py
        session.py                        # async_engine, async_sessionmaker, get_db()
      cache/
        __init__.py
        redis_client.py                   # get_redis(), KEY_PREFIX
    services/
      __init__.py
      files/
        __init__.py
        extract.py                        # get_extension/sanitize_filename/is_text_source_format/has_pdf_text_layer/normalize_text_file
        pdf.py                            # parse_pdf (pypdf)
        docx.py                           # parse_docx (python-docx)
      links/
        __init__.py
        classify.py                       # classify_work_link/normalize_link
      recordings/
        __init__.py
        normalize.py                      # is_recording_format/normalize_recording
      openai/
        __init__.py
        prompts.py                        # build_generate_prompt (читает backend/src/prompts/*.txt)
        generate.py                       # make_client/generate_diagram
  tests/
    __init__.py
    conftest.py                           # mock_llm_server fixture (stdlib http.server, own thread)
    test_config.py
    test_main.py                          # /api/health, /api/config
    infrastructure/
      __init__.py
      test_errors.py
      test_client.py
      test_retry.py
    domain/
      __init__.py
      test_mermaid.py
      test_generate_guard.py
    services/
      __init__.py
      files/
        __init__.py
        test_extract.py
        test_pdf.py
        test_docx.py
      links/
        __init__.py
        test_classify.py
      recordings/
        __init__.py
        test_normalize.py
      openai/
        __init__.py
        test_prompts.py
        test_generate.py
    api/
      __init__.py
      test_generate_endpoint.py
```

Изменённые файлы: `.env.example` (новые `DATABASE_URL`/`REDIS_URL`/`REDIS_KEY_PREFIX`), `.gitignore` (Python-артефакты), `.gitlab-ci.yml` (новый `test-py` job, не трогает существующие), `docker-compose.py.yaml` (новый файл, локальный dev-профиль для `backend-py` + собственный Postgres).

---

# ФАЗА 0 — Каркас

### Task 1: Инициализация проекта (uv) + скелет пакета

**Files:**
- Create: `backend-py/pyproject.toml`
- Create: `backend-py/.python-version`
- Create: `backend-py/app/__init__.py`
- Create: `backend-py/tests/__init__.py`
- Create: `backend-py/.dockerignore`
- Modify: `.gitignore`

- [ ] **Step 1: Создать `.python-version`**

```
3.12
```

- [ ] **Step 2: Создать `pyproject.toml`**

```toml
[project]
name = "backend-py"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic-settings>=2.6",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.30",
    "redis>=5.2",
    "httpx>=0.27",
    "pypdf>=5.1",
    "python-docx>=1.1",
    "python-multipart>=0.0.12",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["app"]
```

- [ ] **Step 3: Создать пустые `__init__.py`**

```python
# backend-py/app/__init__.py
```

```python
# backend-py/tests/__init__.py
```

- [ ] **Step 4: Создать `.dockerignore`**

```
.venv
__pycache__
*.pyc
.pytest_cache
tests
.env
.env.*
!.env.example
```

- [ ] **Step 5: Добавить Python-артефакты в корневой `.gitignore`**

```python
# Edit .gitignore — old_string:
.worktrees/

# new_string:
.worktrees/
backend-py/.venv/
backend-py/__pycache__/
backend-py/.pytest_cache/
backend-py/uv.lock
```

> `uv.lock` не коммитим на этом этапе плана намеренно — он появится автоматически при первом `uv sync` и является генерируемым файлом; если ревьюер захочет коммитить лок-файл для воспроизводимости сборки, убрать строку `backend-py/uv.lock` из `.gitignore` отдельным решением (не в рамках этого шага).

- [ ] **Step 6: Установить зависимости и проверить, что окружение собирается**

Run: `cd backend-py && uv sync`
Expected: создаётся `.venv/`, зависимости из `pyproject.toml` устанавливаются без ошибок, `uv.lock` создан.

- [ ] **Step 7: Commit**

```bash
git add backend-py/pyproject.toml backend-py/.python-version backend-py/app/__init__.py backend-py/tests/__init__.py backend-py/.dockerignore .gitignore
git commit -m "chore: scaffold backend-py project (uv + package skeleton)"
```

---

### Task 2: Конфиг (`Settings`) — паритет с `backend/src/config/index.ts`

**Files:**
- Create: `backend-py/app/config.py`
- Test: `backend-py/tests/test_config.py`
- Modify: `.env.example`

- [ ] **Step 1: Написать падающий тест**

```python
# backend-py/tests/test_config.py
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
```

- [ ] **Step 2: Запустить и убедиться, что падает (модуля ещё нет)**

Run: `cd backend-py && uv run pytest tests/test_config.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.config'`

- [ ] **Step 3: Реализовать `app/config.py`**

```python
# backend-py/app/config.py
from __future__ import annotations

from functools import lru_cache
from typing import Literal

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
    llm_insecure_tls: bool = False

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
```

`MAX_*_MB` намеренно читаются как `str | None`, а не `int`, чтобы точно повторить поведение TS `megabytes()`: невалидное/отсутствующее значение → тихий fallback на дефолт (а не ошибка валидации pydantic на нечисловой строке).

- [ ] **Step 4: Прогнать тесты**

Run: `cd backend-py && uv run pytest tests/test_config.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Добавить новые переменные в `.env.example`**

```
# Edit .env.example — old_string:
LLM_TLS_INSECURE=false

# new_string:
LLM_TLS_INSECURE=false

# backend-py (Phase 0 scaffold — not yet used by prod cutover)
DATABASE_URL=postgresql+asyncpg://uxarch:uxarch@localhost:5432/uxarch
REDIS_URL=redis://localhost:6379/2
REDIS_KEY_PREFIX=uxarch:
```

- [ ] **Step 6: Commit**

```bash
git add backend-py/app/config.py backend-py/tests/test_config.py .env.example
git commit -m "feat(backend-py): add Settings with TS-config parity"
```

---

### Task 3: FastAPI-приложение + `GET /api/health` + `GET /api/config`

**Files:**
- Create: `backend-py/app/api/__init__.py`
- Create: `backend-py/app/api/health.py`
- Create: `backend-py/app/api/config_route.py`
- Create: `backend-py/app/main.py`
- Test: `backend-py/tests/test_main.py`

- [ ] **Step 1: Написать падающие тесты**

```python
# backend-py/tests/test_main.py
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "service": "copilot-mermaid-skeleton"}


def test_config_ok():
    response = client.get("/api/config")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "productHomeUrl" in body


def test_health_response_headers():
    response = client.get("/api/health")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `cd backend-py && uv run pytest tests/test_main.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Реализовать `app/api/__init__.py` (пустой), `app/api/health.py`, `app/api/config_route.py`**

```python
# backend-py/app/api/__init__.py
```

```python
# backend-py/app/api/health.py
from fastapi import APIRouter, Response

router = APIRouter()


@router.get("/api/health")
async def health(response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return {"ok": True, "service": "copilot-mermaid-skeleton"}
```

```python
# backend-py/app/api/config_route.py
from fastapi import APIRouter, Response

from app.config import get_settings

router = APIRouter()


@router.get("/api/config")
async def get_config(response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    settings = get_settings()
    return {"ok": True, "productHomeUrl": settings.product_home_url}
```

- [ ] **Step 4: Реализовать `app/main.py`**

```python
# backend-py/app/main.py
from fastapi import FastAPI

from app.api.config_route import router as config_router
from app.api.health import router as health_router

app = FastAPI(title="ujm-service backend-py")

app.include_router(health_router)
app.include_router(config_router)
```

- [ ] **Step 5: Прогнать тесты**

Run: `cd backend-py && uv run pytest tests/test_main.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add backend-py/app/api/__init__.py backend-py/app/api/health.py backend-py/app/api/config_route.py backend-py/app/main.py backend-py/tests/test_main.py
git commit -m "feat(backend-py): add FastAPI app with /api/health and /api/config parity"
```

---

### Task 4: Postgres — ленивый async engine (заготовка под Фазу 2)

**Files:**
- Create: `backend-py/app/infrastructure/__init__.py`
- Create: `backend-py/app/infrastructure/db/__init__.py`
- Create: `backend-py/app/infrastructure/db/session.py`
- Test: `backend-py/tests/infrastructure/__init__.py`
- Test: `backend-py/tests/infrastructure/test_db_session.py`
- Modify: `backend-py/app/main.py`

- [ ] **Step 1: Написать падающий тест**

```python
# backend-py/tests/infrastructure/__init__.py
```

```python
# backend-py/tests/infrastructure/test_db_session.py
from app.infrastructure.db.session import build_engine, build_sessionmaker


def test_build_engine_does_not_connect_eagerly():
    # SQLAlchemy's async engine is lazy: creating it must not open a socket,
    # so this must succeed even with no Postgres listening on that port.
    engine = build_engine("postgresql+asyncpg://user:pass@localhost:1/nonexistent")
    assert engine is not None


def test_build_sessionmaker_returns_factory():
    engine = build_engine("postgresql+asyncpg://user:pass@localhost:1/nonexistent")
    factory = build_sessionmaker(engine)
    session = factory()
    assert session is not None
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `cd backend-py && uv run pytest tests/infrastructure/test_db_session.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.infrastructure'`

- [ ] **Step 3: Реализовать**

```python
# backend-py/app/infrastructure/__init__.py
```

```python
# backend-py/app/infrastructure/db/__init__.py
```

```python
# backend-py/app/infrastructure/db/session.py
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def build_engine(database_url: str) -> AsyncEngine:
    # create_async_engine is lazy — no connection is opened until the first
    # query, so this is safe to call even when Postgres isn't reachable yet
    # (matches Phase 0 scope: wiring only, no consumer until Phase 2).
    return create_async_engine(database_url, pool_pre_ping=True)


def build_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    async with factory() as session:
        yield session
```

- [ ] **Step 4: Прогнать тесты**

Run: `cd backend-py && uv run pytest tests/infrastructure/test_db_session.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Подключить engine к жизненному циклу приложения**

```python
# backend-py/app/main.py — replace entire file
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.config_route import router as config_router
from app.api.health import router as health_router
from app.config import get_settings
from app.infrastructure.db.session import build_engine, build_sessionmaker


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine = build_engine(settings.database_url)
    app.state.db_sessionmaker = build_sessionmaker(engine)
    yield
    await engine.dispose()


app = FastAPI(title="ujm-service backend-py", lifespan=lifespan)

app.include_router(health_router)
app.include_router(config_router)
```

- [ ] **Step 6: Прогнать полный набор тестов (регрессия по Task 3)**

Run: `cd backend-py && uv run pytest -v`
Expected: все тесты PASS (никаких падений от lifespan — `TestClient` вызывает lifespan-хуки автоматически при входе в `with` блок; текущие тесты в `test_main.py` используют `TestClient(app)` без `with`, что в Starlette ≥0.36 всё равно триггерит lifespan при первом запросе — если тесты упадут на этом шаге, обернуть создание клиента в `with TestClient(app) as client:` в `test_main.py` и подтвердить, что PASS восстанавливается)

- [ ] **Step 7: Commit**

```bash
git add backend-py/app/infrastructure backend-py/tests/infrastructure backend-py/app/main.py
git commit -m "feat(backend-py): wire lazy Postgres async engine into app lifespan"
```

---

### Task 5: Redis — ленивый async client (заготовка под Фазу 2/3)

**Files:**
- Create: `backend-py/app/infrastructure/cache/__init__.py`
- Create: `backend-py/app/infrastructure/cache/redis_client.py`
- Test: `backend-py/tests/infrastructure/test_redis_client.py`
- Modify: `backend-py/app/main.py`

- [ ] **Step 1: Написать падающий тест**

```python
# backend-py/tests/infrastructure/test_redis_client.py
from app.infrastructure.cache.redis_client import build_redis_client, prefixed_key


def test_build_redis_client_does_not_connect_eagerly():
    # redis.asyncio.from_url is lazy — no socket opens until the first command.
    client = build_redis_client("redis://localhost:1/2")
    assert client is not None


def test_prefixed_key_adds_configured_prefix():
    assert prefixed_key("uxarch:", "sess:abc123") == "uxarch:sess:abc123"


def test_prefixed_key_does_not_double_prefix():
    assert prefixed_key("uxarch:", "uxarch:sess:abc123") == "uxarch:sess:abc123"
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `cd backend-py && uv run pytest tests/infrastructure/test_redis_client.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.infrastructure.cache'`

- [ ] **Step 3: Реализовать**

```python
# backend-py/app/infrastructure/cache/__init__.py
```

```python
# backend-py/app/infrastructure/cache/redis_client.py
from redis.asyncio import Redis, from_url


def build_redis_client(redis_url: str) -> Redis:
    # from_url is lazy — no connection is opened until the first command,
    # matching Phase 0 scope: wiring only, no consumer until Phase 2/3.
    return from_url(redis_url, decode_responses=True)


def prefixed_key(prefix: str, key: str) -> str:
    if key.startswith(prefix):
        return key
    return f"{prefix}{key}"
```

- [ ] **Step 4: Прогнать тесты**

Run: `cd backend-py && uv run pytest tests/infrastructure/test_redis_client.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Подключить к жизненному циклу приложения**

```python
# backend-py/app/main.py — old_string:
from app.infrastructure.db.session import build_engine, build_sessionmaker


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine = build_engine(settings.database_url)
    app.state.db_sessionmaker = build_sessionmaker(engine)
    yield
    await engine.dispose()

# new_string:
from app.infrastructure.cache.redis_client import build_redis_client
from app.infrastructure.db.session import build_engine, build_sessionmaker


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine = build_engine(settings.database_url)
    app.state.db_sessionmaker = build_sessionmaker(engine)
    app.state.redis = build_redis_client(settings.redis_url)
    yield
    await app.state.redis.aclose()
    await engine.dispose()
```

- [ ] **Step 6: Прогнать полный набор тестов**

Run: `cd backend-py && uv run pytest -v`
Expected: все тесты PASS

- [ ] **Step 7: Commit**

```bash
git add backend-py/app/infrastructure/cache backend-py/tests/infrastructure/test_redis_client.py backend-py/app/main.py
git commit -m "feat(backend-py): wire lazy Redis async client into app lifespan"
```

---

### Task 6: Dockerfile для `backend-py`

**Files:**
- Create: `backend-py/Dockerfile`

- [ ] **Step 1: Написать Dockerfile (multi-stage, uv-based, паттерн из корневого `Dockerfile`)**

```dockerfile
# syntax=docker/dockerfile:1
# backend-py — experimental Python/FastAPI backend, not yet wired into prod
# compose. Built independently for local iteration ahead of the Phase 5 cutover.

FROM nexus.sogaz.ru/python:3.12-bookworm-slim AS deps
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY backend-py/pyproject.toml ./
RUN uv sync --no-dev --no-install-project

FROM nexus.sogaz.ru/python:3.12-bookworm-slim AS runtime
WORKDIR /app
ENV PYTHONUNBUFFERED=1
RUN groupadd --system --gid 1001 app && useradd --system --uid 1001 --gid app app

COPY --from=deps /app/.venv ./.venv
COPY backend-py/app ./app
ENV PATH="/app/.venv/bin:$PATH"

RUN chown -R app:app /app
USER app

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,os,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('APP_PORT','8001')+'/api/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
```

> Базовый образ `nexus.sogaz.ru/python:3.12-bookworm-slim` — по аналогии с `nexus.sogaz.ru/node:24-bookworm-slim` в корневом `Dockerfile`. Если у зеркала Nexus нет тега `python:3.12-bookworm-slim`, заменить на ближайший доступный (уточнить у DevOps перед первым CI-прогоном) — это единственное внешнее допущение в этом шаге.

- [ ] **Step 2: Проверить, что образ собирается**

Run: `docker build -f backend-py/Dockerfile -t backend-py:local .`
Expected: сборка завершается без ошибок (`Successfully tagged backend-py:local` или аналог для BuildKit). Если базовый образ недоступен — см. примечание к Step 1, подставить рабочий тег и повторить.

- [ ] **Step 3: Commit**

```bash
git add backend-py/Dockerfile
git commit -m "feat(backend-py): add Dockerfile (uv multi-stage build)"
```

---

### Task 7: `docker-compose.py.yaml` — локальный dev-профиль

**Files:**
- Create: `docker-compose.py.yaml`

- [ ] **Step 1: Написать compose-файл**

Собственный Postgres продукта (per-product, как в дизайн-спеке), Redis — внешний из инфра-репо и в этом файле не описывается (только адрес через `.env`). Отдельный файл, не трогает `docker-compose.prod.yaml`/`docker-compose.test.yaml`.

```yaml
networks:
  cx_net:
    external: true
    name: cx_copilot_cx_net

volumes:
  ux-architecture-postgres-data:

services:
  ux-architecture-postgres:
    image: postgres:16-bookworm
    container_name: ux-architecture-postgres
    restart: unless-stopped
    environment:
      POSTGRES_USER: uxarch
      POSTGRES_PASSWORD: uxarch
      POSTGRES_DB: uxarch
    volumes:
      - ux-architecture-postgres-data:/var/lib/postgresql/data
    networks:
      - cx_net

  ux-architecture-backend-py:
    build:
      context: .
      dockerfile: backend-py/Dockerfile
    image: ux-architecture-backend-py:dev
    container_name: ux-architecture-backend-py
    restart: unless-stopped
    env_file:
      - .env
    environment:
      APP_HOST: 0.0.0.0
      APP_PORT: 8001
      DATABASE_URL: postgresql+asyncpg://uxarch:uxarch@ux-architecture-postgres:5432/uxarch
    depends_on:
      - ux-architecture-postgres
    networks:
      - cx_net
```

- [ ] **Step 2: Проверить, что файл валиден (не поднимая контейнеры — `up` не запускаем без явного запроса пользователя)**

Run: `docker compose -f docker-compose.py.yaml config --quiet`
Expected: команда завершается без вывода и с кодом выхода 0 (YAML синтаксически валиден, интерполяция переменных проходит).

- [ ] **Step 3: Commit**

```bash
git add docker-compose.py.yaml
git commit -m "chore(backend-py): add local dev compose profile with per-product Postgres"
```

---

### Task 8: CI — юнит-тесты `backend-py`

**Files:**
- Modify: `.gitlab-ci.yml`

- [ ] **Step 1: Добавить стадию `test` и джобу `test-py`, не трогая существующие `build-*`/`deploy-*` джобы**

```yaml
# Edit .gitlab-ci.yml — old_string:
stages:
  - security
  - build
  - deploy

.changes: &changes
  - Dockerfile
  - frontend/**/*
  - backend/**/*
  - shared/**/*
  - docker-compose*.yaml
  - package.json
  - pnpm-lock.yaml
  - .gitlab-ci.yml

# new_string:
stages:
  - security
  - test
  - build
  - deploy

.changes: &changes
  - Dockerfile
  - frontend/**/*
  - backend/**/*
  - shared/**/*
  - docker-compose*.yaml
  - package.json
  - pnpm-lock.yaml
  - .gitlab-ci.yml

test-py:
  stage: test
  image: nexus.sogaz.ru/python:3.12-bookworm-slim
  script:
    - pip install --no-cache-dir uv
    - cd backend-py
    - uv sync
    - uv run pytest -v
  rules:
    - changes:
        - backend-py/**/*
        - .gitlab-ci.yml
```

`test-py` намеренно без ветки/докера — гоняется на любой ветке/MR, где менялся `backend-py/**`, независимо от `build-test`/`build-prod` (которые остаются привязаны к `backend/` TS-образу до Фазы 5 cutover).

- [ ] **Step 2: Проверить, что YAML синтаксически валиден**

Run: `python3 -c "import yaml; yaml.safe_load(open('.gitlab-ci.yml'))" 2>&1 || python -c "import yaml; yaml.safe_load(open('.gitlab-ci.yml'))"`
Expected: без вывода/ошибок (если `pyyaml` не установлен в текущем окружении — установить временно `pip install pyyaml` для проверки, либо проверить через `uv run --with pyyaml python -c "..."` из `backend-py/`). Фактический запуск джобы `test-py` можно подтвердить только после пуша ветки и открытия MR/CI-пайплайна в GitLab — этот шаг тест-паркует только синтаксис.

- [ ] **Step 3: Commit**

```bash
git add .gitlab-ci.yml
git commit -m "ci: add backend-py unit-test job, independent of existing build/deploy"
```

---

# ФАЗА 1 — LLM-слой + `/generate`

### Task 9: `LLMError`

**Files:**
- Create: `backend-py/app/infrastructure/llm/__init__.py`
- Create: `backend-py/app/infrastructure/llm/errors.py`
- Test: `backend-py/tests/infrastructure/test_errors.py`

- [ ] **Step 1: Написать падающий тест**

```python
# backend-py/tests/infrastructure/test_errors.py
from app.infrastructure.llm.errors import LLMError


def test_llm_error_has_code_and_message():
    err = LLMError("TIMEOUT", "timed out")
    assert err.code == "TIMEOUT"
    assert str(err) == "timed out"
    assert isinstance(err, Exception)


def test_llm_error_stores_cause():
    cause = ValueError("root")
    err = LLMError("HTTP_ERROR", "bad", cause)
    assert err.__cause__ is cause
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `cd backend-py && uv run pytest tests/infrastructure/test_errors.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.infrastructure.llm'`

- [ ] **Step 3: Реализовать**

```python
# backend-py/app/infrastructure/llm/__init__.py
```

```python
# backend-py/app/infrastructure/llm/errors.py
from typing import Literal

LLMErrorCode = Literal[
    "TIMEOUT",
    "HTTP_ERROR",
    "NETWORK_ERROR",
    "INVALID_JSON",
    "SCHEMA_MISMATCH",
    "STRUCTURED_OUTPUT_UNSUPPORTED",
    "EMPTY_RESPONSE",
]


class LLMError(Exception):
    def __init__(self, code: LLMErrorCode, message: str, cause: Exception | None = None):
        super().__init__(message)
        self.code: LLMErrorCode = code
        if cause is not None:
            self.__cause__ = cause
```

- [ ] **Step 4: Прогнать тесты**

Run: `cd backend-py && uv run pytest tests/infrastructure/test_errors.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend-py/app/infrastructure/llm/__init__.py backend-py/app/infrastructure/llm/errors.py backend-py/tests/infrastructure/test_errors.py
git commit -m "feat(backend-py): port LLMError (1:1 with TS infrastructure/llm/errors.ts)"
```

---

### Task 10: Чистые хелперы LLM-клиента (`inline_refs`, `strip_think_tags`, `extract_mermaid`, `extract_json`)

**Files:**
- Create: `backend-py/app/infrastructure/llm/client.py`
- Test: `backend-py/tests/infrastructure/test_client.py` (helpers-часть)

- [ ] **Step 1: Написать падающие тесты для хелперов**

```python
# backend-py/tests/infrastructure/test_client.py
from app.infrastructure.llm.client import (
    extract_json,
    extract_mermaid,
    inline_refs,
    strip_think_tags,
)
from app.infrastructure.llm.errors import LLMError


def test_inline_refs_no_refs_passthrough_drops_defs():
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    assert inline_refs(schema, {}) == schema


def test_inline_refs_inlines_ref():
    defs = {"Foo": {"type": "string"}}
    schema = {"type": "object", "$defs": defs, "properties": {"x": {"$ref": "#/$defs/Foo"}}}
    result = inline_refs(schema, defs)
    assert result["properties"]["x"] == defs["Foo"]
    assert "$defs" not in result


def test_inline_refs_nested_ref_in_array():
    defs = {"Tag": {"type": "string"}}
    schema = {"type": "object", "properties": {"tags": {"type": "array", "items": {"$ref": "#/$defs/Tag"}}}}
    result = inline_refs(schema, defs)
    assert result["properties"]["tags"]["items"] == {"type": "string"}


def test_strip_think_tags_removes_block():
    assert strip_think_tags("<think>let me reason</think>\nflowchart LR\nA --> B") == "flowchart LR\nA --> B"


def test_strip_think_tags_no_tags_unchanged():
    assert strip_think_tags("flowchart LR\nA --> B") == "flowchart LR\nA --> B"


def test_extract_mermaid_finds_flowchart_lr_in_fences():
    result = extract_mermaid("Sure!\n```mermaid\nflowchart LR\nA --> B\n```")
    assert result.startswith("flowchart LR")


def test_extract_mermaid_finds_flowchart_tb_without_fences():
    result = extract_mermaid("Here you go:\nflowchart TB\nA --> B")
    assert result.startswith("flowchart TB")


def test_extract_mermaid_raises_empty_response_when_missing():
    try:
        extract_mermaid("no diagram here")
        assert False, "expected LLMError"
    except LLMError as err:
        assert err.code == "EMPTY_RESPONSE"


def test_extract_json_parses_clean_json():
    result = extract_json('{"mermaid":"flowchart LR\\nA-->B","message":"done"}')
    assert result["mermaid"] == "flowchart LR\nA-->B"
    assert result["message"] == "done"


def test_extract_json_skips_leading_text():
    result = extract_json('Sure: {"mermaid":"x","message":"y"}')
    assert result["mermaid"] == "x"


def test_extract_json_handles_trailing_text():
    result = extract_json('{"a":"b"} extra text here')
    assert result["a"] == "b"


def test_extract_json_raises_invalid_json_when_missing():
    try:
        extract_json("no json here")
        assert False, "expected LLMError"
    except LLMError as err:
        assert err.code == "INVALID_JSON"
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `cd backend-py && uv run pytest tests/infrastructure/test_client.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.infrastructure.llm.client'`

- [ ] **Step 3: Реализовать хелперы**

```python
# backend-py/app/infrastructure/llm/client.py
from __future__ import annotations

import json
import re

from app.infrastructure.llm.errors import LLMError

_THINK_TAGS = re.compile(r"<think>.*?</think>", re.DOTALL)
_FLOWCHART_HEADER = re.compile(r"flowchart\s+(TB|TD|BT|RL|LR)")
_FENCE = re.compile(r"```(?:mermaid|json)?\s*")
_CLOSING_FENCE = re.compile(r"```\s*")


def inline_refs(obj, defs: dict):
    """Preserves identity for unchanged subtrees (mirrors TS `_inlineRefs`:
    returns `obj` itself when nothing changed, required so a `$ref` resolved
    to a leaf definition returns that same definition object)."""
    if isinstance(obj, list):
        mapped = [inline_refs(item, defs) for item in obj]
        return mapped if any(m is not o for m, o in zip(mapped, obj)) else obj
    if isinstance(obj, dict):
        if "$ref" in obj:
            name = obj["$ref"].split("/")[-1]
            return inline_refs(defs[name], defs)
        changed = False
        result = {}
        for key, value in obj.items():
            if key == "$defs":
                changed = True
                continue
            new_value = inline_refs(value, defs)
            if new_value is not value:
                changed = True
            result[key] = new_value
        return result if changed else obj
    return obj


def strip_think_tags(text: str) -> str:
    return _THINK_TAGS.sub("", text).strip()


def extract_mermaid(raw: str) -> str:
    cleaned = _CLOSING_FENCE.sub("", _FENCE.sub("", raw)).strip()
    match = _FLOWCHART_HEADER.search(cleaned)
    if match is None:
        raise LLMError("EMPTY_RESPONSE", f"No flowchart found: {raw[:200]}")
    return cleaned[match.start():].strip()


def extract_json(raw: str) -> dict:
    cleaned = _CLOSING_FENCE.sub("", raw.replace("```json", "").replace("```", "")).strip()
    start = cleaned.find("{")
    if start == -1:
        raise LLMError("INVALID_JSON", f"No JSON object found: {cleaned[:200]}")
    try:
        return json.loads(cleaned[start:])
    except json.JSONDecodeError:
        pass

    depth = 0
    in_str = False
    esc = False
    end = -1
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if esc:
            esc = False
            continue
        if in_str:
            if ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end == -1:
        raise LLMError("INVALID_JSON", f"Unbalanced braces in: {cleaned[start:start + 200]}")
    return json.loads(cleaned[start:end + 1])
```

- [ ] **Step 4: Прогнать тесты**

Run: `cd backend-py && uv run pytest tests/infrastructure/test_client.py -v`
Expected: PASS (12 passed)

- [ ] **Step 5: Commit**

```bash
git add backend-py/app/infrastructure/llm/client.py backend-py/tests/infrastructure/test_client.py
git commit -m "feat(backend-py): port LLM client pure helpers (inline_refs/strip_think_tags/extract_*)"
```

---

### Task 11: `VLLMClient` — HTTP-слой (`complete_text`, `complete_json`)

**Files:**
- Modify: `backend-py/app/infrastructure/llm/client.py`
- Create: `backend-py/tests/conftest.py`
- Modify: `backend-py/tests/infrastructure/test_client.py`

- [ ] **Step 1: Добавить общую fixture для мок-LLM-сервера (stdlib `http.server`, свой поток — прямой аналог `mockLlmServer` из TS-тестов)**

```python
# backend-py/tests/conftest.py
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


class _MockLLMHandler(BaseHTTPRequestHandler):
    response_body: dict = {}
    status_code: int = 200
    delay_forever: bool = False

    def do_POST(self):  # noqa: N802 (stdlib naming)
        if self.delay_forever:
            # Never respond — used to exercise client-side timeout handling.
            while True:
                pass
        body = json.dumps(self.response_body).encode("utf-8")
        self.send_response(self.status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence stdlib's default request logging
        pass


@pytest.fixture
def mock_llm_server():
    servers: list[HTTPServer] = []

    def _make(response_body: dict, status_code: int = 200, delay_forever: bool = False) -> str:
        handler = type(
            "Handler",
            (_MockLLMHandler,),
            {"response_body": response_body, "status_code": status_code, "delay_forever": delay_forever},
        )
        server = HTTPServer(("127.0.0.1", 0), handler)
        servers.append(server)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        return f"http://127.0.0.1:{port}"

    yield _make

    for server in servers:
        server.shutdown()
        server.server_close()
```

- [ ] **Step 2: Написать падающие тесты для HTTP-слоя**

```python
# Append to backend-py/tests/infrastructure/test_client.py
import pytest

from app.infrastructure.llm.client import VLLMClient
from app.infrastructure.llm.errors import LLMError


def _llm_response(content: str, reasoning_content: str | None = None) -> dict:
    message = {"content": content}
    if reasoning_content is not None:
        message["reasoning_content"] = reasoning_content
    return {"choices": [{"message": message}]}


async def test_complete_text_returns_mermaid_from_response(mock_llm_server):
    url = mock_llm_server(_llm_response("flowchart LR\nA --> B"))
    client = VLLMClient(url=url, model="test", response_format_mode="none")
    result = await client.complete_text("make a diagram")
    assert result.startswith("flowchart LR")


async def test_complete_text_strips_think_tags(mock_llm_server):
    url = mock_llm_server(_llm_response("<think>reasoning</think>\nflowchart TB\nA --> B"))
    client = VLLMClient(url=url, model="test", response_format_mode="none")
    result = await client.complete_text("make a diagram")
    assert result.startswith("flowchart TB")
    assert "<think>" not in result


async def test_complete_text_raises_timeout_when_server_too_slow(mock_llm_server):
    url = mock_llm_server({}, delay_forever=True)
    client = VLLMClient(url=url, model="test", timeout_ms=50, response_format_mode="none")
    with pytest.raises(LLMError) as exc_info:
        await client.complete_text("test")
    assert exc_info.value.code == "TIMEOUT"


async def test_complete_json_parses_with_json_schema_mode(mock_llm_server):
    payload = {"mermaid": "flowchart LR\nA --> B", "message": "done"}
    url = mock_llm_server(_llm_response(json.dumps(payload)))
    client = VLLMClient(url=url, model="test", response_format_mode="json_schema")
    schema = {
        "type": "object",
        "properties": {"mermaid": {"type": "string"}, "message": {"type": "string"}},
        "required": ["mermaid", "message"],
    }
    result = await client.complete_json("edit diagram", schema, "ChatOutput")
    assert result["mermaid"] == payload["mermaid"]
    assert result["message"] == payload["message"]


async def test_complete_json_raises_structured_output_unsupported_on_422(mock_llm_server):
    url = mock_llm_server({"error": "unsupported"}, status_code=422)
    client = VLLMClient(url=url, model="test", response_format_mode="json_schema")
    with pytest.raises(LLMError) as exc_info:
        await client.complete_json("x", {}, "X")
    assert exc_info.value.code == "STRUCTURED_OUTPUT_UNSUPPORTED"


async def test_complete_json_uses_reasoning_content_when_content_empty(mock_llm_server):
    payload = {"mermaid": "flowchart LR\nA-->B", "message": "ok"}
    url = mock_llm_server(_llm_response("", reasoning_content=json.dumps(payload)))
    client = VLLMClient(url=url, model="test", response_format_mode="none")
    result = await client.complete_json("x", {}, "X")
    assert result["mermaid"] == payload["mermaid"]


async def test_complete_json_exposes_usage_on_last_usage(mock_llm_server):
    payload = {"mermaid": "flowchart LR\nA-->B", "message": "ok"}
    body = _llm_response(json.dumps(payload))
    body["usage"] = {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}
    url = mock_llm_server(body)
    client = VLLMClient(url=url, model="test", response_format_mode="none")
    await client.complete_json("x", {}, "X")
    assert client.last_usage == {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}


async def test_complete_text_usage_is_none_when_response_omits_it(mock_llm_server):
    url = mock_llm_server(_llm_response("flowchart LR\nA --> B"))
    client = VLLMClient(url=url, model="test", response_format_mode="none")
    await client.complete_text("make a diagram")
    assert client.last_usage is None
```

- [ ] **Step 3: Запустить и убедиться, что падает (класс `VLLMClient` ещё не существует)**

Run: `cd backend-py && uv run pytest tests/infrastructure/test_client.py -v`
Expected: FAIL с `ImportError: cannot import name 'VLLMClient'`

- [ ] **Step 4: Дописать `VLLMClient` в `client.py`**

```python
# Append to backend-py/app/infrastructure/llm/client.py
import httpx

ResponseFormatMode = str  # "json_schema" | "json_object" | "none"


class VLLMClient:
    def __init__(
        self,
        url: str,
        model: str,
        api_key: str | None = None,
        timeout_ms: int = 120_000,
        temperature: float = 0.1,
        seed: int | None = None,
        response_format_mode: ResponseFormatMode = "json_schema",
        insecure_tls: bool = False,
    ):
        self.base_url = url.removesuffix("/chat/completions").rstrip("/")
        self.model = model
        self.timeout_ms = timeout_ms
        self.temperature = temperature
        self.seed = seed
        self.response_format_mode = response_format_mode
        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"
        # httpx's per-client `verify` param is honored reliably (unlike the
        # Node/undici global-dispatcher workaround the TS client needs) — no
        # extra plumbing required to trust an internal-CA / self-signed LLM
        # endpoint when insecure_tls is set.
        self._verify = not insecure_tls
        self.last_usage: dict | None = None

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"

    async def _post(self, messages: list[dict], response_format: dict | None = None) -> dict:
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": False,
        }
        if self.seed is not None:
            payload["seed"] = self.seed
        if response_format:
            payload["response_format"] = response_format

        timeout = httpx.Timeout(self.timeout_ms / 1000)
        try:
            async with httpx.AsyncClient(verify=self._verify, timeout=timeout) as http_client:
                response = await http_client.post(self.endpoint, headers=self.headers, json=payload)
        except httpx.TimeoutException as err:
            raise LLMError("TIMEOUT", f"LLM timed out after {self.timeout_ms}ms") from err
        except httpx.HTTPError as err:
            raise LLMError("NETWORK_ERROR", f"LLM network error: {err}", err) from err

        if response.status_code >= 400:
            body = response.text
            if response.status_code == 422 and self.response_format_mode != "none":
                raise LLMError(
                    "STRUCTURED_OUTPUT_UNSUPPORTED",
                    f"Model rejected response_format: {body[:400]}",
                )
            raise LLMError("HTTP_ERROR", f"LLM HTTP {response.status_code}: {body[:400]}")

        data = response.json()
        message = data.get("choices", [{}])[0].get("message", {})
        usage = None
        if "usage" in data:
            raw_usage = data["usage"]
            usage = {
                "prompt_tokens": raw_usage.get("prompt_tokens", 0),
                "completion_tokens": raw_usage.get("completion_tokens", 0),
                "total_tokens": raw_usage.get("total_tokens", 0),
            }
        return {
            "content": message.get("content") or "",
            "reasoning_content": message.get("reasoning_content") or "",
            "usage": usage,
        }

    async def complete_text(self, prompt: str, system: str | None = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        result = await self._post(messages)
        self.last_usage = result["usage"]
        return extract_mermaid(strip_think_tags(result["content"]))

    async def complete_json(
        self,
        prompt: str,
        schema: dict,
        schema_name: str,
        system: str | None = None,
    ) -> dict:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        defs = schema.get("$defs", {})
        flat_schema = inline_refs(schema, defs)

        response_format = None
        if self.response_format_mode == "json_schema":
            response_format = {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": False, "schema": flat_schema},
            }
        elif self.response_format_mode == "json_object":
            response_format = {"type": "json_object"}

        result = await self._post(messages, response_format)
        self.last_usage = result["usage"]
        raw = result["content"] if "{" in result["content"] else (
            result["reasoning_content"] if "{" in result["reasoning_content"] else result["content"]
        )
        return extract_json(strip_think_tags(raw))
```

- [ ] **Step 5: Прогнать тесты**

Run: `cd backend-py && uv run pytest tests/infrastructure/test_client.py -v`
Expected: PASS (20 passed)

- [ ] **Step 6: Commit**

```bash
git add backend-py/app/infrastructure/llm/client.py backend-py/tests/infrastructure/test_client.py backend-py/tests/conftest.py
git commit -m "feat(backend-py): port VLLMClient HTTP layer (complete_text/complete_json)"
```

---

### Task 12: Retry + fallback-цепочка

**Files:**
- Create: `backend-py/app/infrastructure/llm/retry.py`
- Test: `backend-py/tests/infrastructure/test_retry.py`

- [ ] **Step 1: Написать падающий тест**

```python
# backend-py/tests/infrastructure/test_retry.py
import pytest

from app.infrastructure.llm.errors import LLMError
from app.infrastructure.llm.retry import complete_json_with_fallback, execute_with_retry


async def test_execute_with_retry_returns_value_on_first_success():
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        return 42

    result = await execute_with_retry(fn)
    assert result == 42
    assert calls == 1


async def test_execute_with_retry_retries_on_timeout():
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise LLMError("TIMEOUT", "timed out")
        return "ok"

    result = await execute_with_retry(fn, max_attempts=3, base_delay_ms=0, max_delay_ms=0)
    assert result == "ok"
    assert calls == 3


async def test_execute_with_retry_does_not_retry_schema_mismatch():
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        raise LLMError("SCHEMA_MISMATCH", "bad schema")

    with pytest.raises(LLMError) as exc_info:
        await execute_with_retry(fn, max_attempts=3, base_delay_ms=0, max_delay_ms=0)
    assert calls == 1
    assert exc_info.value.code == "SCHEMA_MISMATCH"


async def test_execute_with_retry_raises_last_error_after_exhausting():
    async def fn():
        raise LLMError("HTTP_ERROR", "bad")

    with pytest.raises(LLMError) as exc_info:
        await execute_with_retry(fn, max_attempts=2, base_delay_ms=0, max_delay_ms=0)
    assert exc_info.value.code == "HTTP_ERROR"


async def test_complete_json_with_fallback_falls_back_on_structured_output_unsupported():
    modes: list[str] = []

    class FakeClient:
        def __init__(self, mode: str):
            self.mode = mode

        async def complete_json(self, *_args):
            if self.mode == "json_schema":
                raise LLMError("STRUCTURED_OUTPUT_UNSUPPORTED", "no")
            return {"ok": True}

    def make_client(mode: str):
        modes.append(mode)
        return FakeClient(mode)

    result = await complete_json_with_fallback(
        make_client,
        "json_schema",
        lambda client: client.complete_json("", {}, ""),
        max_attempts_first=2,
        max_attempts_rest=1,
    )
    assert result == {"ok": True}
    assert "json_schema" in modes
    assert "json_object" in modes


async def test_complete_json_with_fallback_does_not_fall_back_on_http_error():
    modes: list[str] = []

    class FakeClient:
        async def complete_json(self, *_args):
            raise LLMError("HTTP_ERROR", "bad")

    def make_client(mode: str):
        modes.append(mode)
        return FakeClient()

    with pytest.raises(LLMError) as exc_info:
        await complete_json_with_fallback(
            make_client,
            "json_schema",
            lambda client: client.complete_json("", {}, ""),
            max_attempts_first=1,
            max_attempts_rest=1,
        )
    assert exc_info.value.code == "HTTP_ERROR"
    assert len(modes) == 1
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `cd backend-py && uv run pytest tests/infrastructure/test_retry.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.infrastructure.llm.retry'`

- [ ] **Step 3: Реализовать**

```python
# backend-py/app/infrastructure/llm/retry.py
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.infrastructure.llm.errors import LLMError

# Errors that won't change on retry — the model/client produced a bad
# payload, not a transient failure.
NO_RETRY_CODES = {
    "SCHEMA_MISMATCH",
    "STRUCTURED_OUTPUT_UNSUPPORTED",
    "INVALID_JSON",
    "EMPTY_RESPONSE",
}

# Subset of NO_RETRY_CODES relevant to complete_json_with_fallback's
# response_format chain. EMPTY_RESPONSE is deliberately excluded: it comes
# from complete_text's Mermaid extraction, not JSON parsing, so stepping
# down json_schema/json_object/none can't fix it — don't "sync" this set
# with NO_RETRY_CODES.
FALLBACK_CODES = {"SCHEMA_MISMATCH", "STRUCTURED_OUTPUT_UNSUPPORTED", "INVALID_JSON"}

FALLBACK_CHAIN = ["json_schema", "json_object", "none"]


async def execute_with_retry(
    fn: Callable[[], Awaitable],
    max_attempts: int = 3,
    base_delay_ms: int = 1_000,
    max_delay_ms: int = 30_000,
):
    last_err: LLMError | None = None
    for attempt in range(max_attempts):
        try:
            return await fn()
        except LLMError as err:
            if err.code in NO_RETRY_CODES:
                raise
            last_err = err
            if attempt < max_attempts - 1:
                delay = min(base_delay_ms * (2**attempt), max_delay_ms)
                await asyncio.sleep(delay / 1000)
    raise last_err


async def complete_json_with_fallback(
    make_client: Callable[[str], object],
    start_mode: str,
    call: Callable[[object], Awaitable],
    max_attempts_first: int = 3,
    max_attempts_rest: int = 2,
):
    start_index = max(0, FALLBACK_CHAIN.index(start_mode)) if start_mode in FALLBACK_CHAIN else 0
    last_err: LLMError | None = None

    for i in range(start_index, len(FALLBACK_CHAIN)):
        mode = FALLBACK_CHAIN[i]
        client = make_client(mode)
        try:
            return await execute_with_retry(
                lambda c=client: call(c),
                max_attempts_first if i == start_index else max_attempts_rest,
            )
        except LLMError as err:
            last_err = err
            if err.code in FALLBACK_CODES and i < len(FALLBACK_CHAIN) - 1:
                continue
            raise
    raise last_err or LLMError("SCHEMA_MISMATCH", "All response_format modes exhausted")
```

- [ ] **Step 4: Прогнать тесты**

Run: `cd backend-py && uv run pytest tests/infrastructure/test_retry.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add backend-py/app/infrastructure/llm/retry.py backend-py/tests/infrastructure/test_retry.py
git commit -m "feat(backend-py): port retry + response_format fallback chain"
```

---

### Task 13: Mermaid-валидатор

**Files:**
- Create: `backend-py/app/domain/__init__.py`
- Create: `backend-py/app/domain/mermaid.py`
- Test: `backend-py/tests/domain/__init__.py`
- Test: `backend-py/tests/domain/test_mermaid.py`

- [ ] **Step 1: Написать падающий тест**

```python
# backend-py/tests/domain/__init__.py
```

```python
# backend-py/tests/domain/test_mermaid.py
from app.domain.mermaid import validate_mermaid


def test_accepts_flowchart_lr():
    assert validate_mermaid("flowchart LR\nA-->B").ok is True


def test_accepts_flowchart_tb():
    assert validate_mermaid("flowchart TB\nA-->B").ok is True


def test_accepts_td_bt_rl_directions():
    for direction in ("TD", "BT", "RL"):
        assert validate_mermaid(f"flowchart {direction}\nA-->B").ok is True, direction


def test_rejects_non_flowchart():
    assert validate_mermaid("graph LR\nA-->B").ok is False


def test_rejects_xss_content():
    result = validate_mermaid('flowchart LR\nA-->B["<script>alert(1)</script>"]')
    assert result.ok is False
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `cd backend-py && uv run pytest tests/domain/test_mermaid.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.domain'`

- [ ] **Step 3: Реализовать**

```python
# backend-py/app/domain/__init__.py
```

```python
# backend-py/app/domain/mermaid.py
from __future__ import annotations

import re
from dataclasses import dataclass

# Mermaid flowchart directions: TB (top-bottom), TD (top-down, synonym of
# TB), BT, RL, LR. The generate/edit prompts instruct the model to start
# with `flowchart LR` or `flowchart TB` (TB for complex >12-node diagrams),
# so both must pass validation — accept the full set to be safe.
_FLOWCHART_HEADER = re.compile(r"^flowchart\s+(TB|TD|BT|RL|LR)\b")
_UNSAFE_CONTENT = re.compile(r"<script|</script|onerror=|onload=", re.IGNORECASE)


@dataclass
class ValidationResult:
    ok: bool
    reason: str | None = None


def validate_mermaid(code: str) -> ValidationResult:
    trimmed = code.strip()
    if not _FLOWCHART_HEADER.search(trimmed):
        return ValidationResult(False, "Mermaid must start with 'flowchart' and a direction (LR/TB/TD/BT/RL)")
    if _UNSAFE_CONTENT.search(trimmed):
        return ValidationResult(False, "Unsafe content in Mermaid")
    return ValidationResult(True)
```

- [ ] **Step 4: Прогнать тесты**

Run: `cd backend-py && uv run pytest tests/domain/test_mermaid.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add backend-py/app/domain/__init__.py backend-py/app/domain/mermaid.py backend-py/tests/domain
git commit -m "feat(backend-py): port validate_mermaid (1:1 with TS services/mermaid/index.ts)"
```

---

### Task 14: `/generate`-guard (защита от «тихой генерации», #12)

**Files:**
- Create: `backend-py/app/domain/generate_guard.py`
- Test: `backend-py/tests/domain/test_generate_guard.py`

- [ ] **Step 1: Написать падающий тест**

```python
# backend-py/tests/domain/test_generate_guard.py
from app.domain.generate_guard import required_source_error


def test_text_file_without_file_returns_file_required():
    assert required_source_error("text-file", has_file=False, link="") == "file-required"


def test_recording_without_file_returns_file_required():
    assert required_source_error("recording", has_file=False, link="") == "file-required"


def test_text_file_with_file_passes():
    assert required_source_error("text-file", has_file=True, link="") is None


def test_recording_with_file_passes():
    assert required_source_error("recording", has_file=True, link="") is None


def test_link_without_value_returns_link_required():
    assert required_source_error("link", has_file=False, link="") == "link-required"


def test_link_with_only_whitespace_returns_link_required():
    assert required_source_error("link", has_file=False, link="   ") == "link-required"


def test_link_with_value_passes():
    assert required_source_error("link", has_file=False, link="https://example.com/task/1") is None


def test_missing_source_type_returns_diagram_generation():
    assert required_source_error(None, has_file=False, link="") == "diagram-generation"


def test_unknown_source_type_returns_diagram_generation():
    assert required_source_error("totally-bogus", has_file=True, link="https://x") == "diagram-generation"


def test_empty_source_type_returns_diagram_generation():
    assert required_source_error("", has_file=False, link="") == "diagram-generation"
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `cd backend-py && uv run pytest tests/domain/test_generate_guard.py -v`
Expected: FAIL с `ImportError: cannot import name 'required_source_error'`

- [ ] **Step 3: Реализовать**

```python
# backend-py/app/domain/generate_guard.py
from __future__ import annotations


def required_source_error(source_type: str | None, has_file: bool, link: str) -> str | None:
    """Guards against "silent generation" (#12): a /api/generate request that
    carries no usable source must be rejected with a 400 before the LLM is
    ever called. Returns the error code to send back, or None when the
    source is valid."""
    if source_type in ("text-file", "recording"):
        return None if has_file else "file-required"
    if source_type == "link":
        return None if link.strip() else "link-required"
    return "diagram-generation"
```

- [ ] **Step 4: Прогнать тесты**

Run: `cd backend-py && uv run pytest tests/domain/test_generate_guard.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add backend-py/app/domain/generate_guard.py backend-py/tests/domain/test_generate_guard.py
git commit -m "feat(backend-py): port required_source_error (#12 silent-generation guard)"
```

---

### Task 15: Загрузка промптов (переиспользуем существующие `.prompt.txt`)

**Files:**
- Create: `backend-py/app/services/__init__.py`
- Create: `backend-py/app/services/openai/__init__.py`
- Create: `backend-py/app/services/openai/prompts.py`
- Test: `backend-py/tests/services/__init__.py`
- Test: `backend-py/tests/services/openai/__init__.py`
- Test: `backend-py/tests/services/openai/test_prompts.py`

- [ ] **Step 1: Написать падающий тест**

```python
# backend-py/tests/services/__init__.py
```

```python
# backend-py/tests/services/openai/__init__.py
```

```python
# backend-py/tests/services/openai/test_prompts.py
from app.services.openai.prompts import build_generate_prompt


def test_build_generate_prompt_includes_source_and_details():
    result = build_generate_prompt("Some spec text", "extra details")
    assert "<SOURCE_SPECIFICATION>" in result
    assert "Some spec text" in result
    assert "<ADDITIONAL_DETAILS>" in result
    assert "extra details" in result


def test_build_generate_prompt_empty_details_block_is_empty():
    result = build_generate_prompt("spec", "")
    assert "<ADDITIONAL_DETAILS></ADDITIONAL_DETAILS>" in result


def test_build_generate_prompt_sanitizes_triple_backticks():
    result = build_generate_prompt("spec with ``` fence", "")
    assert "```" not in result.split("<SOURCE_SPECIFICATION>")[1].split("</SOURCE_SPECIFICATION>")[0].replace("'''", "")
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `cd backend-py && uv run pytest tests/services/openai/test_prompts.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.services'`

- [ ] **Step 3: Реализовать (читаем существующие файлы из `backend/src/prompts/`, не дублируем контент)**

```python
# backend-py/app/services/__init__.py
```

```python
# backend-py/app/services/openai/__init__.py
```

```python
# backend-py/app/services/openai/prompts.py
from __future__ import annotations

from pathlib import Path

# Reuses the same authored .prompt.txt files as the TS backend
# (backend/src/prompts/) instead of duplicating their content — avoids the
# two backends' generation behavior drifting apart during the Phase 0-4
# parallel-build period. Relocate to a shared location at the Phase 5
# cutover once backend/ (TS) is retired.
_PROMPTS_DIR = Path(__file__).resolve().parents[4] / "backend" / "src" / "prompts"


def _load_prompt(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8").strip()


_GENERATE_SYSTEM = _load_prompt("generateMermaid.prompt.txt")


def _sanitize(text: str) -> str:
    return text.strip()[:60_000].replace("```", "'''")


def build_generate_prompt(source_text: str, additional_details: str) -> str:
    safe_source = _sanitize(source_text)
    safe_details = _sanitize(additional_details)
    details_block = (
        f"<ADDITIONAL_DETAILS>\n{safe_details}\n</ADDITIONAL_DETAILS>"
        if safe_details
        else "<ADDITIONAL_DETAILS></ADDITIONAL_DETAILS>"
    )
    return (
        f"{_GENERATE_SYSTEM}\n\n"
        f"<SOURCE_SPECIFICATION>\n{safe_source}\n</SOURCE_SPECIFICATION>\n\n"
        f"{details_block}"
    )
```

- [ ] **Step 4: Прогнать тесты**

Run: `cd backend-py && uv run pytest tests/services/openai/test_prompts.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend-py/app/services/__init__.py backend-py/app/services/openai/__init__.py backend-py/app/services/openai/prompts.py backend-py/tests/services
git commit -m "feat(backend-py): port build_generate_prompt, reusing backend/src/prompts/*.txt"
```

---

### Task 16: Сервис `files` — извлечение текста (TXT/CSV/PDF/DOCX)

**Files:**
- Create: `backend-py/app/services/files/__init__.py`
- Create: `backend-py/app/services/files/extract.py`
- Create: `backend-py/app/services/files/pdf.py`
- Create: `backend-py/app/services/files/docx.py`
- Test: `backend-py/tests/services/files/__init__.py`
- Test: `backend-py/tests/services/files/test_extract.py`
- Test: `backend-py/tests/services/files/test_pdf.py`
- Test: `backend-py/tests/services/files/test_docx.py`

- [ ] **Step 1: Написать падающие тесты**

```python
# backend-py/tests/services/files/__init__.py
```

```python
# backend-py/tests/services/files/test_extract.py
from app.services.files.extract import (
    get_extension,
    has_pdf_text_layer,
    is_text_source_format,
    normalize_text_file,
    sanitize_filename,
)


def test_get_extension_lowercases_and_strips_dot():
    assert get_extension("Report.PDF") == "pdf"


def test_get_extension_no_dot_returns_empty():
    assert get_extension("noext") == ""


def test_sanitize_filename_replaces_unsafe_chars():
    assert sanitize_filename('a/b\\c:d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"


def test_sanitize_filename_truncates_to_140_chars():
    assert len(sanitize_filename("a" * 300)) == 140


def test_is_text_source_format():
    assert is_text_source_format("txt") is True
    assert is_text_source_format("pdf") is True
    assert is_text_source_format("docx") is True
    assert is_text_source_format("mp3") is False


def test_has_pdf_text_layer_detects_bt_tj_operators():
    content = b"%PDF-1.4\nBT /F1 12 Tf 50 150 Td (Hello) Tj ET"
    assert has_pdf_text_layer("report.pdf", content) is True


def test_has_pdf_text_layer_false_without_operators():
    content = b"%PDF-1.4\n<< /Type /Catalog >>"
    assert has_pdf_text_layer("report.pdf", content) is False


def test_has_pdf_text_layer_non_pdf_always_true():
    assert has_pdf_text_layer("notes.txt", b"anything") is True


async def test_normalize_text_file_txt_uses_raw_content():
    result = await normalize_text_file("notes.txt", b"Hello world", size=11)
    assert result.type == "text-file"
    assert result.text == "Hello world"
    assert result.stub is False
    assert result.file["format"] == "TXT"


async def test_normalize_text_file_xlsx_is_stub():
    result = await normalize_text_file("data.xlsx", b"binary", size=6)
    assert result.stub is True
    assert "XLSX" in result.text
```

```python
# backend-py/tests/services/files/test_pdf.py
from app.services.files.pdf import parse_pdf

GARBAGE_BUFFER = b"this is definitely not a pdf file at all"


async def test_parse_pdf_never_throws_on_non_pdf_buffer():
    text = await parse_pdf(GARBAGE_BUFFER)
    assert text == ""


async def test_parse_pdf_never_throws_on_empty_buffer():
    text = await parse_pdf(b"")
    assert text == ""
```

```python
# backend-py/tests/services/files/test_docx.py
from app.services.files.docx import parse_docx


async def test_parse_docx_returns_string_for_invalid_buffer():
    result = await parse_docx(b"not a docx")
    assert isinstance(result, str)


async def test_parse_docx_never_throws_on_garbage_input():
    result = await parse_docx(bytes([0x00, 0x01, 0x02, 0xFF, 0xFE]))
    assert isinstance(result, str)


async def test_parse_docx_returns_empty_string_on_empty_buffer():
    result = await parse_docx(b"")
    assert result == ""
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `cd backend-py && uv run pytest tests/services/files -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.services.files'`

- [ ] **Step 3: Реализовать `pdf.py` и `docx.py` (никогда не бросают исключение — контракт как у TS `parsePdf`/`parseDocx`)**

```python
# backend-py/app/services/files/pdf.py
from __future__ import annotations

import io

from pypdf import PdfReader


async def parse_pdf(buffer: bytes) -> str:
    """Extracts plain text from a PDF buffer. Never throws: any failure
    (malformed PDF, image-only PDF, parser error) results in an empty
    string so callers can safely fall back."""
    try:
        reader = PdfReader(io.BytesIO(buffer))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        return text.strip()[:60_000]
    except Exception:
        return ""
```

```python
# backend-py/app/services/files/docx.py
from __future__ import annotations

import io

from docx import Document


async def parse_docx(buffer: bytes) -> str:
    """Extracts plain text from a DOCX buffer. Never throws: any failure
    (malformed DOCX, unsupported format, parser error) results in an empty
    string so callers can safely fall back."""
    try:
        document = Document(io.BytesIO(buffer))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        return text.strip()[:60_000]
    except Exception:
        return ""
```

- [ ] **Step 4: Реализовать `extract.py`**

```python
# backend-py/app/services/files/__init__.py
```

```python
# backend-py/app/services/files/extract.py
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.files.docx import parse_docx
from app.services.files.pdf import parse_pdf

_TEXT_FORMATS = {"txt", "docx", "pdf"}
_TABLE_FORMATS = {"xls", "xlsx", "csv"}
_UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


def get_extension(filename: str) -> str:
    parts = filename.lower().split(".")
    return parts[-1] if len(parts) > 1 else ""


def sanitize_filename(filename: str) -> str:
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", filename)[:140]
    return cleaned or "file"


def is_text_source_format(fmt: str) -> bool:
    return fmt in _TEXT_FORMATS


def is_chat_document_format(fmt: str) -> bool:
    return fmt in _TEXT_FORMATS or fmt in _TABLE_FORMATS


def has_pdf_text_layer(filename: str, content: bytes) -> bool:
    if get_extension(filename) != "pdf":
        return True
    text = content.decode("latin1")
    return bool(re.search(r"\bBT\b", text)) and bool(re.search(r"(Tj|TJ)\b", text))


@dataclass
class NormalizedSource:
    type: str
    title: str
    text: str
    description: str
    file: dict | None = None
    url: str | None = None
    stub: bool = False


async def normalize_text_file(filename: str, buffer: bytes, size: int) -> NormalizedSource:
    fmt = get_extension(filename)
    safe_name = sanitize_filename(filename)
    text = f"Файл {safe_name} принят каркасом backend."
    stub = True

    if fmt in ("txt", "csv"):
        text = buffer.decode("utf-8", errors="replace")[:12_000]
        stub = False
    elif fmt == "pdf":
        extracted = await parse_pdf(buffer)
        stub = not extracted
        text = extracted or f"Файл {safe_name}: содержимое не удалось извлечь."
    elif fmt == "docx":
        extracted = await parse_docx(buffer)
        stub = not extracted
        text = extracted or f"Файл {safe_name}: содержимое не удалось извлечь."
    elif fmt in ("xls", "xlsx"):
        text = f"Извлечение содержимого {fmt.upper()} будет подключено в сервисе files. Сейчас используется тестовый контекст каркаса."
        stub = True

    return NormalizedSource(
        type="text-file",
        title=safe_name,
        text=text,
        description=f"{fmt.upper()} · {round(size / 1024)} КБ",
        file={"name": safe_name, "format": fmt.upper(), "size": size},
        stub=stub,
    )
```

- [ ] **Step 5: Прогнать тесты**

Run: `cd backend-py && uv run pytest tests/services/files -v`
Expected: PASS (14 passed)

- [ ] **Step 6: Commit**

```bash
git add backend-py/app/services/files backend-py/tests/services/files
git commit -m "feat(backend-py): port files service (extract/pdf/docx), 1:1 with TS services/files/*"
```

---

### Task 17: Сервис `links` (Jira/Confluence — заглушка)

**Files:**
- Create: `backend-py/app/services/links/__init__.py`
- Create: `backend-py/app/services/links/classify.py`
- Test: `backend-py/tests/services/links/__init__.py`
- Test: `backend-py/tests/services/links/test_classify.py`

- [ ] **Step 1: Написать падающий тест**

```python
# backend-py/tests/services/links/__init__.py
```

```python
# backend-py/tests/services/links/test_classify.py
from app.services.links.classify import classify_work_link, normalize_link


def test_classify_jira_link():
    assert classify_work_link("https://jira.example.com/browse/ABC-1") == "jira"


def test_classify_confluence_link():
    assert classify_work_link("https://confluence.example.com/wiki/page") == "confluence"


def test_classify_unrecognized_link_returns_none():
    assert classify_work_link("https://example.com/random") is None


def test_classify_invalid_url_returns_none():
    assert classify_work_link("not a url") is None


def test_normalize_link_marks_as_stub():
    result = normalize_link("https://jira.example.com/browse/ABC-1")
    assert result.type == "link"
    assert result.stub is True
    assert result.url == "https://jira.example.com/browse/ABC-1"
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `cd backend-py && uv run pytest tests/services/links -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.services.links'`

- [ ] **Step 3: Реализовать**

```python
# backend-py/app/services/links/__init__.py
```

```python
# backend-py/app/services/links/classify.py
from __future__ import annotations

from urllib.parse import urlparse

from app.services.files.extract import NormalizedSource


def classify_work_link(value: str) -> str | None:
    try:
        parsed = urlparse(value)
        if not parsed.scheme or not parsed.netloc:
            return None
        searchable = f"{parsed.netloc}{parsed.path}".lower()
    except ValueError:
        return None
    if "jira" in searchable:
        return "jira"
    if "confluence" in searchable or "wiki" in searchable:
        return "confluence"
    return None


def normalize_link(value: str) -> NormalizedSource:
    link_type = classify_work_link(value)
    label = "Jira" if link_type == "jira" else "Confluence"

    # Temporary integration point: replace this stub with real
    # Jira/Confluence API access once service URLs, credentials and
    # supported link formats are approved (Phase 4).
    return NormalizedSource(
        type="link",
        title=f"{label}: тестовый источник",
        text=f"Контролируемая заглушка {label}. Здесь будет текст задачи или страницы после подключения серверной интеграции.",
        description=f"{label} · {value}",
        url=value,
        stub=True,
    )
```

- [ ] **Step 4: Прогнать тесты**

Run: `cd backend-py && uv run pytest tests/services/links -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add backend-py/app/services/links backend-py/tests/services/links
git commit -m "feat(backend-py): port links service stub (classify_work_link/normalize_link)"
```

---

### Task 18: Сервис `recordings` (транскрибация — заглушка)

**Files:**
- Create: `backend-py/app/services/recordings/__init__.py`
- Create: `backend-py/app/services/recordings/normalize.py`
- Test: `backend-py/tests/services/recordings/__init__.py`
- Test: `backend-py/tests/services/recordings/test_normalize.py`

- [ ] **Step 1: Написать падающий тест**

```python
# backend-py/tests/services/recordings/__init__.py
```

```python
# backend-py/tests/services/recordings/test_normalize.py
from app.services.recordings.normalize import is_recording_format, normalize_recording


def test_is_recording_format_accepts_known_formats():
    for fmt in ("mp3", "m4a", "mp4", "webm"):
        assert is_recording_format(fmt) is True


def test_is_recording_format_rejects_unknown_format():
    assert is_recording_format("pdf") is False


def test_normalize_recording_is_stub():
    result = normalize_recording("meeting.mp3", size=1024)
    assert result.type == "recording"
    assert result.stub is True
    assert result.file["format"] == "MP3"
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `cd backend-py && uv run pytest tests/services/recordings -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.services.recordings'`

- [ ] **Step 3: Реализовать**

```python
# backend-py/app/services/recordings/__init__.py
```

```python
# backend-py/app/services/recordings/normalize.py
from __future__ import annotations

from app.services.files.extract import NormalizedSource, get_extension, sanitize_filename

_RECORDING_FORMATS = {"mp3", "m4a", "mp4", "webm"}


def is_recording_format(fmt: str) -> bool:
    return fmt in _RECORDING_FORMATS


def normalize_recording(filename: str, size: int) -> NormalizedSource:
    fmt = get_extension(filename)
    safe_name = sanitize_filename(filename)

    return NormalizedSource(
        type="recording",
        title=safe_name,
        text="Временная транскрибация записи. Реальное извлечение аудиодорожки и распознавание речи подключаются в сервисе recordings.",
        description=f"{fmt.upper()} · {round(size / 1024)} КБ",
        file={"name": safe_name, "format": fmt.upper(), "size": size},
        stub=True,
    )
```

- [ ] **Step 4: Прогнать тесты**

Run: `cd backend-py && uv run pytest tests/services/recordings -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend-py/app/services/recordings backend-py/tests/services/recordings
git commit -m "feat(backend-py): port recordings service stub (is_recording_format/normalize_recording)"
```

---

### Task 19: `generate_diagram` — связывает LLM-клиент с промптом

**Files:**
- Create: `backend-py/app/services/openai/generate.py`
- Test: `backend-py/tests/services/openai/test_generate.py`

- [ ] **Step 1: Написать падающий тест**

```python
# backend-py/tests/services/openai/test_generate.py
import pytest

from app.infrastructure.llm.client import VLLMClient
from app.services.openai.generate import generate_diagram


def _llm_response(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


async def test_generate_diagram_builds_prompt_and_returns_mermaid(mock_llm_server):
    url = mock_llm_server(_llm_response("flowchart LR\nA --> B"))
    client = VLLMClient(url=url, model="test", response_format_mode="none")
    result = await generate_diagram("Some technical spec", "extra details", client)
    assert result.startswith("flowchart LR")


async def test_generate_diagram_propagates_llm_error_on_repeated_failure(mock_llm_server):
    url = mock_llm_server({"error": "boom"}, status_code=500)
    client = VLLMClient(url=url, model="test", response_format_mode="none")
    with pytest.raises(Exception):
        await generate_diagram("spec", "", client)
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `cd backend-py && uv run pytest tests/services/openai/test_generate.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.services.openai.generate'`

- [ ] **Step 3: Реализовать**

```python
# backend-py/app/services/openai/generate.py
from __future__ import annotations

from app.config import Settings, get_settings
from app.infrastructure.llm.client import VLLMClient
from app.infrastructure.llm.retry import execute_with_retry
from app.services.openai.prompts import build_generate_prompt


def make_client(settings: Settings | None = None) -> VLLMClient:
    settings = settings or get_settings()
    return VLLMClient(
        url=settings.llm_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        timeout_ms=settings.llm_timeout_ms,
        temperature=settings.llm_temperature,
        seed=settings.llm_seed,
        response_format_mode=settings.llm_response_format_mode,
        insecure_tls=settings.llm_insecure_tls,
    )


async def generate_diagram(source_text: str, details: str, client: VLLMClient | None = None) -> str:
    client = client or make_client()
    prompt = build_generate_prompt(source_text, details)
    return await execute_with_retry(lambda: client.complete_text(prompt))
```

- [ ] **Step 4: Прогнать тесты**

Run: `cd backend-py && uv run pytest tests/services/openai/test_generate.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend-py/app/services/openai/generate.py backend-py/tests/services/openai/test_generate.py
git commit -m "feat(backend-py): port generate_diagram service (make_client + retry-wrapped completion)"
```

---

### Task 20: `POST /api/generate` — сборка эндпоинта

**Files:**
- Create: `backend-py/app/api/schemas.py`
- Create: `backend-py/app/api/generate.py`
- Modify: `backend-py/app/main.py`
- Test: `backend-py/tests/api/__init__.py`
- Test: `backend-py/tests/api/test_generate_endpoint.py`

- [ ] **Step 1: Написать падающие тесты для эндпоинта**

```python
# backend-py/tests/api/__init__.py
```

```python
# backend-py/tests/api/test_generate_endpoint.py
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_generate_missing_source_type_returns_400_diagram_generation(client):
    response = client.post("/api/generate", data={})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "diagram-generation"


def test_generate_text_file_without_file_returns_400_file_required(client):
    response = client.post("/api/generate", data={"sourceType": "text-file"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "file-required"


def test_generate_link_without_value_returns_400_link_required(client):
    response = client.post("/api/generate", data={"sourceType": "link", "link": ""})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "link-required"


def test_generate_link_invalid_format_returns_400_invalid_link(client):
    response = client.post("/api/generate", data={"sourceType": "link", "link": "not-a-url"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid-link"


def test_generate_text_file_unsupported_format_returns_400_file_format(client):
    response = client.post(
        "/api/generate",
        data={"sourceType": "text-file"},
        files={"file": ("song.mp3", b"binary data", "audio/mpeg")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "file-format"


def test_generate_text_file_too_large_returns_400_file_size(client):
    huge = b"x" * (10 * 1024 * 1024 + 1)
    response = client.post(
        "/api/generate",
        data={"sourceType": "text-file"},
        files={"file": ("notes.txt", huge, "text/plain")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "file-size"


def test_generate_text_file_success_returns_200(client, monkeypatch):
    async def fake_generate_diagram(source_text, details, client=None):
        return "flowchart LR\nA --> B"

    monkeypatch.setattr("app.api.generate.generate_diagram", fake_generate_diagram)

    response = client.post(
        "/api/generate",
        data={"sourceType": "text-file", "details": "some details"},
        files={"file": ("notes.txt", b"Hello world", "text/plain")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["result"]["mermaidCode"].startswith("flowchart LR")
    assert body["result"]["sourceText"] == "Hello world"


def test_generate_llm_failure_returns_500_diagram_generation(client, monkeypatch):
    async def fake_generate_diagram(source_text, details, client=None):
        raise RuntimeError("LLM down")

    monkeypatch.setattr("app.api.generate.generate_diagram", fake_generate_diagram)

    response = client.post(
        "/api/generate",
        data={"sourceType": "text-file"},
        files={"file": ("notes.txt", b"Hello world", "text/plain")},
    )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "diagram-generation"
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `cd backend-py && uv run pytest tests/api/test_generate_endpoint.py -v`
Expected: FAIL с 404 (роут ещё не существует) на всех тестах

- [ ] **Step 3: Реализовать Pydantic-схемы с camelCase-сериализацией**

```python
# backend-py/app/api/schemas.py
from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class FileMeta(CamelModel):
    name: str
    format: str
    size: int


class SourceContext(CamelModel):
    type: str
    title: str
    description: str
    file: FileMeta | None = None
    url: str | None = None
    stub: bool | None = None


class DiagramResult(CamelModel):
    title: str
    mermaid_code: str
    source_text: str
    source_context: SourceContext
    details: str
    chat: list = []
    warnings: list[str] = []


class ApiError(CamelModel):
    code: str
    message: str
    field: str | None = None
```

- [ ] **Step 4: Реализовать эндпоинт**

```python
# backend-py/app/api/generate.py
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.schemas import ApiError, DiagramResult, FileMeta, SourceContext
from app.domain.generate_guard import required_source_error
from app.domain.mermaid import validate_mermaid
from app.services.files.extract import (
    get_extension,
    has_pdf_text_layer,
    is_text_source_format,
    normalize_text_file,
)
from app.services.links.classify import classify_work_link, normalize_link
from app.services.openai.generate import generate_diagram
from app.services.recordings.normalize import is_recording_format, normalize_recording
from app.config import get_settings

router = APIRouter()

_USER_MESSAGES = {
    "file-required": "Необходимо прикрепить файл",
    "file-format": "Некорректный формат файла",
    "file-size-text": "Файл превышает 10 МБ",
    "file-size-recording": "Файл превышает 100 МБ",
    "link-required": "Поле обязательно для заполнения",
    "invalid-link": "Неверный формат ссылки",
    "diagram-generation": "Схема не сформирована. Перезагрузите страницу или повторите попытку позже",
    "attachment-error": "Ошибка загрузки файла",
}


def _api_error(
    status_code: int, code: str, message_key: str | None = None, field: str | None = None
) -> JSONResponse:
    # `code` is the wire value the frontend matches on (must equal the TS
    # UserErrorCode union in shared/types/index.ts — e.g. always "file-size",
    # never "file-size-text"/"file-size-recording"). `message_key` only
    # selects which _USER_MESSAGES text to show; defaults to `code` when the
    # two coincide.
    error = ApiError(code=code, message=_USER_MESSAGES[message_key or code], field=field)
    return JSONResponse(
        status_code=status_code,
        content={"ok": False, "error": error.model_dump(by_alias=True, exclude_none=True)},
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/api/generate")
async def generate(request: Request):
    form = await request.form()
    source_type = form.get("sourceType")
    details = form.get("details", "") or ""
    link = (form.get("link", "") or "").strip()
    # Frontend field name is "file" (see frontend/src/main.ts:871
    # `form.set("file", selectedFile)`), not "attachment" — "attachment" is
    # only used as the `field` value inside error payloads below.
    upload = form.get("file")
    has_file = upload is not None and bool(getattr(upload, "filename", None))

    missing = required_source_error(source_type, has_file, link)
    if missing:
        return _api_error(400, missing)

    settings = get_settings()

    if source_type == "text-file":
        content = await upload.read()
        fmt = get_extension(upload.filename)
        if len(content) > settings.max_text_file_bytes:
            return _api_error(400, "file-size", message_key="file-size-text")
        if not is_text_source_format(fmt):
            return _api_error(400, "file-format")
        if not has_pdf_text_layer(upload.filename, content):
            return _api_error(400, "attachment-error", field="attachment")
        source = await normalize_text_file(upload.filename, content, len(content))
    elif source_type == "recording":
        content = await upload.read()
        fmt = get_extension(upload.filename)
        if len(content) > settings.max_recording_file_bytes:
            return _api_error(400, "file-size", message_key="file-size-recording")
        if not is_recording_format(fmt):
            return _api_error(400, "file-format")
        source = normalize_recording(upload.filename, len(content))
    elif source_type == "link":
        if not classify_work_link(link):
            return _api_error(400, "invalid-link")
        source = normalize_link(link)
    else:
        return _api_error(400, "diagram-generation")

    try:
        mermaid_code = await generate_diagram(source.text, details)
    except Exception:
        return _api_error(500, "diagram-generation")

    validation = validate_mermaid(mermaid_code)
    if not validation.ok:
        return _api_error(500, "diagram-generation")

    result = DiagramResult(
        title="Тестовая User Flow-схема",
        mermaid_code=mermaid_code,
        source_text=source.text,
        source_context=SourceContext(
            type=source.type,
            title=source.title,
            description=source.description,
            file=FileMeta(**source.file) if source.file else None,
            url=source.url,
            stub=source.stub,
        ),
        details=details,
        chat=[],
        warnings=["Используется временная заглушка backend."] if source.stub else [],
    )
    return JSONResponse(
        status_code=200,
        content={"ok": True, "result": result.model_dump(by_alias=True, exclude_none=True)},
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
```

Оба кода ошибок и имя multipart-поля сверены с TS 1:1: `code: "file-size"` для обоих превышений размера (см. `backend/src/server/index.ts:110,123` и `shared/types/index.ts`'s `UserErrorCode`, где варианта `"file-size-text"` не существует), и поле файла в форме называется `file`, а не `attachment` (см. `frontend/src/main.ts:871` — `form.set("file", selectedFile)`; `"attachment"` встречается только как значение `field` в теле ошибки, никогда как имя form-поля).

- [ ] **Step 5: Подключить роутер**

```python
# backend-py/app/main.py — old_string:
from app.api.config_route import router as config_router
from app.api.health import router as health_router

# new_string:
from app.api.config_route import router as config_router
from app.api.generate import router as generate_router
from app.api.health import router as health_router
```

```python
# backend-py/app/main.py — old_string:
app.include_router(health_router)
app.include_router(config_router)

# new_string:
app.include_router(health_router)
app.include_router(config_router)
app.include_router(generate_router)
```

- [ ] **Step 6: Прогнать тесты эндпоинта**

Run: `cd backend-py && uv run pytest tests/api/test_generate_endpoint.py -v`
Expected: PASS (8 passed)

- [ ] **Step 7: Прогнать весь набор тестов backend-py**

Run: `cd backend-py && uv run pytest -v`
Expected: все тесты PASS, никаких регрессий в ранее написанных тестах.

- [ ] **Step 8: Commit**

```bash
git add backend-py/app/api backend-py/app/main.py backend-py/tests/api
git commit -m "feat(backend-py): wire POST /api/generate end-to-end (Phase 1 done)"
```

---

### Task 21: Финальный самопроверочный прогон

**Files:** (нет новых файлов — только верификация)

- [ ] **Step 1: Полный прогон тестов**

Run: `cd backend-py && uv run pytest -v`
Expected: все тесты (Фаза 0 + Фаза 1) PASS, 0 failed.

- [ ] **Step 2: Сверить с дизайн-спекой**

Пройтись по `docs/superpowers/specs/2026-07-10-python-backend-infra-design.md`, разделу «Дорожная карта»: Фаза 0 (каркас FastAPI + Docker + Postgres/Redis-подключение + паритет `/health`,`/config` + CI) — закрыта Task 1–8; Фаза 1 (LLM-слой + `/generate`, паритет retry/TLS/fallback) — закрыта Task 9–20. Открытый вопрос спеки про httpOnly-cookie vs явный `session_id` остаётся нерешённым — это предмет отдельного плана для Фазы 2, здесь ничего не реализовывать.

- [ ] **Step 3: Проверить сборку Docker-образа ещё раз (после всех изменений в `app/`)**

Run: `docker build -f backend-py/Dockerfile -t backend-py:local .`
Expected: сборка успешна.

- [ ] **Step 4: Commit (если Step 2 выявил недостающие мелочи — зафиксировать их правки здесь; иначе шаг пуст)**

```bash
git status
# Если есть незакоммиченные правки после самопроверки:
git add -A
git commit -m "fix(backend-py): address self-review gaps from Phase 0+1 final pass"
```

---

## После выполнения плана

- `backend-py/` содержит рабочий, протестированный каркас с паритетом `/health`, `/config`, `/generate` относительно TS-бэка.
- `backend/` (TS) не тронут — прод/тест compose и деплой CI продолжают обслуживать его как раньше.
- Следующий шаг — отдельный design-review открытого вопроса про сессии (cookie vs `session_id` в теле) и новый implementation plan для **Фазы 2** (сессии + контекст чата + история, `/chat`).
