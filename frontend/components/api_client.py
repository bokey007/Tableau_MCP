# =============================================================================
# Shared API Client
# =============================================================================
"""HTTP client for backend API - shared across all pages."""

import os
from typing import Any, Dict, List, Optional

import httpx

# Configuration
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
API_PREFIX = "/api/v1"
DEFAULT_TIMEOUT = 300.0


class APIClient:
    """HTTP client for backend API."""
    
    def __init__(self, base_url: str = BACKEND_URL, timeout: float = DEFAULT_TIMEOUT):
        self.base_url = base_url
        self.api_url = f"{base_url}{API_PREFIX}"
        self.timeout = timeout
    
    def _get_client(self) -> httpx.Client:
        """Get configured HTTP client."""
        return httpx.Client(timeout=self.timeout)
    
    def _handle_response(self, response: httpx.Response) -> Dict[str, Any]:
        """Handle API response with error handling."""
        try:
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            error_detail = "Unknown error"
            try:
                error_data = e.response.json()
                error_detail = error_data.get("detail", str(e))
            except:
                error_detail = e.response.text or str(e)
            return {"error": f"HTTP {e.response.status_code}: {error_detail}", "success": False}
        except httpx.TimeoutException:
            return {"error": "Request timed out. Please try again.", "success": False}
        except httpx.ConnectError:
            return {"error": "Unable to connect to server. Please check if backend is running.", "success": False}
        except Exception as e:
            return {"error": str(e), "success": False}
    
    # =========================================================================
    # Health Endpoints
    # =========================================================================
    
    def health_check(self) -> Dict[str, Any]:
        """Check backend health status."""
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"{self.api_url}/health")
                return response.json()
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    # =========================================================================
    # Query Endpoints
    # =========================================================================
    
    def query(
        self, 
        question: str, 
        datasource_id: Optional[str] = None,
        username: str = "default_user",
        thread_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a natural language query with LangGraph conversation memory."""
        try:
            with self._get_client() as client:
                payload = {
                    "question": question,
                    "datasource_id": datasource_id,
                    "username": username,
                }
                if thread_id:
                    payload["thread_id"] = thread_id
                    
                response = client.post(
                    f"{self.api_url}/query",
                    json=payload,
                )
                return self._handle_response(response)
        except Exception as e:
            return {"error": str(e), "success": False}
    
    def get_query_history(
        self, 
        username: str = "default_user", 
        limit: int = 50,
        status: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get query history for a user."""
        try:
            with self._get_client() as client:
                params = {"username": username, "limit": limit}
                if status:
                    params["status"] = status
                response = client.get(f"{self.api_url}/query/history", params=params)
                return self._handle_response(response)
        except Exception as e:
            return {"error": str(e), "queries": []}
    
    def get_query_detail(self, query_id: str) -> Dict[str, Any]:
        """Get detailed information for a specific query."""
        try:
            with self._get_client() as client:
                response = client.get(f"{self.api_url}/query/{query_id}")
                return self._handle_response(response)
        except Exception as e:
            return {"error": str(e)}
    
    def delete_query(self, query_id: str, username: str = "default_user") -> Dict[str, Any]:
        """Delete a query from history."""
        try:
            with self._get_client() as client:
                response = client.delete(
                    f"{self.api_url}/query/{query_id}",
                    params={"username": username}
                )
                return self._handle_response(response)
        except Exception as e:
            return {"error": str(e)}
    
    # =========================================================================
    # Datasource Endpoints
    # =========================================================================
    
    def list_datasources(self, filter: Optional[str] = None) -> Dict[str, Any]:
        """List available datasources."""
        try:
            with self._get_client() as client:
                params = {}
                if filter:
                    params["filter"] = filter
                response = client.get(f"{self.api_url}/datasources", params=params)
                return self._handle_response(response)
        except Exception as e:
            return {"error": str(e), "datasources": []}
    
    def get_datasource_metadata(self, datasource_id: str) -> Dict[str, Any]:
        """Get datasource schema/metadata."""
        try:
            with self._get_client() as client:
                response = client.get(f"{self.api_url}/datasources/{datasource_id}/metadata")
                return self._handle_response(response)
        except Exception as e:
            return {"error": str(e)}
    
    # =========================================================================
    # Feedback Endpoints
    # =========================================================================
    
    def submit_feedback(
        self,
        query_id: str,
        feedback_type: str,
        rating: Optional[int] = None,
        comment: Optional[str] = None,
        username: str = "default_user"
    ) -> Dict[str, Any]:
        """Submit feedback (like/dislike) for a query."""
        try:
            with self._get_client() as client:
                response = client.post(
                    f"{self.api_url}/feedback",
                    json={
                        "query_id": query_id,
                        "feedback_type": feedback_type,
                        "rating": rating,
                        "comment": comment,
                        "username": username,
                    },
                )
                return self._handle_response(response)
        except Exception as e:
            return {"error": str(e)}
    
    def get_feedback_stats(self, username: Optional[str] = None) -> Dict[str, Any]:
        """Get feedback statistics."""
        try:
            with self._get_client() as client:
                params = {}
                if username:
                    params["username"] = username
                response = client.get(f"{self.api_url}/feedback/stats", params=params)
                return self._handle_response(response)
        except Exception as e:
            return {"error": str(e)}
    
    # =========================================================================
    # Analytics Endpoints
    # =========================================================================
    
    def get_dashboard_stats(self, days: int = 30) -> Dict[str, Any]:
        """Get dashboard statistics."""
        try:
            with self._get_client() as client:
                response = client.get(
                    f"{self.api_url}/analytics/dashboard",
                    params={"days": days},
                )
                return self._handle_response(response)
        except Exception as e:
            return {"error": str(e)}
    
    def get_usage_report(
        self, 
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get comprehensive usage report."""
        try:
            with self._get_client() as client:
                params = {}
                if start_date:
                    params["start_date"] = start_date
                if end_date:
                    params["end_date"] = end_date
                response = client.get(f"{self.api_url}/analytics/report", params=params)
                return self._handle_response(response)
        except Exception as e:
            return {"error": str(e)}
    
    def get_activity_counts(self, days: int = 7) -> Dict[str, Any]:
        """Get activity counts by type."""
        try:
            with self._get_client() as client:
                response = client.get(
                    f"{self.api_url}/analytics/activity/counts",
                    params={"days": days},
                )
                return self._handle_response(response)
        except Exception as e:
            return {"error": str(e), "counts": {}}
    
    def get_trends(self, days: int = 30) -> Dict[str, Any]:
        """Get usage trends over time."""
        try:
            with self._get_client() as client:
                response = client.get(
                    f"{self.api_url}/analytics/trends",
                    params={"days": days},
                )
                return self._handle_response(response)
        except Exception as e:
            return {"error": str(e)}


# Singleton instance for easy import
api_client = APIClient()
