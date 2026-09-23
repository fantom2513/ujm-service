# Async delivery for /api/generate and /api/chat, with TTFT+stall inside the worker

Status: draft, not yet approved for implementation. Supersedes the earlier
draft of this same file, which only addressed the LLM client's internal
timeout model. That work is preserved below as an implementation detail —
it now runs inside a background worker instead of inside a request that
holds the browser connection open.

## Motivation

Tonight's incident chain, in order:

1. `backend-py` was tuned against `google/gemma-4` (fast, non-reasoning).
   Production points at `DeepSeek-V4-Flash` in reasoning mode. A trivial
   3-line prompt measured **618.9s** end-to-end, 13,624 SSE chunks, steady
   throughout (worst gap ~20s) — genuinely long, not hung.
2. First fix attempt: a three-phase timeout model inside `VLLMClient`
   (TTFT / stall / overall deadline) so a live, producing call isn't killed
   by an arbitrary wall clock. This is real and still needed — see
   "LLM client behavior" below — but it only fixes what happens **inside
   our backend**. The browser still makes one synchronous HTTP request and
   waits for one final response. For that whole duration the browser-facing
   connection carries **zero bytes in either direction** — the most
   idle-timeout-vulnerable leg in the whole chain, dependent on `nginx.conf`,
   an external corporate gateway we don't control, and any number of
   unknown middleboxes (corporate proxy, VPN) we have no visibility into at
   all. Raising timeouts on the layers we can see doesn't remove the ones
   we can't.
3. This was already identified and deliberately deferred, not overlooked:
   `.intern/08-chat-idempotency.md:72-78` lists, side by side, in "Вне
   scope": `идемпотентность /api/generate` and
   `background jobs, request queue и claim heartbeat`. The `turns` table
   built for task 08's chat idempotency is, structurally, already most of
   a job-result primitive (`request_id`, `claim_token`, `claimed_until`,
   `response_json`) — task 08 built the storage and deliberately left the
   transport (background execution + polling) for later. This document is
   that later.

## Architecture

The browser makes a fast request, gets back an id, and polls a short status
endpoint until the result is ready. No request involved in this exchange
is ever open for more than a few seconds — the entire class of "does some
layer between here and the browser kill idle connections" risk goes away,
rather than being mitigated by picking bigger numbers.

### `/api/chat` — reuses the existing `turns` machinery almost as-is

Today, `ChatService.run_chat()` (`chat_service.py:102-`) already does, in
order: resolve/bind owner → create one `LLMDeadline` → **claim or replay
via `turns`** (`claim_or_take_over`, already fully durable in Postgres
before the LLM is ever called) → acquire session lease → load context →
run LLM → persist + complete claim. The claim/replay branch at lines
171-181 already *is* "check whether a job finished" — it's just invoked
today by the client re-POSTing the same request instead of a dedicated GET.

Split `run_chat()` at the claim boundary:

- **`claim_or_replay()`** — everything up through claim/replay/reject.
  Stays synchronous inside the HTTP handler; it was already fast (no LLM
  call in this path).
- **`execute_claimed_turn()`** — lease acquire → context load → heartbeat →
  undo-or-LLM → persist → complete/cleanup claim. Unchanged internally.
  Only how it's invoked changes: scheduled as a background task instead of
  awaited inline by the request handler.

`POST /api/chat` outcomes:

| Claim outcome | Response |
|---|---|
| Replay (`response_json` already set) | `200` with the `ChatResult`, exactly as today — already fast, no change |
| New claim acquired | `202 {"status": "processing", "sessionId", "requestId"}`; `execute_claimed_turn()` scheduled in the background |
| Conflict / live claim busy | Same `409 request-id-conflict` / `request-in-progress` as today — unchanged |

New `GET /api/chat/{sessionId}/turns/{requestId}`:

