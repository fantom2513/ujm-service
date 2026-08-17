from __future__ import annotations

from urllib.parse import urlparse

from app.services.files.extract import NormalizedSource


def classify_work_link(value: str) -> str | None:
    try:
        parsed = urlparse(value)
        if not parsed.scheme or not parsed.netloc:
            return None
        searchable = f"{parsed.netloc}{parsed.path}".lower()
    except ValueError:
        return None
    if "jira" in searchable:
        return "jira"
    if "confluence" in searchable or "wiki" in searchable:
        return "confluence"
    return None


def normalize_link(value: str) -> NormalizedSource:
    link_type = classify_work_link(value)
    label = "Jira" if link_type == "jira" else "Confluence"

    # Temporary integration point: replace this stub with real
    # Jira/Confluence API access once service URLs, credentials and
    # supported link formats are approved (Phase 4).
    return NormalizedSource(
        type="link",
        title=f"{label}: тестовый источник",
        text=f"Контролируемая заглушка {label}. Здесь будет текст задачи или страницы после подключения серверной интеграции.",
        description=f"{label} · {value}",
        url=value,
        stub=True,
    )
