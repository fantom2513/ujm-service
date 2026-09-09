# Chat attachments in the Python backend

Date: 2026-09-09  
Status: technical debt accepted for the Python backend cutover

## Context

The frontend lets a user attach a file to a message after a diagram has already
been generated. It sends the first attachment as the `file` field of the
`multipart/form-data` request to `POST /api/chat`.

The legacy TypeScript backend reads this field, validates and parses the file,
and includes the extracted text in the LLM edit request. The Python endpoint
currently reads the text fields only. The upload therefore appears successful
in the UI, but the model does not receive the attachment contents.

This gap is accepted for the initial merge and must be addressed as technical
debt before chat attachments are considered supported by the Python backend.

## Required behaviour

1. `POST /api/chat` accepts the optional multipart field `file` without changing
   the existing response contract.
2. The backend applies the same supported-format and file-size rules as the
   generation endpoint. Validation logic should be shared rather than copied.
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

## Out of scope

- Multiple attachments in one chat turn. The current frontend sends only the
  first selected file.
- Changes to initial source upload through `POST /api/generate`.
- Long-term storage or download history for chat attachments.
