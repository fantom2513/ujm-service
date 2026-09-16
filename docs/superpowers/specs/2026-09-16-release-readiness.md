# Release readiness — 2026-09-16

Status: release preparation; production deployment is not approved yet.

## Scope

This document records the release decisions and verification status for:

- frontend stability fixes in the chat and navigation flows;
- Python backend support for chat file attachments;
- deployment configuration and live validation required before production.

The historical chat-attachment technical-debt specification
(`2026-09-09-chat-attachments-tech-debt.md`) remains the original task record;
it carries an implementation-status section describing how that task closed.
This document is the current release source of truth.

## Completed changes

### Frontend stability

- A late chat response is tied to the session that created the request. If a
  user starts a new diagram while an older chat request is pending, the old
  response cannot overwrite the new diagram.
- Resetting the application preserves `productHomeUrl` received from
  `/api/config`. The "go home" action no longer loses the configured URL and
  reverts to the localhost fallback during the same browser session.
- Chat attachment validation is isolated in a tested module and matches the
  Python chat format set and 20 MiB file limit.
- A restored chat attachment no longer survives a page reload as a phantom card
  with no file behind it. `chatAttachment`/`chatAttachments` are cleared on load
  for the same reason `start.file`/`start.recording` already were: the `File`
  they describe cannot survive `sessionStorage`, and `sendChat()` reads from a
  module-level array that is always empty after a reload.
- Starting a new diagram clears a stale chat-composer validation error instead
  of carrying it into the next diagram's chat panel.

### Python chat attachments

- `POST /api/chat` accepts the optional multipart field `file`.
- Supported formats are `txt`, `docx`, `pdf`, `xlsx`, and `csv`.
- Legacy binary `.xls` is rejected. It is not silently accepted with a stub
  because the current parser stack cannot extract its OLE2/BIFF content.
- A valid attachment is parsed and passed as `attachment_context` to the LLM
  prompt for that chat turn.
- Invalid format, a file over 20 MiB, empty/unreadable content, and parser
  failures return the established 4xx API error envelope.
- The chat idempotency fingerprint includes attachment context. Reusing a
  request ID with different attachment content returns a conflict; identical
  content replays safely.
- Parser logs retain the parser name, buffer size, and exception class, but do
  not include a traceback, exception message, or user file content.

### Deployment boundary

- `frontend/nginx.conf` now has an exact-match `location =
  /ux-architecture/api/chat` with `client_max_body_size 21m`, so an oversized
  chat body is rejected at the proxy instead of only by the application. The
  general `/ux-architecture/api/` location keeps its 110m limit for 100 MB
  recordings on `/api/generate`. The limit is 21m rather than 20m because it
  applies to the whole multipart body — `mermaidCode`, `message`, `actionType`,
  `requestId` and `sessionId` travel with the file, and a file of exactly
  20 MiB is legal on both the frontend and in Python.

## Verification completed

- Frontend: 24 automated tests pass (23 before this release, plus one covering
  the restored-chat-attachment fix below) and the production frontend build
  succeeds. Note that `npm test` reports 97 because it also runs the 73 legacy
  `backend/tests` TypeScript tests; 24 is the frontend-only figure.
- Python backend: 293 passed, 0 skipped, verified on 2026-09-16 against a local
  Postgres container — this is the first run in which the Postgres-backed chat
  idempotency tests actually executed rather than skipping. Without a reachable
  database they skip silently and the run reports "224 passed, 69 skipped";
  treat such a run as *not* having verified attachment idempotency.
- The chat proxy limit was verified empirically against nginx 1.27: a 20.99 MiB
  body passes `/api/chat`, 21.93 MiB returns 413, and the same oversized body
  still passes `/api/generate` under its 110m limit.
- An automated browser check against a local instance confirmed that an invalid
  initial upload is not shown twice, the error-toast close button works, and a
  page reload clears the initial-upload state. This was not a human QA session
  and was not run against the test environment; nothing is recorded for it in
  `docs/deployment-smoke-results.md`. Repeat these checks on the test
  environment as part of the smoke test below before treating them as release
  evidence.

## Required before production deployment

1. Set `PRODUCT_HOME_URL` in `ENV_TEST` and `ENV_PROD` to the confirmed CX
   Copilot home URL.

   The checked-in fallback, `http://localhost:3000/`, is suitable only for
   local development. The frontend fix preserves an API-provided URL; it cannot
   supply a production URL that was never configured.

2. Run a smoke test on the test environment with a live LLM:

   - create a diagram;
   - attach a `txt`, `csv`, or `xlsx` file in chat;
   - ask a question answerable only from that file and confirm the answer uses
     its content;
   - verify `.xls` and a file over 20 MiB return a user-visible error;
   - confirm a file of exactly 20 MiB is still accepted — the proxy limit is
     21m precisely so this case is not rejected at the edge;
   - start a chat request, create a new diagram before it completes, and verify
     the old answer does not modify the new diagram;
   - trigger a chat attachment validation error (attach the same file twice, or
     an `.xls`), then start a new diagram and confirm the stale error is gone
     from the new diagram's composer;
   - attach a file in chat, reload the page, and confirm the attachment card is
     gone rather than shown as still attached;
   - reload after an initial-upload error and confirm it is not shown twice;
   - trigger the generation-error toast and confirm its close button clears it;
   - use "go home" and confirm it navigates to the configured CX Copilot URL.

   Record the outcome in `docs/deployment-smoke-results.md`.

3. Verify the deployed configuration.

   After deploying, `curl -s https://<host>/ux-architecture/api/config` and
   confirm the returned `productHomeUrl` is the real CX Copilot URL rather than
   `http://localhost:3000/`.

## Known non-blocking follow-ups

- The frontend sends only the first file when the user selects multiple chat
  attachments.
- The initial-source generation endpoint retains its independent 100 MiB
  recording limit and is outside the 20 MiB chat-attachment scope.
- A live LLM smoke test is still required because automated tests prove data
  flow and error handling, not the model's interpretation of attachment text.

## Release approval criterion

Production deployment is approved after all three required steps above are
complete and their results are recorded in the deployment smoke results.
