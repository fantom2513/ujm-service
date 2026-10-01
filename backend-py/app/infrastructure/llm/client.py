from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator

import httpx

from app.infrastructure.llm.deadline import LLMDeadline
from app.infrastructure.llm.errors import LLMError

logger = logging.getLogger(__name__)


async def _sse_events(response: httpx.Response) -> AsyncIterator[str]:
    data_lines: list[str] = []
    async for line in response.aiter_lines():
        if line == "":
            if data_lines:
                yield "\n".join(data_lines)
                data_lines.clear()
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip(" "))
    if data_lines:
        yield "\n".join(data_lines)

ResponseFormatMode = str  # "json_schema" | "json_object" | "none"

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


class VLLMClient:
    def __init__(
        self,
        url: str,
        model: str,
        deadline: LLMDeadline,
        api_key: str | None = None,
        connect_timeout_ms: int = 5_000,
        pool_timeout_ms: int = 5_000,
        ttft_ms: int = 30_000,
        stall_ms: int = 60_000,
        temperature: float = 0.1,
        seed: int | None = None,
        response_format_mode: ResponseFormatMode = "json_schema",
        insecure_tls: bool = False,
    ):
        self.base_url = url.removesuffix("/chat/completions").rstrip("/")
        self.model = model
        self.deadline = deadline
        self.connect_timeout_ms = connect_timeout_ms
        self.pool_timeout_ms = pool_timeout_ms
        self.ttft_ms = ttft_ms
        self.stall_ms = stall_ms
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
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if self.seed is not None:
            payload["seed"] = self.seed
        if response_format:
            payload["response_format"] = response_format

        # The deadline gates this attempt. Once the model is producing, only
        # TTFT/stall govern the read; total duration is intentionally unbounded.
        remaining = self.deadline.require_remaining()
        timeout = httpx.Timeout(
            timeout=None,
            connect=min(self.connect_timeout_ms / 1000, remaining),
            read=None,
            write=remaining,
            pool=min(self.pool_timeout_ms / 1000, remaining),
        )
        first_limit = self.ttft_ms / 1000
        first_deadline = time.monotonic() + first_limit
        content: list[str] = []
        reasoning: list[str] = []
        usage: dict | None = None
        chunks = 0
        logger.info("LLM stream attempt started")
        try:
            async with httpx.AsyncClient(verify=self._verify, timeout=timeout) as http_client:
                async with asyncio.timeout(first_limit):
                    stream = http_client.stream(
                        "POST", self.endpoint, headers=self.headers, json=payload
                    )
                    response = await stream.__aenter__()
                try:
                    if response.status_code >= 400:
                        body = (await asyncio.wait_for(response.aread(), timeout=self.ttft_ms / 1000)).decode(errors="replace")
                        if response.status_code == 422 and self.response_format_mode != "none":
                            raise LLMError("STRUCTURED_OUTPUT_UNSUPPORTED", f"Model rejected response_format: {body[:400]}")
                        raise LLMError("HTTP_ERROR", f"LLM HTTP {response.status_code}: {body[:400]}")
                    events = _sse_events(response).__aiter__()
                    first = True
                    stall_deadline = 0.0
                    done = False
                    while True:
                        limit = max(0, (first_deadline if first else stall_deadline) - time.monotonic())
                        try:
                            raw = await asyncio.wait_for(anext(events), timeout=limit)
                        except StopAsyncIteration:
                            break
                        except TimeoutError as err:
                            phase = "TTFT" if first else "STALL"
                            logger.warning("LLM %s timeout after %d chunks", phase, chunks)
                            raise LLMError("TIMEOUT", f"LLM {phase} timeout") from err
                        if raw == "[DONE]":
                            done = True
                            break
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError as err:
                            raise LLMError("INVALID_JSON", "Invalid LLM SSE event") from err
                        if data.get("error"):
                            raise LLMError("HTTP_ERROR", "LLM stream reported an error")
                        if data.get("usage") is not None:
                            raw_usage = data["usage"]
                            usage = {
                                "prompt_tokens": raw_usage.get("prompt_tokens", 0),
                                "completion_tokens": raw_usage.get("completion_tokens", 0),
                                "total_tokens": raw_usage.get("total_tokens", 0),
                            }
                        choices = data.get("choices") or []
                        delta = choices[0].get("delta", {}) if choices else {}
                        piece = delta.get("content") or ""
                        thought = delta.get("reasoning_content") or delta.get("reasoning") or ""
                        if piece or thought:
                            content.append(piece)
                            reasoning.append(thought)
                            chunks += 1
                            if first:
                                logger.info("LLM first token received")
                                first = False
                            stall_deadline = time.monotonic() + self.stall_ms / 1000
                            if chunks % 1000 == 0:
                                logger.info("LLM stream received %d chunks", chunks)
                    if not done:
                        raise LLMError("NETWORK_ERROR", "LLM stream ended before [DONE]")
                    logger.info("LLM stream completed after %d chunks", chunks)
                finally:
                    await stream.__aexit__(None, None, None)
        except asyncio.CancelledError:
            raise
        except TimeoutError as err:
            logger.warning("LLM TTFT timeout before response headers")
            raise LLMError("TIMEOUT", "LLM TTFT timeout") from err
        except httpx.TimeoutException as err:
            raise LLMError("TIMEOUT", "LLM HTTP request timed out") from err
        except httpx.HTTPError as err:
            raise LLMError("NETWORK_ERROR", f"LLM network error: {err}", err) from err
        return {"content": "".join(content), "reasoning_content": "".join(reasoning), "usage": usage}

    async def complete_text(self, prompt: str, system: str | None = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        result = await self._post(messages)
        self.last_usage = result["usage"]
        mermaid = extract_mermaid(strip_think_tags(result["content"]))
        return mermaid

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
        parsed = extract_json(strip_think_tags(raw))
        return parsed
