import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.main import app
from app.services.chat.service import ChatService


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_chat_returns_501_with_standard_envelope(client):
    response = client.post("/api/chat")
    assert response.status_code == 501
    assert response.json() == {
        "ok": False,
        "error": {"code": "not-implemented", "message": "Chat is not implemented yet"},
    }


def test_chat_endpoint_respects_dependency_overrides(client):
    # A dependency override that blows up on use only takes effect if
    # app.dependency_overrides is actually being consulted for this route —
    # if the override were ignored, the real get_redis would run instead and
    # the response would stay 501.
    def broken_redis():
        raise RuntimeError("override was actually used")

    app.dependency_overrides[deps.get_redis] = broken_redis
    try:
        response = client.post("/api/chat")
    finally:
        app.dependency_overrides.pop(deps.get_redis, None)

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal-error"


def test_chat_endpoint_never_constructs_chat_service(client, monkeypatch):
    def boom(self, *args, **kwargs):
        raise AssertionError("ChatService must not be constructed by the stub /api/chat route")

    monkeypatch.setattr(ChatService, "__init__", boom)

    response = client.post("/api/chat")

    assert response.status_code == 501
