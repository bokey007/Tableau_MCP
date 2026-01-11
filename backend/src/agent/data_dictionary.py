# =============================================================================
# Data Dictionary Support (Optional)
# =============================================================================
"""
Optional data dictionary integration for translating cryptic field names
to business-friendly terms.

This module is OPTIONAL - the system works without it, but provides
better LLM understanding when available.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict

from src.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class FieldDefinition:
    """Definition of a field from the data dictionary."""
    field_name: str                    # Technical field name (e.g., "PT_MRN")
    business_name: str                 # Human-readable name (e.g., "Patient MRN")
    description: Optional[str] = None  # Detailed description
    data_type: Optional[str] = None    # Expected data type
    example_values: Optional[List[str]] = None  # Example valid values
    is_phi: bool = False               # Whether field contains PHI
    category: Optional[str] = None     # Grouping category (e.g., "Demographics")
    formula: Optional[str] = None      # If calculated field, the formula
    
    def to_prompt_text(self) -> str:
        """Convert to text suitable for LLM prompt."""
        text = f"- **{self.field_name}** ({self.business_name})"
        
        if self.description:
            text += f": {self.description}"
        
        if self.example_values:
            examples = ", ".join(str(v) for v in self.example_values[:5])
            text += f" [Examples: {examples}]"
        
        if self.is_phi:
            text += " [PHI]"
        
        if self.formula:
            text += f" [Calculated: {self.formula}]"
        
        return text


class DataDictionary:
    """
    Optional data dictionary for field name translation and context.
    
    Can be loaded from:
    - JSON file
    - In-memory dict
    - Database (future)
    
    Usage:
        dd = DataDictionary.from_file("data_dictionary.json")
        friendly_name = dd.get_business_name("PT_MRN")  # "Patient MRN"
    """
    
    def __init__(self, fields: Optional[List[FieldDefinition]] = None):
        """Initialize with optional field definitions."""
        self._fields: Dict[str, FieldDefinition] = {}
        
        if fields:
            for field in fields:
                self._fields[field.field_name.lower()] = field
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DataDictionary":
        """
        Create from dictionary.
        
        Expected format:
        {
            "fields": [
                {
                    "field_name": "PT_MRN",
                    "business_name": "Patient MRN",
                    "description": "Medical Record Number",
                    "is_phi": true
                },
                ...
            ]
        }
        """
        fields = []
        for field_data in data.get("fields", []):
            fields.append(FieldDefinition(**field_data))
        return cls(fields)
    
    @classmethod
    def from_file(cls, path: str) -> "DataDictionary":
        """Load from JSON file."""
        file_path = Path(path)
        if not file_path.exists():
            logger.warning(f"Data dictionary file not found: {path}")
            return cls()
        
        try:
            with open(file_path) as f:
                data = json.load(f)
            logger.info(f"Loaded data dictionary from {path}")
            return cls.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to load data dictionary: {e}")
            return cls()
    
    @classmethod
    def from_csv(cls, path: str) -> "DataDictionary":
        """
        Load from CSV file.
        
        Expected columns: field_name, business_name, description, is_phi
        """
        import csv
        
        file_path = Path(path)
        if not file_path.exists():
            logger.warning(f"Data dictionary CSV not found: {path}")
            return cls()
        
        try:
            fields = []
            with open(file_path, newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Convert is_phi to boolean
                    is_phi = str(row.get("is_phi", "")).lower() in ("true", "yes", "1", "y")
                    
                    # Parse example_values if present
                    examples = None
                    if row.get("example_values"):
                        examples = [v.strip() for v in row["example_values"].split("|")]
                    
                    fields.append(FieldDefinition(
                        field_name=row.get("field_name", ""),
                        business_name=row.get("business_name", row.get("field_name", "")),
                        description=row.get("description"),
                        data_type=row.get("data_type"),
                        example_values=examples,
                        is_phi=is_phi,
                        category=row.get("category"),
                        formula=row.get("formula"),
                    ))
            
            logger.info(f"Loaded {len(fields)} fields from CSV")
            return cls(fields)
        except Exception as e:
            logger.error(f"Failed to load data dictionary CSV: {e}")
            return cls()
    
    def is_empty(self) -> bool:
        """Check if dictionary is empty (not loaded)."""
        return len(self._fields) == 0
    
    def get(self, field_name: str) -> Optional[FieldDefinition]:
        """Get field definition by name (case-insensitive)."""
        return self._fields.get(field_name.lower())
    
    def get_business_name(self, field_name: str) -> str:
        """Get business-friendly name for a field."""
        field = self.get(field_name)
        if field:
            return field.business_name
        return field_name  # Return original if not found
    
    def get_description(self, field_name: str) -> Optional[str]:
        """Get description for a field."""
        field = self.get(field_name)
        if field:
            return field.description
        return None
    
    def is_phi(self, field_name: str) -> bool:
        """Check if field is marked as PHI."""
        field = self.get(field_name)
        if field:
            return field.is_phi
        return False
    
    def get_phi_fields(self) -> List[str]:
        """Get list of all PHI field names."""
        return [f.field_name for f in self._fields.values() if f.is_phi]
    
    def enrich_schema(self, schema_text: str) -> str:
        """
        Enrich schema description with data dictionary information.
        
        Replaces technical field names with business names and adds descriptions.
        """
        if self.is_empty():
            return schema_text
        
        lines = schema_text.split("\n")
        enriched_lines = []
        
        for line in lines:
            enriched_line = line
            
            # Check each known field
            for field_def in self._fields.values():
                if field_def.field_name in line:
                    # Add business name and description
                    addition = f" → {field_def.business_name}"
                    if field_def.description:
                        addition += f": {field_def.description}"
                    
                    enriched_line = line.rstrip() + addition
                    break
            
            enriched_lines.append(enriched_line)
        
        return "\n".join(enriched_lines)
    
    def to_prompt_context(self) -> str:
        """Generate context text for LLM prompt."""
        if self.is_empty():
            return ""
        
        # Group by category if available
        categories: Dict[str, List[FieldDefinition]] = {}
        uncategorized: List[FieldDefinition] = []
        
        for field in self._fields.values():
            if field.category:
                if field.category not in categories:
                    categories[field.category] = []
                categories[field.category].append(field)
            else:
                uncategorized.append(field)
        
        lines = ["### Data Dictionary (Field Reference):"]
        
        for category, fields in sorted(categories.items()):
            lines.append(f"\n**{category}:**")
            for field in fields:
                lines.append(field.to_prompt_text())
        
        if uncategorized:
            lines.append("\n**Other Fields:**")
            for field in uncategorized:
                lines.append(field.to_prompt_text())
        
        return "\n".join(lines)
    
    def to_dict(self) -> Dict[str, Any]:
        """Export to dictionary format."""
        return {
            "fields": [asdict(f) for f in self._fields.values()]
        }
    
    def save(self, path: str) -> None:
        """Save to JSON file."""
        with open(path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)
        logger.info(f"Saved data dictionary to {path}")


# =============================================================================
# Global Instance (Optional Loading)
# =============================================================================

_data_dictionary: Optional[DataDictionary] = None


def get_data_dictionary() -> Optional[DataDictionary]:
    """Get the global data dictionary instance (None if not loaded)."""
    return _data_dictionary


def load_data_dictionary(path: str) -> DataDictionary:
    """Load and set the global data dictionary."""
    global _data_dictionary
    
    if path.endswith(".csv"):
        _data_dictionary = DataDictionary.from_csv(path)
    else:
        _data_dictionary = DataDictionary.from_file(path)
    
    return _data_dictionary


def set_data_dictionary(dd: DataDictionary) -> None:
    """Set the global data dictionary instance."""
    global _data_dictionary
    _data_dictionary = dd
