# =============================================================================
# Analytics Service
# =============================================================================
"""Service for analytics and reporting."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select, and_, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import get_logger
from src.db.models import (
    Query, QueryFeedback, ActivityLog, User, Session,
    QueryStatus, FeedbackType, ActivityType, UsageStatistics,
)

logger = get_logger(__name__)


class AnalyticsService:
    """Service for analytics and reporting."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_dashboard_stats(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Get dashboard statistics.
        
        Args:
            start_date: Statistics start date
            end_date: Statistics end date
            
        Returns:
            Dashboard statistics dictionary
        """
        if not start_date:
            start_date = datetime.now(timezone.utc) - timedelta(days=30)
        if not end_date:
            end_date = datetime.now(timezone.utc)
        
        # Query statistics
        query_stats = await self._get_query_stats(start_date, end_date)
        
        # Feedback statistics
        feedback_stats = await self._get_feedback_stats(start_date, end_date)
        
        # User statistics
        user_stats = await self._get_user_stats(start_date, end_date)
        
        # Top datasources
        top_datasources = await self._get_top_datasources(start_date, end_date)
        
        return {
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
            },
            "queries": query_stats,
            "feedback": feedback_stats,
            "users": user_stats,
            "top_datasources": top_datasources,
        }
    
    async def _get_query_stats(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> Dict[str, Any]:
        """Get query statistics."""
        conditions = [
            Query.created_at >= start_date,
            Query.created_at <= end_date,
        ]
        
        # Total queries
        total_result = await self.db.execute(
            select(func.count(Query.id)).where(and_(*conditions))
        )
        total = total_result.scalar() or 0
        
        # By status
        status_result = await self.db.execute(
            select(Query.status, func.count(Query.id))
            .where(and_(*conditions))
            .group_by(Query.status)
        )
        by_status = {row[0].value: row[1] for row in status_result.all()}
        
        # Average execution time
        avg_time_result = await self.db.execute(
            select(func.avg(Query.execution_time_ms))
            .where(and_(*conditions, Query.execution_time_ms.isnot(None)))
        )
        avg_time = avg_time_result.scalar()
        
        # Queries per day
        date_trunc_expr = func.date_trunc('day', Query.created_at)
        daily_result = await self.db.execute(
            select(
                date_trunc_expr.label('date'),
                func.count(Query.id)
            )
            .where(and_(*conditions))
            .group_by(date_trunc_expr)
            .order_by(date_trunc_expr.desc())
        )
        daily = [
            {"date": row[0].isoformat() if row[0] else None, "count": row[1]}
            for row in daily_result.all()
        ]
        
        return {
            "total": total,
            "successful": by_status.get("success", 0),
            "failed": by_status.get("failed", 0),
            "success_rate": (
                by_status.get("success", 0) / total if total > 0 else 0
            ),
            "avg_execution_time_ms": float(avg_time) if avg_time else None,
            "daily": daily,
        }
    
    async def _get_feedback_stats(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> Dict[str, Any]:
        """Get feedback statistics."""
        conditions = [
            QueryFeedback.created_at >= start_date,
            QueryFeedback.created_at <= end_date,
        ]
        
        # By type
        type_result = await self.db.execute(
            select(QueryFeedback.feedback_type, func.count(QueryFeedback.id))
            .where(and_(*conditions))
            .group_by(QueryFeedback.feedback_type)
        )
        by_type = {row[0].value: row[1] for row in type_result.all()}
        
        total = sum(by_type.values())
        likes = by_type.get("like", 0)
        dislikes = by_type.get("dislike", 0)
        
        # Average ratings
        avg_result = await self.db.execute(
            select(
                func.avg(QueryFeedback.rating),
                func.avg(QueryFeedback.accuracy_rating),
                func.avg(QueryFeedback.usefulness_rating),
            ).where(and_(*conditions))
        )
        avg_row = avg_result.one()
        
        return {
            "total": total,
            "likes": likes,
            "dislikes": dislikes,
            "neutral": by_type.get("neutral", 0),
            "satisfaction_rate": likes / total if total > 0 else 0,
            "avg_rating": float(avg_row[0]) if avg_row[0] else None,
            "avg_accuracy": float(avg_row[1]) if avg_row[1] else None,
            "avg_usefulness": float(avg_row[2]) if avg_row[2] else None,
        }
    
    async def _get_user_stats(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> Dict[str, Any]:
        """Get user statistics."""
        # Active users (users with queries in period)
        active_result = await self.db.execute(
            select(func.count(func.distinct(Query.user_id)))
            .where(and_(
                Query.created_at >= start_date,
                Query.created_at <= end_date,
            ))
        )
        active_users = active_result.scalar() or 0
        
        # New users
        new_result = await self.db.execute(
            select(func.count(User.id))
            .where(and_(
                User.created_at >= start_date,
                User.created_at <= end_date,
            ))
        )
        new_users = new_result.scalar() or 0
        
        # Total users
        total_result = await self.db.execute(
            select(func.count(User.id)).where(User.is_active == True)
        )
        total_users = total_result.scalar() or 0
        
        # Sessions
        session_result = await self.db.execute(
            select(func.count(Session.id))
            .where(and_(
                Session.started_at >= start_date,
                Session.started_at <= end_date,
            ))
        )
        total_sessions = session_result.scalar() or 0
        
        return {
            "total": total_users,
            "active": active_users,
            "new": new_users,
            "sessions": total_sessions,
        }
    
    async def _get_top_datasources(
        self,
        start_date: datetime,
        end_date: datetime,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Get top queried datasources."""
        result = await self.db.execute(
            select(
                Query.datasource_id,
                Query.datasource_name,
                func.count(Query.id).label('query_count')
            )
            .where(and_(
                Query.created_at >= start_date,
                Query.created_at <= end_date,
                Query.datasource_id.isnot(None),
            ))
            .group_by(Query.datasource_id, Query.datasource_name)
            .order_by(desc('query_count'))
            .limit(limit)
        )
        
        return [
            {
                "datasource_id": row[0],
                "datasource_name": row[1],
                "query_count": row[2],
            }
            for row in result.all()
        ]
    
    async def get_usage_report(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> Dict[str, Any]:
        """
        Generate a comprehensive usage report.
        
        Args:
            start_date: Report start date
            end_date: Report end date
            
        Returns:
            Usage report
        """
        dashboard = await self.get_dashboard_stats(start_date, end_date)
        
        # Top users by queries
        top_users_result = await self.db.execute(
            select(
                User.username,
                User.display_name,
                func.count(Query.id).label('query_count')
            )
            .join(Query, Query.user_id == User.id)
            .where(and_(
                Query.created_at >= start_date,
                Query.created_at <= end_date,
            ))
            .group_by(User.id, User.username, User.display_name)
            .order_by(desc('query_count'))
            .limit(10)
        )
        top_users = [
            {"username": row[0], "display_name": row[1], "query_count": row[2]}
            for row in top_users_result.all()
        ]
        
        # Recent feedback with comments
        feedback_result = await self.db.execute(
            select(QueryFeedback)
            .where(and_(
                QueryFeedback.created_at >= start_date,
                QueryFeedback.created_at <= end_date,
                QueryFeedback.comment.isnot(None),
            ))
            .order_by(desc(QueryFeedback.created_at))
            .limit(20)
        )
        recent_feedback = [
            {
                "type": f.feedback_type.value,
                "rating": f.rating,
                "comment": f.comment,
                "created_at": f.created_at.isoformat(),
            }
            for f in feedback_result.scalars().all()
        ]
        
        return {
            **dashboard,
            "top_users": top_users,
            "recent_feedback_comments": recent_feedback,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
