import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.infrastructure.db.repositories import MessageRepository, SessionRepository
from app.services.chat.service import RequestInProgress, SessionNotFound
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

    async def fake_chat_edit(options, settings=None, *, deadline=None):
        return ChatEditResult(
            mermaid_code="flowchart LR\nA-->C",
            message="Bound and changed",
            usage=None,
        )

    monkeypatch.setattr("app.services.chat.service.chat_edit", fake_chat_edit)

    try:
        async with factory() as db:
            await make_chat_service(db, factory).run_chat(
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


async def test_anonymous_bind_survives_later_llm_failure(
    real_database_url, monkeypatch
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory, user_id=None)

    async def failing_chat_edit(options, settings=None, *, deadline=None):
        raise RuntimeError("injected LLM failure")

    monkeypatch.setattr("app.services.chat.service.chat_edit", failing_chat_edit)

    try:
        async with factory() as db:
            try:
                await make_chat_service(db, factory).run_chat(
                    session_id=session_id,
                    user_id="alice",
                    message="change",
                    action_type="FREEFORM",
                    client_mermaid="ignored",
                )
            except RuntimeError as error:
                assert str(error) == "injected LLM failure"
            else:
                raise AssertionError("Injected LLM failure was not raised")

        async with factory() as db:
            stored = await SessionRepository(db).get(session_id)
            assert stored is not None
            assert stored.user_id == "alice"
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


class ReachedLLM(RuntimeError):
    """Test signal proving that ownership resolution allowed the request."""


async def test_concurrent_bind_by_different_users_chooses_exactly_one_owner(
    real_database_url, monkeypatch
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory, user_id=None)

    async def stop_at_llm(options, settings=None, *, deadline=None):
        raise ReachedLLM

    monkeypatch.setattr("app.services.chat.service.chat_edit", stop_at_llm)

    async def run_as(user_id: str):
        async with factory() as db:
            return await make_chat_service(db, factory).run_chat(
                session_id=session_id,
                user_id=user_id,
                message="change",
                action_type="FREEFORM",
                client_mermaid="ignored",
            )

    users = ["alice", "bob"]
    try:
        outcomes = await asyncio.gather(
            *(run_as(user_id) for user_id in users),
            return_exceptions=True,
        )

        assert sum(isinstance(outcome, ReachedLLM) for outcome in outcomes) == 1
        assert sum(isinstance(outcome, SessionNotFound) for outcome in outcomes) == 1
        winner = users[next(
            index
            for index, outcome in enumerate(outcomes)
            if isinstance(outcome, ReachedLLM)
        )]

        async with factory() as db:
            stored = await SessionRepository(db).get(session_id)
            assert stored is not None
            assert stored.user_id == winner
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_concurrent_bind_by_same_user_allows_both_requests(
    real_database_url, monkeypatch
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory, user_id=None)

    llm_entered = asyncio.Event()
    release_llm = asyncio.Event()
    both_reached_acquire = asyncio.Event()
    acquire_calls = 0
    original_acquire = SessionRepository.acquire_lease

    async def observed_acquire(self, *args, **kwargs):
        nonlocal acquire_calls
        acquire_calls += 1
        if acquire_calls == 2:
            both_reached_acquire.set()
        return await original_acquire(self, *args, **kwargs)

    async def stop_at_llm(options, settings=None, *, deadline=None):
        llm_entered.set()
        await release_llm.wait()
        raise ReachedLLM

    monkeypatch.setattr(SessionRepository, "acquire_lease", observed_acquire)
    monkeypatch.setattr("app.services.chat.service.chat_edit", stop_at_llm)

    async def run_as_alice():
        async with factory() as db:
            return await make_chat_service(db, factory).run_chat(
                session_id=session_id,
                user_id="alice",
                message="change",
                action_type="FREEFORM",
                client_mermaid="ignored",
            )

    try:
        first = asyncio.create_task(run_as_alice())
        second = asyncio.create_task(run_as_alice())
        await asyncio.wait_for(llm_entered.wait(), timeout=1)
        await asyncio.wait_for(both_reached_acquire.wait(), timeout=1)
        done, _ = await asyncio.wait_for(
            asyncio.wait({first, second}, return_when=asyncio.FIRST_COMPLETED),
            timeout=1,
        )
        assert len(done) == 1
        assert isinstance(next(iter(done)).exception(), RequestInProgress)
        release_llm.set()
        outcomes = await asyncio.gather(
            first,
            second,
            return_exceptions=True,
        )

        assert sum(isinstance(outcome, ReachedLLM) for outcome in outcomes) == 1
        assert sum(
            isinstance(outcome, RequestInProgress) for outcome in outcomes
        ) == 1
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

    async def forbidden_chat_edit(options, settings=None, *, deadline=None):
        nonlocal llm_called
        llm_called = True
        raise AssertionError("LLM must not be called for a foreign session")

    monkeypatch.setattr("app.services.chat.service.chat_edit", forbidden_chat_edit)

    try:
        async with factory() as db:
            try:
                await make_chat_service(db, factory).run_chat(
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

    async def forbidden_chat_edit(options, settings=None, *, deadline=None):
        raise AssertionError("LLM must not be called for a missing session")

    monkeypatch.setattr("app.services.chat.service.chat_edit", forbidden_chat_edit)

    try:
        async with factory() as db:
            try:
                await make_chat_service(db, factory).run_chat(
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
