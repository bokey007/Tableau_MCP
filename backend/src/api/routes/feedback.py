# =============================================================================
# Feedback Routes
# =============================================================================
"""Feedback endpoints for like/dislike tracking."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import get_logger
from src.db import get_db
from src.db.models import FeedbackType, ActivityType
from src.services.activity_service import ActivityService
from src.services.query_service import QueryService
from src.services.user_service import UserService

router = APIRouter()
logger = get_logger(__name__)


class FeedbackRequest(BaseModel):
    """Feedback submission request."""
    query_id: UUID
    feedback_type: FeedbackType
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=1000)
    accuracy_rating: Optional[int] = Field(default=None, ge=1, le=5)
    usefulness_rating: Optional[int] = Field(default=None, ge=1, le=5)
    completeness_rating: Optional[int] = Field(default=None, ge=1, le=5)
    username: str = "default_user"


class FeedbackResponse(BaseModel):
    """Feedback response."""
    id: str
    query_id: str
    feedback_type: str
    rating: Optional[int]
    created_at: str


@router.post("", response_model=FeedbackResponse)
async def submit_feedback(
    feedback_data: FeedbackRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Submit feedback (like/dislike) for a query response.
    
    Users can provide:
    - Like/Dislike/Neutral
    - Optional 1-5 rating
    - Optional comment
    - Optional detailed ratings (accuracy, usefulness, completeness)
    """
    # Get user
    user_service = UserService(db)
    user = await user_service.get_or_create_user(feedback_data.username)
    
    # Verify query exists
    query_service = QueryService(db)
    query = await query_service.get_query(feedback_data.query_id)
    
    if not query:
        raise HTTPException(status_code=404, detail="Query not found")
    
    # Add feedback
    feedback = await query_service.add_feedback(
        query_id=feedback_data.query_id,
        user_id=user.id,
        feedback_type=feedback_data.feedback_type,
        rating=feedback_data.rating,
        comment=feedback_data.comment,
        accuracy_rating=feedback_data.accuracy_rating,
        usefulness_rating=feedback_data.usefulness_rating,
        completeness_rating=feedback_data.completeness_rating,
    )
    
    # Log activity
    activity_service = ActivityService(db)
    await activity_service.log_activity(
        activity_type=ActivityType.FEEDBACK,
        user_id=user.id,
        description=f"Feedback: {feedback_data.feedback_type.value} for query",
        resource_type="query",
        resource_id=str(feedback_data.query_id),
        endpoint="/api/v1/feedback",
        method="POST",
        ip_address=request.client.host if request.client else None,
        metadata={
            "feedback_type": feedback_data.feedback_type.value,
            "rating": feedback_data.rating,
            "has_comment": feedback_data.comment is not None,
        },
    )
    
    await db.commit()
    
    logger.info(
        "Feedback submitted",
        query_id=str(feedback_data.query_id),
        type=feedback_data.feedback_type.value,
    )
    
    return FeedbackResponse(
        id=str(feedback.id),
        query_id=str(feedback.query_id),
        feedback_type=feedback.feedback_type.value,
        rating=feedback.rating,
        created_at=feedback.created_at.isoformat(),
    )


@router.get("/stats")
async def get_feedback_stats(
    username: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Get feedback statistics."""
    user_id = None
    
    if username:
        user_service = UserService(db)
        user = await user_service.get_user_by_username(username)
        if user:
            user_id = user.id
    
    query_service = QueryService(db)
    stats = await query_service.get_feedback_stats(user_id=user_id)
    
    return stats


@router.get("/{query_id}")
async def get_query_feedback(
    query_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get feedback for a specific query."""
    query_service = QueryService(db)
    query = await query_service.get_query(query_id)
    
    if not query:
        raise HTTPException(status_code=404, detail="Query not found")
    
    if not query.feedback:
        return {"feedback": None}
    
    return {
        "feedback": {
            "id": str(query.feedback.id),
            "type": query.feedback.feedback_type.value,
            "rating": query.feedback.rating,
            "comment": query.feedback.comment,
            "accuracy_rating": query.feedback.accuracy_rating,
            "usefulness_rating": query.feedback.usefulness_rating,
            "completeness_rating": query.feedback.completeness_rating,
            "created_at": query.feedback.created_at.isoformat(),
        }
    }
