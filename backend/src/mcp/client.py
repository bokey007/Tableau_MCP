# =============================================================================
# MCP HTTP Client
# =============================================================================
"""Async client for Tableau MCP Server."""

import asyncio
import json
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

import httpx
from cachetools import TTLCache
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from src.core.config import settings
from src.core.exceptions import MCPClientError, MCPConnectionError, MCPToolError
from src.core.logging import get_logger
from src.mcp.models import (
    Datasource,
    DatasourceMetadata,
    TableauField,
    QueryResult,
)

logger = get_logger(__name__)


class MCPClient:
    """Async HTTP client for Tableau MCP Server."""
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[int] = None,
    ):
        self.base_url = (base_url or settings.mcp_server_url).rstrip("/")
        self.timeout = timeout or settings.mcp_request_timeout
        self._cache: TTLCache = TTLCache(
            maxsize=settings.cache_max_size,
            ttl=settings.cache_ttl
        )
        self._session_id: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout),
                headers={
                    "Content-Type": "application/json",
                    # MCP Streamable HTTP requires accepting both JSON and SSE
                    "Accept": "application/json, text/event-stream",
                },
            )
        return self._client
    
    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
    
    async def __aenter__(self) -> "MCPClient":
        return self
    
    async def __aexit__(self, *args) -> None:
        await self.close()
    
    async def _initialize_session(self) -> str:
        """Initialize MCP session."""
        if self._session_id:
            return self._session_id
        
        async with self._lock:
            if self._session_id:
                return self._session_id
            
            try:
                response = await self._send_request("initialize", {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "clientInfo": {"name": "tableau-mcp-agent", "version": "1.0.0"},
                })
                
                self._session_id = response.get("sessionId", str(uuid4()))
                logger.info("MCP session initialized", session_id=self._session_id)
                return self._session_id
            except Exception as e:
                logger.error("Failed to initialize MCP session", error=str(e))
                # Use a temporary session ID to continue
                self._session_id = str(uuid4())
                return self._session_id
    
    @retry(
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def _send_request(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send JSON-RPC request to MCP server."""
        client = await self._get_client()
        request_id = str(uuid4())
        
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        
        headers = {}
        if self._session_id:
            headers["mcp-session-id"] = self._session_id
        
        start_time = time.monotonic()
        
        try:
            # POST directly to base_url - the path is included in the URL
            response = await client.post("", json=payload, headers=headers)
            response.raise_for_status()
        except httpx.ConnectError as e:
            logger.error("MCP connection failed", error=str(e))
            raise MCPConnectionError(f"Failed to connect to MCP server at {self.base_url}: {e}")
        except httpx.TimeoutException as e:
            logger.error("MCP request timed out", error=str(e))
            raise MCPClientError(f"Request timed out after {self.timeout}s: {e}")
        except httpx.HTTPStatusError as e:
            logger.error("MCP HTTP error", status=e.response.status_code)
            raise MCPClientError(f"HTTP error {e.response.status_code}: {e.response.text}")
        
        elapsed_ms = (time.monotonic() - start_time) * 1000
        logger.debug("MCP request completed", method=method, elapsed_ms=round(elapsed_ms, 2))
        
        try:
            # Try parsing as JSON first (some implementations return pure JSON)
            result = response.json()
        except json.JSONDecodeError:
            # Parse as SSE
            result = None
            for line in response.text.splitlines():
                if line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                        # Look for the response matching our request ID
                        if data.get("id") == request_id:
                            result = data
                            break
                        # Or if it's the only result (init)
                        if "result" in data and not result:
                            result = data
                    except json.JSONDecodeError:
                        continue
            
            if not result:
                logger.error("Invalid response format", body=response.text[:1000])
                raise MCPClientError("Failed to parse MCP response (SSE format)")
        
        if "error" in result:
            error = result["error"]
            error_msg = error.get("message", "Unknown MCP error")
            logger.error("MCP RPC Error", error=error)
            raise MCPClientError(f"RPC Error: {error_msg}") from None
            
        return result.get("result", {})
    
    async def call_tool(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Call an MCP tool.
        
        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments
            
        Returns:
            Tool result
        """
        await self._initialize_session()
        
        try:
            result = await self._send_request("tools/call", {
                "name": tool_name,
                "arguments": arguments or {},
            })
            
            if isinstance(result, dict) and result.get("isError"):
                content = result.get("content", [{}])
                error_msg = content[0].get("text", "Unknown error") if content else "Unknown error"
                raise MCPToolError(tool_name, error_msg)
            
            return result
        except MCPClientError:
            raise
        except Exception as e:
            logger.exception(f"Unexpected error calling tool {tool_name}")
            raise MCPToolError(tool_name, f"Unexpected error: {str(e)}")
    
    def _parse_tool_content(self, result: Dict[str, Any]) -> Any:
        """Parse content from MCP tool response."""
        content = result.get("content", [])
        if not content:
            return []
        
        text = content[0].get("text", "")
        if not text:
            return []
        
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    
    async def list_datasources(
        self,
        filter: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Datasource]:
        """
        List available datasources.
        
        Args:
            filter: Optional filter string
            limit: Maximum number of results
            
        Returns:
            List of datasources
        """
        cache_key = f"datasources:{filter}:{limit}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        args: Dict[str, Any] = {}
        if filter:
            args["filter"] = filter
        if limit:
            args["limit"] = limit
        
        result = await self.call_tool("list-datasources", args)
        datasources_data = self._parse_tool_content(result)
        
        if not isinstance(datasources_data, list):
            datasources_data = []
        
        parsed = [Datasource(**ds) for ds in datasources_data]
        
        self._cache[cache_key] = parsed
        return parsed
    
    async def get_datasource_metadata(self, datasource_id: str) -> DatasourceMetadata:
        """
        Get datasource metadata (schema).
        
        Args:
            datasource_id: Datasource LUID
            
        Returns:
            Datasource metadata with fields
        """
        cache_key = f"metadata:{datasource_id}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        result = await self.call_tool("get-datasource-metadata", {
            "datasourceLuid": datasource_id,
        })
        
        data = self._parse_tool_content(result)
        
        fields_data = data.get("fields", []) if isinstance(data, dict) else []
        
        metadata = DatasourceMetadata(
            datasource_id=datasource_id,
            fields=[TableauField(**f) for f in fields_data],
            parameters=data.get("parameters", []) if isinstance(data, dict) else [],
        )
        
        self._cache[cache_key] = metadata
        return metadata
    
    async def query_datasource(
        self,
        datasource_id: str,
        query: Dict[str, Any],
    ) -> QueryResult:
        """
        Execute a VizQL query on a datasource.
        
        Args:
            datasource_id: Datasource LUID
            query: VizQL query object
            
        Returns:
            Query results
        """
        start_time = time.monotonic()
        
        # Sanitize query - ONLY use fields, remove filters to avoid schema issues
        # Date/time filtering is done in Python post-processing
        sanitized_query = {
            "fields": query.get("fields", [])
        }
        
        # Only include parameters if they exist and are valid
        if query.get("parameters"):
            sanitized_query["parameters"] = query["parameters"]
        
        # Log if we're stripping out filters (for debugging)
        if query.get("filters"):
            logger.warning(
                "Stripping filters from query (unsupported schema)",
                filter_count=len(query.get("filters", []))
            )

        result = await self.call_tool("query-datasource", {
            "datasourceLuid": datasource_id,
            "query": sanitized_query,
        })
        
        elapsed_ms = (time.monotonic() - start_time) * 1000
        data = self._parse_tool_content(result)
        
        # Handle different response formats
        if isinstance(data, dict):
            rows = data.get("data", data.get("rows", []))
        elif isinstance(data, list):
            rows = data
        else:
            rows = []
        
        return QueryResult(
            data=rows,
            query=query,
            execution_time_ms=elapsed_ms,
        )
    
    async def search_content(
        self,
        terms: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Search Tableau content.
        
        Args:
            terms: Search terms
            limit: Maximum results
            
        Returns:
            Search results
        """
        args: Dict[str, Any] = {"limit": limit}
        if terms:
            args["terms"] = terms
        
        result = await self.call_tool("search-content", args)
        content = self._parse_tool_content(result)
        
        if isinstance(content, list):
            return content
        return []
    
    def clear_cache(self) -> None:
        """Clear the cache."""
        self._cache.clear()
    
    async def health_check(self) -> bool:
        """
        Check if MCP server is reachable.
        
        Returns:
            True if healthy, False otherwise
        """
        try:
            await self.list_datasources(limit=1)
            return True
        except Exception:
            return False
