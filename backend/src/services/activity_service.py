# =============================================================================
# Activity Service
# =============================================================================
"""Service for managing activity logs."""

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select, and_, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.logging import get_logger
from src.db.models import ActivityLog, ActivityType

logger = get_logger(__name__)


class ActivityService:
    """Service for activity logging and retrieval."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def log_activity(
        self,
        activity_type: ActivityType,
        user_id: Optional[UUID] = None,
        session_id: Optional[UUID] = None,
        description: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        endpoint: Optional[str] = None,
        method: Optional[str] = None,
        request_data: Optional[Dict[str, Any]] = None,
        response_status: Optional[int] = None,
        duration_ms: Optional[float] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ActivityLog:
        """
        Log an activity.
        
        Args:
            activity_type: Type of activity
            user_id: User ID if authenticated
            session_id: Session ID
            description: Activity description
            resource_type: Type of resource accessed
            resource_id: Resource identifier
            endpoint: API endpoint
            method: HTTP method
            request_data: Request payload (sanitized)
            response_status: HTTP response status
            duration_ms: Request duration
            ip_address: Client IP
            user_agent: Client user agent
            metadata: Additional metadata
            
        Returns:
            Created activity log
        """
        # Skip if tracking is disabled
        if not settings.enable_activity_tracking:
            return None
        
        activity = ActivityLog(
            activity_type=activity_type,
            user_id=user_id,
            session_id=session_id,
            description=description,
            resource_type=resource_type,
            resource_id=resource_id,
            endpoint=endpoint,
            method=method,
            request_data=request_data,
            response_status=response_status,
            duration_ms=duration_ms,
            ip_address=ip_address,
            user_agent=user_agent,
            extra_data=metadata,
        )
        
        self.db.add(activity)
        await self.db.flush()
        
        logger.debug(
            "Activity logged",
            activity_type=activity_type.value,
            user_id=str(user_id) if user_id else None,
        )
        
        return activity
    
    async def get_user_activities(
        self,
        user_id: UUID,
        activity_type: Optional[ActivityType] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[ActivityLog]:
        """
        Get activities for a user.
        
        Args:
            user_id: User ID
            activity_type: Filter by activity type
            start_date: Filter by start date
            end_date: Filter by end date
            limit: Maximum results
            offset: Pagination offset
            
        Returns:
            List of activity logs
        """
        conditions = [ActivityLog.user_id == user_id]
        
        if activity_type:
            conditions.append(ActivityLog.activity_type == activity_type)
        if start_date:
            conditions.append(ActivityLog.created_at >= start_date)
        if end_date:
            conditions.append(ActivityLog.created_at <= end_date)
        
        query = (
            select(ActivityLog)
            .where(and_(*conditions))
            .order_by(desc(ActivityLog.created_at))
            .limit(limit)
            .offset(offset)
        )
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_recent_activities(
        self,
        limit: int = 50,
        activity_type: Optional[str] = None,
        activity_types: Optional[List[ActivityType]] = None,
    ) -> List[ActivityLog]:
        """
        Get recent activities across all users.
        
        Args:
            limit: Maximum results
            activity_type: Filter by single type (string)
            activity_types: Filter by multiple types
            
        Returns:
            List of recent activities
        """
        query = select(ActivityLog).order_by(desc(ActivityLog.created_at)).limit(limit)
        
        # Handle string activity type
        if activity_type:
            try:
                at = ActivityType(activity_type)
                query = query.where(ActivityLog.activity_type == at)
            except ValueError:
                pass  # Invalid type, return all
        
        if activity_types:
            query = query.where(ActivityLog.activity_type.in_(activity_types))
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_activity_counts(
        self,
        user_id: Optional[UUID] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, int]:
        """
        Get activity counts by type.
        
        Args:
            user_id: Filter by user
            start_date: Filter by start date
            end_date: Filter by end date
            
        Returns:
            Dictionary of activity type -> count
        """
        conditions = []
        if user_id:
            conditions.append(ActivityLog.user_id == user_id)
        if start_date:
            conditions.append(ActivityLog.created_at >= start_date)
        if end_date:
            conditions.append(ActivityLog.created_at <= end_date)
        
        query = (
            select(ActivityLog.activity_type, func.count(ActivityLog.id))
            .group_by(ActivityLog.activity_type)
        )
        
        if conditions:
            query = query.where(and_(*conditions))
        
        result = await self.db.execute(query)
        return {row[0].value: row[1] for row in result.all()}
    
    async def cleanup_old_activities(
        self,
        retention_days: Optional[int] = None,
    ) -> int:
        """
        Clean up old activity logs based on retention policy.
        
        Args:
            retention_days: Override default retention days
            
        Returns:
            Number of deleted records
        """
        from sqlalchemy import delete
        
        days = retention_days or settings.activity_retention_days
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        
        result = await self.db.execute(
            delete(ActivityLog).where(ActivityLog.created_at < cutoff)
        )
        
        deleted = result.rowcount
        logger.info("Cleaned up old activities", deleted=deleted, cutoff=cutoff.isoformat())
        
        return deleted
