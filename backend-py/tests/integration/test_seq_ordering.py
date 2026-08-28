import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings

BACKEND_PY_ROOT = Path(__file__).resolve().parents[2]


async def _is_reachable(database_url: str) -> bool:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect():
            return True
    except Exception:
        return False
    finally:
        await engine.dispose()


@pytest.fixture
def real_database_settings():
    # Sorting by seq (vs. created_at) can only be proven against a real
    # Postgres — skip gracefully rather than fail when none is reachable
    # (e.g. Docker not running locally), so `uv run pytest` stays green.
    settings = get_settings()
    if not asyncio.run(_is_reachable(settings.database_url)):
        pytest.skip(f"Postgres not reachable at {settings.database_url!r} — skipping DB integration test")

    alembic_cfg = Config(str(BACKEND_PY_ROOT / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")
    return settings


async def test_diagram_versions_sort_by_seq_not_created_at(real_database_settings):
    settings = real_database_settings
    session_id = f"test-seq-{uuid.uuid4()}"
    engine = create_async_engine(settings.database_url)
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
