# =============================================================================
# Custom Exceptions
# =============================================================================
"""Application exception classes."""

from typing import Any, Dict, Optional


class TableauMCPError(Exception):
    """Base exception."""
    
    def __init__(
        self,
        message: str,
        status_code: int = 500,
        error_code: str = "INTERNAL_ERROR",
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.details = details or {}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": {
                "code": self.error_code,
                "message": self.message,
                "details": self.details,
            }
        }


class MCPClientError(TableauMCPError):
    """MCP client error."""
    def __init__(self, message: str, **kwargs):
        error_code = kwargs.pop("error_code", "MCP_CLIENT_ERROR")
        status_code = kwargs.pop("status_code", 502)
        # TableauMCPError does not accept random kwargs, only details
        details = kwargs.pop("details", kwargs or None) 
        super().__init__(message, status_code=status_code, error_code=error_code, details=details)


class MCPConnectionError(MCPClientError):
    """MCP connection error."""
    def __init__(self, message: str = "Failed to connect to MCP server"):
        super().__init__(message, error_code="MCP_CONNECTION_ERROR")


class MCPToolError(MCPClientError):
    """MCP tool execution error."""
    def __init__(self, tool_name: str, message: str):
        super().__init__(f"Tool '{tool_name}' failed: {message}", error_code="MCP_TOOL_ERROR")


class DatabaseError(TableauMCPError):
    """Database error."""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, status_code=500, error_code="DATABASE_ERROR", **kwargs)


class ValidationError(TableauMCPError):
    """Validation error."""
    def __init__(self, message: str, field: Optional[str] = None):
        details = {"field": field} if field else {}
        super().__init__(message, status_code=400, error_code="VALIDATION_ERROR", details=details)


class NotFoundError(TableauMCPError):
    """Resource not found."""
    def __init__(self, resource: str, resource_id: str):
        super().__init__(
            f"{resource} '{resource_id}' not found",
            status_code=404,
            error_code="NOT_FOUND",
            details={"resource": resource, "id": resource_id}
        )
