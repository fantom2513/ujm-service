from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.deps import DbSessionDep, RedisDep, SettingsDep
from app.api.schemas import ApiError

router = APIRouter()


@router.post("/api/chat")
async def chat(db: DbSessionDep, redis: RedisDep, settings: SettingsDep) -> JSONResponse:
    # Proves the DI wiring (db/redis/settings) works end to end. ChatService
    # is intentionally not constructed here — orchestration lands in Tasks 05-06.
    error = ApiError(code="not-implemented", message="Chat is not implemented yet")
    return JSONResponse(
        status_code=501,
        content={"ok": False, "error": error.model_dump(by_alias=True, exclude_none=True)},
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
