from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import DiagramVersion, Message, Session

CHAT_LEASE_TTL = timedelta(seconds=30)

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

    async def get_fresh(self, session_id: str) -> Session | None:
        """Read the current row from PostgreSQL, refreshing any cached ORM object."""
        result = await self._db.execute(
            select(Session)
            .where(Session.id == session_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def set_head(self, session_id: str, version_id: int) -> None:
        await self._db.execute(
            update(Session)
            .where(Session.id == session_id)
            .values(head_version_id=version_id, updated_at=func.now())
        )

    async def set_head_fenced(
        self,
        session_id: str,
        expected_head_version_id: int,
        version_id: int,
        lock_token: str,
    ) -> int:
        """Move the head only while the expected version and lease are current."""
        database_now = func.clock_timestamp()
        result = await self._db.execute(
            update(Session)
            .where(
                Session.id == session_id,
                Session.head_version_id == expected_head_version_id,
                Session.lock_token == lock_token,
                Session.locked_until > database_now,
            )
            .values(head_version_id=version_id, updated_at=database_now)
        )
        return result.rowcount

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

    async def acquire_lease(
        self,
        session_id: str,
        user_id: str | None,
        lock_token: str,
    ) -> int:
        """Atomically claim a free or expired chat lease for an authorized owner."""
        owner_matches = (
            Session.user_id.is_(None)
            if user_id is None
            else Session.user_id == user_id
        )
        database_now = func.clock_timestamp()
        result = await self._db.execute(
            update(Session)
            .where(
                Session.id == session_id,
                owner_matches,
                or_(
                    Session.locked_until.is_(None),
                    Session.locked_until <= database_now,
                ),
            )
            .values(
                lock_token=lock_token,
                locked_until=database_now + CHAT_LEASE_TTL,
                updated_at=database_now,
            )
        )
        return result.rowcount

    async def heartbeat_lease(self, session_id: str, lock_token: str) -> int:
        """Extend only this worker's lease while it is still alive."""
        database_now = func.clock_timestamp()
        result = await self._db.execute(
            update(Session)
            .where(
                Session.id == session_id,
                Session.lock_token == lock_token,
                Session.locked_until > database_now,
            )
            .values(
                locked_until=database_now + CHAT_LEASE_TTL,
                updated_at=database_now,
            )
        )
        return result.rowcount

    async def release_lease(self, session_id: str, lock_token: str) -> int:
        """Release the lease only if the supplied fencing token still owns it."""
        database_now = func.clock_timestamp()
        result = await self._db.execute(
            update(Session)
            .where(
                Session.id == session_id,
                Session.lock_token == lock_token,
            )
            .values(
                lock_token=None,
                locked_until=None,
                updated_at=database_now,
            )
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
