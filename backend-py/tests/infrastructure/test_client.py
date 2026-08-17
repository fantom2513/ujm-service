import json

import pytest

from app.infrastructure.llm.client import (
    VLLMClient,
    extract_json,
    extract_mermaid,
    inline_refs,
    strip_think_tags,
)
from app.infrastructure.llm.errors import LLMError


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


async def test_complete_text_returns_mermaid_from_response(mock_llm_server):
    url = mock_llm_server(_llm_response("flowchart LR\nA --> B"))
    client = VLLMClient(url=url, model="test", response_format_mode="none")
    result = await client.complete_text("make a diagram")
    assert result.startswith("flowchart LR")


async def test_complete_text_strips_think_tags(mock_llm_server):
    url = mock_llm_server(_llm_response("<think>reasoning</think>\nflowchart TB\nA --> B"))
    client = VLLMClient(url=url, model="test", response_format_mode="none")
    result = await client.complete_text("make a diagram")
    assert result.startswith("flowchart TB")
    assert "<think>" not in result


async def test_complete_text_raises_timeout_when_server_too_slow(mock_llm_server):
    url = mock_llm_server({}, delay_forever=True)
    client = VLLMClient(url=url, model="test", timeout_ms=50, response_format_mode="none")
    with pytest.raises(LLMError) as exc_info:
        await client.complete_text("test")
    assert exc_info.value.code == "TIMEOUT"


async def test_complete_json_parses_with_json_schema_mode(mock_llm_server):
    payload = {"mermaid": "flowchart LR\nA --> B", "message": "done"}
    url = mock_llm_server(_llm_response(json.dumps(payload)))
    client = VLLMClient(url=url, model="test", response_format_mode="json_schema")
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
    client = VLLMClient(url=url, model="test", response_format_mode="json_schema")
    with pytest.raises(LLMError) as exc_info:
        await client.complete_json("x", {}, "X")
    assert exc_info.value.code == "STRUCTURED_OUTPUT_UNSUPPORTED"


async def test_complete_json_uses_reasoning_content_when_content_empty(mock_llm_server):
    payload = {"mermaid": "flowchart LR\nA-->B", "message": "ok"}
    url = mock_llm_server(_llm_response("", reasoning_content=json.dumps(payload)))
    client = VLLMClient(url=url, model="test", response_format_mode="none")
    result = await client.complete_json("x", {}, "X")
    assert result["mermaid"] == payload["mermaid"]


async def test_complete_json_exposes_usage_on_last_usage(mock_llm_server):
    payload = {"mermaid": "flowchart LR\nA-->B", "message": "ok"}
    body = _llm_response(json.dumps(payload))
    body["usage"] = {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}
    url = mock_llm_server(body)
    client = VLLMClient(url=url, model="test", response_format_mode="none")
    await client.complete_json("x", {}, "X")
    assert client.last_usage == {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}


async def test_complete_text_usage_is_none_when_response_omits_it(mock_llm_server):
    url = mock_llm_server(_llm_response("flowchart LR\nA --> B"))
    client = VLLMClient(url=url, model="test", response_format_mode="none")
    await client.complete_text("make a diagram")
    assert client.last_usage is None
