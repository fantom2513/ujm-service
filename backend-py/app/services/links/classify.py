from __future__ import annotations

import re
from urllib.parse import urlparse

from app.config import get_settings
from app.infrastructure.jira.client import JiraClient
from app.infrastructure.jira.errors import JiraError
from app.services.files.extract import NormalizedSource

# Ключ задачи Jira: буква, затем буквы/цифры проекта, дефис, номер (напр.
# "ABC-123"). Ищем регистронезависимо и в пути, и в query-строке — ключ может
# быть частью пути ("/browse/ABC-123") или значением параметра
# ("?selectedIssue=abc-123").
_JIRA_KEY_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9]+-\d+")


def extract_jira_key(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    match = _JIRA_KEY_PATTERN.search(parsed.path) or _JIRA_KEY_PATTERN.search(parsed.query)
    return match.group(0).upper() if match else None


def classify_work_link(value: str) -> str | None:
    try:
        parsed = urlparse(value)
        if not parsed.scheme or not parsed.netloc:
            return None
        # `.hostname`, not `.netloc` — netloc includes userinfo/port
        # ("user:jira@host"), which would false-match on credentials rather
        # than the actual host. Parity with TS: backend/src/services/links/
        # index.ts:6 (`url.hostname`).
        searchable = f"{parsed.hostname or ''}{parsed.path}".lower()
    except ValueError:
        return None
    if "jira" in searchable:
        return "jira"
    if "confluence" in searchable or "wiki" in searchable:
        return "confluence"
    return None


def _stub_source(link_type: str | None, value: str) -> NormalizedSource:
    label = "Jira" if link_type == "jira" else "Confluence"
    # Temporary integration point: replace this stub with real Confluence API
    # access once service URLs, credentials and supported link formats are
    # approved (Phase 4). Jira has its own real integration below.
    return NormalizedSource(
        type="link",
        title=f"{label}: тестовый источник",
        text=f"Контролируемая заглушка {label}. Здесь будет текст задачи или страницы после подключения серверной интеграции.",
        description=f"{label} · {value}",
        url=value,
        stub=True,
    )


async def _normalize_jira_link(value: str) -> NormalizedSource | None:
    """Возвращает реальный источник по Jira-ссылке, либо None, если нужно
    откатиться на заглушку (Jira не настроена, в ссылке нет ключа задачи,
    или запрос к Jira завершился ошибкой)."""
    settings = get_settings()
    if not (settings.jira_url and settings.jira_username and settings.jira_api_token):
        return None
    key = extract_jira_key(value)
    if key is None:
        return None
    client = JiraClient(
        settings.jira_url,
        settings.jira_username,
        settings.jira_api_token,
        settings.jira_timeout_ms,
        settings.jira_insecure_tls,
    )
    try:
        issue = await client.get_issue(key)
    except JiraError:
        return None
    return NormalizedSource(
        type="link",
        title=f"Jira: {key}",
        text=f"{issue['summary']}\n\n{issue['description']}".strip(),
        description=f"Jira · {value}",
        url=value,
        stub=False,
    )


async def normalize_link(value: str) -> NormalizedSource:
    link_type = classify_work_link(value)
    if link_type == "jira":
        jira_source = await _normalize_jira_link(value)
        if jira_source is not None:
            return jira_source
    return _stub_source(link_type, value)
