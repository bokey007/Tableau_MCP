# =============================================================================
# API Routes
# =============================================================================
"""Route definitions."""

from fastapi import APIRouter

from src.api.routes.health import router as health_router
from src.api.routes.query import router as query_router
from src.api.routes.datasources import router as datasources_router
from src.api.routes.feedback import router as feedback_router
from src.api.routes.analytics import router as analytics_router
from src.api.routes.agent import router as agent_router

router = APIRouter()

router.include_router(health_router, tags=["Health"])
router.include_router(datasources_router, prefix="/datasources", tags=["Datasources"])
router.include_router(query_router, prefix="/query", tags=["Query"])
router.include_router(feedback_router, prefix="/feedback", tags=["Feedback"])
router.include_router(analytics_router, prefix="/analytics", tags=["Analytics"])
router.include_router(agent_router, prefix="/agent", tags=["Agent"])

__all__ = ["router"]

