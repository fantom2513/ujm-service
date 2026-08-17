from fastapi import APIRouter, Response

router = APIRouter()


@router.get("/api/health")
async def health(response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return {"ok": True, "service": "copilot-mermaid-skeleton"}
