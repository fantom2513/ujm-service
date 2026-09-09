from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.domain.identity import Principal
from app.infrastructure.db.session import get_db_session
from app.services.chat.service import ChatService


async def get_redis(request: Request) -> Redis:
    return request.app.state.redis


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    async for session in get_db_session(request.app.state.db_sessionmaker):
        yield session


def get_db_sessionmaker(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.db_sessionmaker


SettingsDep = Annotated[Settings, Depends(get_settings)]
RedisDep = Annotated[Redis, Depends(get_redis)]
DbSessionDep = Annotated[AsyncSession, Depends(get_db)]
DbSessionmakerDep = Annotated[
    async_sessionmaker[AsyncSession], Depends(get_db_sessionmaker)
]


def get_current_identity(
    settings: SettingsDep,
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
) -> Principal:
    if settings.identity_mode == "anonymous":
        return Principal.anonymous()

    subject = x_user_id.strip() if x_user_id is not None else ""
    if not subject:
        return Principal.anonymous()
    return Principal.authenticated(subject)


CurrentIdentity = Annotated[Principal, Depends(get_current_identity)]


def get_chat_service(
    db: DbSessionDep,
    db_sessionmaker: DbSessionmakerDep,
    redis: RedisDep,
    settings: SettingsDep,
) -> ChatService:
    return ChatService(
        db=db,
        db_sessionmaker=db_sessionmaker,
        redis=redis,
        settings=settings,
    )


ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]
