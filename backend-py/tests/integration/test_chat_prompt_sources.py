from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.infrastructure.db.models import DiagramVersion, Message
from app.infrastructure.db.repositories import (
    DiagramVersionRepository,
    MessageRepository,
    SessionRepository,
)
from app.services.openai.chat import ChatEditResult
from app.services.openai.prompts import build_chat_prompt
from tests.integration._chat_helpers import (
    create_initial_session,
    delete_session,
    make_chat_service,
    upgrade_head,
)


def _render_captured_prompt(options) -> str:
    return build_chat_prompt(
        source_text=options.source_text,
        additional_details=options.additional_details,
        current_mermaid=options.current_mermaid,
        previous_mermaid=options.previous_mermaid,
        history=options.history,
        action_type=options.action_type,
        user_message=options.user_message,
        attachment_context=options.attachment_context,
    )


async def test_run_chat_builds_options_from_postgres_not_client_copy(
    real_database_url, monkeypatch
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(
        factory,
        source_text="DB SOURCE",
        additional_details="DB DETAILS",
        mermaid_code="flowchart LR\nDB_V1-->A",
    )
    captured = {}

    try:
        async with factory() as db:
            sessions = SessionRepository(db)
            versions = DiagramVersionRepository(db)
            messages = MessageRepository(db)
            async with db.begin():
                stored = await sessions.get(session_id)
                v1_id = stored.head_version_id
                messages.add(Message(session_id=session_id, role="user", text="DB USER"))
                messages.add(
                    Message(session_id=session_id, role="assistant", text="DB ASSISTANT")
                )
                v2 = DiagramVersion(
                    session_id=session_id,
                    mermaid_code="flowchart LR\nDB_V2-->B",
                    parent_version_id=v1_id,
                )
                versions.add(v2)
                await db.flush()
                await sessions.set_head(session_id, v2.id)

        async def fake_chat_edit(options, settings=None, *, deadline=None):
            captured["options"] = options
            captured["prompt"] = _render_captured_prompt(options)
            return ChatEditResult(
                mermaid_code="flowchart LR\nDB_V2-->C",
                message="Stored-source edit",
                usage=None,
            )

        monkeypatch.setattr("app.services.chat.service.chat_edit", fake_chat_edit)

        async with factory() as db:
            await make_chat_service(db, factory).run_chat(
                session_id=session_id,
                user_id=None,
                message="CURRENT USER MESSAGE",
                action_type="FREEFORM",
                client_mermaid="CLIENT MERMAID MUST NOT WIN",
            )

        options = captured["options"]
        assert options.source_text == "DB SOURCE"
        assert options.additional_details == "DB DETAILS"
        assert options.current_mermaid == "flowchart LR\nDB_V2-->B"
        assert options.previous_mermaid == "flowchart LR\nDB_V1-->A"
        assert list(options.history) == [
            ("user", "DB USER"),
            ("assistant", "DB ASSISTANT"),
        ]
        assert options.user_message == "CURRENT USER MESSAGE"
        assert "CLIENT MERMAID MUST NOT WIN" not in captured["prompt"]
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()


async def test_single_version_produces_exact_empty_previous_block(
    real_database_url, monkeypatch
):
    await upgrade_head()
    engine = create_async_engine(real_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = await create_initial_session(factory)
    captured = {}

    async def fake_chat_edit(options, settings=None, *, deadline=None):
        captured["prompt"] = _render_captured_prompt(options)
        return ChatEditResult(
            mermaid_code="flowchart LR\nA-->C",
            message="Done",
            usage=None,
        )

    monkeypatch.setattr("app.services.chat.service.chat_edit", fake_chat_edit)

    try:
        async with factory() as db:
            await make_chat_service(db, factory).run_chat(
                session_id=session_id,
                user_id=None,
                message="change",
                action_type="FREEFORM",
                client_mermaid="ignored",
            )

        assert "<PREVIOUS_MERMAID></PREVIOUS_MERMAID>" in captured["prompt"]
    finally:
        await delete_session(engine, session_id)
        await engine.dispose()
