from __future__ import annotations

import asyncio
import logging
import secrets
from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import func, select

from app.api.schemas import ApiError, ChatResult, DiagramResult, FileMeta, SourceContext
from app.config import Settings
from app.domain.chat_request import compute_chat_request_hash
from app.domain.identity import Principal
from app.domain.undo import is_undo_request
from app.infrastructure.db.models import DiagramVersion, Message, Session, Turn
from app.infrastructure.db.repositories import (
    DiagramVersionRepository,
    GenerateRequestRepository,
    MessageRepository,
    SessionRepository,
    TurnRepository,
)
from app.infrastructure.llm.deadline import LLMDeadline
from app.domain.mermaid import validate_mermaid
from app.services.files.extract import NormalizedSource
from app.services.links.classify import normalize_link
from app.services.openai.chat import ChatEditOptions, chat_edit
from app.services.openai.generate import generate_diagram

logger = logging.getLogger(__name__)

CHAT_HEARTBEAT_INTERVAL_SECONDS = 10


class SessionNotFound(Exception):
    """A missing or unauthorized session; deliberately one public outcome."""


class RequestInProgress(Exception):
    """The request or authorized session is already being processed."""


class RequestIdConflict(Exception):
    """The request ID was already used for a different chat payload."""


class VersionConflict(Exception):
    """The persisted head or lease changed before this worker could write."""


class InvalidSessionState(RuntimeError):
    """The session exists but its persisted head/version invariant is broken."""


@dataclass(frozen=True)
class ClaimedChatTurn:
    session_id: str
    request_id: str
    owner_id: str | None
    message: str
    resolved_action: str
    attachment_context: str
    claim_token: str
    deadline: LLMDeadline


@dataclass(frozen=True)
class ClaimedGenerateTurn:
    session_id: str
    request_id: str
    owner_id: str | None
    source: NormalizedSource
    details: str
    claim_token: str
    deadline: LLMDeadline


class GenerateRequestExists(Exception):
    """Roll back the speculative session before reading the winning request."""


class StoredTurnFailure(Exception):
    def __init__(self, error: dict[str, object], status_code: int = 500):
        self.error = error
        self.status_code = status_code
        super().__init__(str(error.get("code", "diagram-generation")))


def success_envelope(result: ChatResult | DiagramResult) -> dict[str, object]:
    return {"ok": True, "result": result.model_dump(by_alias=True, exclude_none=True)}


def resolve_turn_response(turn: Turn) -> dict[str, object]:
    response = turn.response_json
    if response is None:
        raise ValueError("Cannot resolve an incomplete turn")
    if "ok" not in response:
        # Defensive compatibility for a deployment that has not run 0003 yet.
        return {"ok": True, "result": response}
    return response


