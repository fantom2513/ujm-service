from app.services.links.classify import classify_work_link, normalize_link


def test_classify_jira_link():
    assert classify_work_link("https://jira.example.com/browse/ABC-1") == "jira"


def test_classify_confluence_link():
    assert classify_work_link("https://confluence.example.com/wiki/page") == "confluence"


def test_classify_unrecognized_link_returns_none():
    assert classify_work_link("https://example.com/random") is None


def test_classify_invalid_url_returns_none():
    assert classify_work_link("not a url") is None


def test_normalize_link_marks_as_stub():
    result = normalize_link("https://jira.example.com/browse/ABC-1")
    assert result.type == "link"
    assert result.stub is True
    assert result.url == "https://jira.example.com/browse/ABC-1"
