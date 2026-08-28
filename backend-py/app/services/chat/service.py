from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings


class ChatService:
    # Methods land in Tasks 05-06 once chat behavior is defined — this is
    # constructor-only wiring so routes have something real to depend on.
    def __init__(self, db: AsyncSession, redis: Redis, settings: Settings) -> None:
        self._db = db
        self._redis = redis
        self._settings = settings
