from fastapi import FastAPI

from app.api.config_route import router as config_router
from app.api.health import router as health_router

app = FastAPI(title="ujm-service backend-py")

app.include_router(health_router)
app.include_router(config_router)
