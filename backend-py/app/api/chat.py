from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.deps import ChatServiceDep
from app.api.schemas import ApiError
from app.services.chat.service import (
    RequestInProgress,
    SessionNotFound,
    VersionConflict,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_USER_MESSAGES = {
    "session-required": "Необходимо указать идентификатор сессии",
    "session-not-found": "Сессия не найдена",
    "request-in-progress": "Для этой сессии уже выполняется запрос",
    "version-conflict": "Состояние сессии изменилось. Повторите запрос",
    "diagram-generation": "Схема не сформирована. Перезагрузите страницу или повторите попытку позже",
}


def _api_error(status_code: int, code: str, session_id: str) -> JSONResponse:
    error = ApiError(code=code, message=_USER_MESSAGES[code])
    return JSONResponse(
        status_code=status_code,
        content={
            "ok": False,
            "sessionId": session_id,
            "error": error.model_dump(by_alias=True, exclude_none=True),
        },
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/api/chat")
async def chat(request: Request, chat_service: ChatServiceDep) -> JSONResponse:
    form = await request.form()
    session_id = str(form.get("sessionId", "") or "").strip()
    if not session_id:
        return _api_error(400, "session-required", session_id)

    message = str(form.get("message", "") or "")
    action_type = str(form.get("actionType", "") or "FREEFORM")
    client_mermaid = str(form.get("mermaidCode", "") or "")
    user_id = request.headers.get("X-User-Id") or None

    try:
        result = await chat_service.run_chat(
            session_id=session_id,
            user_id=user_id,
            message=message,
            action_type=action_type,
            client_mermaid=client_mermaid,
        )
    except SessionNotFound:
        return _api_error(404, "session-not-found", session_id)
    except RequestInProgress:
        return _api_error(409, "request-in-progress", session_id)
    except VersionConflict:
        return _api_error(409, "version-conflict", session_id)
    except Exception:
        logger.exception("Chat request failed for session %s", session_id)
        return _api_error(500, "diagram-generation", session_id)

    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "result": result.model_dump(by_alias=True, exclude_none=True),
        },
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
