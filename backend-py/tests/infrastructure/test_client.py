from app.infrastructure.llm.client import (
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
