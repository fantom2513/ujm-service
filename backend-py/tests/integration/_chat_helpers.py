import asyncio
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.config import Settings
from app.domain.identity import Principal
from app.services.chat.service import ChatService

BACKEND_PY_ROOT = Path(__file__).resolve().parents[2]


async def upgrade_head() -> None:
    alembic_cfg = Config(str(BACKEND_PY_ROOT / "alembic.ini"))
    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")


def make_chat_service(db, factory) -> ChatService:
    return ChatService(
        db=db,
        db_sessionmaker=factory,
        redis=None,  # type: ignore[arg-type]
        settings=Settings(),
    )


def principal_for(user_id: str | None) -> Principal:
    if user_id is None:
        return Principal.anonymous()
    return Principal.authenticated(user_id)


async def create_initial_session(
    factory,
    *,
    source_text: str = "server specification",
    additional_details: str = "server details",
    user_id: str | None = None,
    mermaid_code: str = "flowchart LR\nA-->B",
) -> str:
    async with factory() as db:
        return await make_chat_service(db, factory).create_session_with_version(
            source_text=source_text,
            additional_details=additional_details,
            principal=principal_for(user_id),
            mermaid_code=mermaid_code,
        )


async def delete_session(engine, session_id: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            sa.text("DELETE FROM sessions WHERE id = :id"), {"id": session_id}
        )
