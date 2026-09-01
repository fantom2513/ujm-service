from __future__ import annotations

import secrets

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

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


class SessionNotFound(Exception):
    """A missing or unauthorized session; deliberately one public outcome."""


class InvalidSessionState(RuntimeError):
    """The session exists but its persisted head/version invariant is broken."""


class ChatService:
    def __init__(self, db: AsyncSession, redis: Redis, settings: Settings) -> None:
        self._db = db
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

        async with self._db.begin():
            stored_session = await sessions.get(session_id)
            if stored_session is None:
                raise SessionNotFound
            if stored_session.user_id is not None and stored_session.user_id != user_id:
                raise SessionNotFound
            if stored_session.user_id is None and user_id:
                if await sessions.bind_user(session_id, user_id) != 1:
                    raise SessionNotFound

            if stored_session.head_version_id is None:
                raise InvalidSessionState("Session has no head version")
            head = await versions.get(stored_session.head_version_id)
            if head is None or head.session_id != session_id:
                raise InvalidSessionState("Session head version is missing or foreign")
            previous = await versions.get_previous(session_id, head.seq)
            history_rows = await messages.list_by_session(session_id)

            # Copy primitives while the read scope is active. No ORM state is
            # accessed during the potentially long LLM call below.
            source_text = stored_session.source_text
            additional_details = stored_session.additional_details or ""
            head_id = head.id
            current_mermaid = head.mermaid_code
            previous_mermaid = previous.mermaid_code if previous else None
            history = [(row.role, row.text) for row in history_rows]

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
            await sessions.set_head(session_id, version.id)

        return ChatResult(
            session_id=session_id,
            mermaid_code=edit_result.mermaid_code,
            message=edit_result.message,
        )

    async def _apply_undo(
        self,
        *,
        session_id: str,
        head_id: int,
        current_mermaid: str,
        previous_mermaid: str | None,
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
            await sessions.set_head(session_id, restored.id)

        return ChatResult(
            session_id=session_id,
            mermaid_code=previous_mermaid,
            message="Предыдущая версия схемы восстановлена.",
        )
