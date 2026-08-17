from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def build_engine(database_url: str) -> AsyncEngine:
    # create_async_engine is lazy — no connection is opened until the first
    # query, so this is safe to call even when Postgres isn't reachable yet
    # (matches Phase 0 scope: wiring only, no consumer until Phase 2).
    return create_async_engine(database_url, pool_pre_ping=True)


def build_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    async with factory() as session:
        yield session
