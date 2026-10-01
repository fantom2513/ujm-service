import asyncio
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.domain.identity import Principal
from app.infrastructure.db.models import GenerateRequest, Session, Turn
from app.infrastructure.db.repositories import TurnRepository
from app.services.chat.service import (
    ClaimedChatTurn,
    ClaimedGenerateTurn,
    RequestIdConflict,
    RequestInProgress,
    run_claimed_chat,
    run_claimed_generate,
)
from app.services.files.extract import NormalizedSource
from app.services.openai.chat import ChatEditResult
from tests.integration._chat_helpers import (
    create_initial_session,
    delete_session,
    make_chat_service,
    principal_for,
    upgrade_head,
)


async def test_chat_claim_background_poll_and_replay(real_database_url, monkeypatch):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)
    entered = asyncio.Event()
    release = asyncio.Event()
    shortened = asyncio.Event()
    heartbeat_seen = asyncio.Event()

    original_heartbeat = TurnRepository.heartbeat_claim

    async def observed_heartbeat(self, session_id, request_id, claim_token):
        updated = await original_heartbeat(self, session_id, request_id, claim_token)
        if shortened.is_set() and updated == 1:
            heartbeat_seen.set()
        return updated

    async def slow_edit(*_args, **_kwargs):
        entered.set()
        await release.wait()
        return ChatEditResult(mermaid_code="flowchart LR\nA-->C", message="done", usage=None)

    monkeypatch.setattr("app.services.chat.service.chat_edit", slow_edit)
    monkeypatch.setattr("app.services.chat.service.CHAT_HEARTBEAT_INTERVAL_SECONDS", 0.02)
    monkeypatch.setattr(TurnRepository, "heartbeat_claim", observed_heartbeat)
    try:
        async with factory() as request_db:
            service = make_chat_service(request_db, factory)
            claim = await service.claim_or_replay(
                session_id=session_id, request_id="async-chat", principal=principal_for(None),
                message="change", action_type="FREEFORM", client_mermaid="ignored",
            )
        assert isinstance(claim, ClaimedChatTurn)
        task = asyncio.create_task(run_claimed_chat(claim, factory, None, Settings()))
        await asyncio.wait_for(entered.wait(), timeout=2)
        async with factory() as db:
            async with db.begin():
                await db.execute(sa.update(Turn).where(
                    Turn.session_id == session_id, Turn.request_id == "async-chat",
                ).values(claimed_until=sa.func.clock_timestamp() + sa.text("interval '1 second'")))
        shortened.set()
        await asyncio.wait_for(heartbeat_seen.wait(), timeout=2)
        async with factory() as db:
            assert await make_chat_service(db, factory).poll_turn(session_id, "async-chat", principal_for(None)) == {"status": "processing"}
            turn = await TurnRepository(db).get_fresh(session_id, "async-chat")
            database_now = await db.scalar(sa.select(sa.func.clock_timestamp()))
            assert (turn.claimed_until - database_now).total_seconds() > 20
        release.set()
        await task
        async with factory() as db:
            assert (await make_chat_service(db, factory).poll_turn(session_id, "async-chat", principal_for(None)))["result"]["message"] == "done"
        async with factory() as db:
            replay = await make_chat_service(db, factory).claim_or_replay(
                session_id=session_id, request_id="async-chat", principal=principal_for(None),
                message="change", action_type="FREEFORM", client_mermaid="ignored",
            )
            assert replay["ok"] is True
    finally:
        release.set()
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_background_failure_is_stored_and_replayed(real_database_url, monkeypatch):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)

    async def failing_edit(*_args, **_kwargs):
        raise RuntimeError("private model error")

    monkeypatch.setattr("app.services.chat.service.chat_edit", failing_edit)
    try:
        async with factory() as db:
            claim = await make_chat_service(db, factory).claim_or_replay(
                session_id=session_id, request_id="failed-chat", principal=Principal.anonymous(),
                message="change", action_type="FREEFORM", client_mermaid="ignored",
            )
        assert isinstance(claim, ClaimedChatTurn)
        await run_claimed_chat(claim, factory, None, Settings())
        async with factory() as db:
            service = make_chat_service(db, factory)
            poll = await service.poll_turn(session_id, "failed-chat", Principal.anonymous())
        assert poll["ok"] is False
        assert poll["error"]["code"] == "diagram-generation"
        assert "private" not in str(poll)
        async with factory() as db:
            assert (await db.get(Session, session_id)).lock_token is None
        async with factory() as db:
            replay = await make_chat_service(db, factory).claim_or_replay(
                session_id=session_id, request_id="failed-chat", principal=Principal.anonymous(),
                message="change", action_type="FREEFORM", client_mermaid="ignored",
            )
        assert replay == poll
        async with factory() as db:
            retry = await make_chat_service(db, factory).claim_or_replay(
                session_id=session_id, request_id="new-chat-after-failure",
                principal=Principal.anonymous(), message="change",
                action_type="FREEFORM", client_mermaid="ignored",
            )
        assert isinstance(retry, ClaimedChatTurn)
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_generate_request_race_and_background_result(real_database_url, monkeypatch):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    request_id = f"generate-{uuid.uuid4()}"
    source = NormalizedSource(type="text-file", title="input.txt", text="hello", description="TXT")

    async def claim_once():
        async with factory() as db:
            return await make_chat_service(db, factory).claim_generate(
                request_id=request_id, request_hash="a" * 64, principal=Principal.anonymous(),
                source=source, details="details",
            )

    async def fake_generate(*_args, **_kwargs):
        return "flowchart LR\nA-->B"

    monkeypatch.setattr("app.services.chat.service.generate_diagram", fake_generate)
    session_id = None
    try:
        outcomes = await asyncio.gather(claim_once(), claim_once(), return_exceptions=True)
        winners = [item for item in outcomes if isinstance(item, ClaimedGenerateTurn)]
        assert len(winners) == 1
        assert any(isinstance(item, RequestInProgress) for item in outcomes)
        claim = winners[0]
        session_id = claim.session_id
        async with factory() as db:
            rows = await db.scalar(sa.select(sa.func.count()).select_from(GenerateRequest).where(GenerateRequest.request_id == request_id))
            assert rows == 1
            session = await db.get(Session, session_id)
            assert session.head_version_id is None
            assert await TurnRepository(db).get_fresh(session_id, request_id) is not None
        await run_claimed_generate(claim, factory, None, Settings())
        async with factory() as db:
            result = await make_chat_service(db, factory).poll_turn(session_id, request_id, Principal.anonymous())
        assert result["ok"] is True
        assert result["result"]["sessionId"] == session_id
        replay = await claim_once()
        assert replay == result
        async with factory() as db:
            with pytest.raises(RequestIdConflict):
                await make_chat_service(db, factory).claim_generate(
                    request_id=request_id, request_hash="b" * 64, principal=Principal.anonymous(),
                    source=source, details="different",
                )
    finally:
        if session_id:
            await delete_session(engine, session_id)
        await engine.dispose()


