import asyncio
import uuid
from datetime import timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.infrastructure.db.models import Turn
from app.infrastructure.db.repositories import TurnRepository
from tests.integration._chat_helpers import (
    create_initial_session,
    delete_session,
    upgrade_head,
)

REQUEST_HASH = "a" * 64


async def _claim(
    factory,
    session_id: str,
    *,
    request_id: str = "request-1",
    request_hash: str = REQUEST_HASH,
    claim_token: str = "token-1",
    remaining_seconds: float = 10,
):
    async with factory() as db:
        async with db.begin():
            return await TurnRepository(db).claim_or_take_over(
                session_id=session_id,
                request_id=request_id,
                request_hash=request_hash,
                claim_token=claim_token,
                remaining_seconds=remaining_seconds,
            )


async def test_claim_creates_live_turn_using_database_clock_and_safety_margin(
    real_database_url,
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)

    try:
        claimed = await _claim(factory, session_id)

        assert claimed is not None
        assert claimed.session_id == session_id
        assert claimed.request_id == "request-1"
        assert claimed.request_hash == REQUEST_HASH
        assert claimed.claim_token == "token-1"
        assert claimed.response_json is None

        async with factory() as db:
            remaining = await db.scalar(
                sa.select(Turn.claimed_until - sa.func.clock_timestamp()).where(
                    Turn.session_id == session_id,
                    Turn.request_id == "request-1",
                )
            )
        assert timedelta(seconds=35) < remaining <= timedelta(seconds=40)
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_nonpositive_remaining_budget_does_not_create_claim(
    real_database_url,
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)

    try:
        with pytest.raises(ValueError, match="remaining_seconds must be positive"):
            await _claim(factory, session_id, remaining_seconds=0)

        async with factory() as db:
            stored = await TurnRepository(db).get_fresh(session_id, "request-1")
        assert stored is None
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_live_claim_cannot_be_taken_over_even_with_matching_hash(
    real_database_url,
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)

    try:
        first = await _claim(factory, session_id, claim_token="token-a")
        second = await _claim(factory, session_id, claim_token="token-b")

        assert first is not None
        assert second is None
        async with factory() as db:
            stored = await TurnRepository(db).get_fresh(session_id, "request-1")
        assert stored is not None
        assert stored.claim_token == "token-a"
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_expired_matching_claim_is_taken_over_without_waiting(
    real_database_url,
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)

    try:
        first = await _claim(factory, session_id, claim_token="old-token")
        assert first is not None
        async with factory() as db:
            async with db.begin():
                await db.execute(
                    sa.update(Turn)
                    .where(
                        Turn.session_id == session_id,
                        Turn.request_id == "request-1",
                    )
                    .values(
                        claimed_until=sa.func.clock_timestamp()
                        - timedelta(seconds=1)
                    )
                )

        taken_over = await _claim(factory, session_id, claim_token="new-token")

        assert taken_over is not None
        assert taken_over.claim_token == "new-token"
        assert taken_over.request_hash == REQUEST_HASH
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_different_hash_cannot_take_over_live_or_expired_claim(
    real_database_url,
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)

    try:
        first = await _claim(factory, session_id, claim_token="old-token")
        live_conflict = await _claim(
            factory,
            session_id,
            request_hash="b" * 64,
            claim_token="new-token",
        )
        assert first is not None
        assert live_conflict is None

        async with factory() as db:
            async with db.begin():
                await db.execute(
                    sa.update(Turn)
                    .where(
                        Turn.session_id == session_id,
                        Turn.request_id == "request-1",
                    )
                    .values(
                        claimed_until=sa.func.clock_timestamp()
                        - timedelta(seconds=1)
                    )
                )

        expired_conflict = await _claim(
            factory,
            session_id,
            request_hash="b" * 64,
            claim_token="new-token",
        )
        assert expired_conflict is None

        async with factory() as db:
            stored = await TurnRepository(db).get_fresh(session_id, "request-1")
        assert stored is not None
        assert stored.request_hash == REQUEST_HASH
        assert stored.claim_token == "old-token"
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_concurrent_claim_has_exactly_one_winner(real_database_url):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)
    ready_count = 0
    ready_lock = asyncio.Lock()
    start = asyncio.Event()

    async def claim(token: str):
        nonlocal ready_count
        async with factory() as db:
            async with db.begin():
                async with ready_lock:
                    ready_count += 1
                    if ready_count == 2:
                        start.set()
                await start.wait()
                return await TurnRepository(db).claim_or_take_over(
                    session_id=session_id,
                    request_id="concurrent-request",
                    request_hash=REQUEST_HASH,
                    claim_token=token,
                    remaining_seconds=10,
                )

    tokens = [f"token-{uuid.uuid4()}" for _ in range(2)]
    try:
        outcomes = await asyncio.gather(*(claim(token) for token in tokens))
        assert sum(outcome is not None for outcome in outcomes) == 1
        winner = next(outcome for outcome in outcomes if outcome is not None)
        assert winner.claim_token in tokens

        async with factory() as db:
            count = await db.scalar(
                sa.select(sa.func.count())
                .select_from(Turn)
                .where(Turn.session_id == session_id)
            )
        assert count == 1
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_complete_requires_matching_token_and_live_incomplete_claim(
    real_database_url,
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)
    response = {
        "sessionId": session_id,
        "mermaidCode": "flowchart LR\nA-->B",
        "message": "Done",
    }

    try:
        claimed = await _claim(factory, session_id, claim_token="owner-token")
        assert claimed is not None

        async with factory() as db:
            async with db.begin():
                wrong_token = await TurnRepository(db).complete(
                    session_id=session_id,
                    request_id="request-1",
                    claim_token="other-token",
                    response_json=response,
                )
        assert wrong_token == 0

        async with factory() as db:
            async with db.begin():
                completed = await TurnRepository(db).complete(
                    session_id=session_id,
                    request_id="request-1",
                    claim_token="owner-token",
                    response_json=response,
                )
        assert completed == 1

        async with factory() as db:
            stored = await TurnRepository(db).get_fresh(session_id, "request-1")
        assert stored is not None
        assert stored.response_json == response
        assert stored.claim_token is None
        assert stored.claimed_until is None

        async with factory() as db:
            async with db.begin():
                completed_cleanup = (
                    await TurnRepository(db).delete_incomplete_owned(
                        session_id=session_id,
                        request_id="request-1",
                        claim_token="owner-token",
                    )
                )
        assert completed_cleanup == 0

        replay_claim = await _claim(
            factory,
            session_id,
            claim_token="replay-must-not-claim",
        )
        assert replay_claim is None
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_expired_claim_cannot_be_completed(real_database_url):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)

    try:
        claimed = await _claim(factory, session_id, claim_token="expired-token")
        assert claimed is not None
        async with factory() as db:
            async with db.begin():
                await db.execute(
                    sa.update(Turn)
                    .where(Turn.session_id == session_id)
                    .values(
                        claimed_until=sa.func.clock_timestamp()
                        - timedelta(seconds=1)
                    )
                )
                completed = await TurnRepository(db).complete(
                    session_id=session_id,
                    request_id="request-1",
                    claim_token="expired-token",
                    response_json={"message": "too late"},
                )
        assert completed == 0
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_old_token_cannot_complete_or_delete_taken_over_claim(
    real_database_url,
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)

    try:
        claimed = await _claim(factory, session_id, claim_token="old-token")
        assert claimed is not None
        async with factory() as db:
            async with db.begin():
                await db.execute(
                    sa.update(Turn)
                    .where(Turn.session_id == session_id)
                    .values(
                        claimed_until=sa.func.clock_timestamp()
                        - timedelta(seconds=1)
                    )
                )

        taken_over = await _claim(factory, session_id, claim_token="new-token")
        assert taken_over is not None

        async with factory() as db:
            async with db.begin():
                stale_completion = await TurnRepository(db).complete(
                    session_id=session_id,
                    request_id="request-1",
                    claim_token="old-token",
                    response_json={"message": "stale"},
                )
                stale_cleanup = await TurnRepository(db).delete_incomplete_owned(
                    session_id=session_id,
                    request_id="request-1",
                    claim_token="old-token",
                )
        assert stale_completion == 0
        assert stale_cleanup == 0

        async with factory() as db:
            stored = await TurnRepository(db).get_fresh(session_id, "request-1")
        assert stored is not None
        assert stored.claim_token == "new-token"
        assert stored.response_json is None
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_cleanup_deletes_only_owned_incomplete_claim(real_database_url):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)

    try:
        claimed = await _claim(factory, session_id, claim_token="owner-token")
        assert claimed is not None

        async with factory() as db:
            async with db.begin():
                wrong_token = await TurnRepository(db).delete_incomplete_owned(
                    session_id=session_id,
                    request_id="request-1",
                    claim_token="other-token",
                )
        assert wrong_token == 0

        async with factory() as db:
            async with db.begin():
                deleted = await TurnRepository(db).delete_incomplete_owned(
                    session_id=session_id,
                    request_id="request-1",
                    claim_token="owner-token",
                )
        assert deleted == 1

        async with factory() as db:
            assert await TurnRepository(db).get_fresh(session_id, "request-1") is None
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()
