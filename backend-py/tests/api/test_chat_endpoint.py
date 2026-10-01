import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.api.schemas import ChatResult
from app.domain.identity import Principal
from app.infrastructure.llm.errors import LLMError
from app.infrastructure.llm.deadline import LLMDeadline
from app.main import app
from app.services.chat.service import (
    ClaimedChatTurn,
    RequestIdConflict,
    RequestInProgress,
    SessionNotFound,
    VersionConflict,
)


class FakeChatService:
    def __init__(self):
        self.error: Exception | None = None
        self.calls: list[dict] = []

    async def claim_or_replay(self, **kwargs) -> dict[str, object]:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        result = ChatResult(
            session_id=kwargs["session_id"],
            mermaid_code="flowchart LR\nA-->B",
            message="Готово",
        )
        return {"ok": True, "result": result.model_dump(by_alias=True)}


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
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(deps.get_chat_service, None)


def test_chat_requires_nonempty_session_id(client, chat_service):
    response = client.post("/api/chat", data={"sessionId": "   "})

    assert response.status_code == 400
    assert response.json() == {
        "ok": False,
        "sessionId": "",
        "error": {
            "code": "session-required",
            "message": "Необходимо указать идентификатор сессии",
        },
    }
    assert chat_service.calls == []


@pytest.mark.parametrize("request_id", [None, "", "   "])
def test_chat_requires_nonempty_request_id(client, chat_service, request_id):
    data = {"sessionId": "session-1"}
    if request_id is not None:
        data["requestId"] = request_id

    response = client.post("/api/chat", data=data)

    assert response.status_code == 400
    assert response.json() == {
        "ok": False,
        "sessionId": "session-1",
        "error": {
            "code": "request-id-required",
            "message": "Необходимо указать идентификатор запроса",
        },
    }
    assert chat_service.calls == []


