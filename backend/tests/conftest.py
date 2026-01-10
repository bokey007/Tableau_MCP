# =============================================================================
# Backend Tests Configuration
# =============================================================================
"""Test configuration and fixtures."""

import asyncio
import os
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

# Set test environment before importing app
os.environ["APP_ENV"] = "test"
os.environ["OPENAI_API_KEY"] = "sk-test-key-not-real"
os.environ["POSTGRES_HOST"] = "localhost"
os.environ["POSTGRES_PASSWORD"] = "testpassword"

from src.main import app
from src.db.models import Base, User, Query, QueryFeedback, QueryStatus, FeedbackType
from src.db import get_db


# =============================================================================
# Event Loop
# =============================================================================

@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Create event loop for async tests."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


# =============================================================================
# Database Fixtures
# =============================================================================

@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """Create async database session for testing using SQLite."""
    # Use SQLite for testing
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    
    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Create session factory
    async_session = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    
    async with async_session() as session:
        yield session
        await session.rollback()
    
    # Drop all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    await engine.dispose()


# =============================================================================
# HTTP Client Fixtures
# =============================================================================

@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """Create async HTTP client for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# =============================================================================
# Sample Data Fixtures
# =============================================================================

@pytest.fixture
def sample_user() -> User:
    """Create a sample user for testing."""
    import uuid
    return User(
        id=uuid.uuid4(),
        username="test_user",
        email="test@example.com",
        display_name="Test User",
    )


@pytest.fixture
def sample_query_request():
    """Sample query request data."""
    return {
        "question": "What are the top 5 customers by sales?",
        "datasource_id": None,
        "username": "test_user",
    }


@pytest.fixture
def sample_feedback_request():
    """Sample feedback request data."""
    return {
        "query_id": "550e8400-e29b-41d4-a716-446655440000",
        "feedback_type": "like",
        "rating": 5,
        "comment": "Great response!",
        "username": "test_user",
    }


# =============================================================================
# Mock Fixtures
# =============================================================================

@pytest.fixture
def mock_mcp_client():
    """Mock MCP client for testing."""
    from src.mcp.models import Datasource, DatasourceMetadata, TableauField, QueryResult, FieldDataType
    
    mock = AsyncMock()
    
    # Mock list_datasources
    mock.list_datasources.return_value = [
        Datasource(id="ds-1", name="Sales Data", description="Sales dataset"),
        Datasource(id="ds-2", name="Customer Data", description="Customer dataset"),
    ]
    
    # Mock get_datasource_metadata
    mock.get_datasource_metadata.return_value = DatasourceMetadata(
        datasource_id="ds-1",
        fields=[
            TableauField(name="Customer Name", dataType=FieldDataType.STRING),
            TableauField(name="Sales", dataType=FieldDataType.REAL),
        ],
    )
    
    # Mock query_datasource
    mock.query_datasource.return_value = QueryResult(
        data=[
            {"Customer Name": "Acme Corp", "Sales": 10000},
            {"Customer Name": "TechCo", "Sales": 8000},
        ],
        row_count=2,
        execution_time_ms=150.0,
    )
    
    # Mock context manager
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=None)
    
    return mock
