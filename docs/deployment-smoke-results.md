# Deployment smoke results

Fill this file after deploying to the closed test server. Do not put secrets,
tokens, full `.env` contents, or user data here.

- Environment:
- Deployed commit:
- Date and operator:
- Compose file:
- Backend image ID (`docker image inspect --format='{{.Id}}' ...`):

Use one generated session for the checks and record its non-secret identifiers:

- `sessionId`:
- completed `requestId` used for replay:

| # | Scenario | Expected result | Actual result |
|---|---|---|---|
| 1 | Generate a diagram from a small test text | HTTP 200; a session and first diagram version are created | |
| 2 | Send several chat turns in the same session | Messages and versions are appended; `sessionId` does not change | |
| 3 | Run Undo / restore previous | A new append-only version is created without an LLM request | |
| 4 | Repeat the exact same `requestId` and payload | The completed response is replayed; no new message/version rows appear | |
| 5 | Repeat that `requestId` with a different message or action | HTTP 409 with `request-id-conflict` | |
| 6 | Send a new unique `requestId` | A normal new turn is completed | |
| 7 | Force an LLM timeout/error | No partial messages/versions and no permanent lease/claim remain | |
| 8 | Repeat the request that ended with the unfinished error | The request can run again instead of remaining permanently locked | |
| 9 | Restart the backend, then continue the session and replay a completed request | Session data survives; completed response replays without duplicate rows | |
| 10 | Repeat a request with an arbitrary `X-User-Id` while `IDENTITY_MODE=anonymous` | The header is ignored and does not change session ownership | |

Useful database snapshot before and after replay/restart checks:

```bash
docker compose -f docker-compose.test.yaml exec ux-architecture-postgres sh -lc \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "SELECT s.id, s.user_id, s.head_version_id, s.lock_token, s.locked_until, \
          (SELECT count(*) FROM diagram_versions v WHERE v.session_id=s.id) AS versions, \
          (SELECT count(*) FROM messages m WHERE m.session_id=s.id) AS messages, \
          (SELECT count(*) FROM turns t WHERE t.session_id=s.id) AS turns \
   FROM sessions s ORDER BY s.created_at DESC LIMIT 5;"'
```

For production replace the Compose filename. Attach relevant HTTP status codes
and short sanitized log excerpts for failures, never the generated `.env`.
