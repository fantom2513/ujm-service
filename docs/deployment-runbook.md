# backend-py deployment runbook

The existing GitLab build/deploy jobs remain unchanged. An authorized `test`
stage now runs Python tests against an ephemeral PostgreSQL service and runs the
Node tests/frontend build before any Docker image build starts.

## Runtime order

1. `ux-architecture-postgres` starts from the corporate Nexus image and waits
   until `pg_isready` succeeds.
2. `ux-architecture-backend` runs `alembic upgrade head`, then replaces its
   shell with Uvicorn through `exec` and passes `/api/health` on port 8001.
3. `ux-architecture-frontend` starts; Nginx proxies API requests to port 8001.

PostgreSQL is reachable only through the Docker network. Its data lives in a
named Docker volume, so rebuilding or restarting containers does not erase it.
Test and production Compose files use different volume names.

## GitLab CI/CD variables

Edit the existing `ENV_TEST` and `ENV_PROD` variables. Keep their current
settings and add the following values. Generate a different password for each
environment with `openssl rand -hex 32`; do not commit the real values to Git.

```env
POSTGRES_USER=uxarch
POSTGRES_PASSWORD=<strong-random-password>
POSTGRES_DB=uxarch
DATABASE_URL=postgresql+asyncpg://uxarch:<url-encoded-password>@ux-architecture-postgres:5432/uxarch

LLM_URL=https://proxy-ai.sogaz.ru/deepseek-v4-flash/v1
LLM_MODEL=DeepSeek-V4-Flash
LLM_API_KEY=
LLM_TLS_INSECURE=false
LLM_DEADLINE_MS=120000
LLM_CONNECT_TIMEOUT_MS=5000
LLM_POOL_TIMEOUT_MS=5000

IDENTITY_MODE=anonymous
```

The hex password can be copied unchanged into both password positions. If a
different password format contains `@`, `:`, `/`, `#`, or `%`, URL encode it
only in `DATABASE_URL`; `POSTGRES_PASSWORD` keeps the original value. The
checked endpoint currently accepts LLM requests without an API key, so an empty
`LLM_API_KEY` is intentional. Redis is not required by the current generate/chat
path; keep `REDIS_URL` if it already exists in the environment.

The external Docker network from the existing deployment must exist:

```bash
docker network inspect cx_copilot_cx_net
```

## Deploy and verify

Push or merge the integration commit into `test`. The pipeline runs `test-py`,
`test-node`, `build-test` and then automatically starts `deploy-test` on the
`ux02-copilot_docker` runner only if all previous stages succeeded. Production
build/deploy jobs remain restricted to `master`, and `deploy-prod` stays manual.
No manual CI-file edit is required after the integration commit.

On the target runner/host, inspect the result with:

```bash
docker compose -f docker-compose.test.yaml ps -a
docker compose -f docker-compose.test.yaml logs --tail=100 ux-architecture-backend
docker compose -f docker-compose.test.yaml exec ux-architecture-postgres sh -lc \
  'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
docker compose -f docker-compose.test.yaml exec \
  ux-architecture-backend alembic current
```

Use `docker-compose.prod.yaml` instead on production. Alembic output is part of
the backend container log. `alembic upgrade head` is safe to execute again on
restart: already applied revisions are not applied twice.

Check the externally exposed route, replacing the host with the real one:

```bash
curl -fsS "https://<service-host>/ux-architecture/api/health"
curl -fsS "https://<service-host>/ux-architecture/api/config"
```

Then open `/ux-architecture/` in a browser and execute every scenario in
`docs/deployment-smoke-results.md`. Record the deployed commit and the actual
result of each check; health alone does not prove that persistence works.

## Restart check

Before restarting, keep the `sessionId`, one completed `requestId`, its exact
payload and response from the smoke check. Restarting the application must not
remove PostgreSQL data:

```bash
docker restart ux-architecture-backend
docker inspect --format='{{.State.Health.Status}}' ux-architecture-backend
docker compose -f docker-compose.test.yaml exec \
  ux-architecture-backend alembic current
```

After the restart, continue the saved session and replay the saved completed
request. The session must continue and the replay response must be identical
without new message/version rows.

## Rollback

Record the last working Git commit before the cutover. If the new backend must
be rolled back, revert the cutover commit in GitLab and run the ordinary deploy
job for that commit. The previous Compose definition restores the TypeScript
backend under the same `ux-architecture-backend` container name.

Do not run `docker compose down -v` and do not delete the PostgreSQL volume.
Do not run `alembic downgrade` as part of an application rollback. Keeping the
volume and schema makes the rollback recoverable and preserves stored chats.
