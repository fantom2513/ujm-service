from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import DiagramVersion, Message, Session

# Repositories own concrete DB operations for one table each. They never
# call commit()/begin() and never open their own transaction — the
# orchestration layer (ChatService) decides the transaction boundary,
# because only it knows the full set of rows that must land atomically
# (primer sections 23-27). `add()` only stages into the unit of work.


class SessionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    def add(self, session: Session) -> None:
        self._db.add(session)

    async def get(self, session_id: str) -> Session | None:
        return await self._db.get(Session, session_id)

    async def set_head(self, session_id: str, version_id: int) -> None:
        await self._db.execute(
            update(Session)
            .where(Session.id == session_id)
            .values(head_version_id=version_id, updated_at=func.now())
        )

    async def bind_user(self, session_id: str, user_id: str) -> int:
        # Conditional UPDATE: only claims a still-anonymous session. Returns
        # the affected row count so the caller can tell "bound it" (1) from
        # "someone/something already owns it" (0) without a prior SELECT.
        result = await self._db.execute(
            update(Session)
            .where(Session.id == session_id, Session.user_id.is_(None))
            .values(user_id=user_id, updated_at=func.now())
        )
        return result.rowcount


class DiagramVersionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    def add(self, version: DiagramVersion) -> None:
        self._db.add(version)

    async def get(self, version_id: int) -> DiagramVersion | None:
        return await self._db.get(DiagramVersion, version_id)

    async def get_previous(
        self, session_id: str, head_seq: int
    ) -> DiagramVersion | None:
        # "Previous version" = same session, greatest seq strictly below the
        # current head's seq. Deliberately by seq order, not by walking the
        # parent_version_id chain.
        result = await self._db.execute(
            select(DiagramVersion)
            .where(
                DiagramVersion.session_id == session_id,
                DiagramVersion.seq < head_seq,
            )
            .order_by(DiagramVersion.seq.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


class MessageRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    def add(self, message: Message) -> None:
        self._db.add(message)

    async def list_by_session(self, session_id: str) -> list[Message]:
        # ORDER BY seq, not created_at: rows written in one transaction share
        # the same transaction timestamp, so created_at can't order them.
        result = await self._db.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.seq)
        )
        return list(result.scalars().all())
