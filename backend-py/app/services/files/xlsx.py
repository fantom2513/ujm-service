from __future__ import annotations

import asyncio
import io
import logging

from openpyxl import load_workbook

logger = logging.getLogger(__name__)


def _extract_text(buffer: bytes) -> str:
    workbook = load_workbook(io.BytesIO(buffer), read_only=True, data_only=True)
    try:
        parts: list[str] = []
        for sheet in workbook.worksheets:
            for row in sheet.iter_rows(values_only=True):
                if all(cell is None for cell in row):
                    continue
                parts.append("\t".join("" if cell is None else str(cell) for cell in row))
        return "\n".join(parts).strip()[:60_000]
    finally:
        workbook.close()


async def parse_xlsx(buffer: bytes) -> str:
    """Извлекает обычный текст из XLSX-буфера. Никогда не бросает исключения:
    любая ошибка (битая книга, не-xlsx байты, ошибка парсера) приводит
    к пустой строке, чтобы вызывающий код мог безопасно откатиться на заглушку.

    Каждая непустая строка таблицы становится одной строкой результата,
    ячейки внутри неё склеены табуляцией; строки, где все ячейки пустые
    (None), полностью выбрасываются из результата.

    Разбор синхронный и CPU-bound (у openpyxl нет async API), поэтому он
    выполняется в отдельном потоке через `asyncio.to_thread`, чтобы не
    блокировать event loop на время разбора большого файла.
    """
    try:
        return await asyncio.to_thread(_extract_text, buffer)
    except Exception:
        logger.exception("parse_xlsx failed for buffer of %d bytes", len(buffer))
        return ""
