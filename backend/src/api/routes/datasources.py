# =============================================================================
# Datasources Routes
# =============================================================================
"""Datasource management endpoints."""

from fastapi import APIRouter, HTTPException

from src.core.logging import get_logger
from src.mcp.client import MCPClient

router = APIRouter()
logger = get_logger(__name__)


@router.get("")
async def list_datasources(filter: str = None, limit: int = None):
    """List available datasources."""
    try:
        async with MCPClient() as client:
            datasources = await client.list_datasources(filter=filter, limit=limit)
            
            return {
                "datasources": [
                    {
                        "id": ds.id,
                        "name": ds.name,
                        "description": ds.description,
                        "project_name": ds.project.name if ds.project else None,
                    }
                    for ds in datasources
                ],
                "count": len(datasources),
            }
    except Exception as e:
        logger.error("Failed to list datasources", error=str(e))
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/{datasource_id}")
async def get_datasource(datasource_id: str):
    """Get datasource details."""
    try:
        async with MCPClient() as client:
            datasources = await client.list_datasources()
            
            for ds in datasources:
                if ds.id == datasource_id:
                    return {
                        "id": ds.id,
                        "name": ds.name,
                        "description": ds.description,
                        "project_name": ds.project.name if ds.project else None,
                    }
            
            raise HTTPException(status_code=404, detail="Datasource not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get datasource", error=str(e))
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/{datasource_id}/metadata")
async def get_metadata(datasource_id: str):
    """Get datasource metadata (schema)."""
    try:
        async with MCPClient() as client:
            metadata = await client.get_datasource_metadata(datasource_id)
            
            return {
                "datasource_id": datasource_id,
                "fields": [
                    {
                        "name": f.name,
                        "data_type": f.dataType.value,
                        "role": f.role.value if f.role else None,
                        "default_aggregation": f.defaultAggregation,
                        "description": f.description,
                    }
                    for f in metadata.fields
                ],
                "dimension_count": len(metadata.dimensions),
                "measure_count": len(metadata.measures),
                "schema_description": metadata.to_schema_description(),
            }
    except Exception as e:
        logger.error("Failed to get metadata", error=str(e))
        raise HTTPException(status_code=502, detail=str(e))
