import sqlalchemy as sa
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.infrastructure.db.models import DiagramVersion
from app.infrastructure.db.repositories import (
    DiagramVersionRepository,
    MessageRepository,
    SessionRepository,
    TurnRepository,
)
from app.services.openai.chat import ChatEditResult
from app.services.chat.service import VersionConflict
from tests.integration._chat_helpers import (
    create_initial_session,
    delete_session,
    make_chat_service,
    upgrade_head,
)


async def test_run_chat_persists_two_messages_new_version_and_head(
    real_database_url, monkeypatch
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)
    active_db = None
    llm_transaction_states: list[bool] = []

    class CompletedDeadline:
        def require_remaining(self) -> float:
            return 120.0

    completed_deadline = CompletedDeadline()

    class CompletedDeadlineFactory:
        @classmethod
        def from_timeout_ms(cls, timeout_ms: int):
            assert timeout_ms == 120_000
            return completed_deadline

    async def fake_chat_edit(options, settings=None, *, deadline=None):
        assert active_db is not None
        assert deadline is completed_deadline
        llm_transaction_states.append(active_db.in_transaction())
        return ChatEditResult(
            mermaid_code="flowchart LR\nA-->B\nB-->C",
            message="Added C",
            usage=None,
        )

    monkeypatch.setattr("app.services.chat.service.chat_edit", fake_chat_edit)
    monkeypatch.setattr(
        "app.services.chat.service.LLMDeadline",
        CompletedDeadlineFactory,
    )

    try:
        async with factory() as db:
            original = await SessionRepository(db).get(session_id)
            assert original is not None
            original_head_id = original.head_version_id

        async with factory() as db:
            active_db = db
            result = await make_chat_service(db, factory).run_chat(
                session_id=session_id,
                request_id="request-persist",
                user_id=None,
                message="add C",
                action_type="FREEFORM",
                client_mermaid="client copy must be ignored",
            )
            assert result.mermaid_code == "flowchart LR\nA-->B\nB-->C"
            assert result.message == "Added C"
            assert llm_transaction_states == [False]

        async with factory() as db:
            stored = await SessionRepository(db).get(session_id)
            assert stored is not None
            assert stored.head_version_id != original_head_id

            new_head = await DiagramVersionRepository(db).get(stored.head_version_id)
            assert new_head is not None
            assert new_head.parent_version_id == original_head_id
            assert new_head.mermaid_code == "flowchart LR\nA-->B\nB-->C"

            messages = await MessageRepository(db).list_by_session(session_id)
            assert [(row.role, row.text) for row in messages] == [
                ("user", "add C"),
                ("assistant", "Added C"),
            ]

            version_count = await db.scalar(
                sa.select(sa.func.count())
                .select_from(DiagramVersion)
                .where(DiagramVersion.session_id == session_id)
            )
            assert version_count == 2
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_run_chat_fenced_cas_failure_rolls_back_messages_version_and_head(
    real_database_url, monkeypatch
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)

    async def fake_chat_edit(options, settings=None, *, deadline=None):
        return ChatEditResult(
            mermaid_code="flowchart LR\nA-->C",
            message="Changed",
            usage=None,
        )

    monkeypatch.setattr("app.services.chat.service.chat_edit", fake_chat_edit)

    async with factory() as db:
        original = await SessionRepository(db).get(session_id)
        assert original is not None
        original_head_id = original.head_version_id

    async def reject_set_head(self, *args, **kwargs) -> int:
        return 0

    monkeypatch.setattr(
        "app.services.chat.service.SessionRepository.set_head_fenced",
        reject_set_head,
    )

    try:
        async with factory() as db:
            with pytest.raises(VersionConflict):
                await make_chat_service(db, factory).run_chat(
                    session_id=session_id,
                    request_id="request-cas-failure",
                    user_id=None,
                    message="change",
                    action_type="FREEFORM",
                    client_mermaid="ignored",
                )

        async with factory() as db:
            stored = await SessionRepository(db).get(session_id)
            assert stored is not None
            assert stored.head_version_id == original_head_id
            assert await MessageRepository(db).list_by_session(session_id) == []
            assert await TurnRepository(db).get_fresh(
                session_id,
                "request-cas-failure",
            ) is None

            version_count = await db.scalar(
                sa.select(sa.func.count())
                .select_from(DiagramVersion)
                .where(DiagramVersion.session_id == session_id)
            )
            assert version_count == 1
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()
