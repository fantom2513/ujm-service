# Chat attachments in the Python backend

Date: 2026-09-09
Last updated: 2026-09-16
Status: implemented; pending deployment configuration and live smoke test

## Context

The frontend lets a user attach a file to a message after a diagram has already
been generated. It sends the first attachment as the `file` field of the
`multipart/form-data` request to `POST /api/chat`.

The legacy TypeScript backend reads this field, validates and parses the file,
and includes the extracted text in the LLM edit request. At the time of the
original specification, the Python endpoint read text fields only, so an upload
appeared successful in the UI while the model received no attachment context.

This gap was accepted for the initial merge and was implemented on 2026-09-16.
The decisions and release gates below are now the source of truth for this
feature.

## Decisions recorded on 2026-09-16

- Chat accepts `txt`, `docx`, `pdf`, `xlsx`, and `csv` files. These are a
  chat-specific format set; it intentionally differs from initial diagram
  generation, which accepts only `txt`, `docx`, and `pdf`.
- Legacy binary `.xls` is rejected as an unsupported format. `openpyxl` cannot
  extract OLE2/BIFF `.xls` data, so accepting it with a placeholder would
  silently lose the user's context.
- The chat attachment limit is 20 MiB (`MAX_CHAT_ATTACHMENT_MB=20`). The
  frontend and Python application enforce the same limit.
- Parser failures must not log raw tracebacks, exception messages, or file
  contents. Logs retain the parser name, buffer size, and exception class so
  operations can identify the failure without exposing user data.

## Required behaviour

1. `POST /api/chat` accepts the optional multipart field `file` without changing
   the existing response contract.
2. The backend accepts only the chat format set recorded above and applies the
   20 MiB chat size limit. Format and extraction helpers are shared rather than
   copied; the initial-generation format set remains independent.
3. A valid attachment is parsed through the existing Python file parsers.
4. Extracted text is passed to `ChatEditOptions.attachment_context` and included
   in the LLM prompt for the current turn.
5. A request without an attachment keeps its current behaviour.
6. Invalid, unsupported, empty, or unreadable files return the established API
   error envelope with an appropriate 4xx status. Raw parser errors and file
   contents must not be exposed to the client or logs.
7. The idempotency fingerprint must account for the attachment. Reusing one
   `requestId` with different file content must be treated as a different
   request or rejected as an idempotency conflict; it must not replay a result
   produced for another file.
8. Temporary buffers and extracted content must not be persisted beyond the
   data explicitly required by the existing chat/session model.

## Acceptance criteria

- An API test proves that a multipart chat request with a file reaches the chat
  service with non-empty `attachment_context`.
- A service or prompt test proves that the extracted context is included in the
  LLM request.
- Tests cover unsupported format, oversized file, parser failure, no-file
  compatibility, and idempotency with different attachment contents.
- Existing `/api/chat` concurrency, deadline, versioning, identity, and
  idempotency tests remain green.
- A manual check confirms that, after generating a diagram, a user can attach a
  second file in chat and ask a question whose answer depends only on that file.

## Implementation status

- Implemented: `POST /api/chat` reads the optional multipart `file`, validates
  it, extracts its text, and passes it to `ChatEditOptions.attachment_context`.
- Implemented: invalid format, file larger than 20 MiB, empty/unreadable
  content, and parser failures return the established 4xx API error envelope.
- Implemented: attachment context participates in the idempotency fingerprint;
  reusing one `requestId` with different attachment content returns a conflict.
- Implemented: unit, API, and Postgres-backed idempotency tests cover these
  paths.

## Release checklist — 2026-09-16

### Completed in the working tree

- Frontend chat responses are bound to the requested session, so a late answer
  cannot overwrite a diagram created after the request started.
- A reset preserves the `productHomeUrl` fetched from `/api/config`; it no
  longer falls back to localhost merely because the user selected "new diagram"
  or "go home".
- Frontend attachment validation uses the same chat format set and 20 MiB limit
  as the Python backend.
- Frontend tests pass (23 tests) and the production frontend build succeeds.
- Python unit, API, and Postgres-backed integration tests pass (293 tests).
  Verified on 2026-09-16 against a local Postgres container: 293 passed, 0
  skipped. Without a reachable Postgres the 69 integration tests skip, so a run
  reporting "224 passed, 69 skipped" has not exercised the attachment
  idempotency guarantees.

### Required before production deployment

1. Add an exact Nginx route for `/ux-architecture/api/chat` with
   `client_max_body_size 20m`. The current shared `/ux-architecture/api/`
   route permits 110 MiB for recordings and diagram generation, so application
   validation alone does not protect the proxy from oversized chat bodies.
2. Set `PRODUCT_HOME_URL` in the production environment to the confirmed CX
   Copilot home URL. The client now preserves the API-provided value across a
   reset, but the checked-in fallback remains `http://localhost:3000/` for
   local development.
3. On a test environment with a live LLM, build a diagram, attach a `txt`,
   `csv`, or `xlsx` file in chat, and verify that an answer relying only on the
   attachment uses its contents. Also verify `.xls` and a file over 20 MiB
   return an error.
4. Commit only the intended production changes and their tests. Do not include
   unrelated working-tree files merely because they are present locally.

### Production release criterion

Production deployment is approved only after items 1–3 above pass on the test
environment and the release commit contains the intended code, tests, and this
specification only.

## Out of scope

- Multiple attachments in one chat turn. The current frontend sends only the
  first selected file.
- Changes to initial source upload through `POST /api/generate`.
- Long-term storage or download history for chat attachments.
