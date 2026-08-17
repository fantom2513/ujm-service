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
