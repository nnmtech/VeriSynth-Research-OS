"""API v1 routes."""
from fastapi import APIRouter

from app.api.v1 import export, health, llm, maker, memory, transform, verify

api_router = APIRouter()

# Include all routers
api_router.include_router(health.router, tags=["health"])
api_router.include_router(memory.router, prefix="/memory", tags=["memory"])
api_router.include_router(verify.router, prefix="/verify", tags=["verify"])
api_router.include_router(transform.router, prefix="/transform", tags=["transform"])
api_router.include_router(export.router, prefix="/export", tags=["export"])
api_router.include_router(llm.router, prefix="/llm", tags=["llm"])
api_router.include_router(maker.router, prefix="/maker", tags=["maker"])
