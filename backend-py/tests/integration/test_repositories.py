"""Repository round-trips against a real Postgres, plus the transaction-scope
spike that settles how ChatService reads then writes on one session.

Skipped automatically when no Postgres is reachable (`real_database_url`)."""

import asyncio
import uuid
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.infrastructure.db.models import DiagramVersion, Message, Session
from app.infrastructure.db.repositories import (
    DiagramVersionRepository,
    MessageRepository,
    SessionRepository,
)

BACKEND_PY_ROOT = Path(__file__).resolve().parents[2]


async def _upgrade_head() -> None:
    alembic_cfg = Config(str(BACKEND_PY_ROOT / "alembic.ini"))
    # command.upgrade calls asyncio.run() inside alembic/env.py — to_thread
    # gives it a loop-free thread (this test already has a running loop).
    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")


async def _delete_session(engine, session_id: str) -> None:
    # ON DELETE CASCADE takes diagram_versions + messages with it.
    async with engine.begin() as conn:
        await conn.execute(
            sa.text("DELETE FROM sessions WHERE id = :id"), {"id": session_id}
        )


async def test_session_version_message_round_trip(real_database_url):
    await _upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = f"test-repo-{uuid.uuid4()}"
    try:
        async with factory() as db:
            sessions = SessionRepository(db)
            versions = DiagramVersionRepository(db)
            messages = MessageRepository(db)
            async with db.begin():
                sessions.add(Session(id=session_id, source_text="spec"))
                # Flush the parent row before adding children: a column-level
                # ForeignKey (no ORM relationship) doesn't make the unit of
                # work order sessions before diagram_versions on its own.
                await db.flush()
                v1 = DiagramVersion(
                    session_id=session_id, mermaid_code="flowchart LR\nA-->B"
                )
                versions.add(v1)
                await db.flush()  # DB assigns v1.id / v1.seq
                assert v1.id is not None
                assert v1.seq is not None
                await sessions.set_head(session_id, v1.id)
                messages.add(Message(session_id=session_id, role="user", text="hi"))
                messages.add(
                    Message(session_id=session_id, role="assistant", text="done")
                )
            v1_id = v1.id

        async with factory() as db:
            got = await SessionRepository(db).get(session_id)
            assert got is not None
            assert got.head_version_id == v1_id
            msgs = await MessageRepository(db).list_by_session(session_id)
            assert [(m.role, m.text) for m in msgs] == [
                ("user", "hi"),
                ("assistant", "done"),
            ]
    finally:
        await _delete_session(engine, session_id)
        await engine.dispose()


async def test_get_previous_is_by_seq(real_database_url):
    await _upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = f"test-prev-{uuid.uuid4()}"
    try:
        async with factory() as db:
            versions = DiagramVersionRepository(db)
            async with db.begin():
                SessionRepository(db).add(
                    Session(id=session_id, source_text="spec")
                )
                await db.flush()
                v1 = DiagramVersion(session_id=session_id, mermaid_code="A")
                v2 = DiagramVersion(session_id=session_id, mermaid_code="B")
                v3 = DiagramVersion(session_id=session_id, mermaid_code="C")
                versions.add(v1)
                versions.add(v2)
                versions.add(v3)
                await db.flush()
                seqs = (v1.seq, v2.seq, v3.seq)

        async with factory() as db:
            versions = DiagramVersionRepository(db)
            prev_of_v3 = await versions.get_previous(session_id, seqs[2])
            assert prev_of_v3 is not None and prev_of_v3.mermaid_code == "B"
            prev_of_v1 = await versions.get_previous(session_id, seqs[0])
            assert prev_of_v1 is None
    finally:
        await _delete_session(engine, session_id)
        await engine.dispose()


async def test_bind_user_only_claims_anonymous_session(real_database_url):
    await _upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    anon_id = f"test-anon-{uuid.uuid4()}"
    owned_id = f"test-owned-{uuid.uuid4()}"
    try:
        async with factory() as db:
            async with db.begin():
                SessionRepository(db).add(Session(id=anon_id, source_text="s"))
                SessionRepository(db).add(
                    Session(id=owned_id, source_text="s", user_id="owner")
                )

        async with factory() as db:
            sessions = SessionRepository(db)
            async with db.begin():
                claimed = await sessions.bind_user(anon_id, "alice")
                ignored = await sessions.bind_user(owned_id, "mallory")
            assert claimed == 1
            assert ignored == 0

        async with factory() as db:
            sessions = SessionRepository(db)
            assert (await sessions.get(anon_id)).user_id == "alice"
            assert (await sessions.get(owned_id)).user_id == "owner"
    finally:
        await _delete_session(engine, anon_id)
        await _delete_session(engine, owned_id)
        await engine.dispose()


async def test_read_scope_then_write_scope_on_one_session(real_database_url):
    """The autobegin decision: ChatService does its reads inside one
    `async with db.begin()` and its writes inside a second one, on the SAME
    AsyncSession. This must commit cleanly, not raise "a transaction is
    already begun". If this ever fails, switch the read scope to a separate
    session and update the plan."""
    await _upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = f"test-autobegin-{uuid.uuid4()}"
    try:
        async with factory() as db:
            sessions = SessionRepository(db)
            versions = DiagramVersionRepository(db)

            async with db.begin():  # seed
                sessions.add(Session(id=session_id, source_text="spec"))
                await db.flush()
                v1 = DiagramVersion(
                    session_id=session_id, mermaid_code="flowchart LR\nA-->B"
                )
                versions.add(v1)
                await db.flush()
                await sessions.set_head(session_id, v1.id)

            async with db.begin():  # read scope
                loaded = await sessions.get(session_id)
                head = await versions.get(loaded.head_version_id)
                prev = await versions.get_previous(session_id, head.seq)
            assert prev is None
            head_id, head_seq = head.id, head.seq

            async with db.begin():  # write scope, same session
                v2 = DiagramVersion(
                    session_id=session_id,
                    mermaid_code="flowchart LR\nA-->C",
                    parent_version_id=head_id,
                )
                versions.add(v2)
                await db.flush()
                await sessions.set_head(session_id, v2.id)
            v2_id = v2.id

        async with factory() as db:
            got = await SessionRepository(db).get(session_id)
            assert got.head_version_id == v2_id
    finally:
        await _delete_session(engine, session_id)
        await engine.dispose()
