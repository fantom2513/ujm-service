import sqlalchemy as sa
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.infrastructure.db.models import DiagramVersion
from app.infrastructure.db.repositories import (
    DiagramVersionRepository,
    MessageRepository,
    SessionRepository,
)
from app.services.chat.service import VersionConflict
from tests.integration._chat_helpers import (
    create_initial_session,
    delete_session,
    make_chat_service,
    upgrade_head,
)


def forbid_llm(monkeypatch) -> None:
    async def fail_chat_edit(*args, **kwargs):
        raise AssertionError("Undo must not call the LLM")

    monkeypatch.setattr("app.services.chat.service.chat_edit", fail_chat_edit)


async def version_rows(db, session_id: str):
    result = await db.execute(
        sa.select(DiagramVersion)
        .where(DiagramVersion.session_id == session_id)
        .order_by(DiagramVersion.seq)
    )
    return list(result.scalars())


async def test_undo_without_previous_returns_current_and_writes_nothing(
    real_database_url, monkeypatch
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    original_mermaid = "flowchart LR\nA-->B"
    session_id = await create_initial_session(factory, mermaid_code=original_mermaid)
    forbid_llm(monkeypatch)

    async def forbid_head_write(self, *args, **kwargs):
        raise AssertionError("No-op undo must not attempt a head update")

    monkeypatch.setattr(SessionRepository, "set_head_fenced", forbid_head_write)

    try:
        async with factory() as db:
            result = await make_chat_service(db, factory).run_chat(
                session_id=session_id,
                user_id=None,
                message="верни предыдущую версию",
                action_type="FREEFORM",
                client_mermaid="ignored client copy",
            )

        assert result.mermaid_code == original_mermaid
        assert result.message == "Предыдущая версия схемы недоступна."

        async with factory() as db:
            stored = await SessionRepository(db).get(session_id)
            rows = await version_rows(db, session_id)
            assert stored is not None
            assert len(rows) == 1
            assert stored.head_version_id == rows[0].id
            assert await MessageRepository(db).list_by_session(session_id) == []
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_explicit_undo_appends_copy_and_moves_head(
    real_database_url, monkeypatch
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    mermaid_a = "flowchart LR\nA-->B"
    mermaid_b = "flowchart LR\nA-->B\nB-->C"
    session_id = await create_initial_session(factory, mermaid_code=mermaid_a)
    forbid_llm(monkeypatch)

    try:
        async with factory() as db:
            session = await SessionRepository(db).get(session_id)
            assert session is not None
            version_a_id = session.head_version_id

            version_b = DiagramVersion(
                session_id=session_id,
                mermaid_code=mermaid_b,
                parent_version_id=version_a_id,
            )
            DiagramVersionRepository(db).add(version_b)
            await db.flush()
            await SessionRepository(db).set_head(session_id, version_b.id)
            await db.commit()
            version_b_id = version_b.id

        async with factory() as db:
            result = await make_chat_service(db, factory).run_chat(
                session_id=session_id,
                user_id=None,
                message="undo via explicit action",
                action_type="RESTORE_PREVIOUS",
                client_mermaid="ignored",
            )

        assert result.mermaid_code == mermaid_a
        assert result.message == "Предыдущая версия схемы восстановлена."

        async with factory() as db:
            stored = await SessionRepository(db).get(session_id)
            rows = await version_rows(db, session_id)
            assert stored is not None
            assert len(rows) == 3
            assert [row.mermaid_code for row in rows] == [
                mermaid_a,
                mermaid_b,
                mermaid_a,
            ]
            assert rows[0].id == version_a_id
            assert rows[1].id == version_b_id
            assert rows[2].parent_version_id == version_b_id
            assert stored.head_version_id == rows[2].id
            assert await MessageRepository(db).list_by_session(session_id) == []
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_mutating_undo_fenced_cas_failure_rolls_back_new_version(
    real_database_url, monkeypatch
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    mermaid_a = "flowchart LR\nA-->B"
    mermaid_b = "flowchart LR\nA-->C"
    session_id = await create_initial_session(factory, mermaid_code=mermaid_a)
    forbid_llm(monkeypatch)

    try:
        async with factory() as db:
            session = await SessionRepository(db).get(session_id)
            assert session is not None
            version_a_id = session.head_version_id
            version_b = DiagramVersion(
                session_id=session_id,
                mermaid_code=mermaid_b,
                parent_version_id=version_a_id,
            )
            DiagramVersionRepository(db).add(version_b)
            await db.flush()
            await SessionRepository(db).set_head(session_id, version_b.id)
            await db.commit()
            version_b_id = version_b.id

        async def reject_fenced_head(self, *args, **kwargs):
            return 0

        monkeypatch.setattr(
            SessionRepository,
            "set_head_fenced",
            reject_fenced_head,
        )

        async with factory() as db:
            with pytest.raises(VersionConflict):
                await make_chat_service(db, factory).run_chat(
                    session_id=session_id,
                    user_id=None,
                    message="верни предыдущую версию",
                    action_type="FREEFORM",
                    client_mermaid="ignored",
                )

        async with factory() as db:
            stored = await SessionRepository(db).get(session_id)
            rows = await version_rows(db, session_id)
            assert stored is not None
            assert stored.head_version_id == version_b_id
            assert [row.mermaid_code for row in rows] == [mermaid_a, mermaid_b]
            assert stored.lock_token is None
            assert stored.locked_until is None
            assert await MessageRepository(db).list_by_session(session_id) == []
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_two_undos_toggle_between_last_two_states(real_database_url, monkeypatch):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    mermaid_a = "flowchart LR\nA-->B"
    mermaid_b = "flowchart LR\nA-->C"
    session_id = await create_initial_session(factory, mermaid_code=mermaid_a)

    async def return_b(options, settings=None):
        from app.services.openai.chat import ChatEditResult

        return ChatEditResult(mermaid_code=mermaid_b, message="Changed", usage=None)

    monkeypatch.setattr("app.services.chat.service.chat_edit", return_b)

    try:
        async with factory() as db:
            await make_chat_service(db, factory).run_chat(
                session_id=session_id,
                user_id=None,
                message="change A to C",
                action_type="FREEFORM",
                client_mermaid="ignored",
            )

        forbid_llm(monkeypatch)
        restored_codes = []
        for _ in range(2):
            async with factory() as db:
                result = await make_chat_service(db, factory).run_chat(
                    session_id=session_id,
                    user_id=None,
                    message="верни предыдущую версию",
                    action_type="FREEFORM",
                    client_mermaid="ignored",
                )
                restored_codes.append(result.mermaid_code)

        assert restored_codes == [mermaid_a, mermaid_b]

        async with factory() as db:
            stored = await SessionRepository(db).get(session_id)
            rows = await version_rows(db, session_id)
            assert stored is not None
            assert [row.mermaid_code for row in rows] == [
                mermaid_a,
                mermaid_b,
                mermaid_a,
                mermaid_b,
            ]
            assert stored.head_version_id == rows[-1].id
            stored_messages = await MessageRepository(db).list_by_session(session_id)
            assert [(row.role, row.text) for row in stored_messages] == [
                ("user", "change A to C"),
                ("assistant", "Changed"),
            ]
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()
