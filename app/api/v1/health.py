"""Health check endpoints."""
from datetime import datetime

from fastapi import APIRouter

from app.core.config import get_settings
from app.models.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    settings = get_settings()
    return HealthResponse(
        status="healthy",
        version=settings.app_version,
        timestamp=datetime.utcnow(),
        environment=settings.environment,
    )


@router.get("/ready", response_model=HealthResponse)
async def readiness_check() -> HealthResponse:
    """Readiness check endpoint."""
    settings = get_settings()
    return HealthResponse(
        status="ready",
        version=settings.app_version,
        timestamp=datetime.utcnow(),
        environment=settings.environment,
    )
