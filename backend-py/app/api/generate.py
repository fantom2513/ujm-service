from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.deps import ChatServiceDep, CurrentIdentity
from app.api.schemas import ApiError, DiagramResult, FileMeta, SourceContext
from app.config import get_settings
from app.domain.generate_guard import required_source_error
from app.domain.mermaid import validate_mermaid
from app.services.files.extract import (
    get_extension,
    has_pdf_text_layer,
    is_text_source_format,
    normalize_text_file,
)
from app.services.links.classify import classify_work_link, normalize_link
from app.services.openai.generate import generate_diagram
from app.services.recordings.normalize import is_recording_format, normalize_recording

logger = logging.getLogger(__name__)

router = APIRouter()

_USER_MESSAGES = {
    "file-required": "Необходимо прикрепить файл",
    "file-format": "Некорректный формат файла",
    "file-size-text": "Файл превышает 10 МБ",
    "file-size-recording": "Файл превышает 100 МБ",
    "link-required": "Поле обязательно для заполнения",
    "invalid-link": "Неверный формат ссылки",
    "diagram-generation": "Схема не сформирована. Перезагрузите страницу или повторите попытку позже",
    "attachment-error": "Ошибка загрузки файла",
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
    source_type = form.get("sourceType")
    details = form.get("details", "") or ""
    link = (form.get("link", "") or "").strip()
    # Frontend field name is "file" (see frontend/src/main.ts:871
    # `form.set("file", selectedFile)`), not "attachment" — "attachment" is
    # only used as the `field` value inside error payloads below.
    upload = form.get("file")
    has_file = upload is not None and bool(getattr(upload, "filename", None))

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
        if not has_pdf_text_layer(upload.filename, content):
            return _api_error(400, "attachment-error", field="attachment")
        source = await normalize_text_file(upload.filename, content, len(content))
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
        source = await normalize_link(link)
    else:
        return _api_error(400, "diagram-generation")

    try:
        mermaid_code = await generate_diagram(source.text, details)
    except Exception:
        # Parity with TS: backend/src/server/index.ts:143
        # (`console.error("generateDiagram failed:", err)`).
        logger.exception("generateDiagram failed")
        return _api_error(500, "diagram-generation")

    validation = validate_mermaid(mermaid_code)
    if not validation.ok:
        # Parity with TS: backend/src/server/index.ts:148 — logs the
        # validation reason and the bad output's first line, not the
        # user-facing generic message, since the raw Mermaid may contain
        # unsafe/oversized content unsuitable for a client-visible error.
        first_line = mermaid_code.strip().split("\n", 1)[0]
        logger.error(
            "generateDiagram validation failed: %s | first line: %s",
            validation.reason,
            first_line,
        )
        return _api_error(500, "diagram-generation")

    try:
        session_id = await chat_service.create_session_with_version(
            source_text=source.text,
            additional_details=details,
            principal=identity,
            mermaid_code=mermaid_code,
        )
    except Exception:
        # The service owns the transaction boundary, so an exception here
        # has already rolled back session + V1 + head as one operation.
        logger.exception("Failed to persist generated diagram")
        return _api_error(500, "diagram-generation")

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
        details=details,
        chat=[],
        warnings=["Используется временная заглушка backend."] if source.stub else [],
    )
    return JSONResponse(
        status_code=200,
        content={"ok": True, "result": result.model_dump(by_alias=True, exclude_none=True)},
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
