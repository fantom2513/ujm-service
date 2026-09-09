import asyncio
import json
import socket
import time

import httpx
import pytest

from app.infrastructure.llm.client import (
    VLLMClient,
    extract_json,
    extract_mermaid,
    inline_refs,
    strip_think_tags,
)
from app.infrastructure.llm.deadline import LLMDeadline
from app.infrastructure.llm.errors import LLMError
from app.infrastructure.llm.retry import execute_with_retry


def test_inline_refs_no_refs_passthrough_drops_defs():
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    assert inline_refs(schema, {}) == schema


def test_inline_refs_inlines_ref():
    defs = {"Foo": {"type": "string"}}
    schema = {"type": "object", "$defs": defs, "properties": {"x": {"$ref": "#/$defs/Foo"}}}
    result = inline_refs(schema, defs)
    assert result["properties"]["x"] == defs["Foo"]
    assert "$defs" not in result


def test_inline_refs_nested_ref_in_array():
    defs = {"Tag": {"type": "string"}}
    schema = {"type": "object", "properties": {"tags": {"type": "array", "items": {"$ref": "#/$defs/Tag"}}}}
    result = inline_refs(schema, defs)
    assert result["properties"]["tags"]["items"] == {"type": "string"}


def test_strip_think_tags_removes_block():
    assert strip_think_tags("<think>let me reason</think>\nflowchart LR\nA --> B") == "flowchart LR\nA --> B"


def test_strip_think_tags_no_tags_unchanged():
    assert strip_think_tags("flowchart LR\nA --> B") == "flowchart LR\nA --> B"


def test_extract_mermaid_finds_flowchart_lr_in_fences():
    result = extract_mermaid("Sure!\n```mermaid\nflowchart LR\nA --> B\n```")
    assert result.startswith("flowchart LR")


def test_extract_mermaid_finds_flowchart_tb_without_fences():
    result = extract_mermaid("Here you go:\nflowchart TB\nA --> B")
    assert result.startswith("flowchart TB")


def test_extract_mermaid_raises_empty_response_when_missing():
    try:
        extract_mermaid("no diagram here")
        assert False, "expected LLMError"
    except LLMError as err:
        assert err.code == "EMPTY_RESPONSE"


def test_extract_json_parses_clean_json():
    result = extract_json('{"mermaid":"flowchart LR\\nA-->B","message":"done"}')
    assert result["mermaid"] == "flowchart LR\nA-->B"
    assert result["message"] == "done"


def test_extract_json_skips_leading_text():
    result = extract_json('Sure: {"mermaid":"x","message":"y"}')
    assert result["mermaid"] == "x"


def test_extract_json_handles_trailing_text():
    result = extract_json('{"a":"b"} extra text here')
    assert result["a"] == "b"


def test_extract_json_raises_invalid_json_when_missing():
    try:
        extract_json("no json here")
        assert False, "expected LLMError"
    except LLMError as err:
        assert err.code == "INVALID_JSON"


def _llm_response(content: str, reasoning_content: str | None = None) -> dict:
    message = {"content": content}
    if reasoning_content is not None:
        message["reasoning_content"] = reasoning_content
    return {"choices": [{"message": message}]}


def _deadline(timeout_ms: int = 120_000) -> LLMDeadline:
    return LLMDeadline.from_timeout_ms(timeout_ms)


async def test_complete_text_returns_mermaid_from_response(mock_llm_server):
    url = mock_llm_server(_llm_response("flowchart LR\nA --> B"))
    client = VLLMClient(
        url=url,
        model="test",
        deadline=_deadline(),
        response_format_mode="none",
    )
    result = await client.complete_text("make a diagram")
    assert result.startswith("flowchart LR")


async def test_complete_text_strips_think_tags(mock_llm_server):
    url = mock_llm_server(_llm_response("<think>reasoning</think>\nflowchart TB\nA --> B"))
    client = VLLMClient(
        url=url,
        model="test",
        deadline=_deadline(),
        response_format_mode="none",
    )
    result = await client.complete_text("make a diagram")
    assert result.startswith("flowchart TB")
    assert "<think>" not in result


