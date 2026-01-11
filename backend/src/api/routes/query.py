# =============================================================================
# Query Routes
# =============================================================================
"""Query endpoints for natural language queries."""

import time
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Query as QueryParam
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent import TableauAgent
from src.core.config import settings
from src.core.logging import get_logger
from src.db import get_db
from src.db.models import QueryStatus, ActivityType
from src.mcp.client import MCPClient
from src.services.activity_service import ActivityService
from src.services.query_service import QueryService
from src.services.user_service import UserService

router = APIRouter()
logger = get_logger(__name__)


class QueryRequest(BaseModel):
    """Query request schema."""
    question: str = Field(min_length=3, max_length=2000)
    datasource_id: Optional[str] = None
    thread_id: Optional[str] = None  # LangGraph conversation thread
    username: str = Field(default="default_user")


class QueryResponse(BaseModel):
    """Query response schema."""
    success: bool
    query_id: Optional[str] = None
    question: str
    thread_id: Optional[str] = None  # LangGraph thread for continuation
    message_count: Optional[int] = None  # Messages in conversation
    datasource: Optional[Dict[str, str]] = None
    analysis: Optional[str] = None
    query: Optional[Dict[str, Any]] = None
    results: Optional[Dict[str, Any]] = None
    analyzed_data: Optional[Dict[str, Any]] = None  # What the LLM actually analyzed
    visualization: Optional[Dict[str, Any]] = None
    execution_time_ms: Optional[float] = None
    error: Optional[str] = None
    error_type: Optional[str] = None


