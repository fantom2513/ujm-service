import asyncio
import os
import textwrap
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine

BACKEND_PY_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_TABLES = {"sessions", "diagram_versions", "messages", "turns"}
HEAD_REVISION = "0002"


async def _table_names(database_url: str) -> set[str]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                sa.text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
            )
            return {row[0] for row in result.fetchall()}
    finally:
        await engine.dispose()


async def _sessions_columns(database_url: str) -> set[str]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                sa.text("SELECT column_name FROM information_schema.columns WHERE table_name = 'sessions'")
            )
            return {row[0] for row in result.fetchall()}
    finally:
        await engine.dispose()


async def _turns_request_hash_metadata(database_url: str) -> tuple[str, str, None]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                sa.text(
                    """
                    SELECT data_type, is_nullable, column_default
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'turns'
                      AND column_name = 'request_hash'
                    """
                )
            )
            row = result.one()
            return row[0], row[1], row[2]
    finally:
        await engine.dispose()


async def _alembic_current_version(database_url: str) -> str:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(sa.text("SELECT version_num FROM alembic_version"))
            return result.scalar_one()
    finally:
        await engine.dispose()


async def _upgrade(alembic_cfg: Config, revision: str) -> None:
    # command.upgrade ultimately calls asyncio.run() inside alembic/env.py —
    # to_thread gives it a fresh thread with no event loop of its own, since
    # these tests already have one running (pytest-asyncio).
    await asyncio.to_thread(command.upgrade, alembic_cfg, revision)


async def _downgrade(alembic_cfg: Config, revision: str) -> None:
    await asyncio.to_thread(command.downgrade, alembic_cfg, revision)


async def test_upgrade_downgrade_upgrade_cycle(real_database_url):
    # This is the actual acceptance-criteria proof (upgrade head -> downgrade
    # base -> upgrade head), run automatically instead of only by hand.
    alembic_cfg = Config(str(BACKEND_PY_ROOT / "alembic.ini"))

    await _upgrade(alembic_cfg, "head")
    assert EXPECTED_TABLES <= await _table_names(real_database_url)
    assert await _turns_request_hash_metadata(real_database_url) == (
        "text",
        "NO",
        None,
    )

    await _downgrade(alembic_cfg, "base")
    assert not (EXPECTED_TABLES & await _table_names(real_database_url))

    await _upgrade(alembic_cfg, "head")
    assert EXPECTED_TABLES <= await _table_names(real_database_url)

    await _downgrade(alembic_cfg, "base")  # leave a clean slate behind


async def test_broken_migration_rolls_back_and_leaves_schema_consistent(real_database_url, tmp_path):
    # Simulates shipping a new, buggy migration on top of an already-deployed
    # head: it must not corrupt the existing schema, and alembic_version must
    # still point at the last migration that actually succeeded.
    alembic_cfg = Config(str(BACKEND_PY_ROOT / "alembic.ini"))
    await _upgrade(alembic_cfg, "head")

    broken_revision_id = "broken_test_revision"
    (tmp_path / f"{broken_revision_id}.py").write_text(
        textwrap.dedent(
            f'''
            revision = "{broken_revision_id}"
            down_revision = "{HEAD_REVISION}"
            branch_labels = None
            depends_on = None

            from alembic import op

            def upgrade():
                # First statement succeeds on its own...
                op.execute("ALTER TABLE sessions ADD COLUMN oops_this_breaks TEXT")
                # ...but the whole migration is one transaction, so this
                # deliberately invalid statement must roll the ADD COLUMN
                # back too, not just fail in isolation.
                op.execute("SELECT * FROM this_table_does_not_exist")

            def downgrade():
                op.execute("ALTER TABLE sessions DROP COLUMN oops_this_breaks")
            '''
        )
    )

    script_dir = ScriptDirectory.from_config(alembic_cfg)
    # With the default Alembic layout version_locations is empty and the
    # implicit <script_location>/versions directory is exposed as .versions.
    # Preserve that directory when adding the temporary test location.
    real_locations = list(script_dir.version_locations) or [script_dir.versions]
    alembic_cfg.set_main_option("version_locations", os.pathsep.join([*real_locations, str(tmp_path)]))

    with pytest.raises(Exception):
        await _upgrade(alembic_cfg, broken_revision_id)

    # The failed migration's own transaction rolled back: the half-applied
    # ADD COLUMN must not have survived the later statement's failure.
    assert "oops_this_breaks" not in await _sessions_columns(real_database_url)

    # alembic_version must still name the last migration that
    # actually succeeded) — not the broken one, and not "nothing".
    assert await _alembic_current_version(real_database_url) == HEAD_REVISION

    # Deploy behaves as designed: a broken migration blocks progress but
    # doesn't corrupt what's there — the schema is still fully usable, and
    # once the bad revision is out of the picture, upgrade head proceeds
    # normally again.
    alembic_cfg.set_main_option("version_locations", os.pathsep.join(real_locations))
    await _upgrade(alembic_cfg, "head")
    assert EXPECTED_TABLES <= await _table_names(real_database_url)
    assert await _turns_request_hash_metadata(real_database_url) == (
        "text",
        "NO",
        None,
    )

    await _downgrade(alembic_cfg, "base")  # leave a clean slate behind
