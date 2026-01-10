# =============================================================================
# MCP Data Models
# =============================================================================
"""Pydantic models for MCP data structures."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field as PydanticField


class FieldDataType(str, Enum):
    """Field data type enumeration."""
    STRING = "STRING"
    INTEGER = "INTEGER"
    REAL = "REAL"
    DATE = "DATE"
    DATETIME = "DATETIME"
    BOOLEAN = "BOOLEAN"


class FieldRole(str, Enum):
    """Field role enumeration."""
    DIMENSION = "DIMENSION"
    MEASURE = "MEASURE"


class Project(BaseModel):
    """Tableau project model."""
    id: str
    name: str


class Datasource(BaseModel):
    """Tableau datasource model."""
    id: str
    name: str
    description: Optional[str] = None
    project: Optional[Project] = None


class TableauField(BaseModel):
    """Tableau field model."""
    name: str
    dataType: FieldDataType = PydanticField(alias="dataType")
    columnClass: Optional[str] = PydanticField(default=None, alias="columnClass")
    defaultAggregation: Optional[str] = PydanticField(default=None, alias="defaultAggregation")
    role: Optional[FieldRole] = None
    description: Optional[str] = None
    
    model_config = {"populate_by_name": True}


class DatasourceMetadata(BaseModel):
    """Datasource metadata including fields and parameters."""
    datasource_id: str
    fields: List[TableauField]
    parameters: List[Dict[str, Any]] = []
    
    @property
    def dimensions(self) -> List[TableauField]:
        """Get dimension fields."""
        return [f for f in self.fields if f.role == FieldRole.DIMENSION]
    
    @property
    def measures(self) -> List[TableauField]:
        """Get measure fields."""
        return [f for f in self.fields if f.role == FieldRole.MEASURE]
    
    def get_field_by_name(self, name: str) -> Optional[TableauField]:
        """Find field by name (case-insensitive)."""
        name_lower = name.lower()
        for field in self.fields:
            if field.name.lower() == name_lower:
                return field
        return None
    
    def to_schema_description(self) -> str:
        """Generate human-readable schema description."""
        lines = ["Available fields:"]
        
        if self.dimensions:
            lines.append("\nDimensions:")
            for f in self.dimensions:
                desc = f" - {f.description}" if f.description else ""
                lines.append(f"  - {f.name} ({f.dataType.value}){desc}")
        
        if self.measures:
            lines.append("\nMeasures:")
            for f in self.measures:
                agg = f" [default: {f.defaultAggregation}]" if f.defaultAggregation else ""
                desc = f" - {f.description}" if f.description else ""
                lines.append(f"  - {f.name} ({f.dataType.value}){agg}{desc}")
        
        if not self.dimensions and not self.measures:
            lines.append("\n  (No fields with role information)")
            for f in self.fields[:20]:  # Limit to first 20
                lines.append(f"  - {f.name} ({f.dataType.value})")
        
        return "\n".join(lines)


class QueryResult(BaseModel):
    """Query execution result."""
    data: List[Dict[str, Any]]
    row_count: int = 0
    query: Optional[Dict[str, Any]] = None
    execution_time_ms: Optional[float] = None
    
    def model_post_init(self, __context: Any) -> None:
        """Initialize row_count from data length if not provided."""
        if not self.row_count and self.data:
            object.__setattr__(self, 'row_count', len(self.data))
    
    def to_markdown_table(self, max_rows: int = 20) -> str:
        """Convert to markdown table format."""
        if not self.data:
            return "No data returned."
        
        headers = list(self.data[0].keys())
        lines = []
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
        
        for row in self.data[:max_rows]:
            values = [str(row.get(h, "")).replace("|", "\\|") for h in headers]
            lines.append("| " + " | ".join(values) + " |")
        
        if len(self.data) > max_rows:
            lines.append(f"\n*Showing {max_rows} of {len(self.data)} rows*")
        
        return "\n".join(lines)


class Workbook(BaseModel):
    """Tableau workbook model."""
    id: str
    name: str
    webpageUrl: Optional[str] = PydanticField(default=None, alias="webpageUrl")
    project: Optional[Project] = None
    
    model_config = {"populate_by_name": True}


class View(BaseModel):
    """Tableau view model."""
    id: str
    name: str
    workbook: Optional[Dict[str, str]] = None
