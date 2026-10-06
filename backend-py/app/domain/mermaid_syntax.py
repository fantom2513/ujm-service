from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.domain.mermaid import ValidationResult
from app.infrastructure.llm.deadline import LLMDeadline
from app.infrastructure.llm.errors import LLMError

_PARSER_SCRIPT = Path(__file__).with_name("mermaid_parser.mjs")
_PARSER_TIMEOUT_SECONDS = 10.0


class MermaidParserUnavailable(RuntimeError):
    pass


async def validate_mermaid_syntax(code: str, deadline: LLMDeadline) -> ValidationResult:
    # Local parsing must still validate a completed response after the LLM budget expires.
    timeout = _PARSER_TIMEOUT_SECONDS
    try:
        process = await asyncio.create_subprocess_exec(
            "node",
            str(_PARSER_SCRIPT),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as error:
        raise MermaidParserUnavailable("Mermaid parser could not start") from error

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(code.encode("utf-8")), timeout=timeout
        )
    except (asyncio.CancelledError, TimeoutError) as error:
        if process.returncode is None:
            process.kill()
        await process.wait()
        if isinstance(error, TimeoutError):
            raise LLMError("TIMEOUT", "Mermaid validation timed out") from error
        raise

    if process.returncode != 0:
        raise MermaidParserUnavailable(
            f"Mermaid parser failed: {stderr.decode('utf-8', errors='replace')[:200]}"
        )
    try:
        result = json.loads(stdout)
        if not isinstance(result["ok"], bool):
            raise ValueError("Invalid parser result")
        if result["ok"]:
            return ValidationResult(True)
        reason = result.get("reason")
        return ValidationResult(False, reason if isinstance(reason, str) else "Mermaid parse failed")
    except (ValueError, KeyError, TypeError) as error:
        raise MermaidParserUnavailable("Mermaid parser returned an invalid result") from error