@router.post("", response_model=QueryResponse)
async def query_natural_language(
    request_data: QueryRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Query Tableau data using natural language.
    
    This endpoint:
    1. Validates the question
    2. Creates a query record for tracking
    3. Uses the AI agent to analyze and execute
    4. Returns results with analysis
    
    The query is tracked in the database for history and analytics.
    """
    start_time = time.time()
    
    # Validate OpenAI is configured
    if not settings.openai_configured:
        return QueryResponse(
            success=False,
            question=request_data.question,
            error="AI service is not configured. Please contact administrator.",
            error_type="configuration_error",
        )
    
    # Get or create user
    user_service = UserService(db)
    user = await user_service.get_or_create_user(request_data.username)
    
    # Create query record
    query_service = QueryService(db)
    query_record = await query_service.create_query(
        user_id=user.id,
        question=request_data.question,
        datasource_id=request_data.datasource_id,
    )
    
    # Log activity
    activity_service = ActivityService(db)
    await activity_service.log_activity(
        activity_type=ActivityType.QUERY,
        user_id=user.id,
        description=f"Query: {request_data.question[:100]}",
        resource_type="query",
        resource_id=str(query_record.id),
        endpoint="/api/v1/query",
        method="POST",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    
    try:
        async with MCPClient() as mcp_client:
            agent = TableauAgent(mcp_client=mcp_client)
            result = await agent.query(
                question=request_data.question,
                datasource_id=request_data.datasource_id,
                thread_id=request_data.thread_id,  # LangGraph native
            )
        
        execution_time_ms = (time.time() - start_time) * 1000
        
        # Extract datasource info
        datasource_info = result.get("datasource")
        datasource_name = datasource_info.get("name") if datasource_info else None
        
        # Update query record with results
        await query_service.update_query_result(
            query_id=query_record.id,
            status=QueryStatus.SUCCESS if result.get("success") else QueryStatus.FAILED,
            generated_query=result.get("query"),
            response_text=result.get("analysis"),
            response_data=result.get("results"),
            analyzed_data=result.get("analyzed_data"),  # What LLM analyzed
            visualization_config=result.get("visualization"),
            execution_time_ms=execution_time_ms,
            row_count=result.get("results", {}).get("row_count") if result.get("results") else None,
            error_message=result.get("error"),
        )
        
        # Update datasource name if discovered
        if datasource_name and not query_record.datasource_name:
            query_record.datasource_name = datasource_name
            query_record.datasource_id = datasource_info.get("id")
        
        await db.commit()
        
        return QueryResponse(
            success=result.get("success", False),
            query_id=str(query_record.id),
            question=request_data.question,
            thread_id=result.get("thread_id"),  # LangGraph thread
            message_count=result.get("message_count"),  # Conversation length
            datasource=datasource_info,
            analysis=result.get("analysis"),
            query=result.get("query"),
            results=result.get("results"),
            analyzed_data=result.get("analyzed_data"),  # What LLM analyzed
            visualization=result.get("visualization"),
            execution_time_ms=execution_time_ms,
            error=result.get("error"),
            error_type="agent_error" if result.get("error") else None,
        )
        
    except Exception as e:
        logger.exception("Query failed", error=str(e))
        execution_time_ms = (time.time() - start_time) * 1000
        
        # Determine error type
        error_msg = str(e)
        if "connect" in error_msg.lower() or "timeout" in error_msg.lower():
            error_type = "connection_error"
            user_message = "Unable to connect to the data service. Please try again later."
        elif "authentication" in error_msg.lower() or "unauthorized" in error_msg.lower():
            error_type = "auth_error"
            user_message = "Authentication failed. Please check your credentials."
        elif "openai" in error_msg.lower() or "rate" in error_msg.lower():
            error_type = "ai_error"
            user_message = "AI service temporarily unavailable. Please try again in a moment."
        else:
            error_type = "internal_error"
            user_message = f"An error occurred: {error_msg}"
        
        await query_service.update_query_result(
            query_id=query_record.id,
            status=QueryStatus.FAILED,
            error_message=error_msg,
            execution_time_ms=execution_time_ms,
        )
        
        await db.commit()
        
        return QueryResponse(
            success=False,
            query_id=str(query_record.id),
            question=request_data.question,
            error=user_message,
            error_type=error_type,
            execution_time_ms=execution_time_ms,
        )


@router.get("/history")
async def get_query_history(
    username: str = "default_user",
    limit: int = QueryParam(default=50, ge=1, le=200),
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Get query history for a user.
    
    Args:
        username: User's username
        limit: Maximum number of queries to return
        status: Filter by status (pending, processing, success, failed)
    """
    user_service = UserService(db)
    user = await user_service.get_user_by_username(username)
    
    if not user:
        return {"queries": [], "count": 0, "message": "No query history found"}
    
    # Parse status filter
    status_filter = None
    if status:
        try:
            status_filter = QueryStatus(status)
        except ValueError:
            pass
    
    query_service = QueryService(db)
    queries = await query_service.get_user_queries(
        user.id, 
        status=status_filter,
        limit=limit
    )
    
    return {
        "queries": [
            {
                "id": str(q.id),
                "question": q.question,
                "status": q.status.value,
                "datasource_id": q.datasource_id,
                "datasource_name": q.datasource_name,
                "created_at": q.created_at.isoformat(),
                "execution_time_ms": q.execution_time_ms,
                "row_count": q.row_count,
                "has_feedback": q.feedback is not None,
                "feedback_type": q.feedback.feedback_type.value if q.feedback else None,
            }
            for q in queries
        ],
        "count": len(queries),
        "username": username,
    }


# =============================================================================
# LangGraph Thread Endpoints
# =============================================================================

@router.get("/thread/{thread_id}")
async def get_thread_history(
    thread_id: str,
):
    """Get conversation state for a LangGraph thread."""
    from src.agent import TableauAgent
    
    # Use agent to get state (handles graph access)
    agent = TableauAgent()
    
    try:
        state = await agent.get_state(thread_id)
        
        if not state:
            return {
                "thread_id": thread_id,
                "messages": [],
                "exists": False,
            }
        
        # Extract messages from state
        messages = []
        for msg in state.get("messages", []):
            role = "unknown"
            if msg.__class__.__name__ == "HumanMessage":
                role = "user"
            elif msg.__class__.__name__ == "AIMessage":
                role = "assistant"
            elif msg.__class__.__name__ == "SystemMessage":
                role = "system"
            elif msg.__class__.__name__ == "ToolMessage":
                role = "tool"
                
            messages.append({
                "role": role,
                "content": msg.content,
                "type": msg.__class__.__name__
            })
        
        return {
            "thread_id": thread_id,
            "messages": messages,
            "message_count": len(messages),
            "exists": True,
        }
    except Exception as e:
        return {
            "thread_id": thread_id,
            "messages": [],
            "exists": False,
            "error": str(e),
        }


@router.get("/{query_id}")
async def get_query(
    query_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific query by ID with full details."""
    query_service = QueryService(db)
    query = await query_service.get_query(query_id)
    
    if not query:
        raise HTTPException(status_code=404, detail="Query not found")
    
    return {
        "id": str(query.id),
        "question": query.question,
        "status": query.status.value,
        "datasource_id": query.datasource_id,
        "datasource_name": query.datasource_name,
        "analysis": query.response_text,
        "query": query.generated_query,
        "results": query.response_data,
        "analyzed_data": query.analyzed_data,  # What LLM analyzed (for debugging)
        "visualization": query.visualization_config,
        "execution_time_ms": query.execution_time_ms,
        "row_count": query.row_count,
        "error": query.error_message,
        "created_at": query.created_at.isoformat(),
        "completed_at": query.completed_at.isoformat() if query.completed_at else None,
        "feedback": {
            "type": query.feedback.feedback_type.value,
            "rating": query.feedback.rating,
            "comment": query.feedback.comment,
            "created_at": query.feedback.created_at.isoformat(),
        } if query.feedback else None,
    }


@router.delete("/{query_id}")
async def delete_query(
    query_id: UUID,
    username: str = "default_user",
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a query from history.
    
    Users can only delete their own queries.
    """
    user_service = UserService(db)
    user = await user_service.get_user_by_username(username)
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    query_service = QueryService(db)
    query = await query_service.get_query(query_id)
    
    if not query:
        raise HTTPException(status_code=404, detail="Query not found")
    
    if query.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this query")
    
    await db.delete(query)
    await db.commit()
    
    return {"deleted": True, "query_id": str(query_id)}
