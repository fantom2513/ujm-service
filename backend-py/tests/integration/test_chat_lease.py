import asyncio
import uuid
from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.infrastructure.db.models import DiagramVersion, Session
from app.infrastructure.db.repositories import (
    DiagramVersionRepository,
    SessionRepository,
)
from tests.integration._chat_helpers import delete_session, upgrade_head


async def create_session(factory, *, user_id: str | None) -> str:
    session_id = f"test-lease-{uuid.uuid4()}"
    async with factory() as db:
        async with db.begin():
            SessionRepository(db).add(
                Session(id=session_id, source_text="spec", user_id=user_id)
            )
    return session_id


async def test_acquire_lease_claims_free_session_and_rejects_live_lease(
    real_database_url,
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_session(factory, user_id="alice")

    try:
        async with factory() as db:
            async with db.begin():
                acquired = await SessionRepository(db).acquire_lease(
                    session_id, "alice", "token-a"
                )
        assert acquired == 1

        async with factory() as db:
            async with db.begin():
                busy = await SessionRepository(db).acquire_lease(
                    session_id, "alice", "token-b"
                )
        assert busy == 0

        async with factory() as db:
            stored = await SessionRepository(db).get(session_id)
            assert stored is not None
            assert stored.lock_token == "token-a"
            assert stored.locked_until is not None
            remaining = await db.scalar(
                sa.select(Session.locked_until - sa.func.clock_timestamp()).where(
                    Session.id == session_id
                )
            )
            assert timedelta(seconds=20) < remaining <= timedelta(seconds=30)
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_acquire_lease_replaces_expired_token(real_database_url):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_session(factory, user_id="alice")

    try:
        async with factory() as db:
            async with db.begin():
                await db.execute(
                    sa.update(Session)
                    .where(Session.id == session_id)
                    .values(
                        lock_token="expired-token",
                        locked_until=sa.func.clock_timestamp() - timedelta(seconds=1),
                    )
                )

        async with factory() as db:
            async with db.begin():
                acquired = await SessionRepository(db).acquire_lease(
                    session_id, "alice", "new-token"
                )
        assert acquired == 1

        async with factory() as db:
            stored = await SessionRepository(db).get(session_id)
            assert stored is not None
            assert stored.lock_token == "new-token"
            assert stored.locked_until is not None
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_acquire_lease_allows_anonymous_request_for_anonymous_session(
    real_database_url,
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_session(factory, user_id=None)

    try:
        async with factory() as db:
            async with db.begin():
                acquired = await SessionRepository(db).acquire_lease(
                    session_id, None, "anonymous-token"
                )

        assert acquired == 1
        async with factory() as db:
            stored = await SessionRepository(db).get(session_id)
            assert stored is not None
            assert stored.user_id is None
            assert stored.lock_token == "anonymous-token"
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_acquire_lease_rejects_wrong_owner_and_missing_session(
    real_database_url,
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_session(factory, user_id="alice")

    try:
        async with factory() as db:
            async with db.begin():
                wrong_owner = await SessionRepository(db).acquire_lease(
                    session_id, "bob", "token-b"
                )
                missing = await SessionRepository(db).acquire_lease(
                    "missing-session", "alice", "token-a"
                )

        assert wrong_owner == 0
        assert missing == 0
        async with factory() as db:
            stored = await SessionRepository(db).get(session_id)
            assert stored is not None
            assert stored.lock_token is None
            assert stored.locked_until is None
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_concurrent_acquire_has_exactly_one_winner(real_database_url):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_session(factory, user_id="alice")
    ready_count = 0
    ready_lock = asyncio.Lock()
    start = asyncio.Event()

    async def acquire(token: str) -> int:
        nonlocal ready_count
        async with factory() as db:
            async with db.begin():
                async with ready_lock:
                    ready_count += 1
                    if ready_count == 2:
                        start.set()
                await start.wait()
                return await SessionRepository(db).acquire_lease(
                    session_id, "alice", token
                )

    tokens = ["token-a", "token-b"]
    try:
        outcomes = await asyncio.gather(*(acquire(token) for token in tokens))
        assert sorted(outcomes) == [0, 1]
        winning_token = tokens[outcomes.index(1)]

        async with factory() as db:
            stored = await SessionRepository(db).get(session_id)
            assert stored is not None
            assert stored.lock_token == winning_token
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_heartbeat_extends_live_lease_with_matching_token(real_database_url):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_session(factory, user_id="alice")

    try:
        async with factory() as db:
            async with db.begin():
                acquired = await SessionRepository(db).acquire_lease(
                    session_id, "alice", "token-a"
                )
                assert acquired == 1
                await db.execute(
                    sa.update(Session)
                    .where(Session.id == session_id)
                    .values(
                        locked_until=sa.func.clock_timestamp()
                        + timedelta(seconds=5)
                    )
                )

        async with factory() as db:
            before = await db.scalar(
                sa.select(Session.locked_until).where(Session.id == session_id)
            )

        # Heartbeat uses a new short-lived DB session, as the service task will.
        async with factory() as db:
            async with db.begin():
                extended = await SessionRepository(db).heartbeat_lease(
                    session_id, "token-a"
                )
        assert extended == 1

        async with factory() as db:
            stored = await SessionRepository(db).get(session_id)
            assert stored is not None
            assert stored.lock_token == "token-a"
            assert stored.locked_until is not None
            assert before is not None
            assert stored.locked_until > before
            remaining = await db.scalar(
                sa.select(Session.locked_until - sa.func.clock_timestamp()).where(
                    Session.id == session_id
                )
            )
            assert timedelta(seconds=20) < remaining <= timedelta(seconds=30)
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_heartbeat_rejects_wrong_token_and_does_not_revive_expired_lease(
    real_database_url,
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_session(factory, user_id="alice")

    try:
        async with factory() as db:
            async with db.begin():
                await db.execute(
                    sa.update(Session)
                    .where(Session.id == session_id)
                    .values(
                        lock_token="expired-token",
                        locked_until=sa.func.clock_timestamp() - timedelta(seconds=1),
                    )
                )

        async with factory() as db:
            async with db.begin():
                wrong_token = await SessionRepository(db).heartbeat_lease(
                    session_id, "other-token"
                )
                expired = await SessionRepository(db).heartbeat_lease(
                    session_id, "expired-token"
                )

        assert wrong_token == 0
        assert expired == 0
        async with factory() as db:
            stored = await SessionRepository(db).get(session_id)
            assert stored is not None
            assert stored.lock_token == "expired-token"
            assert stored.locked_until is not None
            is_expired = await db.scalar(
                sa.select(Session.locked_until <= sa.func.clock_timestamp()).where(
                    Session.id == session_id
                )
            )
            assert is_expired is True
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_release_clears_live_lease_owned_by_token(real_database_url):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_session(factory, user_id="alice")

    try:
        async with factory() as db:
            async with db.begin():
                acquired = await SessionRepository(db).acquire_lease(
                    session_id, "alice", "token-a"
                )
        assert acquired == 1

        # Release also gets its own short-lived DB session.
        async with factory() as db:
            async with db.begin():
                released = await SessionRepository(db).release_lease(
                    session_id, "token-a"
                )
        assert released == 1

        async with factory() as db:
            stored = await SessionRepository(db).get(session_id)
            assert stored is not None
            assert stored.lock_token is None
            assert stored.locked_until is None
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_old_token_cannot_heartbeat_or_release_new_lease(real_database_url):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_session(factory, user_id="alice")

    try:
        async with factory() as db:
            async with db.begin():
                acquired = await SessionRepository(db).acquire_lease(
                    session_id, "alice", "old-token"
                )
                assert acquired == 1
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
                    session_id, "alice", "new-token"
                )
        assert taken_over == 1

        async with factory() as db:
            async with db.begin():
                stale_heartbeat = await SessionRepository(db).heartbeat_lease(
                    session_id, "old-token"
                )
        assert stale_heartbeat == 0

        async with factory() as db:
            async with db.begin():
                stale_release = await SessionRepository(db).release_lease(
                    session_id, "old-token"
                )
        assert stale_release == 0

        async with factory() as db:
            stored = await SessionRepository(db).get(session_id)
            assert stored is not None
            assert stored.lock_token == "new-token"
            assert stored.locked_until is not None
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_fenced_head_update_requires_expected_head_token_and_live_lease(
    real_database_url,
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_session(factory, user_id="alice")

    try:
        async with factory() as db:
            sessions = SessionRepository(db)
            versions = DiagramVersionRepository(db)
            async with db.begin():
                first = DiagramVersion(session_id=session_id, mermaid_code="first")
                versions.add(first)
                await db.flush()
                await sessions.set_head(session_id, first.id)
                acquired = await sessions.acquire_lease(
                    session_id, "alice", "token-a"
                )
                assert acquired == 1

        async with factory() as db:
            async with db.begin():
                second = DiagramVersion(
                    session_id=session_id,
                    mermaid_code="second",
                    parent_version_id=first.id,
                )
                DiagramVersionRepository(db).add(second)
                await db.flush()
            second_id = second.id

        async with factory() as db:
            sessions = SessionRepository(db)
            async with db.begin():
                wrong_head = await sessions.set_head_fenced(
                    session_id, first.id + second_id + 1, second_id, "token-a"
                )
                wrong_token = await sessions.set_head_fenced(
                    session_id, first.id, second_id, "wrong-token"
                )
                await db.execute(
                    sa.update(Session)
                    .where(Session.id == session_id)
                    .values(
                        locked_until=sa.func.clock_timestamp() - timedelta(seconds=1)
                    )
                )
                expired = await sessions.set_head_fenced(
                    session_id, first.id, second_id, "token-a"
                )

        assert wrong_head == 0
        assert wrong_token == 0
        assert expired == 0

        async with factory() as db:
            sessions = SessionRepository(db)
            async with db.begin():
                taken_over = await sessions.acquire_lease(
                    session_id, "alice", "token-b"
                )
                updated = await sessions.set_head_fenced(
                    session_id, first.id, second_id, "token-b"
                )
        assert taken_over == 1
        assert updated == 1

        async with factory() as db:
            stored = await SessionRepository(db).get(session_id)
            assert stored is not None
            assert stored.head_version_id == second_id
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()
