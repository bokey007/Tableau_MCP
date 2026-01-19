# =============================================================================
# Dashboard Agent API Routes
# =============================================================================
"""
API endpoints for the Tableau Extension Dashboard Agent.
This is the entry point for all requests from the Tableau Extension.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Any, AsyncIterator, Dict, List, Optional
import asyncio
import json

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
    query_type: Optional[str] = None  # standard, comparison, anomaly, storytelling
    context_scope: Optional[str] = None  # filtered or global
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
                "name": "comparison",
                "description": "Compare time periods, regions, or categories",
                "examples": ["Compare Q1 vs Q2", "Year over year growth", "East vs West region"]
            },
            {
                "name": "anomaly",
                "description": "Detect outliers and unusual patterns",
                "examples": ["What's unusual?", "Find anomalies", "Any red flags?"]
            },
            {
                "name": "storytelling",
                "description": "Generate executive summaries and narratives",
                "examples": ["Summarize this dashboard", "Executive summary", "Tell me the story"]
            },
            {
                "name": "data_query",
                "description": "Execute standard data analysis queries",
                "examples": ["Top 5 customers", "Sales trend", "Total by region"]
            }
        ],
        "features": [
            "Natural language queries",
            "Dashboard context awareness",
            "Filter-aware responses (filtered vs global scope)",
            "Comparison analysis (Q1 vs Q2, YoY)",
            "Anomaly detection (outliers, unusual patterns)",
            "Data storytelling (executive summaries)",
            "Conversation memory (multi-turn)",
            "Query history and favorites",
            "Data visualization recommendations"
        ]
    }


# =============================================================================
# Query History & Favorites
# =============================================================================

class QueryHistoryItem(BaseModel):
    """A query history item."""
    id: str
    question: str
    intent: Optional[str] = None
    query_type: Optional[str] = None
    is_favorite: bool = False
    favorite_label: Optional[str] = None
    created_at: str
    success: bool
    analysis_preview: Optional[str] = None


class FavoriteRequest(BaseModel):
    """Request to toggle favorite status."""
    query_id: str
    is_favorite: bool
    label: Optional[str] = None


@router.get("/history")
async def get_query_history(
    username: str = "extension_user",
    limit: int = 20,
    offset: int = 0,
    search: Optional[str] = None,
    favorites_only: bool = False
):
    """
    Get query history for a user.
    
    Supports pagination, search, and filtering by favorites.
    """
    # Note: In production, this would query the database
    # For now, return a mock response showing the structure
    return {
        "items": [],
        "total": 0,
        "limit": limit,
        "offset": offset,
        "message": "Query history endpoint ready. Enable database persistence to store history."
    }


@router.post("/favorites")
async def toggle_favorite(request: FavoriteRequest):
    """Toggle favorite status for a query."""
    # Note: In production, this would update the database
    return {
        "success": True,
        "query_id": request.query_id,
        "is_favorite": request.is_favorite,
        "label": request.label,
        "message": "Favorite toggled. Enable database persistence for full functionality."
    }


@router.get("/favorites")
async def get_favorites(username: str = "extension_user", limit: int = 50):
    """Get all favorite queries for a user."""
    # Note: In production, this would query the database
    return {
        "items": [],
        "total": 0,
        "message": "Favorites endpoint ready. Enable database persistence to store favorites."
    }


# =============================================================================
# Real-time Streaming (SSE)
# =============================================================================

@router.post("/query/stream")
async def stream_query(request: DashboardQueryRequest):
    """
    Stream query processing with Server-Sent Events (SSE).
    
    Provides real-time updates as the agent processes:
    1. thinking - Intent classification in progress
    2. querying - Executing VizQL query
    3. analyzing - Analyzing results
    4. complete - Final result
    """
    
    async def event_generator() -> AsyncIterator[str]:
        """Generate SSE events for real-time updates."""
        try:
            # Build dashboard context
            context = DashboardContext(
                dashboard_name=request.dashboard_name,
                worksheets=[{"name": w.name} for w in (request.worksheets or [])],
                filters=[f.model_dump() for f in (request.filters or [])],
                datasources=[d.model_dump() for d in (request.datasources or [])],
                parameters=request.parameters,
                selected_marks=request.selected_marks,
            )
            
            # Send thinking event
            yield f"data: {json.dumps({'event': 'thinking', 'message': 'Analyzing your question...'})}\n\n"
            await asyncio.sleep(0.1)  # Small delay for UX
            
            # Get agent and process
            agent = get_dashboard_agent()  # sync function, not async
            
            # Send querying event
            yield f"data: {json.dumps({'event': 'querying', 'message': 'Processing query...'})}\n\n"
            
            # Process the query
            import time
            start_time = time.time()
            
            result = await agent.process(
                question=request.question,
                dashboard_context=context,  # Match method signature
                thread_id=request.thread_id
            )
            
            processing_time = (time.time() - start_time) * 1000
            
            # Send analyzing event if we have data
            if result.get("results"):
                yield f"data: {json.dumps({'event': 'analyzing', 'message': 'Analyzing results...'})}\n\n"
                await asyncio.sleep(0.1)
            
            # Build final response
            # Success if no error and we have analysis OR status is complete
            is_success = (not result.get("error")) and (
                result.get("status") == "complete" or 
                result.get("analysis") is not None
            )
            response = {
                "event": "complete",
                "data": {
                    "success": is_success,
                    "intent": result.get("intent"),
                    "query_type": result.get("query_type"),
                    "context_scope": result.get("context_scope"),
                    "analysis": result.get("analysis"),
                    "results": result.get("results"),
                    "visualization": result.get("visualization"),
                    "error": result.get("error"),
                    "processing_time_ms": processing_time,
                    "thread_id": result.get("thread_id"),
                }
            }
            
            yield f"data: {json.dumps(response)}\n\n"
            
        except Exception as e:
            logger.exception("Streaming query failed", error=str(e))
            error_response = {
                "event": "error",
                "data": {
                    "success": False,
                    "error": str(e)
                }
            }
            yield f"data: {json.dumps(error_response)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )
