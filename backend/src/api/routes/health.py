# =============================================================================
# Health Routes
# =============================================================================
"""Health check endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.logging import get_logger
from src.db import get_db
from src.mcp.client import MCPClient

router = APIRouter()
logger = get_logger(__name__)


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """
    Health check endpoint.
    
    Checks:
    - Database connectivity
    - MCP server connectivity
    - OpenAI configuration
    """
    status = "healthy"
    checks = {}
    
    # Check database
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception as e:
        checks["database"] = False
        status = "unhealthy"
        logger.error("Database health check failed", error=str(e))
    
    # Check MCP
    try:
        async with MCPClient() as client:
            await client.list_datasources(limit=1)
            checks["mcp"] = True
    except Exception as e:
        checks["mcp"] = False
        if status == "healthy":
            status = "degraded"
        logger.warning("MCP health check failed", error=str(e))
    
    # Check OpenAI configuration
    checks["openai_configured"] = settings.openai_configured
    if not checks["openai_configured"] and status == "healthy":
        status = "degraded"
    
    return {
        "status": status,
        "version": "1.0.0",
        "environment": settings.app_env,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "mcp_connected": checks.get("mcp", False),
        "database_connected": checks.get("database", False),
    }


@router.get("/ready")
async def readiness(db: AsyncSession = Depends(get_db)):
    """
    Readiness probe for Kubernetes.
    
    Returns ready only if database is connected.
    """
    try:
        await db.execute(text("SELECT 1"))
        return {"ready": True}
    except Exception as e:
        logger.error("Readiness check failed", error=str(e))
        return {"ready": False, "error": str(e)}


@router.get("/live")
async def liveness():
    """
    Liveness probe for Kubernetes.
    
    Always returns alive (process is running).
    """
    return {"alive": True}
