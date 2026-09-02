import asyncio
from datetime import timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.infrastructure.db.models import DiagramVersion, Session
from app.infrastructure.db.repositories import MessageRepository, SessionRepository
from app.infrastructure.llm.errors import LLMError
from app.services.chat.service import VersionConflict
from app.services.openai.chat import ChatEditResult
from tests.integration._chat_helpers import (
    create_initial_session,
    delete_session,
    make_chat_service,
    upgrade_head,
)


async def run_chat(factory, session_id: str, message: str = "change"):
    async with factory() as db:
        return await make_chat_service(db, factory).run_chat(
            session_id=session_id,
            user_id=None,
            message=message,
            action_type="FREEFORM",
            client_mermaid="ignored",
        )


async def assert_lease_released(factory, session_id: str) -> None:
    async with factory() as db:
        stored = await SessionRepository(db).get(session_id)
        assert stored is not None
        assert stored.lock_token is None
        assert stored.locked_until is None


async def test_different_sessions_run_in_llm_concurrently_without_holding_connections(
    real_database_url, monkeypatch
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    first_session_id = await create_initial_session(factory)
    second_session_id = await create_initial_session(factory)
    entered_messages: set[str] = set()
    both_entered = asyncio.Event()
    release_llm = asyncio.Event()

    async def blocking_chat_edit(options, settings=None, *, deadline=None):
        entered_messages.add(options.user_message)
        if len(entered_messages) == 2:
            both_entered.set()
        await release_llm.wait()
        return ChatEditResult(
            mermaid_code=f"flowchart LR\nA-->{options.user_message}",
            message="Changed",
            usage=None,
        )

    monkeypatch.setattr("app.services.chat.service.chat_edit", blocking_chat_edit)

    try:
        baseline = engine.pool.checkedout()
        first = asyncio.create_task(run_chat(factory, first_session_id, "first"))
        second = asyncio.create_task(run_chat(factory, second_session_id, "second"))

        await asyncio.wait_for(both_entered.wait(), timeout=1)
        assert entered_messages == {"first", "second"}
        assert engine.pool.checkedout() == baseline

        release_llm.set()
        results = await asyncio.gather(first, second)
        assert {result.message for result in results} == {"Changed"}
        await assert_lease_released(factory, first_session_id)
        await assert_lease_released(factory, second_session_id)
    finally:
        release_llm.set()
        await delete_session(engine, first_session_id)
        await delete_session(engine, second_session_id)
        await engine.dispose()


async def test_llm_error_still_releases_lease(real_database_url, monkeypatch):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)

    async def failing_chat_edit(options, settings=None, *, deadline=None):
        raise RuntimeError("injected LLM failure")

    monkeypatch.setattr("app.services.chat.service.chat_edit", failing_chat_edit)

    try:
        with pytest.raises(RuntimeError, match="injected LLM failure"):
            await run_chat(factory, session_id)
        await assert_lease_released(factory, session_id)
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_llm_timeout_uses_boundary_deadline_and_rolls_back_chat_writes(
    real_database_url,
    monkeypatch,
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)
    deadline_created = False
    deadline_budget_ms: int | None = None
    deadline_sentinel = object()
    heartbeat_started = asyncio.Event()
    heartbeat_stopped = asyncio.Event()
    hold_heartbeat = asyncio.Event()
    original_bind_user = SessionRepository.bind_user
    original_acquire_lease = SessionRepository.acquire_lease

    class ObservedDeadlineFactory:
        @classmethod
        def from_timeout_ms(cls, timeout_ms: int):
            nonlocal deadline_created, deadline_budget_ms
            deadline_created = True
            deadline_budget_ms = timeout_ms
            return deadline_sentinel

    async def observed_bind_user(self, *args, **kwargs):
        assert deadline_created is False
        return await original_bind_user(self, *args, **kwargs)

    async def observed_acquire_lease(self, *args, **kwargs):
        assert deadline_created is True
        return await original_acquire_lease(self, *args, **kwargs)

    async def observed_heartbeat(self, session_id, lock_token):
        heartbeat_started.set()
        try:
            await hold_heartbeat.wait()
        finally:
            heartbeat_stopped.set()

    async def timeout_chat_edit(options, settings=None, *, deadline=None):
        assert deadline is deadline_sentinel
        await heartbeat_started.wait()
        raise LLMError("TIMEOUT", "logical LLM deadline exhausted")

    monkeypatch.setattr(
        "app.services.chat.service.LLMDeadline",
        ObservedDeadlineFactory,
    )
    monkeypatch.setattr(SessionRepository, "bind_user", observed_bind_user)
    monkeypatch.setattr(SessionRepository, "acquire_lease", observed_acquire_lease)
    monkeypatch.setattr(
        "app.services.chat.service.ChatService._heartbeat_lease",
        observed_heartbeat,
    )
    monkeypatch.setattr("app.services.chat.service.chat_edit", timeout_chat_edit)

    try:
        async with factory() as db:
            stored = await SessionRepository(db).get(session_id)
            assert stored is not None
            original_head_id = stored.head_version_id

        async with factory() as request_db:
            service = make_chat_service(request_db, factory)
            with pytest.raises(LLMError) as exc_info:
                await service.run_chat(
                    session_id=session_id,
                    user_id="owner",
                    message="change",
                    action_type="FREEFORM",
                    client_mermaid="ignored",
                )

        assert exc_info.value.code == "TIMEOUT"
        assert deadline_budget_ms == 120_000
        assert heartbeat_stopped.is_set()

        async with factory() as db:
            stored = await SessionRepository(db).get(session_id)
            assert stored is not None
            assert stored.user_id == "owner"
            assert stored.head_version_id == original_head_id
            assert stored.lock_token is None
            assert stored.locked_until is None
            assert await MessageRepository(db).list_by_session(session_id) == []
            version_count = await db.scalar(
                sa.select(sa.func.count())
                .select_from(DiagramVersion)
                .where(DiagramVersion.session_id == session_id)
            )
            assert version_count == 1
    finally:
        hold_heartbeat.set()
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_cancellation_stops_heartbeat_and_releases_lease(
    real_database_url, monkeypatch
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)
    llm_entered = asyncio.Event()
    hold_llm = asyncio.Event()

    async def blocking_chat_edit(options, settings=None, *, deadline=None):
        llm_entered.set()
        await hold_llm.wait()
        raise AssertionError("Cancelled LLM should not resume")

    monkeypatch.setattr("app.services.chat.service.chat_edit", blocking_chat_edit)

    try:
        task = asyncio.create_task(run_chat(factory, session_id))
        await asyncio.wait_for(llm_entered.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await assert_lease_released(factory, session_id)
    finally:
        hold_llm.set()
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_heartbeat_uses_another_session_and_main_db_is_idle_during_llm(
    real_database_url, monkeypatch
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)
    llm_entered = asyncio.Event()
    release_llm = asyncio.Event()
    heartbeat_seen = asyncio.Event()
    heartbeat_dbs = []
    original_heartbeat = SessionRepository.heartbeat_lease

    async def observed_heartbeat(self, *args, **kwargs):
        heartbeat_dbs.append(self._db)
        result = await original_heartbeat(self, *args, **kwargs)
        heartbeat_seen.set()
        return result

    async def blocking_chat_edit(options, settings=None, *, deadline=None):
        llm_entered.set()
        await release_llm.wait()
        return ChatEditResult(
            mermaid_code="flowchart LR\nA-->C",
            message="Changed",
            usage=None,
        )

    monkeypatch.setattr(SessionRepository, "heartbeat_lease", observed_heartbeat)
    monkeypatch.setattr(
        "app.services.chat.service.CHAT_HEARTBEAT_INTERVAL_SECONDS", 0.01
    )
    monkeypatch.setattr("app.services.chat.service.chat_edit", blocking_chat_edit)

    try:
        async with factory() as request_db:
            service = make_chat_service(request_db, factory)
            task = asyncio.create_task(
                service.run_chat(
                    session_id=session_id,
                    user_id=None,
                    message="change",
                    action_type="FREEFORM",
                    client_mermaid="ignored",
                )
            )
            await asyncio.wait_for(llm_entered.wait(), timeout=1)
            await asyncio.wait_for(heartbeat_seen.wait(), timeout=1)
            assert request_db.in_transaction() is False
            assert heartbeat_dbs
            assert all(heartbeat_db is not request_db for heartbeat_db in heartbeat_dbs)
            release_llm.set()
            await task

        await assert_lease_released(factory, session_id)
    finally:
        release_llm.set()
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_release_db_error_is_warning_and_does_not_mask_success(
    real_database_url, monkeypatch
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)
    warnings: list[str] = []

    async def successful_chat_edit(options, settings=None, *, deadline=None):
        return ChatEditResult(
            mermaid_code="flowchart LR\nA-->C",
            message="Changed",
            usage=None,
        )

    async def failing_release(self, session_id, lock_token):
        raise RuntimeError("injected release failure")

    def capture_warning(message, *args, **kwargs):
        warnings.append(message)

    monkeypatch.setattr("app.services.chat.service.chat_edit", successful_chat_edit)
    monkeypatch.setattr(SessionRepository, "release_lease", failing_release)
    monkeypatch.setattr("app.services.chat.service.logger.warning", capture_warning)

    try:
        result = await run_chat(factory, session_id)
        assert result.message == "Changed"
        assert any("Chat lease release failed" in warning for warning in warnings)
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_expired_lease_takeover_fences_old_worker_and_rolls_back_everything(
    real_database_url, monkeypatch
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)
    llm_entered = asyncio.Event()
    release_llm = asyncio.Event()
    takeover_token = "takeover-token"

    async def blocking_chat_edit(options, settings=None, *, deadline=None):
        llm_entered.set()
        await release_llm.wait()
        return ChatEditResult(
            mermaid_code="flowchart LR\nA-->stale",
            message="Stale result",
            usage=None,
        )

    monkeypatch.setattr("app.services.chat.service.chat_edit", blocking_chat_edit)

    task = asyncio.create_task(run_chat(factory, session_id))
    try:
        await asyncio.wait_for(llm_entered.wait(), timeout=1)

        async with factory() as db:
            stored = await SessionRepository(db).get(session_id)
            assert stored is not None
            original_head_id = stored.head_version_id
            old_token = stored.lock_token
            assert old_token is not None

        async with factory() as db:
            async with db.begin():
                await db.execute(
                    sa.update(Session)
                    .where(Session.id == session_id)
                    .values(
                        locked_until=sa.func.clock_timestamp() - timedelta(seconds=1)
                    )
                )

        async with factory() as db:
            async with db.begin():
                taken_over = await SessionRepository(db).acquire_lease(
                    session_id, None, takeover_token
                )
        assert taken_over == 1

        release_llm.set()
        with pytest.raises(VersionConflict):
            await task

        async with factory() as db:
            stored = await SessionRepository(db).get(session_id)
            assert stored is not None
            assert stored.head_version_id == original_head_id
            assert stored.lock_token == takeover_token
            assert await MessageRepository(db).list_by_session(session_id) == []
            version_count = await db.scalar(
                sa.select(sa.func.count())
                .select_from(DiagramVersion)
                .where(DiagramVersion.session_id == session_id)
            )
            assert version_count == 1
    finally:
        release_llm.set()
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        await delete_session(engine, session_id)
        await engine.dispose()
