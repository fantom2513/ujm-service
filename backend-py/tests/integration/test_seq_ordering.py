import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

BACKEND_PY_ROOT = Path(__file__).resolve().parents[2]


async def test_diagram_versions_sort_by_seq_not_created_at(real_database_url):
    alembic_cfg = Config(str(BACKEND_PY_ROOT / "alembic.ini"))
    # command.upgrade ultimately calls asyncio.run() inside alembic/env.py —
    # to_thread gives it a fresh thread with no event loop of its own,
    # since this test function already has one running (pytest-asyncio).
    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")

    session_id = f"test-seq-{uuid.uuid4()}"
    engine = create_async_engine(real_database_url)
    try:
        # Same created_at for both rows on purpose — if anything ever sorts
        # by created_at instead of seq, this tie makes the bug observable.
        fixed_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        async with engine.begin() as conn:
            await conn.execute(
                sa.text("INSERT INTO sessions (id, source_text) VALUES (:id, 'test')"),
                {"id": session_id},
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO diagram_versions (session_id, mermaid_code, created_at) "
                    "VALUES (:sid, 'first', :ts)"
                ),
                {"sid": session_id, "ts": fixed_time},
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO diagram_versions (session_id, mermaid_code, created_at) "
                    "VALUES (:sid, 'second', :ts)"
                ),
                {"sid": session_id, "ts": fixed_time},
            )

        async with engine.connect() as conn:
            result = await conn.execute(
                sa.text("SELECT mermaid_code FROM diagram_versions WHERE session_id = :sid ORDER BY seq"),
                {"sid": session_id},
            )
            texts = [row[0] for row in result.fetchall()]

        assert texts == ["first", "second"]
    finally:
        # ON DELETE CASCADE on diagram_versions.session_id takes the two
        # rows above with it — no leftover fixture data either way.
        async with engine.begin() as conn:
            await conn.execute(sa.text("DELETE FROM sessions WHERE id = :id"), {"id": session_id})
        await engine.dispose()
