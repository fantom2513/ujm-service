import asyncio
from datetime import timedelta

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domain.chat_request import compute_chat_request_hash
from app.infrastructure.db.models import DiagramVersion, Message, Turn
from app.infrastructure.db.repositories import (
    DiagramVersionRepository,
    MessageRepository,
    SessionRepository,
    TurnRepository,
)
from app.infrastructure.llm.errors import LLMError
from app.services.chat.service import RequestIdConflict, RequestInProgress
from app.services.openai.chat import ChatEditResult
from tests.integration._chat_helpers import (
    create_initial_session,
    delete_session,
    make_chat_service,
    upgrade_head,
)


async def _run_chat(
    factory,
    session_id: str,
    *,
    request_id: str,
    message: str = "change",
    action_type: str = "FREEFORM",
    user_id: str | None = None,
    client_mermaid: str = "ignored",
):
    async with factory() as db:
        return await make_chat_service(db, factory).run_chat(
            session_id=session_id,
            request_id=request_id,
            user_id=user_id,
            message=message,
            action_type=action_type,
            client_mermaid=client_mermaid,
        )


async def _business_state(factory, session_id: str) -> tuple[int | None, int, int, int]:
    async with factory() as db:
        session = await SessionRepository(db).get(session_id)
        assert session is not None
        message_count = await db.scalar(
            sa.select(sa.func.count())
            .select_from(Message)
            .where(Message.session_id == session_id)
        )
        version_count = await db.scalar(
            sa.select(sa.func.count())
            .select_from(DiagramVersion)
            .where(DiagramVersion.session_id == session_id)
        )
        turn_count = await db.scalar(
            sa.select(sa.func.count())
            .select_from(Turn)
            .where(Turn.session_id == session_id)
        )
        return (
            session.head_version_id,
            int(message_count or 0),
            int(version_count or 0),
            int(turn_count or 0),
        )


