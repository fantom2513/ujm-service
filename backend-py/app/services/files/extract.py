from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.files.docx import parse_docx
from app.services.files.pdf import parse_pdf

_TEXT_FORMATS = {"txt", "docx", "pdf"}
_TABLE_FORMATS = {"xls", "xlsx", "csv"}
_UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


def get_extension(filename: str) -> str:
    parts = filename.lower().split(".")
    return parts[-1] if len(parts) > 1 else ""


def sanitize_filename(filename: str) -> str:
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", filename)[:140]
    return cleaned or "file"


def is_text_source_format(fmt: str) -> bool:
    return fmt in _TEXT_FORMATS


def is_chat_document_format(fmt: str) -> bool:
    return fmt in _TEXT_FORMATS or fmt in _TABLE_FORMATS


def has_pdf_text_layer(filename: str, content: bytes) -> bool:
    if get_extension(filename) != "pdf":
        return True
    text = content.decode("latin1")
    return bool(re.search(r"\bBT\b", text)) and bool(re.search(r"(Tj|TJ)\b", text))


@dataclass
class NormalizedSource:
    type: str
    title: str
    text: str
    description: str
    file: dict | None = None
    url: str | None = None
    stub: bool = False


async def normalize_text_file(filename: str, buffer: bytes, size: int) -> NormalizedSource:
    fmt = get_extension(filename)
    safe_name = sanitize_filename(filename)
    text = f"Файл {safe_name} принят каркасом backend."
    stub = True

    if fmt in ("txt", "csv"):
        text = buffer.decode("utf-8", errors="replace")[:12_000]
        stub = False
    elif fmt == "pdf":
        extracted = await parse_pdf(buffer)
        stub = not extracted
        text = extracted or f"Файл {safe_name}: содержимое не удалось извлечь."
    elif fmt == "docx":
        extracted = await parse_docx(buffer)
        stub = not extracted
        text = extracted or f"Файл {safe_name}: содержимое не удалось извлечь."
    elif fmt in ("xls", "xlsx"):
        text = f"Извлечение содержимого {fmt.upper()} будет подключено в сервисе files. Сейчас используется тестовый контекст каркаса."
        stub = True

    return NormalizedSource(
        type="text-file",
        title=safe_name,
        text=text,
        description=f"{fmt.upper()} · {round(size / 1024)} КБ",
        file={"name": safe_name, "format": fmt.upper(), "size": size},
        stub=stub,
    )
