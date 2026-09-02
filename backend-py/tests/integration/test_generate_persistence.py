"""Atomic session + V1 + head persistence against a real Postgres."""

import asyncio
import uuid
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.infrastructure.db.models import DiagramVersion
from app.infrastructure.db.repositories import SessionRepository
from app.services.chat.service import ChatService

BACKEND_PY_ROOT = Path(__file__).resolve().parents[2]


async def _upgrade_head() -> None:
    alembic_cfg = Config(str(BACKEND_PY_ROOT / "alembic.ini"))
    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")


async def _delete_session(engine, session_id: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            sa.text("DELETE FROM sessions WHERE id = :id"), {"id": session_id}
        )


async def test_create_session_with_version_persists_complete_initial_state(
    real_database_url,
):
    await _upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id: str | None = None
    try:
        async with factory() as db:
            service = ChatService(
                db=db,
                db_sessionmaker=factory,
                redis=None,  # type: ignore[arg-type]
                settings=Settings(),
            )
            session_id = await service.create_session_with_version(
                source_text="server specification",
                additional_details="extra constraints",
                user_id="alice",
                mermaid_code="flowchart LR\nA-->B",
            )

        async with factory() as db:
            stored_session = await SessionRepository(db).get(session_id)
            assert stored_session is not None
            assert stored_session.user_id == "alice"
            assert stored_session.source_text == "server specification"
            assert stored_session.additional_details == "extra constraints"
            assert stored_session.head_version_id is not None

            stored_version = await db.get(
                DiagramVersion, stored_session.head_version_id
            )
            assert stored_version is not None
            assert stored_version.session_id == session_id
            assert stored_version.mermaid_code == "flowchart LR\nA-->B"
            assert stored_version.parent_version_id is None

            message_count = await db.scalar(
                sa.text("SELECT count(*) FROM messages WHERE session_id = :id"),
                {"id": session_id},
            )
            assert message_count == 0
    finally:
        if session_id is not None:
            await _delete_session(engine, session_id)
        await engine.dispose()


async def test_create_session_with_version_rolls_back_everything_on_head_failure(
    real_database_url, monkeypatch
):
    await _upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = f"test-generate-rollback-{uuid.uuid4()}"

    monkeypatch.setattr(
        "app.services.chat.service.secrets.token_urlsafe",
        lambda _bytes: session_id,
    )

    async def fail_set_head(self, target_session_id: str, version_id: int) -> None:
        raise RuntimeError("injected head update failure")

    monkeypatch.setattr(
        "app.services.chat.service.SessionRepository.set_head",
        fail_set_head,
    )

    try:
        async with factory() as db:
            service = ChatService(
                db=db,
                db_sessionmaker=factory,
                redis=None,  # type: ignore[arg-type]
                settings=Settings(),
            )
            try:
                await service.create_session_with_version(
                    source_text="server specification",
                    additional_details="",
                    user_id=None,
                    mermaid_code="flowchart LR\nA-->B",
                )
            except RuntimeError as err:
                assert str(err) == "injected head update failure"
            else:
                raise AssertionError("Injected persistence failure was not raised")

        async with factory() as db:
            assert await SessionRepository(db).get(session_id) is None
            version_count = await db.scalar(
                sa.select(sa.func.count())
                .select_from(DiagramVersion)
                .where(DiagramVersion.session_id == session_id)
            )
            assert version_count == 0
    finally:
        await _delete_session(engine, session_id)
        await engine.dispose()
