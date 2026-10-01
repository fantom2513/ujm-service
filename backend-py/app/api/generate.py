from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.deps import ChatServiceDep, CurrentIdentity
from app.api.schemas import ApiError
from app.domain.generate_request import compute_generate_request_hash
from app.config import get_settings
from app.domain.generate_guard import required_source_error
from app.services.files.extract import get_extension, is_text_source_format, normalize_text_file
from app.services.links.classify import classify_work_link, link_stub_source
from app.services.chat.background import register_background_task
from app.services.chat.service import (
    ClaimedGenerateTurn,
    RequestIdConflict,
    RequestInProgress,
    run_claimed_generate,
)
from app.services.recordings.normalize import is_recording_format, normalize_recording

logger = logging.getLogger(__name__)

router = APIRouter()
MAX_REQUEST_ID_LENGTH = 128

_USER_MESSAGES = {
    "file-required": "Необходимо прикрепить файл",
    "file-format": "Некорректный формат файла",
    "file-size-text": "Файл превышает 10 МБ",
    "file-size-recording": "Файл превышает 100 МБ",
    "link-required": "Поле обязательно для заполнения",
    "invalid-link": "Неверный формат ссылки",
    "diagram-generation": "Схема не сформирована. Перезагрузите страницу или повторите попытку позже",
    "attachment-error": "Ошибка загрузки файла",
    "request-id-required": "Необходимо указать идентификатор запроса",
    "invalid-request": "Некорректный запрос",
    "request-id-conflict": "Идентификатор запроса уже использован для других данных",
    "request-in-progress": "Запрос уже выполняется",
}


def _api_error(
    status_code: int, code: str, message_key: str | None = None, field: str | None = None
) -> JSONResponse:
    # `code` is the wire value the frontend matches on (must equal the TS
    # UserErrorCode union in shared/types/index.ts — e.g. always "file-size",
    # never "file-size-text"/"file-size-recording"). `message_key` only
    # selects which _USER_MESSAGES text to show; defaults to `code` when the
    # two coincide.
    error = ApiError(code=code, message=_USER_MESSAGES[message_key or code], field=field)
    return JSONResponse(
        status_code=status_code,
        content={"ok": False, "error": error.model_dump(by_alias=True, exclude_none=True)},
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/api/generate")
async def generate(
    request: Request,
    identity: CurrentIdentity,
    chat_service: ChatServiceDep,
):
    form = await request.form()
    request_id = str(form.get("requestId", "") or "").strip()
    if not request_id:
        return _api_error(400, "request-id-required")
    if len(request_id) > MAX_REQUEST_ID_LENGTH:
        return _api_error(400, "invalid-request")
    source_type = form.get("sourceType")
    details = form.get("details", "") or ""
    link = (form.get("link", "") or "").strip()
    # Frontend field name is "file" (see frontend/src/main.ts:871
    # `form.set("file", selectedFile)`), not "attachment" — "attachment" is
    # only used as the `field` value inside error payloads below.
    upload = form.get("file")
    has_file = upload is not None and bool(getattr(upload, "filename", None))
    content = b""

    missing = required_source_error(source_type, has_file, link)
    if missing:
        return _api_error(400, missing)

    settings = get_settings()

    if source_type == "text-file":
        content = await upload.read()
        fmt = get_extension(upload.filename)
        if len(content) > settings.max_text_file_bytes:
            return _api_error(400, "file-size", message_key="file-size-text")
        if not is_text_source_format(fmt):
            return _api_error(400, "file-format")
        source = await normalize_text_file(upload.filename, content, len(content))
        # Same rule as /api/chat's _read_attachment_context: a stub result
        # means normalize_text_file (via parse_pdf/parse_docx) genuinely
        # found no extractable content, so surface that instead of silently
        # generating a diagram from a placeholder string.
        if source.stub:
            return _api_error(400, "attachment-error", field="attachment")
    elif source_type == "recording":
        content = await upload.read()
        fmt = get_extension(upload.filename)
        if len(content) > settings.max_recording_file_bytes:
            return _api_error(400, "file-size", message_key="file-size-recording")
        if not is_recording_format(fmt):
            return _api_error(400, "file-format")
        source = normalize_recording(upload.filename, len(content))
    elif source_type == "link":
        if not classify_work_link(link):
            return _api_error(400, "invalid-link")
        source = link_stub_source(link)
    else:
        return _api_error(400, "diagram-generation")

    request_hash = compute_generate_request_hash(
        source_type=str(source_type),
        details=str(details),
        link=link,
        filename=upload.filename if has_file else "",
        file_content=content,
    )
    try:
        outcome = await chat_service.claim_generate(
            request_id=request_id,
            request_hash=request_hash,
            principal=identity,
            source=source,
            details=str(details),
        )
    except RequestIdConflict:
        return _api_error(409, "request-id-conflict")
    except RequestInProgress:
        return _api_error(409, "request-in-progress")
    except Exception:
        logger.exception("Could not claim generate request %s", request_id)
        return _api_error(500, "diagram-generation")
    if isinstance(outcome, ClaimedGenerateTurn):
        register_background_task(
            request.app,
            run_claimed_generate(
                outcome,
                chat_service._db_sessionmaker,
                chat_service._redis,
                chat_service._settings,
            ),
            f"generate:{outcome.session_id}:{request_id}",
        )
        return JSONResponse(
            status_code=202,
            content={"status": "processing", "sessionId": outcome.session_id, "requestId": request_id},
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )
    if outcome["ok"]:
        return JSONResponse(status_code=200, content=outcome["result"], headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
    code = outcome["error"]["code"]
    status = 404 if code == "session-not-found" else 409 if code in {"request-in-progress", "version-conflict"} else 500
    return JSONResponse(status_code=status, content=outcome, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/api/generate/{session_id}/turns/{request_id}")
async def poll_generate_turn(
    session_id: str,
    request_id: str,
    identity: CurrentIdentity,
    chat_service: ChatServiceDep,
) -> JSONResponse:
    from app.services.chat.service import SessionNotFound

    try:
        outcome = await chat_service.poll_turn(session_id, request_id, identity)
    except SessionNotFound:
        return _api_error(404, "diagram-generation")
    if outcome is None:
        return _api_error(404, "diagram-generation")
    content = outcome["result"] if outcome.get("ok") else outcome
    return JSONResponse(status_code=200, content=content, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
