from __future__ import annotations

import asyncio
import io
import logging

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

logger = logging.getLogger(__name__)


def _extract_text(buffer: bytes) -> str:
    document = Document(io.BytesIO(buffer))
    # `iter_inner_content()` walks the body in document order (paragraphs
    # interleaved with tables), unlike `.paragraphs` alone which silently
    # skips every table cell. Parity with TS: backend/src/services/files/
    # docx.ts uses mammoth's `extractRawText`, which captures table content too.
    parts: list[str] = []
    for block in document.iter_inner_content():
        if isinstance(block, Paragraph):
            if block.text:
                parts.append(block.text)
        elif isinstance(block, Table):
            for row in block.rows:
                for cell in row.cells:
                    if cell.text:
                        parts.append(cell.text)
    return "\n".join(parts).strip()[:60_000]


async def parse_docx(buffer: bytes) -> str:
    """Extracts plain text from a DOCX buffer. Never throws: any failure
    (malformed DOCX, unsupported format, parser error) results in an empty
    string so callers can safely fall back.

    Parsing is synchronous/CPU-bound (python-docx has no async API), so it
    runs on a worker thread via `asyncio.to_thread` to avoid blocking the
    event loop for the duration of a large upload's parse.
    """
    try:
        return await asyncio.to_thread(_extract_text, buffer)
    except Exception:
        logger.exception("parse_docx failed for buffer of %d bytes", len(buffer))
        return ""
