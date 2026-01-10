# =============================================================================
# Service Tests
# =============================================================================
"""Tests for service layer."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from src.db.models import FeedbackType, QueryStatus


class TestQueryService:
    """Tests for QueryService."""
    
    @pytest.mark.asyncio
    async def test_feedback_stats_structure(self):
        """Test feedback stats returns proper structure."""
        from src.services.query_service import QueryService
        
        # Create mock db session
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_result.one.return_value = (None, None, None, None)
        mock_db.execute.return_value = mock_result
        
        service = QueryService(mock_db)
        stats = await service.get_feedback_stats()
        
        assert "total" in stats
        assert "likes" in stats
        assert "dislikes" in stats
        assert "like_ratio" in stats


class TestUserService:
    """Tests for UserService."""
    
    @pytest.mark.asyncio
    async def test_get_or_create_user_creates_new(self):
        """Test get_or_create_user creates new user if not exists."""
        from src.services.user_service import UserService
        from src.db.models import User
        
        # Create mock db session
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        mock_db.flush = AsyncMock()
        
        service = UserService(mock_db)
        user = await service.get_or_create_user("new_user")
        
        # Verify add was called
        mock_db.add.assert_called_once()


class TestActivityService:
    """Tests for ActivityService."""
    
    @pytest.mark.asyncio
    async def test_log_activity_creates_log(self):
        """Test log_activity creates activity log."""
        from src.services.activity_service import ActivityService
        from src.db.models import ActivityType
        
        # Create mock db session
        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        
        service = ActivityService(mock_db)
        
        await service.log_activity(
            activity_type=ActivityType.QUERY,
            description="Test query",
        )
        
        # Verify add was called
        mock_db.add.assert_called_once()


class TestAnalyticsService:
    """Tests for AnalyticsService."""
    
    @pytest.mark.asyncio
    async def test_dashboard_stats_structure(self):
        """Test dashboard stats returns proper structure."""
        from src.services.analytics_service import AnalyticsService
        from datetime import datetime, timedelta, timezone
        
        # Create mock db session with proper return values
        mock_db = AsyncMock()
        
        # Mock all the execute calls
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_result.all.return_value = []
        mock_result.one.return_value = (None, None, None)
        mock_db.execute.return_value = mock_result
        
        service = AnalyticsService(mock_db)
        
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=7)
        
        # This should not raise an error
        stats = await service.get_dashboard_stats(start, end)
        
        assert "period" in stats
        assert "queries" in stats
