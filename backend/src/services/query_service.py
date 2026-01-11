# =============================================================================
# Query Service
# =============================================================================
"""Service for managing queries and feedback."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select, and_, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.logging import get_logger
from src.db.models import Query, QueryFeedback, QueryStatus, FeedbackType

logger = get_logger(__name__)


class QueryService:
    """Service for query management."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_query(
        self,
        user_id: UUID,
        question: str,
        session_id: Optional[UUID] = None,
        datasource_id: Optional[str] = None,
        datasource_name: Optional[str] = None,
    ) -> Query:
        """
        Create a new query record.
        
        Args:
            user_id: User ID
            question: User's question
            session_id: Session ID
            datasource_id: Target datasource
            datasource_name: Datasource name
            
        Returns:
            Created query
        """
        query = Query(
            user_id=user_id,
            session_id=session_id,
            question=question,
            datasource_id=datasource_id,
            datasource_name=datasource_name,
            status=QueryStatus.PENDING,
        )
        
        self.db.add(query)
        await self.db.flush()
        
        logger.info("Query created", query_id=str(query.id))
        return query
    
    async def update_query_result(
        self,
        query_id: UUID,
        status: QueryStatus,
        generated_query: Optional[Dict[str, Any]] = None,
        response_text: Optional[str] = None,
        response_data: Optional[Dict[str, Any]] = None,
        analyzed_data: Optional[Dict[str, Any]] = None,
        visualization_config: Optional[Dict[str, Any]] = None,
        execution_time_ms: Optional[float] = None,
        row_count: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> Optional[Query]:
        """
        Update query with execution results.
        
        Args:
            query_id: Query ID
            status: New status
            generated_query: VizQL query used
            response_text: AI-generated response
            response_data: Query result data (raw/limited)
            analyzed_data: What LLM actually analyzed (for debugging)
            visualization_config: Chart configuration
            execution_time_ms: Execution time
            row_count: Number of rows
            error_message: Error if failed
            
        Returns:
            Updated query
        """
        result = await self.db.execute(select(Query).where(Query.id == query_id))
        query = result.scalar_one_or_none()
        
        if not query:
            return None
        
        query.status = status
        query.generated_query = generated_query
        query.response_text = response_text
        query.response_data = response_data
        query.analyzed_data = analyzed_data
        query.visualization_config = visualization_config
        query.execution_time_ms = execution_time_ms
        query.row_count = row_count
        query.error_message = error_message
        query.completed_at = datetime.now(timezone.utc)
        
        await self.db.flush()
        
        logger.info(
            "Query updated",
            query_id=str(query_id),
            status=status.value,
        )
        
        return query
    
    async def get_query(self, query_id: UUID) -> Optional[Query]:
        """Get query by ID with feedback."""
        result = await self.db.execute(
            select(Query)
            .options(selectinload(Query.feedback))
            .where(Query.id == query_id)
        )
        return result.scalar_one_or_none()
    
    async def get_user_queries(
        self,
        user_id: UUID,
        status: Optional[QueryStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Query]:
        """Get queries for a user."""
        conditions = [Query.user_id == user_id]
        
        if status:
            conditions.append(Query.status == status)
        
        query = (
            select(Query)
            .options(selectinload(Query.feedback))
            .where(and_(*conditions))
            .order_by(desc(Query.created_at))
            .limit(limit)
            .offset(offset)
        )
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def add_feedback(
        self,
        query_id: UUID,
        user_id: UUID,
        feedback_type: FeedbackType,
        rating: Optional[int] = None,
        comment: Optional[str] = None,
        accuracy_rating: Optional[int] = None,
        usefulness_rating: Optional[int] = None,
        completeness_rating: Optional[int] = None,
    ) -> QueryFeedback:
        """
        Add or update feedback for a query.
        
        Args:
            query_id: Query ID
            user_id: User ID
            feedback_type: Like/Dislike/Neutral
            rating: Overall rating (1-5)
            comment: User comment
            accuracy_rating: Accuracy rating (1-5)
            usefulness_rating: Usefulness rating (1-5)
            completeness_rating: Completeness rating (1-5)
            
        Returns:
            Created/updated feedback
        """
        # Check if feedback exists
        result = await self.db.execute(
            select(QueryFeedback).where(QueryFeedback.query_id == query_id)
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            # Update existing
            existing.feedback_type = feedback_type
            existing.rating = rating
            existing.comment = comment
            existing.accuracy_rating = accuracy_rating
            existing.usefulness_rating = usefulness_rating
            existing.completeness_rating = completeness_rating
            existing.updated_at = datetime.now(timezone.utc)
            feedback = existing
        else:
            # Create new
            feedback = QueryFeedback(
                query_id=query_id,
                user_id=user_id,
                feedback_type=feedback_type,
                rating=rating,
                comment=comment,
                accuracy_rating=accuracy_rating,
                usefulness_rating=usefulness_rating,
                completeness_rating=completeness_rating,
            )
            self.db.add(feedback)
        
        await self.db.flush()
        
        logger.info(
            "Feedback recorded",
            query_id=str(query_id),
            feedback_type=feedback_type.value,
        )
        
        return feedback
    
    async def get_feedback_stats(
        self,
        user_id: Optional[UUID] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Get feedback statistics.
        
        Args:
            user_id: Filter by user
            start_date: Filter by start date
            end_date: Filter by end date
            
        Returns:
            Feedback statistics
        """
        conditions = []
        
        if user_id:
            conditions.append(QueryFeedback.user_id == user_id)
        if start_date:
            conditions.append(QueryFeedback.created_at >= start_date)
        if end_date:
            conditions.append(QueryFeedback.created_at <= end_date)
        
        # Count by type
        type_query = (
            select(QueryFeedback.feedback_type, func.count(QueryFeedback.id))
            .group_by(QueryFeedback.feedback_type)
        )
        if conditions:
            type_query = type_query.where(and_(*conditions))
        
        type_result = await self.db.execute(type_query)
        type_counts = {row[0].value: row[1] for row in type_result.all()}
        
        # Average ratings
        avg_query = select(
            func.avg(QueryFeedback.rating),
            func.avg(QueryFeedback.accuracy_rating),
            func.avg(QueryFeedback.usefulness_rating),
            func.avg(QueryFeedback.completeness_rating),
        )
        if conditions:
            avg_query = avg_query.where(and_(*conditions))
        
        avg_result = await self.db.execute(avg_query)
        avg_row = avg_result.one()
        
        return {
            "total": sum(type_counts.values()),
            "likes": type_counts.get("like", 0),
            "dislikes": type_counts.get("dislike", 0),
            "neutral": type_counts.get("neutral", 0),
            "like_ratio": (
                type_counts.get("like", 0) / sum(type_counts.values())
                if type_counts else 0
            ),
            "avg_rating": float(avg_row[0]) if avg_row[0] else None,
            "avg_accuracy": float(avg_row[1]) if avg_row[1] else None,
            "avg_usefulness": float(avg_row[2]) if avg_row[2] else None,
            "avg_completeness": float(avg_row[3]) if avg_row[3] else None,
        }
