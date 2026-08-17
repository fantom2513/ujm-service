from __future__ import annotations

import io

from docx import Document


async def parse_docx(buffer: bytes) -> str:
    """Extracts plain text from a DOCX buffer. Never throws: any failure
    (malformed DOCX, unsupported format, parser error) results in an empty
    string so callers can safely fall back."""
    try:
        document = Document(io.BytesIO(buffer))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        return text.strip()[:60_000]
    except Exception:
        return ""
