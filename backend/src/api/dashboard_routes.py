# =============================================================================
# Dashboard Agent API Routes
# =============================================================================
"""
API endpoints for the Tableau Extension Dashboard Agent.
This is the entry point for all requests from the Tableau Extension.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

from src.agent.dashboard_agent import get_dashboard_agent, DashboardContext
from src.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/dashboard", tags=["Dashboard Agent"])


# =============================================================================
# Request/Response Models
# =============================================================================

class DashboardFilter(BaseModel):
    """A filter applied in the dashboard."""
    field: str
    value: Optional[str] = None
    type: Optional[str] = None
    worksheet: Optional[str] = None


class DashboardWorksheet(BaseModel):
    """A worksheet in the dashboard."""
    name: str


class DashboardDatasource(BaseModel):
    """A datasource in the dashboard."""
    name: str
    id: Optional[str] = None


class DashboardQueryRequest(BaseModel):
    """Request from Tableau Extension."""
    question: str = Field(..., description="User's natural language question")
    username: str = Field(default="extension_user", description="User identifier")
    thread_id: Optional[str] = Field(default=None, description="Thread ID for conversation memory (multi-turn)")
    
    # Dashboard context from Tableau
    dashboard_name: Optional[str] = Field(default=None, description="Name of the dashboard")
    worksheets: Optional[List[DashboardWorksheet]] = Field(default=None, description="Worksheets in dashboard")
    filters: Optional[List[DashboardFilter]] = Field(default=None, description="Applied filters")
    datasources: Optional[List[DashboardDatasource]] = Field(default=None, description="Available datasources")
    parameters: Optional[List[Dict[str, Any]]] = Field(default=None, description="Dashboard parameters")
    selected_marks: Optional[List[Dict[str, Any]]] = Field(default=None, description="Selected marks/data points")


class DashboardQueryResponse(BaseModel):
    """Response to Tableau Extension."""
    success: bool
    intent: Optional[str] = None
    analysis: Optional[str] = None
    results: Optional[Dict[str, Any]] = None
    visualization: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    processing_time_ms: Optional[float] = None
    needs_clarification: Optional[bool] = None
    dashboard_state: Optional[Dict[str, Any]] = None
    thread_id: Optional[str] = None  # For conversation continuity


# =============================================================================
# API Endpoints
# =============================================================================

@router.post("/query", response_model=DashboardQueryResponse)
async def dashboard_query(request: DashboardQueryRequest) -> DashboardQueryResponse:
    """
    Process a question from the Tableau Extension.
    
    This is the main entry point for all extension requests. The Dashboard Agent
    will classify the intent and either:
    - Answer directly (chat, context, clarification)
    - Delegate to the Data Agent (complex data queries)
    """
    logger.info(
        "Dashboard query received",
        question=request.question[:50],
        dashboard=request.dashboard_name
    )
    
    try:
        # Build dashboard context
        context: DashboardContext = {}
        
        if request.dashboard_name:
            context["dashboard_name"] = request.dashboard_name
        
        if request.worksheets:
            context["worksheets"] = [w.model_dump() for w in request.worksheets]
        
        if request.filters:
            context["filters"] = [f.model_dump() for f in request.filters]
        
        if request.datasources:
            context["datasources"] = [d.model_dump() for d in request.datasources]
        
        if request.parameters:
            context["parameters"] = request.parameters
        
        if request.selected_marks:
            context["selected_marks"] = request.selected_marks
        
        # Get Dashboard Agent and process
        agent = get_dashboard_agent()
        result = await agent.process(
            question=request.question,
            dashboard_context=context,
            username=request.username,
            thread_id=request.thread_id  # Pass thread_id for conversation memory
        )
        
        return DashboardQueryResponse(**result)
        
    except Exception as e:
        logger.error("Dashboard query failed", error=str(e))
        return DashboardQueryResponse(
            success=False,
            error=str(e),
            analysis=f"An error occurred: {str(e)}"
        )


@router.get("/health")
async def health_check():
    """Health check endpoint for the Dashboard Agent."""
    return {
        "status": "healthy",
        "service": "dashboard-agent",
        "version": "1.0.0"
    }


@router.get("/capabilities")
async def get_capabilities():
    """Return Dashboard Agent capabilities for the extension."""
    return {
        "intents": [
            {
                "name": "chat",
                "description": "Handle greetings and casual conversation",
                "examples": ["Hello", "Thanks!", "How are you?"]
            },
            {
                "name": "capability",
                "description": "Explain what the assistant can do",
                "examples": ["What can you do?", "Help me", "How do I use this?"]
            },
            {
                "name": "dashboard_context",
                "description": "Answer questions about current dashboard state",
                "examples": ["What filter is applied?", "What's selected?"]
            },
            {
                "name": "clarification_needed",
                "description": "Ask for clarification on vague questions",
                "examples": ["sales", "show data"]
            },
            {
                "name": "data_query",
                "description": "Execute data analysis queries",
                "examples": ["Top 5 customers", "Sales trend", "Compare regions"]
            }
        ],
        "features": [
            "Natural language queries",
            "Dashboard context awareness",
            "Filter-aware responses",
            "Data visualization recommendations"
        ]
    }
