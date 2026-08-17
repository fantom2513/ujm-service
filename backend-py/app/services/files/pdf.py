from __future__ import annotations

import io

from pypdf import PdfReader


async def parse_pdf(buffer: bytes) -> str:
    """Extracts plain text from a PDF buffer. Never throws: any failure
    (malformed PDF, image-only PDF, parser error) results in an empty
    string so callers can safely fall back."""
    try:
        reader = PdfReader(io.BytesIO(buffer))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        return text.strip()[:60_000]
    except Exception:
        return ""
