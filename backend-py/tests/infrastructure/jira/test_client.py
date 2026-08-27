import socket

import pytest

from app.infrastructure.jira.client import JiraClient
from app.infrastructure.jira.errors import JiraError


def _unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _issue_response(summary: str = "Fix the bug", description: str = "Steps to reproduce...") -> dict:
    return {"fields": {"summary": summary, "description": description}}


async def test_get_issue_returns_parsed_summary_and_description(mock_jira_server):
    url = mock_jira_server(_issue_response("Fix the bug", "Steps to reproduce..."))
    client = JiraClient(url, "user", "token")
    issue = await client.get_issue("ABC-123")
    assert issue == {"summary": "Fix the bug", "description": "Steps to reproduce..."}


async def test_get_issue_raises_unauthorized_on_401(mock_jira_server):
    url = mock_jira_server({}, status_code=401)
    client = JiraClient(url, "user", "wrong-token")
    with pytest.raises(JiraError) as exc_info:
        await client.get_issue("ABC-123")
    assert exc_info.value.code == "UNAUTHORIZED"


async def test_get_issue_raises_not_found_on_404(mock_jira_server):
    url = mock_jira_server({}, status_code=404)
    client = JiraClient(url, "user", "token")
    with pytest.raises(JiraError) as exc_info:
        await client.get_issue("ABC-404")
    assert exc_info.value.code == "NOT_FOUND"


async def test_get_issue_raises_http_error_on_other_status(mock_jira_server):
    url = mock_jira_server({}, status_code=500)
    client = JiraClient(url, "user", "token")
    with pytest.raises(JiraError) as exc_info:
        await client.get_issue("ABC-123")
    assert exc_info.value.code == "HTTP_ERROR"


async def test_get_issue_raises_timeout_when_server_too_slow(mock_jira_server):
    url = mock_jira_server({}, delay_forever=True)
    client = JiraClient(url, "user", "token", timeout_ms=50)
    with pytest.raises(JiraError) as exc_info:
        await client.get_issue("ABC-123")
    assert exc_info.value.code == "TIMEOUT"


async def test_get_issue_raises_network_error_when_nobody_listening():
    port = _unused_port()
    client = JiraClient(f"http://127.0.0.1:{port}", "user", "token")
    with pytest.raises(JiraError) as exc_info:
        await client.get_issue("ABC-123")
    assert exc_info.value.code == "NETWORK_ERROR"
