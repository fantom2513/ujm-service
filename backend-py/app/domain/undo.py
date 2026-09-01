from __future__ import annotations

import re


UNDO_PHRASES: frozenset[str] = frozenset(
    {
        "верни предыдущую версию",
        "вернуть предыдущую версию",
        "верни прошлую схему",
        "отмени последнее изменение",
        "откатить последнее изменение",
        "назад к предыдущей схеме",
    }
)


def normalize_undo_message(message: str) -> str:
    """Normalize a chat message exactly like the TypeScript chat handler."""
    normalized = re.sub(r"\s+", " ", message.lower().strip())
    return re.sub(r"[.!?]$", "", normalized)


def is_undo_request(message: str) -> bool:
    return normalize_undo_message(message) in UNDO_PHRASES
