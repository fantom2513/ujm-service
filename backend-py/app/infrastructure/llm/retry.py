from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.infrastructure.llm.deadline import LLMDeadline
from app.infrastructure.llm.errors import LLMError

# Errors that won't change on retry — the model/client produced a bad
# payload, not a transient failure.
#
# TIMEOUT is deliberately included too, despite being "transient" in the usual
# sense: vLLM serves a shared generation queue, so a request that didn't get an
# answer within the read timeout almost always means the queue is backed up,
# not a one-off blip. Retrying resubmits a brand-new generation request into
# that same overloaded queue, adding load instead of relieving it. NETWORK_ERROR
# (refused/reset connections, i.e. failures before generation ever started) is
# not in this set — those are cheap to retry and don't touch the queue.
NO_RETRY_CODES = {
    "SCHEMA_MISMATCH",
    "STRUCTURED_OUTPUT_UNSUPPORTED",
    "INVALID_JSON",
    "EMPTY_RESPONSE",
    "TIMEOUT",
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
    error_type: type[Exception] = LLMError,
    no_retry_codes: set[str] = NO_RETRY_CODES,
    deadline: LLMDeadline | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
):
    # Generic over `error_type` so non-LLM callers (e.g. JiraClient) can
    # reuse the same retry/backoff loop with their own error class and
    # non-retryable code set, instead of duplicating this loop per client.
    last_err: Exception | None = None
    for attempt in range(max_attempts):
        if deadline is not None:
            deadline.require_remaining()
        try:
            result = await fn()
            if deadline is not None:
                deadline.require_remaining()
            return result
        except error_type as err:
            if deadline is not None:
                deadline.require_remaining()
            if err.code in no_retry_codes:
                raise
            last_err = err
            if attempt < max_attempts - 1:
                delay_seconds = min(
                    base_delay_ms * (2**attempt),
                    max_delay_ms,
                ) / 1000
                if deadline is not None:
                    delay_seconds = min(
                        delay_seconds,
                        deadline.require_remaining(),
                    )
                await sleep(delay_seconds)
                if deadline is not None:
                    deadline.require_remaining()
    assert last_err is not None
    raise last_err


async def complete_json_with_fallback(
    make_client: Callable[[str, LLMDeadline], object],
    start_mode: str,
    call: Callable[[object], Awaitable],
    deadline: LLMDeadline,
    max_attempts_first: int = 3,
    max_attempts_rest: int = 2,
):
    start_index = max(0, FALLBACK_CHAIN.index(start_mode)) if start_mode in FALLBACK_CHAIN else 0
    last_err: LLMError | None = None

    for i in range(start_index, len(FALLBACK_CHAIN)):
        deadline.require_remaining()
        mode = FALLBACK_CHAIN[i]
        client = make_client(mode, deadline)

        async def attempt(c: object = client) -> object:
            return await call(c)

        try:
            return await execute_with_retry(
                attempt,
                max_attempts_first if i == start_index else max_attempts_rest,
                deadline=deadline,
            )
        except LLMError as err:
            deadline.require_remaining()
            last_err = err
            if err.code in FALLBACK_CODES and i < len(FALLBACK_CHAIN) - 1:
                continue
            raise
    raise last_err or LLMError("SCHEMA_MISMATCH", "All response_format modes exhausted")