def error_for_exception(error: BaseException) -> tuple[int, dict[str, object]]:
    if isinstance(error, SessionNotFound):
        return 404, ApiError(code="session-not-found", message="Сессия не найдена").model_dump(by_alias=True)
    if isinstance(error, RequestInProgress):
        return 409, ApiError(code="request-in-progress", message="Для этой сессии уже выполняется запрос").model_dump(by_alias=True)
    if isinstance(error, VersionConflict):
        return 409, ApiError(code="version-conflict", message="Состояние сессии изменилось. Повторите запрос").model_dump(by_alias=True)
    return 500, ApiError(code="diagram-generation", message="Схема не сформирована. Перезагрузите страницу или повторите попытку позже").model_dump(by_alias=True)


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
        principal: Principal,
        mermaid_code: str,
    ) -> str:
        owner_id = principal.subject
        session_id = secrets.token_urlsafe(32)
        sessions = SessionRepository(self._db)
        versions = DiagramVersionRepository(self._db)

        async with self._db.begin():
            sessions.add(
                Session(
                    id=session_id,
                    user_id=owner_id,
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

    async def claim_generate(
        self,
        *,
        request_id: str,
        request_hash: str,
        principal: Principal,
        source: NormalizedSource,
        details: str,
    ) -> ClaimedGenerateTurn | dict[str, object]:
        deadline = LLMDeadline.from_timeout_ms(self._settings.llm_deadline_ms)
        remaining = deadline.require_remaining()
        session_id = secrets.token_urlsafe(32)
        claim_token = secrets.token_urlsafe(32)
        try:
            async with self._db.begin():
                self._db.add(Session(
                    id=session_id,
                    user_id=principal.subject,
                    source_text=source.text,
                    additional_details=details or None,
                ))
                # The lookup has an immediate FK to sessions, so the parent
                # must exist before INSERT ... ON CONFLICT.
                await self._db.flush()
                won = await GenerateRequestRepository(self._db).insert_if_absent(request_id, session_id)
                if not won:
                    raise GenerateRequestExists
                claimed = await TurnRepository(self._db).claim_or_take_over(
                    session_id=session_id,
                    request_id=request_id,
                    request_hash=request_hash,
                    claim_token=claim_token,
                    remaining_seconds=remaining,
                )
                if claimed is None:
                    raise RequestInProgress
        except GenerateRequestExists:
            async with self._db.begin():
                repo = GenerateRequestRepository(self._db)
                session_id = await repo.get_session_id(request_id)
                if session_id is None:
                    raise RequestInProgress
                session = await SessionRepository(self._db).get_fresh(session_id)
                if session is None or (session.user_id is not None and session.user_id != principal.subject):
                    raise RequestIdConflict
                turns = TurnRepository(self._db)
                turn = await turns.get_fresh(session_id, request_id)
                if turn is None:
                    raise RequestInProgress
                if turn.request_hash != request_hash:
                    raise RequestIdConflict
                if turn.response_json is not None:
                    return resolve_turn_response(turn)
                claimed = await turns.claim_or_take_over(
                    session_id=session_id,
                    request_id=request_id,
                    request_hash=request_hash,
                    claim_token=claim_token,
                    remaining_seconds=remaining,
                )
                if claimed is None:
                    raise RequestInProgress
                if session.user_id is None and principal.subject is not None:
                    sessions = SessionRepository(self._db)
                    if await sessions.bind_user(session_id, principal.subject) != 1:
                        current = await sessions.get_fresh(session_id)
                        if current is None or current.user_id != principal.subject:
                            raise RequestIdConflict
        return ClaimedGenerateTurn(
            session_id=session_id,
            request_id=request_id,
            owner_id=principal.subject,
            source=source,
            details=details,
            claim_token=claim_token,
            deadline=deadline,
        )

    async def execute_claimed_generate(self, claim: ClaimedGenerateTurn) -> DiagramResult:
        session_id = claim.session_id
        request_id = claim.request_id
        lock_token = secrets.token_urlsafe(32)
        lease_claimed = False
        heartbeats: list[asyncio.Task[None]] = []
        try:
            async with self._db.begin():
                acquired = await SessionRepository(self._db).acquire_lease(
                    session_id, claim.owner_id, lock_token
                )
                if acquired != 1:
                    raise RequestInProgress
                lease_claimed = True
            heartbeats = [
                asyncio.create_task(self._heartbeat_lease(session_id, lock_token)),
                asyncio.create_task(self._heartbeat_claim(session_id, request_id, claim.claim_token)),
            ]
            source = (
                await normalize_link(claim.source.url)
                if claim.source.type == "link" and claim.source.url
                else claim.source
            )
            mermaid_code = await generate_diagram(
                source.text, claim.details, settings=self._settings, deadline=claim.deadline
            )
            if not validate_mermaid(mermaid_code).ok:
                raise ValueError("Generated Mermaid failed validation")
            result = DiagramResult(
                session_id=session_id,
                title="Тестовая User Flow-схема",
                mermaid_code=mermaid_code,
                source_text=source.text,
                source_context=SourceContext(
                    type=source.type,
                    title=source.title,
                    description=source.description,
                    file=FileMeta(**source.file) if source.file else None,
                    url=source.url,
                    stub=source.stub,
                ),
                details=claim.details,
                chat=[],
                warnings=["Используется временная заглушка backend."] if source.stub else [],
            )
            async with self._db.begin():
                version = DiagramVersion(
                    session_id=session_id,
                    mermaid_code=mermaid_code,
                    parent_version_id=None,
                )
                self._db.add(version)
                await self._db.flush()
                updated = await SessionRepository(self._db).set_head_fenced(
                    session_id=session_id,
                    expected_head_version_id=None,
                    version_id=version.id,
                    lock_token=lock_token,
                )
                if updated != 1:
                    raise VersionConflict
                if source.text != claim.source.text:
                    await SessionRepository(self._db).set_source_text(session_id, source.text)
                completed = await TurnRepository(self._db).complete(
                    session_id=session_id,
                    request_id=request_id,
                    claim_token=claim.claim_token,
                    response_json=success_envelope(result),
                )
                if completed != 1:
                    raise RequestInProgress
                lease_released = await self._release_lease_in_transaction(
                    self._db, session_id, lock_token
                )
            lease_claimed = not lease_released
            return result
        except BaseException as error:
            released = await self._complete_failure(
                session_id, request_id, claim.claim_token, error,
                lock_token if lease_claimed else None,
            )
            if released:
                lease_claimed = False
            raise
        finally:
            for task in heartbeats:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.warning(
                        "Generate heartbeat task failed for session %s",
                        session_id,
                        exc_info=True,
                    )
            if lease_claimed:
                await self._release_lease(session_id, lock_token)

    async def run_chat(
        self,
        *,
        session_id: str,
        request_id: str,
        principal: Principal,
        message: str,
        action_type: str,
        client_mermaid: str,
        attachment_context: str = "",
    ) -> ChatResult:
        """Compatibility entry point for synchronous service callers."""
        outcome = await self.claim_or_replay(
            session_id=session_id,
            request_id=request_id,
            principal=principal,
            message=message,
            action_type=action_type,
            client_mermaid=client_mermaid,
            attachment_context=attachment_context,
        )
        if isinstance(outcome, dict):
            if not outcome["ok"]:
                raise StoredTurnFailure(outcome["error"])
            return ChatResult.model_validate(outcome["result"])
        return await self.execute_claimed_turn(outcome)

    async def claim_or_replay(
        self,
        *,
        session_id: str,
        request_id: str,
        principal: Principal,
        message: str,
        action_type: str,
        client_mermaid: str,
        attachment_context: str = "",
    ) -> ClaimedChatTurn | dict[str, object]:
        owner_id = principal.subject
        sessions = SessionRepository(self._db)

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
            if (
                stored_session.user_id is not None
                and stored_session.user_id != owner_id
            ):
                raise SessionNotFound
            if stored_session.user_id is None and owner_id is not None:
                if await sessions.bind_user(session_id, owner_id) != 1:
                    # A concurrent request may have completed the same bind
                    # while this UPDATE waited. Do not trust stored_session:
                    # expire_on_commit=False keeps it in the identity map with
                    # its old user_id. Force a new SELECT and refresh it from
                    # PostgreSQL before deciding whether access is allowed.
                    current = await sessions.get_fresh(session_id)
                    if current is None or current.user_id != owner_id:
                        raise SessionNotFound

        deadline = LLMDeadline.from_timeout_ms(self._settings.llm_deadline_ms)
        # Exact undo phrases take precedence over the frontend action. Resolve
        # this before hashing so request identity matches the action we execute.
        resolved_action = (
            "RESTORE_PREVIOUS" if is_undo_request(message) else action_type
        )
        request_hash = compute_chat_request_hash(
            message=message,
            effective_action_type=resolved_action,
            attachment_context=attachment_context,
        )
        claim_token = secrets.token_urlsafe(32)
        remaining_seconds = deadline.require_remaining()
        async with self._db.begin():
            turns = TurnRepository(self._db)
            claimed_turn = await turns.claim_or_take_over(
                session_id=session_id,
                request_id=request_id,
                request_hash=request_hash,
                claim_token=claim_token,
                remaining_seconds=remaining_seconds,
            )
            if claimed_turn is None:
                current_turn = await turns.get_fresh(session_id, request_id)
                if current_turn is None:
                    # The conflicting row may have been removed between the
                    # upsert and classification. Let a retry claim it cleanly.
                    raise RequestInProgress
                if current_turn.request_hash != request_hash:
                    raise RequestIdConflict
                if current_turn.response_json is not None:
                    return resolve_turn_response(current_turn)
                raise RequestInProgress
        return ClaimedChatTurn(
            session_id=session_id,
            request_id=request_id,
            owner_id=owner_id,
            message=message,
            resolved_action=resolved_action,
            attachment_context=attachment_context,
            claim_token=claim_token,
            deadline=deadline,
        )

    async def execute_claimed_turn(self, claim: ClaimedChatTurn) -> ChatResult:
        session_id = claim.session_id
        request_id = claim.request_id
        owner_id = claim.owner_id
        message = claim.message
        resolved_action = claim.resolved_action
        attachment_context = claim.attachment_context
        claim_token = claim.claim_token
        deadline = claim.deadline
        sessions = SessionRepository(self._db)
        versions = DiagramVersionRepository(self._db)
        messages = MessageRepository(self._db)
        lock_token = secrets.token_urlsafe(32)
        lease_claimed = False
        heartbeat_task: asyncio.Task[None] | None = None
        claim_heartbeat_task: asyncio.Task[None] | None = None

        try:
            async with self._db.begin():
                acquired = await sessions.acquire_lease(
                    session_id, owner_id, lock_token
                )
                if acquired != 1:
                    current = await sessions.get_fresh(session_id)
                    if current is None or current.user_id != owner_id:
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
            claim_heartbeat_task = asyncio.create_task(
                self._heartbeat_claim(session_id, request_id, claim_token),
                name=f"chat-claim-heartbeat:{session_id}:{request_id}",
            )

            if resolved_action == "RESTORE_PREVIOUS":
                result, lease_released = await self._apply_undo(
                    session_id=session_id,
                    request_id=request_id,
                    claim_token=claim_token,
                    head_id=head_id,
                    current_mermaid=current_mermaid,
                    previous_mermaid=previous_mermaid,
                    lock_token=lock_token,
                )
                lease_claimed = not lease_released
                return result

            edit_result = await chat_edit(
                ChatEditOptions(
                    source_text=source_text,
                    additional_details=additional_details,
                    current_mermaid=current_mermaid,
                    previous_mermaid=previous_mermaid,
                    history=history,
                    action_type=resolved_action,
                    user_message=message,
                    attachment_context=attachment_context,
                ),
                self._settings,
                deadline=deadline,
            )

            result = ChatResult(
                session_id=session_id,
                mermaid_code=edit_result.mermaid_code,
                message=edit_result.message,
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
                completed = await TurnRepository(self._db).complete(
                    session_id=session_id,
                    request_id=request_id,
                    claim_token=claim_token,
                    response_json=success_envelope(result),
                )
                if completed != 1:
                    raise RequestInProgress
                lease_released = await self._release_lease_in_transaction(
                    self._db, session_id, lock_token
                )

            lease_claimed = not lease_released
            return result
        except BaseException as error:
            released = await self._complete_failure(
                session_id, request_id, claim_token, error,
                lock_token if lease_claimed else None,
            )
            if released:
                lease_claimed = False
            raise
        finally:
            for task in (heartbeat_task, claim_heartbeat_task):
                if task is None:
                    continue
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.warning(
                        "Chat heartbeat task failed for session %s",
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
                logger.warning("Chat lease heartbeat lost ownership for session %s", session_id)
                return

    async def _heartbeat_claim(
        self, session_id: str, request_id: str, claim_token: str
    ) -> None:
        while True:
            await asyncio.sleep(CHAT_HEARTBEAT_INTERVAL_SECONDS)
            try:
                async with self._db_sessionmaker() as db:
                    async with db.begin():
                        extended = await TurnRepository(db).heartbeat_claim(
                            session_id, request_id, claim_token
                        )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Claim heartbeat failed for %s/%s", session_id, request_id, exc_info=True)
                return
            if extended != 1:
                logger.warning("Claim heartbeat lost ownership for %s/%s", session_id, request_id)
                return

    async def _complete_failure(
        self, session_id: str, request_id: str, claim_token: str,
        error: BaseException, lock_token: str | None = None,
    ) -> bool:
        _, public_error = error_for_exception(error)
        released = False
        try:
            async with self._db_sessionmaker() as db:
                async with db.begin():
                    completed = await TurnRepository(db).complete(
                        session_id=session_id,
                        request_id=request_id,
                        claim_token=claim_token,
                        response_json={"ok": False, "error": public_error},
                    )
                    if lock_token is not None:
                        released = await self._release_lease_in_transaction(
                            db, session_id, lock_token
                        )
            if completed != 1:
                logger.warning("Could not complete failed claim for %s/%s", session_id, request_id)
        except Exception:
            logger.exception("Could not persist failed claim for %s/%s", session_id, request_id)
            return False
        return released

    async def _release_lease_in_transaction(
        self, db: AsyncSession, session_id: str, lock_token: str
    ) -> bool:
        try:
            async with db.begin_nested():
                released = await SessionRepository(db).release_lease(
                    session_id, lock_token
                )
        except Exception:
            logger.warning(
                "Chat lease release failed for session %s", session_id,
                exc_info=True,
            )
            return False
        if released != 1:
            logger.warning("Chat lease release lost ownership for session %s", session_id)
            return False
        return True

    async def poll_turn(
        self, session_id: str, request_id: str, principal: Principal
    ) -> dict[str, object] | None:
        async with self._db.begin():
            session = await SessionRepository(self._db).get_fresh(session_id)
            if session is None or (session.user_id is not None and session.user_id != principal.subject):
                raise SessionNotFound
            turn = await TurnRepository(self._db).get_fresh(session_id, request_id)
            if turn is None:
                return None
            if turn.response_json is not None:
                return resolve_turn_response(turn)
            now = await self._db.scalar(select(func.clock_timestamp()))
            if turn.claimed_until is not None and turn.claimed_until > now:
                return {"status": "processing"}
            return {"status": "failed", "retryable": True}

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
        request_id: str,
        claim_token: str,
        head_id: int,
        current_mermaid: str,
        previous_mermaid: str | None,
        lock_token: str,
    ) -> tuple[ChatResult, bool]:
        if previous_mermaid is None:
            result = ChatResult(
                session_id=session_id,
                mermaid_code=current_mermaid,
                message="Предыдущая версия схемы недоступна.",
            )
            async with self._db.begin():
                completed = await TurnRepository(self._db).complete(
                    session_id=session_id,
                    request_id=request_id,
                    claim_token=claim_token,
                    response_json=success_envelope(result),
                )
                if completed != 1:
                    raise RequestInProgress
                lease_released = await self._release_lease_in_transaction(
                    self._db, session_id, lock_token
                )
            return result, lease_released

        sessions = SessionRepository(self._db)
        versions = DiagramVersionRepository(self._db)

        # Undo is append-only: preserve every old row, copy the previous
        # Mermaid into a new child of the current head, then move the head.
        result = ChatResult(
            session_id=session_id,
            mermaid_code=previous_mermaid,
            message="Предыдущая версия схемы восстановлена.",
        )
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
            completed = await TurnRepository(self._db).complete(
                session_id=session_id,
                request_id=request_id,
                claim_token=claim_token,
                response_json=success_envelope(result),
            )
            if completed != 1:
                raise RequestInProgress
            lease_released = await self._release_lease_in_transaction(
                self._db, session_id, lock_token
            )

        return result, lease_released


async def run_claimed_chat(
    claim: ClaimedChatTurn,
    db_sessionmaker: async_sessionmaker[AsyncSession],
    redis: Redis,
    settings: Settings,
) -> None:
    try:
        async with db_sessionmaker() as db:
            service = ChatService(db, db_sessionmaker, redis, settings)
            await service.execute_claimed_turn(claim)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Background chat failed for %s/%s", claim.session_id, claim.request_id)


async def run_claimed_generate(
    claim: ClaimedGenerateTurn,
    db_sessionmaker: async_sessionmaker[AsyncSession],
    redis: Redis,
    settings: Settings,
) -> None:
    try:
        async with db_sessionmaker() as db:
            service = ChatService(db, db_sessionmaker, redis, settings)
            await service.execute_claimed_generate(claim)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Background generate failed for %s/%s", claim.session_id, claim.request_id)
