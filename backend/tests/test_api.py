# =============================================================================
# API Endpoint Tests
# =============================================================================
"""Tests for API endpoints."""

import pytest
from httpx import AsyncClient


class TestHealthEndpoints:
    """Tests for health check endpoints."""
    
    @pytest.mark.asyncio
    async def test_liveness_probe(self, async_client: AsyncClient):
        """Test liveness probe returns alive."""
        response = await async_client.get("/api/v1/live")
        assert response.status_code == 200
        data = response.json()
        assert data["alive"] is True
    
    @pytest.mark.asyncio
    async def test_readiness_probe(self, async_client: AsyncClient):
        """Test readiness probe returns ready."""
        response = await async_client.get("/api/v1/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["ready"] is True
    
    @pytest.mark.asyncio
    async def test_root_endpoint(self, async_client: AsyncClient):
        """Test root endpoint returns app info."""
        response = await async_client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Tableau MCP AI Agent"
        assert "version" in data


class TestQueryEndpoints:
    """Tests for query endpoints."""
    
    @pytest.mark.asyncio
    async def test_query_validation_empty_question(self, async_client: AsyncClient):
        """Test query validation rejects empty question."""
        response = await async_client.post(
            "/api/v1/query",
            json={"question": "", "username": "test"}
        )
        assert response.status_code == 422
    
    @pytest.mark.asyncio
    async def test_query_validation_short_question(self, async_client: AsyncClient):
        """Test query validation rejects too short question."""
        response = await async_client.post(
            "/api/v1/query",
            json={"question": "ab", "username": "test"}
        )
        assert response.status_code == 422
    
    @pytest.mark.asyncio
    async def test_query_requires_question_field(self, async_client: AsyncClient):
        """Test query endpoint requires question field."""
        response = await async_client.post(
            "/api/v1/query",
            json={"username": "test"}
        )
        assert response.status_code == 422
    
    @pytest.mark.asyncio
    async def test_query_history_returns_list(self, async_client: AsyncClient):
        """Test query history returns list structure."""
        response = await async_client.get(
            "/api/v1/query/history",
            params={"username": "nonexistent_user"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "queries" in data
        assert "count" in data
        assert isinstance(data["queries"], list)


class TestFeedbackEndpoints:
    """Tests for feedback endpoints."""
    
    @pytest.mark.asyncio
    async def test_feedback_stats_endpoint(self, async_client: AsyncClient):
        """Test feedback stats endpoint returns statistics."""
        response = await async_client.get("/api/v1/feedback/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "likes" in data
        assert "dislikes" in data
    
    @pytest.mark.asyncio
    async def test_feedback_validation_requires_query_id(self, async_client: AsyncClient):
        """Test feedback requires valid query_id."""
        response = await async_client.post(
            "/api/v1/feedback",
            json={
                "feedback_type": "like",
                "username": "test"
            }
        )
        assert response.status_code == 422


class TestDatasourceEndpoints:
    """Tests for datasource endpoints."""
    
    @pytest.mark.asyncio
    async def test_list_datasources_endpoint(self, async_client: AsyncClient):
        """Test list datasources endpoint structure."""
        # This may fail if MCP is not connected, but should return proper structure
        response = await async_client.get("/api/v1/datasources")
        # Either success or 502 (MCP not available)
        assert response.status_code in [200, 502]


class TestAnalyticsEndpoints:
    """Tests for analytics endpoints."""
    
    @pytest.mark.asyncio
    async def test_dashboard_endpoint(self, async_client: AsyncClient):
        """Test dashboard stats endpoint."""
        response = await async_client.get(
            "/api/v1/analytics/dashboard",
            params={"days": 7}
        )
        assert response.status_code == 200
        data = response.json()
        assert "period" in data or "queries" in data
    
    @pytest.mark.asyncio
    async def test_activity_counts_endpoint(self, async_client: AsyncClient):
        """Test activity counts endpoint."""
        response = await async_client.get(
            "/api/v1/analytics/activity/counts",
            params={"days": 7}
        )
        assert response.status_code == 200
        data = response.json()
        assert "counts" in data
