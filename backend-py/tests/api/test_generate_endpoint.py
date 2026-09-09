import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.domain.identity import Principal
from app.main import app


class FakeChatService:
    def __init__(self):
        self.session_id = "test-session-id"
        self.error: Exception | None = None
        self.create_calls: list[dict] = []

    async def create_session_with_version(self, **kwargs) -> str:
        self.create_calls.append(kwargs)
        if self.error:
            raise self.error
        return self.session_id


@pytest.fixture
def chat_service():
    return FakeChatService()


@pytest.fixture
def identity_override():
    current = Principal.anonymous()

    def set_identity(principal: Principal) -> None:
        nonlocal current
        current = principal

    app.dependency_overrides[deps.get_current_identity] = lambda: current
    try:
        yield set_identity
    finally:
        app.dependency_overrides.pop(deps.get_current_identity, None)


@pytest.fixture
def client(chat_service, identity_override):
    app.dependency_overrides[deps.get_chat_service] = lambda: chat_service
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(deps.get_chat_service, None)


def test_generate_missing_source_type_returns_400_diagram_generation(client):
    response = client.post("/api/generate", data={})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "diagram-generation"


def test_generate_text_file_without_file_returns_400_file_required(client):
    response = client.post("/api/generate", data={"sourceType": "text-file"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "file-required"


def test_generate_link_without_value_returns_400_link_required(client):
    response = client.post("/api/generate", data={"sourceType": "link", "link": ""})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "link-required"


def test_generate_link_invalid_format_returns_400_invalid_link(client):
    response = client.post("/api/generate", data={"sourceType": "link", "link": "not-a-url"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid-link"


def test_generate_text_file_unsupported_format_returns_400_file_format(client):
    response = client.post(
        "/api/generate",
        data={"sourceType": "text-file"},
        files={"file": ("song.mp3", b"binary data", "audio/mpeg")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "file-format"


def test_generate_text_file_too_large_returns_400_file_size(client):
    huge = b"x" * (10 * 1024 * 1024 + 1)
    response = client.post(
        "/api/generate",
        data={"sourceType": "text-file"},
        files={"file": ("notes.txt", huge, "text/plain")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "file-size"


def test_generate_text_file_success_returns_200(
    client, chat_service, identity_override, monkeypatch
):
    async def fake_generate_diagram(source_text, details, client=None):
        return "flowchart LR\nA --> B"

    monkeypatch.setattr("app.api.generate.generate_diagram", fake_generate_diagram)
    identity_override(Principal.authenticated("alice"))

    response = client.post(
        "/api/generate",
        data={"sourceType": "text-file", "details": "some details"},
        files={"file": ("notes.txt", b"Hello world", "text/plain")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["result"]["mermaidCode"].startswith("flowchart LR")
    assert body["result"]["sourceText"] == "Hello world"
    assert body["result"]["sessionId"] == "test-session-id"
    assert chat_service.create_calls == [
        {
            "source_text": "Hello world",
            "additional_details": "some details",
            "principal": Principal.authenticated("alice"),
            "mermaid_code": "flowchart LR\nA --> B",
        }
    ]


def test_generate_link_jira_success_returns_200(client, monkeypatch):
    from app.services.files.extract import NormalizedSource

    async def fake_normalize_link(value):
        return NormalizedSource(
            type="link",
            title="Jira: ABC-1",
            text="Fix the bug\n\nSteps to reproduce...",
            description=f"Jira · {value}",
            url=value,
            stub=False,
        )

    async def fake_generate_diagram(source_text, details, client=None):
        return "flowchart LR\nA --> B"

    monkeypatch.setattr("app.api.generate.normalize_link", fake_normalize_link)
    monkeypatch.setattr("app.api.generate.generate_diagram", fake_generate_diagram)

    response = client.post(
        "/api/generate",
        data={"sourceType": "link", "link": "https://jira.example.com/browse/ABC-1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["result"]["sourceContext"]["stub"] is False


def test_generate_llm_failure_returns_500_diagram_generation(client, chat_service, monkeypatch):
    async def fake_generate_diagram(source_text, details, client=None):
        raise RuntimeError("LLM down")

    monkeypatch.setattr("app.api.generate.generate_diagram", fake_generate_diagram)

    response = client.post(
        "/api/generate",
        data={"sourceType": "text-file"},
        files={"file": ("notes.txt", b"Hello world", "text/plain")},
    )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "diagram-generation"
    assert chat_service.create_calls == []


def test_generate_persistence_failure_returns_500_diagram_generation(
    client, chat_service, monkeypatch
):
    async def fake_generate_diagram(source_text, details, client=None):
        return "flowchart LR\nA --> B"

    monkeypatch.setattr("app.api.generate.generate_diagram", fake_generate_diagram)
    chat_service.error = RuntimeError("database write failed")

    response = client.post(
        "/api/generate",
        data={"sourceType": "text-file"},
        files={"file": ("notes.txt", b"Hello world", "text/plain")},
    )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "diagram-generation"
