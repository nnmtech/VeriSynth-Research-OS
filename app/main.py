"""
VeriSynth Research OS - Main Application.

Production-ready FastAPI application implementing MDAP framework.
"""
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import api_router
from app.core.config import get_settings

# Configure structured logging
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
)

logger = structlog.get_logger(__name__)


def create_application() -> FastAPI:
    """Create and configure FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API router
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.on_event("startup")
    async def startup_event() -> None:
        """Startup event handler."""
        logger.info(
            "application_startup",
            app_name=settings.app_name,
            version=settings.app_version,
            environment=settings.environment,
            is_cloud_run=settings.is_cloud_run(),
        )

    @app.on_event("shutdown")
    async def shutdown_event() -> None:
        """Shutdown event handler."""
        logger.info("application_shutdown")

    @app.exception_handler(Exception)
    async def global_exception_handler(request: any, exc: Exception) -> JSONResponse:
        """Global exception handler."""
        logger.error(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
            error=str(exc),
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "detail": str(exc) if settings.debug else "An error occurred",
            },
        )

    return app


# Create app instance
app = create_application()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8080,
        reload=settings.debug,
        log_level="info",
    )
