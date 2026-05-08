"""
Health Check Endpoints
GET /api/v1/health - API health status
GET /api/v1/health/ready - Readiness probe
"""
from fastapi import APIRouter
import structlog

router = APIRouter(prefix="/api/v1", tags=["health"])
logger = structlog.get_logger(__name__)


@router.get(
    "/health",
    summary="Health check"
)
async def health_check() -> dict:
    """API health status"""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "timestamp": __import__('datetime').datetime.utcnow().isoformat()
    }


@router.get(
    "/health/ready",
    summary="Readiness probe"
)
async def readiness_check() -> dict:
    """Readiness probe for Kubernetes"""
    # In production, check database, cache, message queue, etc.
    return {
        "ready": True,
        "checks": {
            "database": "ok",
            "cache": "ok",
            "message_queue": "ok"
        }
    }


@router.get(
    "/health/live",
    summary="Liveness probe"
)
async def liveness_check() -> dict:
    """Liveness probe for Kubernetes"""
    return {"alive": True}
