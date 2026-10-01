# Deployment smoke results

Fill this file after deploying to the closed test server. Do not put secrets,
tokens, full `.env` contents, or user data here.

- Environment:
- Deployed commit:
- Date and operator:
- Compose file:
- Backend image ID (`docker image inspect --format='{{.Id}}' ...`):

Use one generated session for the checks. Record only a short suffix of its
`sessionId`: the full value grants access to that session.

- `sessionId` suffix:
- completed `requestId` used for replay:

| # | Scenario | Expected result | Actual result |
|---|---|---|---|
| 1 | Generate a diagram from a small test text | `POST /api/generate` returns HTTP 202 with `sessionId` and `requestId`; polling returns the diagram; a session and first version are created | |
| 2 | Send several chat turns in the same session | Each new `POST /api/chat` returns HTTP 202; polling returns each result; messages and versions are appended and `sessionId` does not change | |
| 3 | Run Undo / restore previous | HTTP 202 followed by a poll result; a new append-only version is created without an LLM request | |
| 4 | Repeat the exact same `requestId` and payload | The completed response is replayed; no new message/version rows appear | |
| 5 | Repeat that `requestId` with a different message or action | HTTP 409 with `request-id-conflict` | |
| 6 | Send a new unique `requestId` | A normal new turn is completed | |
| 7 | Force an LLM timeout/error | Poll returns HTTP 200 with `ok: false` and a safe error; no partial messages/versions or lease remain; the failed claim is retained | |
| 8 | Repeat the failed `requestId`, then send a new one | The old failure is replayed without another LLM call; a new `requestId` can start a fresh request | |
| 9 | Restart the backend, then continue the session and replay a completed request | Session data survives; completed response replays without duplicate rows | |
| 10 | Repeat a request with an arbitrary `X-User-Id` while `IDENTITY_MODE=anonymous` | The header is ignored and does not change session ownership | |
| 11 | Reload the page while generation or chat is processing | The pending `sessionId` and `requestId` are restored; polling resumes and shows the result once ready | |

Useful database snapshot before and after replay/restart checks:

```bash
docker compose -f docker-compose.py.yaml exec ux-architecture-postgres sh -lc \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "SELECT right(s.id, 6) AS session_suffix, s.user_id, s.head_version_id, \
          (s.lock_token IS NOT NULL) AS has_lease, s.locked_until, \
          (SELECT count(*) FROM diagram_versions v WHERE v.session_id=s.id) AS versions, \
          (SELECT count(*) FROM messages m WHERE m.session_id=s.id) AS messages, \
          (SELECT count(*) FROM turns t WHERE t.session_id=s.id) AS turns \
   FROM sessions s ORDER BY s.created_at DESC LIMIT 5;"'
```

Use the Compose file actually deployed in the target environment. Attach relevant HTTP status codes
and short sanitized log excerpts for failures, never the generated `.env`.
