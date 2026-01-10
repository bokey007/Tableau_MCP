# =============================================================================
# Main Application
# =============================================================================
"""FastAPI application for Tableau MCP AI Agent."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.routes import router
from src.core.config import settings
from src.core.exceptions import TableauMCPError
from src.core.logging import get_logger, setup_logging
from src.db.session import init_db, close_db

# Setup logging
setup_logging(
    log_level=settings.log_level,
    json_logs=settings.is_production,
)

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Application lifespan manager."""
    # Startup
    logger.info("Starting Tableau MCP Backend", env=settings.app_env)
    
    # Initialize database
    try:
        await init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.error("Database initialization failed", error=str(e))
    
    yield
    
    # Shutdown
    logger.info("Shutting down")
    await close_db()


def create_app() -> FastAPI:
    """Create FastAPI application."""
    app = FastAPI(
        title="Tableau MCP AI Agent API",
        description="""
        AI-powered API for querying and analyzing Tableau data.
        
        ## Features
        - Natural Language Queries
        - Activity & Usage Tracking
        - Like/Dislike Feedback
        - Analytics Dashboard
        """,
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    
    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Routes
    app.include_router(router, prefix=settings.api_prefix)
    
    # Exception handlers
    @app.exception_handler(TableauMCPError)
    async def mcp_error_handler(request: Request, exc: TableauMCPError):
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())
    
    @app.exception_handler(Exception)
    async def general_error_handler(request: Request, exc: Exception):
        logger.exception("Unexpected error", error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": str(exc)}},
        )
    
    @app.get("/")
    async def root():
        return {
            "name": "Tableau MCP AI Agent",
            "version": "1.0.0",
            "docs": "/docs",
            "api_prefix": settings.api_prefix,
        }
    
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        reload=not settings.is_production,
    )
