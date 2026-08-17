from __future__ import annotations

import json
import re

from app.infrastructure.llm.errors import LLMError

_THINK_TAGS = re.compile(r"<think>.*?</think>", re.DOTALL)
_FLOWCHART_HEADER = re.compile(r"flowchart\s+(TB|TD|BT|RL|LR)")
_FENCE = re.compile(r"```(?:mermaid|json)?\s*")
_CLOSING_FENCE = re.compile(r"```\s*")


def inline_refs(obj, defs: dict):
    """Preserves identity for unchanged subtrees (mirrors TS `_inlineRefs`:
    returns `obj` itself when nothing changed, required so a `$ref` resolved
    to a leaf definition returns that same definition object)."""
    if isinstance(obj, list):
        mapped = [inline_refs(item, defs) for item in obj]
        return mapped if any(m is not o for m, o in zip(mapped, obj)) else obj
    if isinstance(obj, dict):
        if "$ref" in obj:
            name = obj["$ref"].split("/")[-1]
            return inline_refs(defs[name], defs)
        changed = False
        result = {}
        for key, value in obj.items():
            if key == "$defs":
                changed = True
                continue
            new_value = inline_refs(value, defs)
            if new_value is not value:
                changed = True
            result[key] = new_value
        return result if changed else obj
    return obj


def strip_think_tags(text: str) -> str:
    return _THINK_TAGS.sub("", text).strip()


def extract_mermaid(raw: str) -> str:
    cleaned = _CLOSING_FENCE.sub("", _FENCE.sub("", raw)).strip()
    match = _FLOWCHART_HEADER.search(cleaned)
    if match is None:
        raise LLMError("EMPTY_RESPONSE", f"No flowchart found: {raw[:200]}")
    return cleaned[match.start():].strip()


def extract_json(raw: str) -> dict:
    cleaned = _CLOSING_FENCE.sub("", raw.replace("```json", "").replace("```", "")).strip()
    start = cleaned.find("{")
    if start == -1:
        raise LLMError("INVALID_JSON", f"No JSON object found: {cleaned[:200]}")
    try:
        return json.loads(cleaned[start:])
    except json.JSONDecodeError:
        pass

    depth = 0
    in_str = False
    esc = False
    end = -1
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if esc:
            esc = False
            continue
        if in_str:
            if ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end == -1:
        raise LLMError("INVALID_JSON", f"Unbalanced braces in: {cleaned[start:start + 200]}")
    return json.loads(cleaned[start:end + 1])
