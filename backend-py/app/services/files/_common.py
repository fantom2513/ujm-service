from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable


async def parse_in_thread(
    extract_text: Callable[[bytes], str],
    buffer: bytes,
    logger: logging.Logger,
    parser_name: str,
) -> str:
    """Runs a synchronous/CPU-bound `extract_text(buffer)` on a worker
    thread via `asyncio.to_thread`, so it doesn't block the event loop for
    the duration of a large upload's parse. Never raises: any failure is
    logged without the exception's message or traceback -- both can quote
    fragments of the uploaded file's content -- and results in an empty
    string, so callers can safely fall back to a stub. The exception's type
    name plus the parser and buffer size are still logged, which is enough
    to find the root cause without leaking file content into logs.

    Shared by pdf.py/docx.py/xlsx.py, which otherwise repeat this exact
    try/except and had already started drifting (only one of them logged
    on failure) — keep new parsers on this helper instead of copying the
    try/except again.
    """
    try:
        return await asyncio.to_thread(extract_text, buffer)
    except Exception as exc:
        logger.error(
            "%s failed for buffer of %d bytes: %s",
            parser_name,
            len(buffer),
            type(exc).__name__,
        )
        return ""