async def test_complete_text_raises_timeout_when_server_too_slow(mock_llm_server):
    url = mock_llm_server({}, delay_forever=True)
    client = VLLMClient(
        url=url,
        model="test",
        deadline=_deadline(50),
        response_format_mode="none",
    )
    with pytest.raises(LLMError) as exc_info:
        await client.complete_text("test")
    assert exc_info.value.code == "TIMEOUT"


async def test_http_phase_timeouts_are_capped_by_remaining_deadline(monkeypatch):
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return _llm_response("flowchart LR\nA --> B")

    class FakeAsyncClient:
        def __init__(self, *, verify, timeout):
            captured["verify"] = verify
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(
        "app.infrastructure.llm.client.httpx.AsyncClient",
        FakeAsyncClient,
    )
    deadline = LLMDeadline.from_timeout_ms(2_000, clock=lambda: 10.0)
    client = VLLMClient(
        url="http://llm.invalid",
        model="test",
        deadline=deadline,
        connect_timeout_ms=5_000,
        pool_timeout_ms=500,
        response_format_mode="none",
    )

    result = await client.complete_text("test")

    assert result == "flowchart LR\nA --> B"
    timeout = captured["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == pytest.approx(2.0)
    assert timeout.read == pytest.approx(2.0)
    assert timeout.write == pytest.approx(2.0)
    assert timeout.pool == pytest.approx(0.5)


async def test_expired_deadline_does_not_start_http(monkeypatch):
    def fail_if_constructed(*_args, **_kwargs):
        raise AssertionError("HTTP client must not be created after expiry")

    monkeypatch.setattr(
        "app.infrastructure.llm.client.httpx.AsyncClient",
        fail_if_constructed,
    )
    client = VLLMClient(
        url="http://llm.invalid",
        model="test",
        deadline=_deadline(0),
        response_format_mode="none",
    )

    with pytest.raises(LLMError) as exc_info:
        await client.complete_text("test")

    assert exc_info.value.code == "TIMEOUT"


async def test_deadline_expiry_during_response_parsing_stays_timeout(monkeypatch):
    now = [0.0]

    class ExpiringResponse:
        status_code = 200

        def json(self):
            now[0] = 1.0
            return _llm_response("flowchart LR\nA --> B")

    class FakeAsyncClient:
        def __init__(self, *, verify, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, *_args, **_kwargs):
            return ExpiringResponse()

    monkeypatch.setattr(
        "app.infrastructure.llm.client.httpx.AsyncClient",
        FakeAsyncClient,
    )
    deadline = LLMDeadline.from_timeout_ms(1_000, clock=lambda: now[0])
    client = VLLMClient(
        url="http://llm.invalid",
        model="test",
        deadline=deadline,
        response_format_mode="none",
    )

    with pytest.raises(LLMError) as exc_info:
        await client.complete_text("test")

    assert exc_info.value.code == "TIMEOUT"


async def test_external_cancellation_is_not_converted_to_timeout(monkeypatch):
    entered_post = asyncio.Event()
    hold_post = asyncio.Event()

    class BlockingAsyncClient:
        def __init__(self, *, verify, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, *_args, **_kwargs):
            entered_post.set()
            await hold_post.wait()
            raise AssertionError("cancelled HTTP request must not resume")

    monkeypatch.setattr(
        "app.infrastructure.llm.client.httpx.AsyncClient",
        BlockingAsyncClient,
    )
    client = VLLMClient(
        url="http://llm.invalid",
        model="test",
        deadline=_deadline(30_000),
        response_format_mode="none",
    )

    task = asyncio.create_task(client.complete_text("test"))
    await entered_post.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


async def test_complete_text_raises_network_error_fast_when_port_is_closed():
    # Nothing listens on this port, so the OS rejects the connection
    # (ECONNREFUSED) well before the deadline elapses — this is what the short
    # connect timeout is for, distinct from a slow-to-respond server. The
    # OS-level rejection itself isn't instant on every platform (Windows adds
    # a ~2s floor even for a local refused connection), so we assert against a
    # generous fraction of the deadline rather than an absolute constant.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    url = f"http://127.0.0.1:{port}"
    deadline_ms = 30_000
    client = VLLMClient(
        url=url,
        model="test",
        deadline=_deadline(deadline_ms),
        response_format_mode="none",
    )

    start = time.monotonic()
    with pytest.raises(LLMError) as exc_info:
        await client.complete_text("test")
    elapsed = time.monotonic() - start

    assert exc_info.value.code == "NETWORK_ERROR"
    assert elapsed < (deadline_ms / 1000) / 2, (
        f"expected a fast connection-refused failure, took {elapsed}s"
    )


async def test_execute_with_retry_does_not_retry_timeout_end_to_end(mock_llm_server):
    url = mock_llm_server({}, delay_forever=True)
    client = VLLMClient(
        url=url,
        model="test",
        deadline=_deadline(50),
        response_format_mode="none",
    )
    attempts = 0

    async def attempt():
        nonlocal attempts
        attempts += 1
        return await client.complete_text("test")

    with pytest.raises(LLMError) as exc_info:
        await execute_with_retry(
            attempt,
            max_attempts=3,
            base_delay_ms=0,
            max_delay_ms=0,
        )

    assert exc_info.value.code == "TIMEOUT"
    assert attempts == 1


async def test_execute_with_retry_retries_network_error_end_to_end(mock_llm_server):
    call_counter = [0]
    url = mock_llm_server({}, reset_connection=True, call_counter=call_counter)
    client = VLLMClient(
        url=url,
        model="test",
        deadline=_deadline(5_000),
        response_format_mode="none",
    )

    with pytest.raises(LLMError) as exc_info:
        await execute_with_retry(
            lambda: client.complete_text("test"), max_attempts=3, base_delay_ms=0, max_delay_ms=0
        )

    assert exc_info.value.code == "NETWORK_ERROR"
    assert call_counter[0] == 3


async def test_complete_json_parses_with_json_schema_mode(mock_llm_server):
    payload = {"mermaid": "flowchart LR\nA --> B", "message": "done"}
    url = mock_llm_server(_llm_response(json.dumps(payload)))
    client = VLLMClient(
        url=url,
        model="test",
        deadline=_deadline(),
        response_format_mode="json_schema",
    )
    schema = {
        "type": "object",
        "properties": {"mermaid": {"type": "string"}, "message": {"type": "string"}},
        "required": ["mermaid", "message"],
    }
    result = await client.complete_json("edit diagram", schema, "ChatOutput")
    assert result["mermaid"] == payload["mermaid"]
    assert result["message"] == payload["message"]


async def test_complete_json_raises_structured_output_unsupported_on_422(mock_llm_server):
    url = mock_llm_server({"error": "unsupported"}, status_code=422)
    client = VLLMClient(
        url=url,
        model="test",
        deadline=_deadline(),
        response_format_mode="json_schema",
    )
    with pytest.raises(LLMError) as exc_info:
        await client.complete_json("x", {}, "X")
    assert exc_info.value.code == "STRUCTURED_OUTPUT_UNSUPPORTED"


async def test_complete_json_uses_reasoning_content_when_content_empty(mock_llm_server):
    payload = {"mermaid": "flowchart LR\nA-->B", "message": "ok"}
    url = mock_llm_server(_llm_response("", reasoning_content=json.dumps(payload)))
    client = VLLMClient(
        url=url,
        model="test",
        deadline=_deadline(),
        response_format_mode="none",
    )
    result = await client.complete_json("x", {}, "X")
    assert result["mermaid"] == payload["mermaid"]


async def test_complete_json_exposes_usage_on_last_usage(mock_llm_server):
    payload = {"mermaid": "flowchart LR\nA-->B", "message": "ok"}
    body = _llm_response(json.dumps(payload))
    body["usage"] = {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}
    url = mock_llm_server(body)
    client = VLLMClient(
        url=url,
        model="test",
        deadline=_deadline(),
        response_format_mode="none",
    )
    await client.complete_json("x", {}, "X")
    assert client.last_usage == {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}


async def test_complete_text_usage_is_none_when_response_omits_it(mock_llm_server):
    url = mock_llm_server(_llm_response("flowchart LR\nA --> B"))
    client = VLLMClient(
        url=url,
        model="test",
        deadline=_deadline(),
        response_format_mode="none",
    )
    await client.complete_text("make a diagram")
    assert client.last_usage is None
