# =============================================================================
# MCP Package
# =============================================================================
"""MCP Client for Tableau integration."""

from src.mcp.client import MCPClient
from src.mcp.models import (
    Datasource,
    DatasourceMetadata,
    TableauField,
    QueryResult,
    FieldDataType,
    FieldRole,
)

__all__ = [
    "MCPClient",
    "Datasource",
    "DatasourceMetadata",
    "TableauField",
    "QueryResult",
    "FieldDataType",
    "FieldRole",
]