async def test_completed_request_replays_without_lease_context_llm_or_writes(
    real_database_url,
    monkeypatch,
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)
    llm_calls = 0

    async def successful_chat_edit(options, settings=None, *, deadline=None):
        nonlocal llm_calls
        llm_calls += 1
        return ChatEditResult(
            mermaid_code="flowchart LR\nA-->replayed",
            message="Changed once",
            usage=None,
        )

    monkeypatch.setattr("app.services.chat.service.chat_edit", successful_chat_edit)

    try:
        first = await _run_chat(
            factory,
            session_id,
            request_id="request-replay",
            message="change once",
            client_mermaid="first client copy",
        )
        state_after_first = await _business_state(factory, session_id)

        async def forbid_replay_work(*args, **kwargs):
            raise AssertionError("Replay must not acquire a lease or load context")

        monkeypatch.setattr(SessionRepository, "acquire_lease", forbid_replay_work)
        monkeypatch.setattr(DiagramVersionRepository, "get", forbid_replay_work)
        monkeypatch.setattr(MessageRepository, "list_by_session", forbid_replay_work)
        monkeypatch.setattr("app.services.chat.service.chat_edit", forbid_replay_work)

        replay = await _run_chat(
            factory,
            session_id,
            request_id="request-replay",
            message="change once",
            client_mermaid="different client copy",
        )

        assert replay == first
        assert llm_calls == 1
        assert await _business_state(factory, session_id) == state_after_first
        async with factory() as db:
            turn = await TurnRepository(db).get_fresh(session_id, "request-replay")
        assert turn is not None
        assert turn.response_json == {
            "sessionId": session_id,
            "mermaidCode": "flowchart LR\nA-->replayed",
            "message": "Changed once",
        }
        assert "ok" not in turn.response_json
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_concurrent_same_request_has_one_worker_and_one_live_claim_outcome(
    real_database_url,
    monkeypatch,
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)
    llm_entered = asyncio.Event()
    release_llm = asyncio.Event()
    llm_calls = 0

    async def blocking_chat_edit(options, settings=None, *, deadline=None):
        nonlocal llm_calls
        llm_calls += 1
        llm_entered.set()
        await release_llm.wait()
        return ChatEditResult(
            mermaid_code="flowchart LR\nA-->winner",
            message="Winner",
            usage=None,
        )

    monkeypatch.setattr("app.services.chat.service.chat_edit", blocking_chat_edit)
    first = asyncio.create_task(
        _run_chat(
            factory,
            session_id,
            request_id="request-concurrent-replay",
            message="same concurrent payload",
        )
    )

    try:
        await asyncio.wait_for(llm_entered.wait(), timeout=1)
        with pytest.raises(RequestInProgress):
            await _run_chat(
                factory,
                session_id,
                request_id="request-concurrent-replay",
                message="same concurrent payload",
            )

        release_llm.set()
        result = await first
        assert result.message == "Winner"
        assert llm_calls == 1
    finally:
        release_llm.set()
        if not first.done():
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_reused_completed_request_id_with_different_payload_conflicts(
    real_database_url,
    monkeypatch,
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)

    async def successful_chat_edit(options, settings=None, *, deadline=None):
        return ChatEditResult(
            mermaid_code="flowchart LR\nA-->B",
            message="Changed",
            usage=None,
        )

    monkeypatch.setattr("app.services.chat.service.chat_edit", successful_chat_edit)

    try:
        await _run_chat(
            factory,
            session_id,
            request_id="request-conflict",
            message="first payload",
        )
        state_after_first = await _business_state(factory, session_id)

        async def forbid_new_work(*args, **kwargs):
            raise AssertionError("Conflicting request must not start chat work")

        monkeypatch.setattr(SessionRepository, "acquire_lease", forbid_new_work)
        monkeypatch.setattr("app.services.chat.service.chat_edit", forbid_new_work)
        with pytest.raises(RequestIdConflict):
            await _run_chat(
                factory,
                session_id,
                request_id="request-conflict",
                message="different payload",
            )

        assert await _business_state(factory, session_id) == state_after_first
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_live_claim_is_classified_as_busy_or_payload_conflict(
    real_database_url,
    monkeypatch,
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)
    request_hash = compute_chat_request_hash(
        message="same payload",
        effective_action_type="FREEFORM",
    )

    try:
        async with factory() as db:
            async with db.begin():
                claimed = await TurnRepository(db).claim_or_take_over(
                    session_id=session_id,
                    request_id="request-live",
                    request_hash=request_hash,
                    claim_token="other-worker-token",
                    remaining_seconds=60,
                )
        assert claimed is not None

        async def forbid_new_work(*args, **kwargs):
            raise AssertionError("Rejected claim must not acquire the session lease")

        monkeypatch.setattr(SessionRepository, "acquire_lease", forbid_new_work)
        with pytest.raises(RequestInProgress):
            await _run_chat(
                factory,
                session_id,
                request_id="request-live",
                message="same payload",
            )
        with pytest.raises(RequestIdConflict):
            await _run_chat(
                factory,
                session_id,
                request_id="request-live",
                message="different payload",
            )

        async with factory() as db:
            turn = await TurnRepository(db).get_fresh(session_id, "request-live")
        assert turn is not None
        assert turn.claim_token == "other-worker-token"
        assert turn.response_json is None
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_replay_validates_saved_chat_result_before_returning_it(
    real_database_url,
    monkeypatch,
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)
    request_hash = compute_chat_request_hash(
        message="invalid saved response",
        effective_action_type="FREEFORM",
    )

    try:
        async with factory() as db:
            async with db.begin():
                claimed = await TurnRepository(db).claim_or_take_over(
                    session_id=session_id,
                    request_id="request-invalid-replay",
                    request_hash=request_hash,
                    claim_token="response-writer",
                    remaining_seconds=60,
                )
                assert claimed is not None
                completed = await TurnRepository(db).complete(
                    session_id=session_id,
                    request_id="request-invalid-replay",
                    claim_token="response-writer",
                    response_json={"sessionId": session_id},
                )
                assert completed == 1

        async def forbid_new_work(*args, **kwargs):
            raise AssertionError("Replay validation must happen before session work")

        monkeypatch.setattr(SessionRepository, "acquire_lease", forbid_new_work)
        with pytest.raises(ValidationError):
            await _run_chat(
                factory,
                session_id,
                request_id="request-invalid-replay",
                message="invalid saved response",
            )
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_expired_matching_claim_is_taken_over_and_completed(
    real_database_url,
    monkeypatch,
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)
    request_hash = compute_chat_request_hash(
        message="take over",
        effective_action_type="FREEFORM",
    )

    async def successful_chat_edit(options, settings=None, *, deadline=None):
        return ChatEditResult(
            mermaid_code="flowchart LR\nA-->takeover",
            message="Taken over",
            usage=None,
        )

    monkeypatch.setattr("app.services.chat.service.chat_edit", successful_chat_edit)

    try:
        async with factory() as db:
            async with db.begin():
                await TurnRepository(db).claim_or_take_over(
                    session_id=session_id,
                    request_id="request-takeover",
                    request_hash=request_hash,
                    claim_token="dead-worker-token",
                    remaining_seconds=60,
                )
                await db.execute(
                    sa.update(Turn)
                    .where(
                        Turn.session_id == session_id,
                        Turn.request_id == "request-takeover",
                    )
                    .values(
                        claimed_until=sa.func.clock_timestamp()
                        - timedelta(seconds=1)
                    )
                )

        result = await _run_chat(
            factory,
            session_id,
            request_id="request-takeover",
            message="take over",
        )

        assert result.message == "Taken over"
        async with factory() as db:
            turn = await TurnRepository(db).get_fresh(
                session_id,
                "request-takeover",
            )
        assert turn is not None
        assert turn.response_json is not None
        assert turn.claim_token is None
        assert turn.claimed_until is None
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_busy_session_lease_cleans_up_new_request_claim(
    real_database_url,
    monkeypatch,
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)

    async def forbid_llm(*args, **kwargs):
        raise AssertionError("Busy session must not call the LLM")

    monkeypatch.setattr("app.services.chat.service.chat_edit", forbid_llm)

    try:
        async with factory() as db:
            async with db.begin():
                acquired = await SessionRepository(db).acquire_lease(
                    session_id,
                    None,
                    "other-session-worker",
                )
        assert acquired == 1

        with pytest.raises(RequestInProgress):
            await _run_chat(
                factory,
                session_id,
                request_id="request-busy-session",
            )

        async with factory() as db:
            turn = await TurnRepository(db).get_fresh(
                session_id,
                "request-busy-session",
            )
            session = await SessionRepository(db).get(session_id)
        assert turn is None
        assert session is not None
        assert session.lock_token == "other-session-worker"
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_completion_failure_rolls_back_business_writes_and_cleans_claim(
    real_database_url,
    monkeypatch,
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)
    original_state = await _business_state(factory, session_id)

    async def successful_chat_edit(options, settings=None, *, deadline=None):
        return ChatEditResult(
            mermaid_code="flowchart LR\nA-->must_rollback",
            message="Must roll back",
            usage=None,
        )

    async def reject_completion(self, **kwargs):
        return 0

    monkeypatch.setattr("app.services.chat.service.chat_edit", successful_chat_edit)
    monkeypatch.setattr(TurnRepository, "complete", reject_completion)

    try:
        with pytest.raises(RequestInProgress):
            await _run_chat(
                factory,
                session_id,
                request_id="request-completion-failure",
            )

        assert await _business_state(factory, session_id) == original_state
        async with factory() as db:
            turn = await TurnRepository(db).get_fresh(
                session_id,
                "request-completion-failure",
            )
        assert turn is None
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_noop_undo_completes_and_replays_without_new_version(
    real_database_url,
    monkeypatch,
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)

    async def forbid_llm(*args, **kwargs):
        raise AssertionError("Undo must not call the LLM")

    monkeypatch.setattr("app.services.chat.service.chat_edit", forbid_llm)

    try:
        first = await _run_chat(
            factory,
            session_id,
            request_id="request-noop-undo-replay",
            message="верни предыдущую версию",
        )
        first_state = await _business_state(factory, session_id)
        replay = await _run_chat(
            factory,
            session_id,
            request_id="request-noop-undo-replay",
            message="верни предыдущую версию",
            action_type="RESTORE_PREVIOUS",
        )

        assert replay == first
        assert first_state[1:] == (0, 1, 1)
        assert await _business_state(factory, session_id) == first_state
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_mutating_undo_completion_failure_rolls_back_version_and_head(
    real_database_url,
    monkeypatch,
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(
        factory,
        mermaid_code="flowchart LR\nA-->first",
    )

    async def forbid_llm(*args, **kwargs):
        raise AssertionError("Undo must not call the LLM")

    async def reject_completion(self, **kwargs):
        return 0

    monkeypatch.setattr("app.services.chat.service.chat_edit", forbid_llm)
    monkeypatch.setattr(TurnRepository, "complete", reject_completion)

    try:
        async with factory() as db:
            async with db.begin():
                session = await SessionRepository(db).get(session_id)
                assert session is not None
                second = DiagramVersion(
                    session_id=session_id,
                    mermaid_code="flowchart LR\nA-->second",
                    parent_version_id=session.head_version_id,
                )
                DiagramVersionRepository(db).add(second)
                await db.flush()
                await SessionRepository(db).set_head(session_id, second.id)

        original_state = await _business_state(factory, session_id)
        with pytest.raises(RequestInProgress):
            await _run_chat(
                factory,
                session_id,
                request_id="request-undo-completion-failure",
                message="undo via explicit action",
                action_type="RESTORE_PREVIOUS",
            )

        assert await _business_state(factory, session_id) == original_state
        async with factory() as db:
            assert await TurnRepository(db).get_fresh(
                session_id,
                "request-undo-completion-failure",
            ) is None
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_mutating_undo_completes_and_replays_without_extra_version(
    real_database_url,
    monkeypatch,
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(
        factory,
        mermaid_code="flowchart LR\nA-->first",
    )

    async def forbid_llm(*args, **kwargs):
        raise AssertionError("Undo must not call the LLM")

    monkeypatch.setattr("app.services.chat.service.chat_edit", forbid_llm)

    try:
        async with factory() as db:
            async with db.begin():
                session = await SessionRepository(db).get(session_id)
                assert session is not None
                second = DiagramVersion(
                    session_id=session_id,
                    mermaid_code="flowchart LR\nA-->second",
                    parent_version_id=session.head_version_id,
                )
                DiagramVersionRepository(db).add(second)
                await db.flush()
                await SessionRepository(db).set_head(session_id, second.id)

        first = await _run_chat(
            factory,
            session_id,
            request_id="request-mutating-undo-replay",
            message="undo via explicit action",
            action_type="RESTORE_PREVIOUS",
        )
        first_state = await _business_state(factory, session_id)
        replay = await _run_chat(
            factory,
            session_id,
            request_id="request-mutating-undo-replay",
            message="undo via explicit action",
            action_type="RESTORE_PREVIOUS",
        )

        assert first.mermaid_code == "flowchart LR\nA-->first"
        assert replay == first
        assert first_state[1:] == (0, 3, 1)
        assert await _business_state(factory, session_id) == first_state
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_exhausted_deadline_binds_owner_but_does_not_create_claim(
    real_database_url,
    monkeypatch,
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory, user_id=None)

    class ExhaustedDeadline:
        def require_remaining(self) -> float:
            raise LLMError("TIMEOUT", "deadline exhausted before claim")

    class ExhaustedDeadlineFactory:
        @classmethod
        def from_timeout_ms(cls, timeout_ms: int):
            return ExhaustedDeadline()

    async def forbid_claim(*args, **kwargs):
        raise AssertionError("Exhausted deadline must not create a claim")

    monkeypatch.setattr(
        "app.services.chat.service.LLMDeadline",
        ExhaustedDeadlineFactory,
    )
    monkeypatch.setattr(TurnRepository, "claim_or_take_over", forbid_claim)

    try:
        with pytest.raises(LLMError) as exc_info:
            await _run_chat(
                factory,
                session_id,
                request_id="request-expired-before-claim",
                user_id="alice",
            )
        assert exc_info.value.code == "TIMEOUT"

        async with factory() as db:
            session = await SessionRepository(db).get(session_id)
            turn_count = await db.scalar(
                sa.select(sa.func.count())
                .select_from(Turn)
                .where(Turn.session_id == session_id)
            )
        assert session is not None
        assert session.user_id == "alice"
        assert turn_count == 0
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_cleanup_error_is_warning_and_does_not_mask_primary_error(
    real_database_url,
    monkeypatch,
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)

    async def failing_chat_edit(options, settings=None, *, deadline=None):
        raise RuntimeError("primary chat failure")

    async def failing_cleanup(self, **kwargs):
        raise RuntimeError("cleanup database failure")

    warnings: list[str] = []

    def capture_warning(message, *args, **kwargs):
        warnings.append(message)

    monkeypatch.setattr("app.services.chat.service.chat_edit", failing_chat_edit)
    monkeypatch.setattr(TurnRepository, "delete_incomplete_owned", failing_cleanup)
    monkeypatch.setattr(
        "app.services.chat.service.logger.warning",
        capture_warning,
    )

    try:
        with pytest.raises(RuntimeError, match="primary chat failure"):
            await _run_chat(
                factory,
                session_id,
                request_id="request-cleanup-warning",
            )

        assert any("Chat request claim cleanup failed" in item for item in warnings)
        async with factory() as db:
            turn = await TurnRepository(db).get_fresh(
                session_id,
                "request-cleanup-warning",
            )
        assert turn is not None
        assert turn.response_json is None
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()
