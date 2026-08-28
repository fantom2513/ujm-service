from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.infrastructure.db.session import get_db_session


async def get_redis(request: Request) -> Redis:
    return request.app.state.redis


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    async for session in get_db_session(request.app.state.db_sessionmaker):
        yield session


SettingsDep = Annotated[Settings, Depends(get_settings)]
RedisDep = Annotated[Redis, Depends(get_redis)]
DbSessionDep = Annotated[AsyncSession, Depends(get_db)]
