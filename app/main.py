"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.routes import router
from app.config import settings

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Local audio transcription service.",
)

app.include_router(router)