def test_chat_rejects_request_id_longer_than_128_characters(client, chat_service):
    response = client.post(
        "/api/chat",
        data={"sessionId": "session-1", "requestId": "r" * 129},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid-request"
    assert chat_service.calls == []


def test_chat_accepts_128_character_request_id_after_trimming(client, chat_service):
    response = client.post(
        "/api/chat",
        data={"sessionId": "session-1", "requestId": f"  {'r' * 128}  "},
    )

    assert response.status_code == 200
    assert chat_service.calls[0]["request_id"] == "r" * 128


def test_chat_returns_session_not_found_without_leaking_ownership(
    client, chat_service, identity_override
):
    chat_service.error = SessionNotFound()
    identity_override(Principal.authenticated("mallory"))

    response = client.post(
        "/api/chat",
        data={
            "sessionId": "unknown",
            "requestId": "request-unknown",
            "message": "change it",
        },
    )

    assert response.status_code == 404
    assert response.json()["sessionId"] == "unknown"
    assert response.json()["error"]["code"] == "session-not-found"
    assert chat_service.calls[0]["principal"] == Principal.authenticated("mallory")


def test_chat_returns_request_in_progress_as_conflict(client, chat_service):
    chat_service.error = RequestInProgress()

    response = client.post(
        "/api/chat",
        data={
            "sessionId": "session-1",
            "requestId": "request-busy",
            "message": "change it",
        },
    )

    assert response.status_code == 409
    assert response.json()["sessionId"] == "session-1"
    assert response.json()["error"]["code"] == "request-in-progress"


def test_chat_returns_request_id_conflict_as_conflict(client, chat_service):
    chat_service.error = RequestIdConflict()

    response = client.post(
        "/api/chat",
        data={
            "sessionId": "session-1",
            "requestId": "reused-request",
            "message": "change it",
        },
    )

    assert response.status_code == 409
    assert response.json()["sessionId"] == "session-1"
    assert response.json()["error"]["code"] == "request-id-conflict"


def test_chat_returns_version_conflict_as_conflict(client, chat_service):
    chat_service.error = VersionConflict()

    response = client.post(
        "/api/chat",
        data={
            "sessionId": "session-1",
            "requestId": "request-version-conflict",
            "message": "change it",
        },
    )

    assert response.status_code == 409
    assert response.json()["sessionId"] == "session-1"
    assert response.json()["error"]["code"] == "version-conflict"


def test_chat_success_returns_standard_result_and_passes_parsed_fields(
    client, chat_service, identity_override
):
    identity_override(Principal.authenticated("alice"))
    response = client.post(
        "/api/chat",
        data={
            "sessionId": "session-1",
            "requestId": "  request-success  ",
            "message": "add B",
            "actionType": "SIMPLIFY",
            "mermaidCode": "client copy",
            "sourceText": "must be ignored by the route",
            "history": '[{"role":"user","text":"bogus"}]',
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "sessionId": "session-1",
        "mermaidCode": "flowchart LR\nA-->B",
        "message": "Готово",
    }
    assert chat_service.calls == [
        {
            "session_id": "session-1",
            "request_id": "request-success",
            "principal": Principal.authenticated("alice"),
            "message": "add B",
            "action_type": "SIMPLIFY",
            "client_mermaid": "client copy",
            "attachment_context": "",
        }
    ]


def test_chat_new_claim_returns_202_and_poll_exposes_states(client, chat_service, monkeypatch):
    scheduled = []

    async def claim(**_kwargs):
        return ClaimedChatTurn(
            session_id="session-1", request_id="r-1", owner_id=None,
            message="change", resolved_action="FREEFORM", attachment_context="",
            claim_token="token", deadline=LLMDeadline.from_timeout_ms(900_000),
        )

    def register(_app, work, name):
        scheduled.append(name)
        work.close()

    monkeypatch.setattr(chat_service, "claim_or_replay", claim)
    monkeypatch.setattr("app.api.chat.register_background_task", register)
    chat_service._db_sessionmaker = None
    chat_service._redis = None
    chat_service._settings = None

    response = client.post("/api/chat", data={"sessionId": "session-1", "requestId": "r-1", "message": "change"})
    assert response.status_code == 202
    assert response.json() == {"status": "processing", "sessionId": "session-1", "requestId": "r-1"}
    assert scheduled == ["chat:session-1:r-1"]

    for outcome, expected in [
        ({"status": "processing"}, {"status": "processing"}),
        ({"status": "failed", "retryable": True}, {"status": "failed", "retryable": True}),
        ({"ok": True, "result": {"sessionId": "session-1", "mermaidCode": "flowchart LR\nA-->B", "message": "done"}}, {"sessionId": "session-1", "mermaidCode": "flowchart LR\nA-->B", "message": "done"}),
        ({"ok": False, "error": {"code": "diagram-generation", "message": "failed"}}, {"ok": False, "error": {"code": "diagram-generation", "message": "failed"}}),
        (None, None),
    ]:
        async def poll(*_args):
            return outcome

        monkeypatch.setattr(chat_service, "poll_turn", poll, raising=False)
        polled = client.get("/api/chat/session-1/turns/r-1")
        assert polled.status_code == (404 if expected is None else 200)
        if expected is not None:
            assert polled.json() == expected


def test_chat_defaults_action_type_to_freeform(client, chat_service):
    response = client.post(
        "/api/chat",
        data={
            "sessionId": "session-1",
            "requestId": "request-default-action",
            "message": "add B",
        },
    )

    assert response.status_code == 200
    assert chat_service.calls[0]["action_type"] == "FREEFORM"


def test_chat_with_txt_attachment_passes_extracted_text_as_attachment_context(
    client, chat_service
):
    response = client.post(
        "/api/chat",
        data={
            "sessionId": "session-1",
            "requestId": "request-with-file",
            "message": "what does the attachment say?",
        },
        files={"file": ("notes.txt", b"Invoice total: 100 USD", "text/plain")},
    )

    assert response.status_code == 200
    assert chat_service.calls[0]["attachment_context"] == "Invoice total: 100 USD"


def test_chat_without_attachment_passes_empty_attachment_context(client, chat_service):
    response = client.post(
        "/api/chat",
        data={"sessionId": "session-1", "requestId": "request-no-file", "message": "hi"},
    )

    assert response.status_code == 200
    assert chat_service.calls[0]["attachment_context"] == ""


def test_chat_rejects_unsupported_attachment_format(client, chat_service):
    response = client.post(
        "/api/chat",
        data={"sessionId": "session-1", "requestId": "request-bad-format", "message": "hi"},
        files={"file": ("legacy.xls", b"binary", "application/vnd.ms-excel")},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "file-format"
    assert chat_service.calls == []


def test_chat_rejects_oversized_attachment(client, chat_service, monkeypatch):
    from app.api import chat as chat_module

    monkeypatch.setattr(chat_module, "get_settings", lambda: _TinySettings())

    response = client.post(
        "/api/chat",
        data={"sessionId": "session-1", "requestId": "request-too-big", "message": "hi"},
        files={"file": ("notes.txt", b"0123456789", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "file-size"
    assert chat_service.calls == []


def test_chat_rejects_attachment_whose_content_cannot_be_extracted(client, chat_service):
    # An empty .docx (not a real zip/OOXML body) fails parsing -> normalize_text_file
    # falls back to its generic stub, which must not be treated as valid text.
    response = client.post(
        "/api/chat",
        data={"sessionId": "session-1", "requestId": "request-empty-doc", "message": "hi"},
        files={
            "file": (
                "empty.docx",
                b"not a real docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "attachment-error"
    assert chat_service.calls == []


class _TinySettings:
    max_chat_attachment_bytes = 5


def test_chat_llm_error_returns_diagram_generation_with_session_id(
    client, chat_service
):
    chat_service.error = LLMError("SCHEMA_MISMATCH", "bad model output")

    response = client.post(
        "/api/chat",
        data={
            "sessionId": "session-1",
            "requestId": "request-llm-error",
            "message": "add B",
        },
    )

    assert response.status_code == 500
    assert response.json()["sessionId"] == "session-1"
    assert response.json()["error"]["code"] == "diagram-generation"
