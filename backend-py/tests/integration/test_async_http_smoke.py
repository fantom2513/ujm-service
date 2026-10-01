import asyncio
import json

import httpx

from app.config import Settings, get_settings
from app.infrastructure.db.models import Session
from app.main import app
from app.services.files.extract import NormalizedSource
from tests.integration._chat_helpers import delete_session, upgrade_head


async def _poll(client: httpx.AsyncClient, path: str) -> httpx.Response:
    for _ in range(100):
        response = await client.get(path)
        if response.json().get("status") != "processing":
            return response
        await asyncio.sleep(0.05)
    raise AssertionError(f"Turn stayed processing: {path}")


async def test_real_http_generate_then_chat_with_streaming_llm(
    real_database_url, mock_llm_server, monkeypatch
):
    await upgrade_head()
    generate_calls = [0]
    chat_calls = [0]
    generate_url = mock_llm_server(
        {"choices": [{"message": {"content": "flowchart LR\nA-->B"}}]},
        call_counter=generate_calls,
    )
    chat_url = mock_llm_server(
        {"choices": [{"message": {"content": json.dumps({
            "mermaid": "flowchart LR\nA-->C", "message": "Changed",
        })}}]},
        call_counter=chat_calls,
    )
    settings = Settings(database_url=real_database_url, llm_url=generate_url)
    app.dependency_overrides[get_settings] = lambda: settings
    session_ids = []
    link_started = asyncio.Event()
    release_link = asyncio.Event()

    async def delayed_link(value: str) -> NormalizedSource:
        link_started.set()
        await release_link.wait()
        return NormalizedSource(
            type="link", title="Jira: ABC-1", text="Actual Jira issue",
            description="Jira", url=value, stub=False,
        )

    monkeypatch.setattr("app.services.chat.service.normalize_link", delayed_link)
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                generated = await client.post(
                    "/api/generate",
                    data={"requestId": "http-generate", "sourceType": "text-file"},
                    files={"file": ("notes.txt", b"First step", "text/plain")},
                )
                assert generated.status_code == 202, generated.text
                session_id = generated.json()["sessionId"]
                session_ids.append(session_id)
                poll_path = f"/api/generate/{session_id}/turns/http-generate"
                result = await _poll(client, poll_path)
                assert result.status_code == 200, result.text
                assert result.json()["mermaidCode"] == "flowchart LR\nA-->B"
                assert generate_calls == [1]
                async with app.state.db_sessionmaker() as db:
                    assert (await db.get(Session, session_id)).lock_token is None

                replay = await client.post(
                    "/api/generate",
                    data={"requestId": "http-generate", "sourceType": "text-file"},
                    files={"file": ("notes.txt", b"First step", "text/plain")},
                )
                assert replay.status_code == 200, replay.text
                assert replay.json()["sessionId"] == session_id
                assert generate_calls == [1]

                settings.llm_url = chat_url
                changed = await client.post(
                    "/api/chat",
                    data={"sessionId": session_id, "requestId": "http-chat", "message": "Change B to C"},
                )
                assert changed.status_code == 202, changed.text
                chat_result = await _poll(client, f"/api/chat/{session_id}/turns/http-chat")
                assert chat_result.status_code == 200, chat_result.text
                assert chat_result.json()["mermaidCode"] == "flowchart LR\nA-->C"
                assert chat_calls == [1]
                async with app.state.db_sessionmaker() as db:
                    assert (await db.get(Session, session_id)).lock_token is None

                chat_replay = await client.post(
                    "/api/chat",
                    data={"sessionId": session_id, "requestId": "http-chat", "message": "Change B to C"},
                )
                assert chat_replay.status_code == 200, chat_replay.text
                assert chat_replay.json()["message"] == "Changed"
                assert chat_calls == [1]

                settings.llm_url = generate_url
                link_claim = await client.post(
                    "/api/generate",
                    data={"requestId": "http-link", "sourceType": "link", "link": "https://jira.example.com/browse/ABC-1"},
                )
                assert link_claim.status_code == 202, link_claim.text
                link_session_id = link_claim.json()["sessionId"]
                session_ids.append(link_session_id)
                await asyncio.wait_for(link_started.wait(), timeout=2)
                async with app.state.db_sessionmaker() as db:
                    provisional = await db.get(Session, link_session_id)
                    assert provisional.source_text != "Actual Jira issue"
                release_link.set()
                link_result = await _poll(client, f"/api/generate/{link_session_id}/turns/http-link")
                assert link_result.status_code == 200, link_result.text
                assert link_result.json()["sourceText"] == "Actual Jira issue"
                async with app.state.db_sessionmaker() as db:
                    assert (await db.get(Session, link_session_id)).source_text == "Actual Jira issue"
    finally:
        release_link.set()
        app.dependency_overrides.pop(get_settings, None)
        if session_ids:
            from sqlalchemy.ext.asyncio import create_async_engine

            engine = create_async_engine(real_database_url)
            try:
                for session_id in session_ids:
                    await delete_session(engine, session_id)
            finally:
                await engine.dispose()
