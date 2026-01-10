# =============================================================================
# Analytics Routes
# =============================================================================
"""Analytics and reporting endpoints."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import get_logger
from src.db import get_db
from src.services.analytics_service import AnalyticsService
from src.services.activity_service import ActivityService

router = APIRouter()
logger = get_logger(__name__)


@router.get("/dashboard")
async def get_dashboard(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """
    Get dashboard statistics.
    
    Includes:
    - Query statistics (total, success rate, avg execution time)
    - Feedback statistics (likes, dislikes, satisfaction rate)
    - User statistics (active, new, total)
    - Top datasources
    """
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)
    
    analytics_service = AnalyticsService(db)
    stats = await analytics_service.get_dashboard_stats(start_date, end_date)
    
    return stats


@router.get("/report")
async def get_usage_report(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a comprehensive usage report.
    
    Includes:
    - All dashboard statistics
    - Top users
    - Recent feedback with comments
    """
    now = datetime.now(timezone.utc)
    
    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        except ValueError:
            start_dt = now - timedelta(days=30)
    else:
        start_dt = now - timedelta(days=30)
    
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        except ValueError:
            end_dt = now
    else:
        end_dt = now
    
    analytics_service = AnalyticsService(db)
    report = await analytics_service.get_usage_report(start_dt, end_dt)
    
    return report


@router.get("/activity")
async def get_recent_activity(
    limit: int = Query(default=50, ge=1, le=200),
    activity_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Get recent activity across all users.
    
    Args:
        limit: Maximum number of activities to return
        activity_type: Filter by activity type (query, feedback, etc.)
    """
    activity_service = ActivityService(db)
    activities = await activity_service.get_recent_activities(
        limit=limit,
        activity_type=activity_type,
    )
    
    return {
        "activities": [
            {
                "id": str(a.id),
                "type": a.activity_type.value,
                "description": a.description,
                "user_id": str(a.user_id) if a.user_id else None,
                "resource_type": a.resource_type,
                "resource_id": a.resource_id,
                "endpoint": a.endpoint,
                "duration_ms": a.duration_ms,
                "created_at": a.created_at.isoformat(),
            }
            for a in activities
        ],
        "count": len(activities),
    }


@router.get("/activity/counts")
async def get_activity_counts(
    days: int = Query(default=7, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """Get activity counts by type for the specified period."""
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)
    
    activity_service = ActivityService(db)
    counts = await activity_service.get_activity_counts(
        start_date=start_date,
        end_date=end_date,
    )
    
    return {
        "period_days": days,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "counts": counts,
    }


@router.get("/trends")
async def get_trends(
    days: int = Query(default=30, ge=7, le=365),
    db: AsyncSession = Depends(get_db),
):
    """
    Get usage trends over time.
    
    Returns daily aggregated data for charting.
    """
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)
    
    analytics_service = AnalyticsService(db)
    stats = await analytics_service.get_dashboard_stats(start_date, end_date)
    
    return {
        "period_days": days,
        "daily_queries": stats.get("queries", {}).get("daily", []),
        "summary": {
            "total_queries": stats.get("queries", {}).get("total", 0),
            "success_rate": stats.get("queries", {}).get("success_rate", 0),
            "satisfaction_rate": stats.get("feedback", {}).get("satisfaction_rate", 0),
            "active_users": stats.get("users", {}).get("active", 0),
        },
    }
