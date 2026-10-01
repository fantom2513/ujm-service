import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.domain.identity import Principal
from app.main import app
from app.infrastructure.llm.deadline import LLMDeadline
from app.services.chat.service import ClaimedGenerateTurn, RequestIdConflict, RequestInProgress
from app.services.files.extract import NormalizedSource


class FakeService:
    def __init__(self):
        self.calls = []
        self.error = None

    async def claim_generate(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {
            "ok": True,
            "result": {
                "sessionId": "server-session",
                "title": "Тестовая User Flow-схема",
                "mermaidCode": "flowchart LR\nA-->B",
                "sourceText": kwargs["source"].text,
                "sourceContext": {"type": kwargs["source"].type, "title": kwargs["source"].title, "description": kwargs["source"].description},
                "details": kwargs["details"],
                "chat": [],
                "warnings": [],
            },
        }


@pytest.fixture
def fake_service():
    service = FakeService()
    app.dependency_overrides[deps.get_chat_service] = lambda: service
    app.dependency_overrides[deps.get_current_identity] = Principal.anonymous
    try:
        with TestClient(app) as client:
            yield client, service
    finally:
        app.dependency_overrides.clear()


def test_generate_requires_request_id(fake_service):
    client, service = fake_service
    response = client.post("/api/generate", data={"sourceType": "link", "link": "https://jira.example.com/browse/A-1"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "request-id-required"
    assert not service.calls


@pytest.mark.parametrize(
    "data,expected",
    [
        ({"sourceType": "text-file"}, "file-required"),
        ({"sourceType": "link", "link": ""}, "link-required"),
        ({"sourceType": "link", "link": "bad"}, "invalid-link"),
    ],
)
def test_generate_validation(fake_service, data, expected):
    client, service = fake_service
    response = client.post("/api/generate", data={**data, "requestId": "r-1"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == expected
    assert not service.calls


def test_generate_replays_completed_result(fake_service):
    client, service = fake_service
    response = client.post(
        "/api/generate",
        data={"sourceType": "text-file", "details": "details", "requestId": "r-1"},
        files={"file": ("notes.txt", b"Hello world", "text/plain")},
    )
    assert response.status_code == 200
    assert response.json()["sessionId"] == "server-session"
    assert service.calls[0]["request_id"] == "r-1"
    assert service.calls[0]["source"].text == "Hello world"


def test_generate_new_claim_returns_202_and_poll_result(fake_service, monkeypatch):
    client, service = fake_service
    scheduled = []

    async def claim(**_kwargs):
        return ClaimedGenerateTurn(
            session_id="server-session", request_id="r-1", owner_id=None,
            source=NormalizedSource(type="text-file", title="notes.txt", text="Hello", description="TXT"),
            details="", claim_token="token", deadline=LLMDeadline.from_timeout_ms(900_000),
        )

    def register(_app, work, name):
        scheduled.append(name)
        work.close()

    monkeypatch.setattr(service, "claim_generate", claim)
    monkeypatch.setattr("app.api.generate.register_background_task", register)
    service._db_sessionmaker = None
    service._redis = None
    service._settings = None

    response = client.post(
        "/api/generate", data={"requestId": "r-1", "sourceType": "text-file"},
        files={"file": ("notes.txt", b"Hello", "text/plain")},
    )
    assert response.status_code == 202
    assert response.json() == {"status": "processing", "sessionId": "server-session", "requestId": "r-1"}
    assert scheduled == ["generate:server-session:r-1"]

    async def poll(*_args):
        return {"ok": True, "result": {"sessionId": "server-session", "mermaidCode": "flowchart LR\nA-->B"}}

    service.poll_turn = poll
    polled = client.get("/api/generate/server-session/turns/r-1")
    assert polled.status_code == 200
    assert polled.json() == {"sessionId": "server-session", "mermaidCode": "flowchart LR\nA-->B"}


@pytest.mark.parametrize("error,code", [(RequestIdConflict(), "request-id-conflict"), (RequestInProgress(), "request-in-progress")])
def test_generate_claim_conflicts(fake_service, error, code):
    client, service = fake_service
    service.error = error
    response = client.post(
        "/api/generate",
        data={"sourceType": "text-file", "requestId": "r-1"},
        files={"file": ("notes.txt", b"Hello world", "text/plain")},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == code
