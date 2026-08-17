from fastapi import APIRouter, Response

from app.config import get_settings

router = APIRouter()


@router.get("/api/config")
async def get_config(response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    settings = get_settings()
    return {"ok": True, "productHomeUrl": settings.product_home_url}
