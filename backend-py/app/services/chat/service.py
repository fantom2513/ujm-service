from __future__ import annotations

import asyncio
import logging
import secrets

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.schemas import ChatResult
from app.config import Settings
from app.domain.undo import is_undo_request
from app.infrastructure.db.models import DiagramVersion, Message, Session
from app.infrastructure.db.repositories import (
    DiagramVersionRepository,
    MessageRepository,
    SessionRepository,
)
from app.services.openai.chat import ChatEditOptions, chat_edit

logger = logging.getLogger(__name__)

CHAT_HEARTBEAT_INTERVAL_SECONDS = 10


class SessionNotFound(Exception):
    """A missing or unauthorized session; deliberately one public outcome."""


class RequestInProgress(Exception):
    """The authorized session already has a live chat lease."""


class VersionConflict(Exception):
    """The persisted head or lease changed before this worker could write."""


class InvalidSessionState(RuntimeError):
    """The session exists but its persisted head/version invariant is broken."""


class ChatService:
    def __init__(
        self,
        db: AsyncSession,
        db_sessionmaker: async_sessionmaker[AsyncSession],
        redis: Redis,
        settings: Settings,
    ) -> None:
        self._db = db
        self._db_sessionmaker = db_sessionmaker
        self._redis = redis
        self._settings = settings

    async def create_session_with_version(
        self,
        *,
        source_text: str,
        additional_details: str,
        user_id: str | None,
        mermaid_code: str,
    ) -> str:
        session_id = secrets.token_urlsafe(32)
        sessions = SessionRepository(self._db)
        versions = DiagramVersionRepository(self._db)

        async with self._db.begin():
            sessions.add(
                Session(
                    id=session_id,
                    user_id=user_id,
                    source_text=source_text,
                    additional_details=additional_details or None,
                )
            )
            # A column-level FK does not give SQLAlchemy enough relationship
            # information to order these inserts, so persist the parent row
            # before staging its first diagram version. This is still inside
            # the same transaction and rolls back with everything below.
            await self._db.flush()

            version = DiagramVersion(
                session_id=session_id,
                mermaid_code=mermaid_code,
                parent_version_id=None,
            )
            versions.add(version)
            await self._db.flush()  # Postgres assigns version.id / version.seq.
            await sessions.set_head(session_id, version.id)

        return session_id

    async def run_chat(
        self,
        *,
        session_id: str,
        user_id: str | None,
        message: str,
        action_type: str,
        client_mermaid: str,
    ) -> ChatResult:
        sessions = SessionRepository(self._db)
        versions = DiagramVersionRepository(self._db)
        messages = MessageRepository(self._db)

        # The client copy is advisory only. The persisted head below is the
        # source of truth for prompt construction and parent_version_id.
        _ = client_mermaid

        # Ownership is resolved in its own transaction. In particular, a
        # successful anonymous bind must remain committed if context loading,
        # lease acquisition (added by the concurrency flow), the LLM, or the
        # final persistence step fails later.
        async with self._db.begin():
            stored_session = await sessions.get(session_id)
            if stored_session is None:
                raise SessionNotFound
            if stored_session.user_id is not None and stored_session.user_id != user_id:
                raise SessionNotFound
            if stored_session.user_id is None and user_id:
                if await sessions.bind_user(session_id, user_id) != 1:
                    # A concurrent request may have completed the same bind
                    # while this UPDATE waited. Do not trust stored_session:
                    # expire_on_commit=False keeps it in the identity map with
                    # its old user_id. Force a new SELECT and refresh it from
                    # PostgreSQL before deciding whether access is allowed.
                    current = await sessions.get_fresh(session_id)
                    if current is None or current.user_id != user_id:
                        raise SessionNotFound

        lock_token = secrets.token_urlsafe(32)
        lease_claimed = False
        heartbeat_task: asyncio.Task[None] | None = None

        try:
            async with self._db.begin():
                acquired = await sessions.acquire_lease(
                    session_id, user_id, lock_token
                )
                if acquired != 1:
                    current = await sessions.get_fresh(session_id)
                    if current is None or current.user_id != user_id:
                        raise SessionNotFound
                    raise RequestInProgress
                lease_claimed = True

                stored_session = await sessions.get_fresh(session_id)
                if stored_session is None:
                    raise SessionNotFound
                if stored_session.head_version_id is None:
                    raise InvalidSessionState("Session has no head version")
                head = await versions.get(stored_session.head_version_id)
                if head is None or head.session_id != session_id:
                    raise InvalidSessionState(
                        "Session head version is missing or foreign"
                    )
                previous = await versions.get_previous(session_id, head.seq)
                history_rows = await messages.list_by_session(session_id)

                # Copy primitives while the read scope is active. No ORM state
                # is accessed during the potentially long LLM call below.
                source_text = stored_session.source_text
                additional_details = stored_session.additional_details or ""
                head_id = head.id
                current_mermaid = head.mermaid_code
                previous_mermaid = previous.mermaid_code if previous else None
                history = [(row.role, row.text) for row in history_rows]

            # The acquire/context transaction is closed before this background
            # task starts, so it never shares self._db with the main flow.
            heartbeat_task = asyncio.create_task(
                self._heartbeat_lease(session_id, lock_token),
                name=f"chat-lease-heartbeat:{session_id}",
            )

            # Exact undo phrases take precedence over the frontend action. This
            # keeps undo deterministic even when an older client sends FREEFORM.
            resolved_action = (
                "RESTORE_PREVIOUS" if is_undo_request(message) else action_type
            )
            if resolved_action == "RESTORE_PREVIOUS":
                return await self._apply_undo(
                    session_id=session_id,
                    head_id=head_id,
                    current_mermaid=current_mermaid,
                    previous_mermaid=previous_mermaid,
                    lock_token=lock_token,
                )

            edit_result = await chat_edit(
                ChatEditOptions(
                    source_text=source_text,
                    additional_details=additional_details,
                    current_mermaid=current_mermaid,
                    previous_mermaid=previous_mermaid,
                    history=history,
                    action_type=resolved_action,
                    user_message=message,
                ),
                self._settings,
            )

            async with self._db.begin():
                messages.add(Message(session_id=session_id, role="user", text=message))
                messages.add(
                    Message(
                        session_id=session_id,
                        role="assistant",
                        text=edit_result.message,
                    )
                )
                version = DiagramVersion(
                    session_id=session_id,
                    mermaid_code=edit_result.mermaid_code,
                    parent_version_id=head_id,
                )
                versions.add(version)
                await self._db.flush()
                head_updated = await sessions.set_head_fenced(
                    session_id=session_id,
                    expected_head_version_id=head_id,
                    version_id=version.id,
                    lock_token=lock_token,
                )
                if head_updated != 1:
                    raise VersionConflict

            return ChatResult(
                session_id=session_id,
                mermaid_code=edit_result.mermaid_code,
                message=edit_result.message,
            )
        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.warning(
                        "Chat lease heartbeat task failed for session %s",
                        session_id,
                        exc_info=True,
                    )
            if lease_claimed:
                await self._release_lease(session_id, lock_token)

    async def _heartbeat_lease(self, session_id: str, lock_token: str) -> None:
        while True:
            await asyncio.sleep(CHAT_HEARTBEAT_INTERVAL_SECONDS)
            try:
                async with self._db_sessionmaker() as db:
                    async with db.begin():
                        extended = await SessionRepository(db).heartbeat_lease(
                            session_id, lock_token
                        )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "Chat lease heartbeat failed for session %s",
                    session_id,
                    exc_info=True,
                )
                return
            if extended != 1:
                logger.warning(
                    "Chat lease heartbeat lost ownership for session %s",
                    session_id,
                )
                return

    async def _release_lease(self, session_id: str, lock_token: str) -> None:
        try:
            async with self._db_sessionmaker() as db:
                async with db.begin():
                    released = await SessionRepository(db).release_lease(
                        session_id, lock_token
                    )
        except Exception:
            logger.warning(
                "Chat lease release failed for session %s",
                session_id,
                exc_info=True,
            )
            return
        if released != 1:
            logger.warning(
                "Chat lease release lost ownership for session %s",
                session_id,
            )

    async def _apply_undo(
        self,
        *,
        session_id: str,
        head_id: int,
        current_mermaid: str,
        previous_mermaid: str | None,
        lock_token: str,
    ) -> ChatResult:
        if previous_mermaid is None:
            return ChatResult(
                session_id=session_id,
                mermaid_code=current_mermaid,
                message="Предыдущая версия схемы недоступна.",
            )

        sessions = SessionRepository(self._db)
        versions = DiagramVersionRepository(self._db)

        # Undo is append-only: preserve every old row, copy the previous
        # Mermaid into a new child of the current head, then move the head.
        async with self._db.begin():
            restored = DiagramVersion(
                session_id=session_id,
                mermaid_code=previous_mermaid,
                parent_version_id=head_id,
            )
            versions.add(restored)
            await self._db.flush()
            head_updated = await sessions.set_head_fenced(
                session_id=session_id,
                expected_head_version_id=head_id,
                version_id=restored.id,
                lock_token=lock_token,
            )
            if head_updated != 1:
                raise VersionConflict

        return ChatResult(
            session_id=session_id,
            mermaid_code=previous_mermaid,
            message="Предыдущая версия схемы восстановлена.",
        )