| `turns` row state | Response |
|---|---|
| `response_json` present, `ok: true` | `200` with the `ChatResult` — same shape the frontend already parses from today's synchronous `200` |
| `response_json` present, `ok: false` | `200` with the stored error envelope — terminal, see "Failure is a completed claim" below |
| `response_json` NULL, `claimed_until > now` | `200 {"status": "processing"}` |
| `response_json` NULL, `claimed_until <= now` (worker genuinely died, e.g. process killed — should be rare once claim heartbeat below exists) | `200 {"status": "failed", "retryable": true}` — frontend re-`POST`s the same `requestId`; the existing takeover branch in `claim_or_take_over` reclaims an expired incomplete claim with a matching hash |
| No row at all | `404` (defensive — shouldn't happen once a claim response was returned) |

### Claim heartbeat — the claim must outlive a legitimately long attempt

`claimed_until` is currently sized **once**, at claim time:
`service.py:158` → `remaining_seconds = deadline.require_remaining()` →
`repositories.py:195-235` → `claimed_until = now + remaining_seconds + 30s`.
That number comes from `LLMDeadline`, and this design deliberately lets a
healthy single attempt run past `LLM_DEADLINE_MS`. Left as-is, a genuinely
long but successful attempt finishes *after* its own claim has expired —
`TurnRepository.complete()` (`repositories.py:251-276`) requires
`claimed_until > database_now`, so completion silently affects zero rows
and the result is lost even though the LLM answered correctly.

Fix: extend `claimed_until` on a **fixed** periodic heartbeat, the same
mechanism and cadence already used for the session lease
(`_heartbeat_lease`, `service.py:318`, every `CHAT_HEARTBEAT_INTERVAL_SECONDS`
= 10s) — not tied to chunk/stall activity. Add
`TurnRepository.heartbeat_claim(session_id, request_id, claim_token) -> int`,
fencing on `claim_token` and `response_json IS NULL` exactly like
`heartbeat_lease` fences on `lock_token`. Run it as a second heartbeat task
alongside the existing lease heartbeat for the duration of
`execute_claimed_turn()`.

**Deliberately not chunk-driven, despite the earlier draft floating that
option:** with a 60s stall budget, a claim heartbeat that only resets on
chunk arrival could sit idle for up to 60s during a perfectly legitimate
pause — long enough to blow past a short claim TTL before the stall timer
itself would even complain. Liveness-of-the-model (TTFT/stall) and
liveness-of-the-worker-process (claim heartbeat) are different questions
answered by different mechanisms; conflating them reintroduces exactly the
race being fixed here.

**What happens if the claim is lost anyway** (heartbeat itself fails
repeatedly, or a `rowcount == 0` shows someone else took over): this
codebase already has a policy for the analogous session-lease case
(`DESIGN-RATIONALE.md` section 06 — "Cleanup не должен маскировать
основной результат; последняя страховка — TTL"), and claim heartbeat
follows the same one rather than inventing a stricter rule. `complete()`
already fences on `claim_token`, so a worker that lost its claim
*structurally cannot* write a result under a superseded token — that part
is a correctness guarantee, not a behavior to implement. What the lost
worker does with its still-running LLM call is a cheaper, optional
improvement, not a correctness requirement: best-effort, cancel the
in-flight attempt once heartbeat failure is detected, to stop burning an
LLM slot on work that can never be persisted — but if that cancellation
doesn't happen promptly, nothing is unsafe, only wasteful.

### `/api/generate` — new claim, reusing the same `turns` shape

Today `generate.py` has no `requestId` and creates the `Session` only
*after* a successful LLM call (`create_session_with_version`, called at
`generate.py:125`). Nothing here is reusable as-is; the shape is new but
directly mirrors `/api/chat`'s — **with one ordering problem chat doesn't
have**, worth stating plainly: chat's session already exists before the
first chat turn, so `(session_id, requestId)` is a stable claim key from
the start. `/api/generate` has no session yet, and "create session, then
claim by `(session_id, requestId)`" cannot be idempotent if `session_id`
is freshly generated on every `POST` — a retried `requestId` would get a
different `session_id` each time.

**Rejected fix, kept here so it isn't proposed again:** using the
client-generated `requestId` itself as `session_id`. `frontend/src/utils/id.ts:26-28`
is explicit about why not — its fallback path (no Web Crypto available)
is `` `fallback-${Date.now().toString(36)}-${Math.random().toString(36)...}` ``,
documented in the code as "Request IDs are idempotency keys, not
credentials." A `session_id` in this system *is* the access-control token
for that session (ownership is resolved purely by knowing the id, see
`run_chat`'s owner-bind logic) — collapsing an idempotency key into a
session identifier would downgrade session access to guessable-in-the-
degraded-case. `session_id` stays exactly as today:
`secrets.token_urlsafe(32)`, server-generated, never derived from anything
client-supplied.

Fix: a small new lookup, decoupled from `session_id` generation, doubling
as the atomic existence check needed below.

```sql
CREATE TABLE generate_requests (
    request_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE
);
```

`POST /api/generate` with client-generated `requestId`:

1. Generate `session_id = secrets.token_urlsafe(32)` (unchanged mechanism).
2. One transaction, same `INSERT ... ON CONFLICT ... RETURNING` idiom
   already proven in `TurnRepository.claim_or_take_over`
   (`repositories.py:211-237`):
   `INSERT INTO generate_requests (request_id, session_id) VALUES (:request_id, :session_id) ON CONFLICT (request_id) DO NOTHING RETURNING session_id`.
   - A row returns with **our** generated `session_id` → we won the race.
     Create the `Session` row with that id, `source_text`,
     `additional_details`, **`head_version_id = NULL`** (already nullable,
     `models.py:36`) in the same transaction, then claim a `turns` row
     keyed by `(session_id, requestId)` via the existing, unmodified
     `TurnRepository.claim_or_take_over()`. `request_hash` computed from
     the generate-specific payload via a new
     `compute_generate_request_hash()`, mirroring `compute_chat_request_hash`.
   - Nothing returns (conflict) → someone else already owns this
     `requestId` (this is a retry, possibly a genuinely concurrent one —
     this statement is exactly what closes the TOCTOU race, not a
     check-then-insert). Fresh `SELECT session_id FROM generate_requests
     WHERE request_id = :request_id` to find the real owner, then proceed
     straight to `turns.get_fresh(that_session_id, requestId)` — same
     replay/in-progress/conflict classification chat already has. Never a
     bare insert failure, never a 500 for this case.
3. Schedule the background task (see claim heartbeat and failure-state
   sections below — same mechanisms as chat, not reimplemented).
4. Return `202 {"status": "processing", "sessionId": session_id}`.

New `GET /api/generate/{sessionId}/turns/{requestId}` — same states as
chat's poll endpoint below.

Reusing `turns` for `/api/generate` closes both deferred task-08 items at
once: the async-job transport, and `/api/generate` idempotency (a retried
`requestId` now naturally replays instead of re-running the LLM) — that
was always going to be needed together, they were listed next to each
other in the same out-of-scope list for a reason.

`Turn.session_id` has `ForeignKey("sessions.id", ondelete="CASCADE")`, so
the `Session` row must exist before the `turns` claim — satisfied by the
ordering above.

### Failure is a completed claim, not a deleted one

The existing synchronous cleanup path (`delete_incomplete_owned`,
`repositories.py:278-294`, used today by chat on error/cancellation before
any result exists) is right for what it does — remove a claim that never
produced anything so a retry can claim cleanly. It is the wrong tool for
the **async** failure path: if a background task deletes the claim on
failure, `GET .../turns/{requestId}` finds no row at all, and the poll
table above can only say `404` — indistinguishable from "this id never
existed," with the actual failure reason gone.

Fix: on background-task failure (LLM error, validation failure, anything
past the point where a claim exists), call the existing `complete()`
(`repositories.py:251-276`) — not delete — with an error-shaped
`response_json`. `complete()` already accepts any `dict[str, object]`; no
schema change. "Done" and "failed" become the same state at the DB level —
`response_json IS NOT NULL` — distinguished only by an `ok` field.

**This changes the stored shape, and the existing synchronous replay path
was never designed for that — it must change too, not just the new poll
endpoint.** Today, `run_chat()`'s replay branch reads the row directly as
a bare result: `ChatResult.model_validate(current_turn.response_json)`
(`service.py:171,179-180`). If a *failed* claim can now be replayed too
(a `POST` retry hitting an already-failed `requestId`, which was always
possible and today would crash `model_validate` against whatever shape a
stored error takes), that line breaks. Fix by making the envelope
consistent for **both** outcomes, and giving both call sites — the
existing synchronous replay branch and the new poll endpoint — one shared
deserializer instead of each guessing the shape independently:

```
stored on success: {"ok": true,  "result": <ChatResult.model_dump()>}
stored on failure: {"ok": false, "error": <ApiError.model_dump()>}
```

One function, e.g. `resolve_turn_response(turn: Turn) -> ChatResult`
(raises the appropriate domain exception — the same one the live LLM path
would have raised — when `ok` is `false`), used by:
- `run_chat()`'s replay branch (`service.py:179-180`), replacing the
  direct `model_validate` call — a synchronous `POST` retry that lands on
  a completed *failure* now surfaces that failure the same way a live
  failure would, instead of crashing on schema mismatch.
- The new `GET .../turns/{requestId}`, which additionally needs the
  `processing`/not-found states this function doesn't have to handle.

Every existing/new call site that writes `response_json` via `complete()`
must be updated to wrap in this envelope — the success path included, not
only the new failure path. A completed failure is not retried
automatically or replayed as if it might change: the user retries by
letting the frontend generate a **new** `requestId`, the same way a manual
"try again" already implies a new request today. The old failed claim
stays around exactly as long as a completed success would (`turns`
retention/cleanup was already out of scope in task 08 and stays out of
scope here).

The genuinely-expired-with-no-`response_json` row in the poll table above
now means something narrower and rarer than before: the worker process
itself died (crashed, container killed) before it could either complete or
fail cleanly — not a normal LLM error, which now always produces a
completed (possibly failing) claim.

### Background task lifecycle

- **The background task cannot reuse the request's `AsyncSession`.**
  `ChatServiceDep` (`deps.py:51-62`) is built from `DbSessionDep`, which is
  `get_db()` (`deps.py:18-20`) — a request-scoped generator dependency that
  FastAPI tears down when the request's context exits, i.e. right after the
  handler returns `202`. `ChatService` already holds `self._db_sessionmaker`
  separately (today used only for the lease heartbeat's and cleanup's own
  short-lived sessions, `service.py:53-61,318,343`) — that sessionmaker,
  not `self._db`, is what the background task must use. The task needs its
  own top-level `AsyncSession` opened from `db_sessionmaker` for the entire
  claim-execution flow (context load, LLM call, persist), not just for
  heartbeat/cleanup as today. Concretely: `execute_claimed_turn()` becomes
  a free function (or takes a fresh `ChatService` instance) constructed
  with a new session from `db_sessionmaker` when the task starts, separate
  from whatever `ChatService` instance served the original HTTP request.
  The earlier claim in this document that background execution is
  "internally unchanged" was wrong on this specific point — the
  transaction/lease/persist *logic* is unchanged, but which DB session
  object it runs on is not.
- Do not fire-and-forget with a bare `asyncio.create_task()` and no kept
  reference — asyncio can garbage-collect an unreferenced task mid-flight.
  Register each task in `app.state.background_tasks: set[asyncio.Task]` on
  creation, discard via a done-callback on completion.
- Every background task wraps its body in its own top-level
  `try/except`+`finally` and logs failures itself — nothing awaits it
  directly, so an uncaught exception would otherwise only produce asyncio's
  "Task exception was never retrieved" warning and silently strand the
  claim/lease until TTL expiry. Cleanup (lease release, claim cleanup) must
  run in that `finally` exactly as it does today in the synchronous path.
- App shutdown (`lifespan`, `main.py:20-31`) should attempt to cancel and
  await any tasks still in `app.state.background_tasks` before disposing
  the DB engine. Not strictly required for correctness — the DB-persisted
  claim/lease TTLs already make an abandoned task recoverable on the next
  claim attempt — but avoids unnecessary reported failures on a clean
  redeploy.

### Frontend

- `/api/generate` and `/api/chat` calls change from "await one fetch, get
  the final result" to "POST → read `{status, sessionId, requestId}` →
  poll `GET .../turns/{requestId}` on an interval until `done`/`failed`".
- Replace the single spinner tied to one pending fetch with a "generating"
  state driven by poll status. Real incremental progress (e.g. token
  counts) is a future upgrade, not this ticket — polling only reports
  coarse status for now.
- Because `sessionId`/`requestId` are known immediately, a page
  reload mid-generation can resume polling — fits the existing
  session-restore logic in `frontend/src/state/session.ts` rather than
  fighting it.

## LLM client behavior (inside the background worker)

Unchanged in substance from the earlier draft, relocated: this no longer
protects a browser connection, only the worker's own call to the LLM.

`VLLMClient._post()`: `stream: true`, SSE consumption, reconstructs the
same `{"content", "reasoning_content", "usage"}` shape so `complete_text()`
/ `complete_json()` need no changes. Tolerant field parsing: accept
`reasoning` or `reasoning_content`, whichever the response actually
contains (real gateway sends `reasoning`; `client.py:197` currently reads
only `reasoning_content`, so this field is silently always empty today —
found independently of the timeout work, fixed here because it's the same
response-shape handling in the same file).

Three-phase model per attempt:

```
before starting this attempt (initial call / retry / fallback / repair):
  deadline.require_remaining() — no budget left → do not start, LLMError("TIMEOUT")

send request
  → wait up to TTFT budget for the first SSE chunk
      no chunk in time  → LLMError("TIMEOUT") [logged as TTFT]
  → for each subsequent chunk, wait up to stall budget
      no chunk in time  → LLMError("TIMEOUT") [logged as STALL]
  → [DONE] → return reconstructed result
     (no additional wall-clock cutoff here — a healthy attempt runs to
     completion regardless of total elapsed time)
```

`LLMDeadline` keeps its task-07 job — bounding the total budget across
every attempt of one logical operation (retry/fallback/repair) — checked
only before a *new* attempt starts, never wrapping the read of one already
confirmed alive. `asyncio.timeout(remaining)` currently wraps the whole
`_post()` including the read (`client.py:157-165`); that wrapper is removed
for the read phase specifically.

### Every `require_remaining()` call site needs reclassifying, not just the wrapper

There are 18 existing calls, not one. Removing the `asyncio.timeout` wrapper
around the read is not sufficient — most of these calls are terminal
post-success checks that would still discard an otherwise-complete result
the moment elapsed time crosses `LLM_DEADLINE_MS`, regardless of streaming:

```
client.py:  148 (gate: sizes this attempt's httpx.Timeout — keep)
            175 (post-response, pre-status-check — terminal, REMOVE)
            200 (end of _post(), pre-return — terminal, REMOVE)
            211 (end of complete_text(), pre-return — terminal, REMOVE)
            244 (end of complete_json(), pre-return — terminal, REMOVE)
retry.py:    53 (top of attempt loop — gates next attempt, keep)
             57 (right after a *successful* fn() — terminal, REMOVE:
                 this is the one that would silently eat a good result
                 from a long-but-healthy attempt)
             61 (in except, before no-retry-code check — redundant with
                 53/73, REMOVE)
             73 (caps backoff sleep duration — keep, doesn't discard a result)
             77 (after sleep, before next loop iteration — redundant with
                 53, safe to remove for clarity, not required)
             94 (top of fallback-chain loop — gates next attempt, keep)
            108 (except branch, before trying next response_format — gates
                 next attempt, keep)
service.py: 158 (sizes the initial turns claim TTL — keep, see claim
                 heartbeat below for what covers time *after* this)
chat.py:    108 (post-fallback-success, before deciding whether repair is
                 needed — gates a possible next attempt, keep)
            115 (same, after validate_mermaid — gates repair, keep)
            122 (post-repair-success, pre-revalidate — terminal, REMOVE)
            124 (post-revalidate-success — terminal, REMOVE)
            146 (final return — terminal, REMOVE)
```

Rule of thumb for implementation: a `require_remaining()` call is correct
only when a **new** LLM attempt (fresh `_post()`, retry iteration, fallback
mode, repair call) might follow it. Any call sitting after a step has
already produced its final, successful value with nothing further planned
must go — otherwise the regression test can pass at the `_post()`/client
level while the operation as a whole still raises `TIMEOUT` on a
perfectly good result, exactly reproducing tonight's failure one layer up.

TTFT/stall failures reuse the existing `LLMError("TIMEOUT", ...)` code
(keeps `retry.py`'s `NO_RETRY_CODES` untouched; differentiate via log
message only) — task 03 already made `TIMEOUT` non-retryable regardless of
cause.

Structural logging at phase boundaries (attempt start, TTFT reached,
periodic chunk-count checkpoint, attempt end) needs to actually reach
`docker logs`: `logging.basicConfig()` is never called anywhere in
`backend-py` today, so any `logger.info(...)` is silently dropped by
Python's `lastResort` handler (`WARNING`+ only). Fixed as part of this work.

Proposed budgets (now genuinely internal-only, not fronting a browser wait,
so these can be picked purely for "how long is a real generation worth
waiting on before giving up" — no coupling to nginx/gateway/browser
timeouts anymore, since no single outer request spans the whole duration):

| Budget | Proposed default | Basis |
|---|---|---|
| `LLM_TTFT_MS` | 30,000 | Observed first chunk at 0.1–3.9s in testing; margin for cold connections |
| `LLM_STALL_MS` | 60,000 | Observed worst inter-chunk gap ~20s in testing; margin above that |
| `LLM_DEADLINE_MS` | 900,000 (15 min) | Total multi-attempt budget for one logical operation |

## What this removes from the earlier draft

- The nginx/gateway alignment gate is no longer required for correctness.
  Individual requests (the initial `POST`, each poll `GET`) are all
  short-lived by construction — the default 300s in `frontend/nginx.conf`
  is already generous for either. This was the "honest remaining gap" the
  previous version of this document couldn't close; async delivery closes
  it structurally instead of by raising numbers.
- No product decision about "how long may a user's browser tab wait" is
  forced by this change — polling can run indefinitely without holding any
  single connection open, so there's no analogous cutoff to argue about.

## Out of scope

- SSE/WebSocket push instead of polling — pure UX upgrade (lower latency
  between "done" and the UI noticing), not required for correctness. Poll
  interval is good enough for a first version.
- Exposing incremental progress (partial Mermaid, token counts) through the
  poll endpoint — the streaming groundwork inside the worker makes this
  possible later, not included now.
- `reasoning_effort`/`variant_id`-equivalent gateway parameter to bound
  reasoning length — still pending an answer from whoever operates
  `proxy-ai.sogaz.ru`.
- Choosing between `DeepSeek-V4-Flash` and `Gemma` for production — product
  decision, not this ticket.
- Retention/cleanup of old completed `turns` rows — already explicitly
  deferred in task 08, unaffected by this change.
- Process-wide concurrency semaphore and circuit breaker
  (`DESIGN-RATIONALE.md` section 07) — process-local semantics need a
  separate decision on N-worker behavior first.

## Test plan

`backend-py/tests/`:

- **LLM client** (extends `test_client.py`, fake clock, mirrors the earlier
  draft's plan): TTFT trip, stall trip, a mock stream running past the old
  120s/300s defaults that still completes successfully (regression test
  for tonight's literal incident), tolerant `reasoning`/`reasoning_content`
  parsing, `complete_json()`'s reasoning-fallback actually firing.
- **Chat async split**: claim → background execution → poll transitions
  through processing → done; replay path still returns synchronously from
  `POST`.
- **Claim heartbeat** (regression test for the incident reproduced tonight,
  one level up from the LLM-client one): a fake-clock-driven attempt that
  runs longer than the *original* claim TTL (`LLM_DEADLINE_MS + 30s`) but
  keeps extending via `heartbeat_claim()` throughout — completes
  successfully, `complete()` does not return `rowcount == 0`. A second test
  without the heartbeat running proves the failure mode this fixes (claim
  expires, completion silently fails) — documents the bug, not just the fix.
- **Failure is completed, not deleted**: a background task that fails after
  acquiring a claim leaves a row with `response_json = {"ok": false, ...}`,
  not a deleted row. Polling it returns the error envelope, not `404`. A
  fresh `requestId` after a failure claims cleanly (doesn't collide with
  the old failed claim).
- **Shared turn-response deserializer**: `resolve_turn_response()` used
  identically by the synchronous `POST` replay branch and the `GET` poll
  endpoint. Regression test: a synchronous `POST` retry that lands on an
  already-*failed* completed claim surfaces that failure through the
  normal `POST` error response, instead of crashing on `ChatResult.model_validate`
  against a shape it was never written for (today's literal behavior if
  this deserializer isn't introduced).
- **Generate request-id race**: two concurrent `POST /api/generate` calls
  with the same client-generated `requestId` — exactly one creates
  `generate_requests`/`Session`/`turns` rows; the other's `INSERT ...
  ON CONFLICT DO NOTHING` returns nothing, its fresh `SELECT` finds the
  winner's `session_id`, and it proceeds to the normal claim/replay
  classification. Neither path raises an unhandled exception or produces a
  duplicate session.
- **`require_remaining()` reclassification**: for each call site marked
  REMOVE above, a test where the deadline has already elapsed by the time
  that point in the code is reached, and the already-obtained successful
  result is still returned rather than replaced by `LLMError("TIMEOUT")`.
  At minimum: `retry.py:57` (successful `fn()` past deadline still returns),
  `client.py:200/211/244` (successful `_post`/`complete_text`/`complete_json`
  past deadline still returns).
- **Generate claim + idempotency**: `POST /api/generate` with a
  client-supplied `requestId` creates a `generate_requests` row, a
  server-generated-id `Session` (`head_version_id IS NULL`), and a `turns`
  claim before any LLM call. Retrying the identical `POST` (same
  `requestId`, same payload) finds the existing `session_id` via
  `generate_requests` — before completion, gets `request-in-progress`;
  after completion, replays without a second LLM call or a second session.
  Retrying with a *different* payload under the same `requestId` gets
  `request-id-conflict` (mirrors chat's existing behavior, now exercised
  for generate too).
- **Background DB session isolation**: the background task's `AsyncSession`
  (opened from `db_sessionmaker`) is a different object from the one the
  original HTTP request used, and stays usable after the request's own
  session has been torn down.
- **Background task registry**: a task that raises is still logged and
  removed from `app.state.background_tasks`; shutdown awaits/cancels
  outstanding tasks without hanging.

## Rollout

1. Land `/api/chat` split (claim/replay stays sync, execution moves to
   background) + poll endpoint. Lower risk — reuses tested machinery.
2. Land `/api/generate` claim + background execution + poll endpoint.
3. Land the LLM client TTFT/stall/streaming/reasoning-field work inside the
   worker (independent of 1-2 in principle, but only pays off once nothing
   is awaiting it synchronously from a browser-facing request).
4. Frontend: switch both flows from await-one-fetch to poll.
5. Re-run the smoke test in `docs/deployment-smoke-results.md` — this time
   without needing to touch `frontend/nginx.conf` or chase the external
   gateway's timeout at all.
