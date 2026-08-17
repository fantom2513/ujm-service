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


import httpx

ResponseFormatMode = str  # "json_schema" | "json_object" | "none"


class VLLMClient:
    def __init__(
        self,
        url: str,
        model: str,
        api_key: str | None = None,
        timeout_ms: int = 120_000,
        temperature: float = 0.1,
        seed: int | None = None,
        response_format_mode: ResponseFormatMode = "json_schema",
        insecure_tls: bool = False,
    ):
        self.base_url = url.removesuffix("/chat/completions").rstrip("/")
        self.model = model
        self.timeout_ms = timeout_ms
        self.temperature = temperature
        self.seed = seed
        self.response_format_mode = response_format_mode
        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"
        # httpx's per-client `verify` param is honored reliably (unlike the
        # Node/undici global-dispatcher workaround the TS client needs) — no
        # extra plumbing required to trust an internal-CA / self-signed LLM
        # endpoint when insecure_tls is set.
        self._verify = not insecure_tls
        self.last_usage: dict | None = None

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"

    async def _post(self, messages: list[dict], response_format: dict | None = None) -> dict:
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": False,
        }
        if self.seed is not None:
            payload["seed"] = self.seed
        if response_format:
            payload["response_format"] = response_format

        timeout = httpx.Timeout(self.timeout_ms / 1000)
        try:
            async with httpx.AsyncClient(verify=self._verify, timeout=timeout) as http_client:
                response = await http_client.post(self.endpoint, headers=self.headers, json=payload)
        except httpx.TimeoutException as err:
            raise LLMError("TIMEOUT", f"LLM timed out after {self.timeout_ms}ms") from err
        except httpx.HTTPError as err:
            raise LLMError("NETWORK_ERROR", f"LLM network error: {err}", err) from err

        if response.status_code >= 400:
            body = response.text
            if response.status_code == 422 and self.response_format_mode != "none":
                raise LLMError(
                    "STRUCTURED_OUTPUT_UNSUPPORTED",
                    f"Model rejected response_format: {body[:400]}",
                )
            raise LLMError("HTTP_ERROR", f"LLM HTTP {response.status_code}: {body[:400]}")

        data = response.json()
        message = data.get("choices", [{}])[0].get("message", {})
        usage = None
        if "usage" in data:
            raw_usage = data["usage"]
            usage = {
                "prompt_tokens": raw_usage.get("prompt_tokens", 0),
                "completion_tokens": raw_usage.get("completion_tokens", 0),
                "total_tokens": raw_usage.get("total_tokens", 0),
            }
        return {
            "content": message.get("content") or "",
            "reasoning_content": message.get("reasoning_content") or "",
            "usage": usage,
        }

    async def complete_text(self, prompt: str, system: str | None = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        result = await self._post(messages)
        self.last_usage = result["usage"]
        return extract_mermaid(strip_think_tags(result["content"]))

    async def complete_json(
        self,
        prompt: str,
        schema: dict,
        schema_name: str,
        system: str | None = None,
    ) -> dict:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        defs = schema.get("$defs", {})
        flat_schema = inline_refs(schema, defs)

        response_format = None
        if self.response_format_mode == "json_schema":
            response_format = {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": False, "schema": flat_schema},
            }
        elif self.response_format_mode == "json_object":
            response_format = {"type": "json_object"}

        result = await self._post(messages, response_format)
        self.last_usage = result["usage"]
        raw = result["content"] if "{" in result["content"] else (
            result["reasoning_content"] if "{" in result["reasoning_content"] else result["content"]
        )
        return extract_json(strip_think_tags(raw))