async def test_claim_heartbeat_prevents_expiry(real_database_url):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)
    try:
        async with factory() as db:
            async with db.begin():
                await TurnRepository(db).claim_or_take_over(
                    session_id=session_id, request_id="heartbeat", request_hash="a" * 64,
                    claim_token="owner", remaining_seconds=1,
                )
                await db.execute(sa.update(Turn).where(Turn.session_id == session_id, Turn.request_id == "heartbeat").values(claimed_until=sa.func.clock_timestamp() + sa.text("interval '1 second'")))
        async with factory() as db:
            async with db.begin():
                assert await TurnRepository(db).heartbeat_claim(session_id, "heartbeat", "owner") == 1
                assert await TurnRepository(db).complete(
                    session_id=session_id, request_id="heartbeat", claim_token="owner",
                    response_json={"ok": True, "result": {}},
                ) == 1
        async with factory() as db:
            async with db.begin():
                await TurnRepository(db).claim_or_take_over(
                    session_id=session_id, request_id="expired", request_hash="a" * 64,
                    claim_token="owner", remaining_seconds=1,
                )
                await db.execute(sa.update(Turn).where(Turn.session_id == session_id, Turn.request_id == "expired").values(claimed_until=sa.func.clock_timestamp() - sa.text("interval '1 second'")))
                assert await TurnRepository(db).complete(
                    session_id=session_id, request_id="expired", claim_token="owner",
                    response_json={"ok": True, "result": {}},
                ) == 0
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_generate_expired_anonymous_claim_can_be_taken_over_by_its_authenticated_owner(real_database_url):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    request_id = f"generate-{uuid.uuid4()}"
    source = NormalizedSource(type="text-file", title="input.txt", text="hello", description="TXT")
    session_id = None
    try:
        async with factory() as db:
            first = await make_chat_service(db, factory).claim_generate(
                request_id=request_id, request_hash="a" * 64, principal=Principal.anonymous(),
                source=source, details="",
            )
        assert isinstance(first, ClaimedGenerateTurn)
        session_id = first.session_id
        async with factory() as db:
            async with db.begin():
                await db.execute(sa.update(Turn).where(
                    Turn.session_id == session_id, Turn.request_id == request_id,
                ).values(claimed_until=sa.func.clock_timestamp() - sa.text("interval '1 second'")))
        async with factory() as db:
            second = await make_chat_service(db, factory).claim_generate(
                request_id=request_id, request_hash="a" * 64,
                principal=Principal.authenticated("alice"), source=source, details="",
            )
        assert isinstance(second, ClaimedGenerateTurn)
        assert second.session_id == session_id
        assert second.owner_id == "alice"
        async with factory() as db:
            assert (await db.get(Session, session_id)).user_id == "alice"
    finally:
        if session_id:
            await delete_session(engine, session_id)
        await engine.dispose()
