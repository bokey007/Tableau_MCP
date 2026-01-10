# =============================================================================
# Database Model Tests
# =============================================================================
"""Tests for database models."""

import pytest
from uuid import uuid4
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import User, Query, QueryFeedback, QueryStatus, FeedbackType


class TestUserModel:
    """Tests for User model."""
    
    @pytest.mark.asyncio
    async def test_create_user(self, db: AsyncSession):
        """Test creating a user."""
        user = User(
            username="test_user",
            email="test@example.com",
            display_name="Test User",
        )
        db.add(user)
        await db.commit()
        
        assert user.id is not None
        assert user.username == "test_user"
        assert user.is_active is True


class TestQueryModel:
    """Tests for Query model."""
    
    @pytest.mark.asyncio
    async def test_create_query(self, db: AsyncSession):
        """Test creating a query."""
        # First create a user
        user = User(username="query_test_user")
        db.add(user)
        await db.flush()
        
        query = Query(
            user_id=user.id,
            question="What are the top sales?",
            status=QueryStatus.PENDING,
        )
        db.add(query)
        await db.commit()
        
        assert query.id is not None
        assert query.status == QueryStatus.PENDING


class TestFeedbackModel:
    """Tests for QueryFeedback model."""
    
    @pytest.mark.asyncio
    async def test_create_feedback(self, db: AsyncSession):
        """Test creating feedback."""
        # Create user and query
        user = User(username="feedback_test_user")
        db.add(user)
        await db.flush()
        
        query = Query(
            user_id=user.id,
            question="Test question",
            status=QueryStatus.SUCCESS,
        )
        db.add(query)
        await db.flush()
        
        feedback = QueryFeedback(
            query_id=query.id,
            user_id=user.id,
            feedback_type=FeedbackType.LIKE,
            rating=5,
        )
        db.add(feedback)
        await db.commit()
        
        assert feedback.id is not None
        assert feedback.feedback_type == FeedbackType.LIKE
        assert feedback.rating == 5
