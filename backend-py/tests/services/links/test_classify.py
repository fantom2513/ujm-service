from app.config import Settings
from app.infrastructure.jira.errors import JiraError
from app.services.links.classify import classify_work_link, extract_jira_key, normalize_link


def _jira_settings(**overrides) -> Settings:
    fields = {
        "jira_url": "https://jira.example.com",
        "jira_username": "user",
        "jira_api_token": "token",
    }
    fields.update(overrides)
    return Settings(_env_file=None, **fields)


def test_classify_jira_link():
    assert classify_work_link("https://jira.example.com/browse/ABC-1") == "jira"


def test_classify_confluence_link():
    assert classify_work_link("https://confluence.example.com/wiki/page") == "confluence"


def test_classify_unrecognized_link_returns_none():
    assert classify_work_link("https://example.com/random") is None


def test_classify_invalid_url_returns_none():
    assert classify_work_link("not a url") is None


def test_classify_ignores_userinfo_in_url():
    # urlparse().netloc includes userinfo ("user:jira@host"), but the TS
    # original matches on url.hostname only (backend/src/services/links/
    # index.ts:6) — a URL with unrelated credentials must not misclassify.
    assert classify_work_link("https://user:jira@example.com/page") is None


def test_extract_jira_key_from_path():
    assert extract_jira_key("https://jira.example.com/browse/ABC-123") == "ABC-123"


def test_extract_jira_key_from_query_param():
    url = "https://jira.example.com/secure/RapidBoard.jspa?selectedIssue=abc-123"
    assert extract_jira_key(url) == "ABC-123"


def test_extract_jira_key_is_case_insensitive():
    assert extract_jira_key("https://jira.example.com/browse/abc-123") == "ABC-123"


def test_extract_jira_key_returns_none_without_key():
    assert extract_jira_key("https://jira.example.com/projects/ABC") is None


def test_extract_jira_key_returns_none_for_invalid_url():
    assert extract_jira_key("not a url") is None


async def test_normalize_link_confluence_is_stub():
    result = await normalize_link("https://confluence.example.com/wiki/page")
    assert result.type == "link"
    assert result.stub is True
    assert result.url == "https://confluence.example.com/wiki/page"


async def test_normalize_link_jira_not_configured_is_stub_without_network(monkeypatch):
    monkeypatch.setattr("app.services.links.classify.get_settings", lambda: Settings(_env_file=None))

    class ExplodingClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("JiraClient must not be constructed when Jira isn't configured")

    monkeypatch.setattr("app.services.links.classify.JiraClient", ExplodingClient)

    result = await normalize_link("https://jira.example.com/browse/ABC-1")
    assert result.stub is True


async def test_normalize_link_jira_without_key_is_stub(monkeypatch):
    monkeypatch.setattr("app.services.links.classify.get_settings", lambda: _jira_settings())

    class ExplodingClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("JiraClient must not be constructed when the URL has no issue key")

    monkeypatch.setattr("app.services.links.classify.JiraClient", ExplodingClient)

    result = await normalize_link("https://jira.example.com/projects/ABC")
    assert result.stub is True


async def test_normalize_link_jira_success(monkeypatch):
    monkeypatch.setattr("app.services.links.classify.get_settings", lambda: _jira_settings())

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def get_issue(self, key):
            assert key == "ABC-1"
            return {"summary": "Fix the bug", "description": "Steps to reproduce..."}

    monkeypatch.setattr("app.services.links.classify.JiraClient", FakeClient)

    result = await normalize_link("https://jira.example.com/browse/ABC-1")
    assert result.stub is False
    assert "Fix the bug" in result.text
    assert "Steps to reproduce..." in result.text


async def test_normalize_link_jira_error_is_stub(monkeypatch):
    monkeypatch.setattr("app.services.links.classify.get_settings", lambda: _jira_settings())

    class FailingClient:
        def __init__(self, *args, **kwargs):
            pass

        async def get_issue(self, key):
            raise JiraError("NOT_FOUND", f"Jira issue {key} not found")

    monkeypatch.setattr("app.services.links.classify.JiraClient", FailingClient)

    result = await normalize_link("https://jira.example.com/browse/ABC-1")
    assert result.type == "link"
    assert result.stub is True
