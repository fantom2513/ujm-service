# syntax=docker/dockerfile:1
# Python/FastAPI backend used by the test and production Compose stacks.

FROM nexus.sogaz.ru/python:3.12-bookworm AS deps
WORKDIR /app

ENV PIP_INDEX_URL=https://nexus.sogaz.ru/repository/pypi-group/simple \
    PIP_TRUSTED_HOST=nexus.sogaz.ru \
    UV_INDEX_URL=https://nexus.sogaz.ru/repository/pypi-group/simple \
    UV_SYSTEM_CERTS=true \
    UV_INSECURE_HOST=nexus.sogaz.ru

RUN pip install --no-cache-dir uv
COPY backend-py/pyproject.toml ./
RUN uv sync --no-dev --no-install-project

FROM nexus.sogaz.ru/python:3.12-bookworm AS runtime
WORKDIR /app
ENV PYTHONUNBUFFERED=1
RUN groupadd --system --gid 1001 app && useradd --system --uid 1001 --gid app app

COPY --from=deps /app/.venv ./.venv
COPY backend-py/app ./app
COPY backend-py/alembic.ini ./
COPY backend-py/alembic ./alembic
# app/services/openai/prompts.py resolves _PROMPTS_DIR as
# Path(__file__).resolve().parents[4] / "backend/src/prompts", i.e. "/backend/src/prompts"
# from this image's WORKDIR — reuses the TS backend's prompt files without
# duplicating their content (see that module's docstring). Must land at
# this exact path or the app fails to import at container startup.
COPY backend/src/prompts /backend/src/prompts
ENV PATH="/app/.venv/bin:$PATH"
ENV APP_PORT=8001

RUN chown -R app:app /app
USER app

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,os,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('APP_PORT','8001')+'/api/health').status==200 else 1)"

# The production Compose command runs `alembic upgrade head` first and then
# starts Uvicorn with `exec`, matching the deployment pattern used by CX Copilot.
# This default remains useful for running the image without Compose.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${APP_PORT}\""]
