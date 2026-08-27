from __future__ import annotations

import io
import logging

from pypdf import PdfReader

from app.services.files._common import parse_in_thread

logger = logging.getLogger(__name__)


def _extract_text(buffer: bytes) -> str:
    reader = PdfReader(io.BytesIO(buffer))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return text.strip()[:60_000]


async def parse_pdf(buffer: bytes) -> str:
    """Extracts plain text from a PDF buffer. Never throws: any failure
    (malformed PDF, image-only PDF, parser error) results in an empty
    string so callers can safely fall back.

    Parsing is synchronous/CPU-bound (pypdf has no async API), so it runs
    on a worker thread via `asyncio.to_thread` to avoid blocking the event
    loop for the duration of a large upload's parse.
    """
    return await parse_in_thread(_extract_text, buffer, logger, "parse_pdf")
