from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.infrastructure.db.repositories import MessageRepository, SessionRepository
from app.services.chat.service import SessionNotFound
from app.services.openai.chat import ChatEditResult
from tests.integration._chat_helpers import (
    create_initial_session,
    delete_session,
    make_chat_service,
    upgrade_head,
)


async def test_anonymous_session_is_bound_to_supplied_user(
    real_database_url, monkeypatch
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory, user_id=None)

    async def fake_chat_edit(options, settings=None):
        return ChatEditResult(
            mermaid_code="flowchart LR\nA-->C",
            message="Bound and changed",
            usage=None,
        )

    monkeypatch.setattr("app.services.chat.service.chat_edit", fake_chat_edit)

    try:
        async with factory() as db:
            await make_chat_service(db).run_chat(
                session_id=session_id,
                user_id="alice",
                message="change",
                action_type="FREEFORM",
                client_mermaid="ignored",
            )

        async with factory() as db:
            stored = await SessionRepository(db).get(session_id)
            assert stored is not None
            assert stored.user_id == "alice"
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_owned_session_is_hidden_from_different_user(
    real_database_url, monkeypatch
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory, user_id="alice")
    llm_called = False

    async def forbidden_chat_edit(options, settings=None):
        nonlocal llm_called
        llm_called = True
        raise AssertionError("LLM must not be called for a foreign session")

    monkeypatch.setattr("app.services.chat.service.chat_edit", forbidden_chat_edit)

    try:
        async with factory() as db:
            try:
                await make_chat_service(db).run_chat(
                    session_id=session_id,
                    user_id="mallory",
                    message="steal it",
                    action_type="FREEFORM",
                    client_mermaid="ignored",
                )
            except SessionNotFound:
                pass
            else:
                raise AssertionError("Foreign session was not hidden")

        assert llm_called is False
        async with factory() as db:
            assert await MessageRepository(db).list_by_session(session_id) == []
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_unknown_session_raises_same_not_found_error(
    real_database_url, monkeypatch
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    unknown_id = "definitely-not-a-real-session"

    async def forbidden_chat_edit(options, settings=None):
        raise AssertionError("LLM must not be called for a missing session")

    monkeypatch.setattr("app.services.chat.service.chat_edit", forbidden_chat_edit)

    try:
        async with factory() as db:
            try:
                await make_chat_service(db).run_chat(
                    session_id=unknown_id,
                    user_id=None,
                    message="change",
                    action_type="FREEFORM",
                    client_mermaid="ignored",
                )
            except SessionNotFound:
                pass
            else:
                raise AssertionError("Missing session did not raise SessionNotFound")
    finally:
        await engine.dispose()
