from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.deps import ChatServiceDep, CurrentIdentity
from app.api.schemas import ApiError
from app.config import get_settings
from app.services.chat.service import (
    RequestIdConflict,
    RequestInProgress,
    SessionNotFound,
    VersionConflict,
)
from app.services.files.extract import (
    get_extension,
    is_chat_document_format,
    normalize_text_file,
)

logger = logging.getLogger(__name__)

router = APIRouter()
MAX_REQUEST_ID_LENGTH = 128

_USER_MESSAGES = {
    "invalid-request": "Некорректный запрос",
    "session-required": "Необходимо указать идентификатор сессии",
    "request-id-required": "Необходимо указать идентификатор запроса",
    "session-not-found": "Сессия не найдена",
    "request-in-progress": "Для этой сессии уже выполняется запрос",
    "request-id-conflict": "Идентификатор запроса уже использован для других данных",
    "version-conflict": "Состояние сессии изменилось. Повторите запрос",
    "diagram-generation": "Схема не сформирована. Перезагрузите страницу или повторите попытку позже",
    "file-format": "Этот формат файла не поддерживается",
    "file-size": "Размер файла не должен превышать 20 МБ",
    "attachment-error": "Не удалось прочитать содержимое файла",
}


async def _read_attachment_context(form, session_id: str) -> str | JSONResponse:
    """Returns the extracted text for an optional `file` attachment, "" when
    none was sent, or a 4xx JSONResponse the caller must return as-is.

    A stub/unreadable-content attachment is rejected as `attachment-error`,
    same as /api/generate -- so a chat attachment can never silently reach
    the model as a placeholder string instead of its real content.
    """
    upload = form.get("file")
    if upload is None or not getattr(upload, "filename", None):
        return ""

    settings = get_settings()
    content = await upload.read()
    if len(content) > settings.max_chat_attachment_bytes:
        return _api_error(400, "file-size", session_id)

    fmt = get_extension(upload.filename)
    if not is_chat_document_format(fmt):
        return _api_error(400, "file-format", session_id)

    normalized = await normalize_text_file(upload.filename, content, len(content))
    if normalized.stub:
        return _api_error(400, "attachment-error", session_id)

    return normalized.text


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
async def chat(
    request: Request,
    identity: CurrentIdentity,
    chat_service: ChatServiceDep,
) -> JSONResponse:
    form = await request.form()
    session_id = str(form.get("sessionId", "") or "").strip()
    if not session_id:
        return _api_error(400, "session-required", session_id)

    request_id = str(form.get("requestId", "") or "").strip()
    if not request_id:
        return _api_error(400, "request-id-required", session_id)
    if len(request_id) > MAX_REQUEST_ID_LENGTH:
        return _api_error(400, "invalid-request", session_id)

    message = str(form.get("message", "") or "")
    action_type = str(form.get("actionType", "") or "FREEFORM")
    client_mermaid = str(form.get("mermaidCode", "") or "")

    attachment_context = await _read_attachment_context(form, session_id)
    if isinstance(attachment_context, JSONResponse):
        return attachment_context

    try:
        result = await chat_service.run_chat(
            session_id=session_id,
            request_id=request_id,
            principal=identity,
            message=message,
            action_type=action_type,
            client_mermaid=client_mermaid,
            attachment_context=attachment_context,
        )
    except SessionNotFound:
        return _api_error(404, "session-not-found", session_id)
    except RequestInProgress:
        return _api_error(409, "request-in-progress", session_id)
    except RequestIdConflict:
        return _api_error(409, "request-id-conflict", session_id)
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
