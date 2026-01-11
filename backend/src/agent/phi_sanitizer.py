# =============================================================================
# PHI/PII Sanitizer
# =============================================================================
"""
Defense-in-depth PHI/PII detection and masking.
Even if data is pre-masked, this provides an additional safety layer.
"""

import re
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass
import hashlib

from src.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class SanitizationResult:
    """Result of sanitization operation."""
    sanitized_data: Any
    phi_detected: bool
    phi_fields: List[str]
    phi_count: int


# =============================================================================
# PHI Detection Patterns
# =============================================================================

# Field name patterns that likely contain PHI
PHI_FIELD_PATTERNS = [
    # Patient identifiers
    r"(?i)(patient|pt|pat)[\s_-]*(id|identifier|number|num|no)",
    r"(?i)mrn|medical[\s_-]*record",
    r"(?i)ssn|social[\s_-]*security",
    r"(?i)member[\s_-]*(id|number)",
    r"(?i)account[\s_-]*(id|number|num)",
    
    # Names
    r"(?i)(patient|pt|pat|person)[\s_-]*(name|nm)",
    r"(?i)(first|last|middle|full)[\s_-]*(name|nm)",
    r"(?i)given[\s_-]*name",
    r"(?i)family[\s_-]*name",
    r"(?i)surname",
    
    # Contact information
    r"(?i)phone|telephone|mobile|cell",
    r"(?i)email|e[\s_-]*mail",
    r"(?i)address|addr|street|city|zip|postal",
    r"(?i)fax",
    
    # Dates (sensitive in healthcare context)
    r"(?i)(date[\s_-]*of[\s_-]*birth|dob|birth[\s_-]*date)",
    r"(?i)death[\s_-]*date",
    
    # Financial
    r"(?i)credit[\s_-]*card|cc[\s_-]*(num|number)",
    r"(?i)bank[\s_-]*account",
    r"(?i)insurance[\s_-]*(id|number|policy)",
    
    # Other identifiers
    r"(?i)driver[\s_-]*license",
    r"(?i)passport",
    r"(?i)npi|provider[\s_-]*id",
]

# Value patterns that indicate PHI
PHI_VALUE_PATTERNS = [
    # SSN format
    (r"\b\d{3}-\d{2}-\d{4}\b", "SSN"),
    (r"\b\d{9}\b", "POSSIBLE_SSN"),
    
    # Phone numbers
    (r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b", "PHONE"),
    (r"\b\(\d{3}\)\s*\d{3}[-.\s]?\d{4}\b", "PHONE"),
    
    # Email
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "EMAIL"),
    
    # Credit card (basic patterns)
    (r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b", "CREDIT_CARD"),
    
    # MRN patterns (common formats)
    (r"\bMRN\d{6,10}\b", "MRN"),
    (r"\b[A-Z]{2,3}\d{6,10}\b", "POSSIBLE_MRN"),
    
    # Date patterns (could be DOB)
    (r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", "DATE"),
    (r"\b\d{4}-\d{2}-\d{2}\b", "DATE"),
]


class PHISanitizer:
    """
    Sanitizes data to remove or mask PHI before sending to LLM.
    
    This is a defense-in-depth measure - even if upstream data is masked,
    this provides an additional safety layer.
    """
    
    def __init__(
        self,
        mask_format: str = "[MASKED_{type}]",
        hash_instead_of_mask: bool = False,
        additional_patterns: Optional[List[str]] = None,
        whitelist_fields: Optional[Set[str]] = None,
    ):
        """
        Initialize sanitizer.
        
        Args:
            mask_format: Format for masked values, {type} replaced with PHI type
            hash_instead_of_mask: If True, use hash instead of mask (preserves uniqueness)
            additional_patterns: Additional regex patterns to detect PHI field names
            whitelist_fields: Field names to never mask (e.g., known safe fields)
        """
        self.mask_format = mask_format
        self.hash_instead_of_mask = hash_instead_of_mask
        self.whitelist_fields = whitelist_fields or set()
        
        # Compile patterns
        self.field_patterns = [re.compile(p) for p in PHI_FIELD_PATTERNS]
        if additional_patterns:
            self.field_patterns.extend([re.compile(p) for p in additional_patterns])
        
        self.value_patterns = [(re.compile(p), t) for p, t in PHI_VALUE_PATTERNS]
    
    def is_phi_field(self, field_name: str) -> bool:
        """Check if a field name likely contains PHI."""
        if field_name.lower() in self.whitelist_fields:
            return False
        
        for pattern in self.field_patterns:
            if pattern.search(field_name):
                return True
        return False
    
    def detect_phi_in_value(self, value: Any) -> Optional[str]:
        """
        Detect PHI patterns in a value.
        
        Returns:
            PHI type if detected, None otherwise
        """
        if value is None:
            return None
        
        str_value = str(value)
        
        for pattern, phi_type in self.value_patterns:
            if pattern.search(str_value):
                return phi_type
        
        return None
    
    def mask_value(self, value: Any, phi_type: str = "DATA") -> str:
        """Mask a value, optionally using hash for uniqueness preservation."""
        if self.hash_instead_of_mask:
            # Use hash to preserve uniqueness while masking
            hash_val = hashlib.sha256(str(value).encode()).hexdigest()[:8]
            return f"[HASH_{phi_type}_{hash_val}]"
        else:
            return self.mask_format.format(type=phi_type)
    
    def sanitize_row(self, row: Dict[str, Any], phi_fields: Optional[Set[str]] = None) -> Dict[str, Any]:
        """
        Sanitize a single data row.
        
        Args:
            row: Data row as dictionary
            phi_fields: Pre-identified PHI fields (for efficiency)
            
        Returns:
            Sanitized row
        """
        if phi_fields is None:
            phi_fields = {k for k in row.keys() if self.is_phi_field(k)}
        
        sanitized = {}
        for key, value in row.items():
            if key in phi_fields:
                # Field is known PHI - mask it
                sanitized[key] = self.mask_value(value, "FIELD")
            else:
                # Check value for PHI patterns
                phi_type = self.detect_phi_in_value(value)
                if phi_type:
                    sanitized[key] = self.mask_value(value, phi_type)
                else:
                    sanitized[key] = value
        
        return sanitized
    
    def sanitize_data(self, data: List[Dict[str, Any]]) -> SanitizationResult:
        """
        Sanitize a list of data rows.
        
        Args:
            data: List of data rows
            
        Returns:
            SanitizationResult with sanitized data and detection stats
        """
        if not data:
            return SanitizationResult(
                sanitized_data=[],
                phi_detected=False,
                phi_fields=[],
                phi_count=0,
            )
        
        # Pre-identify PHI fields from first row
        first_row = data[0]
        phi_fields = {k for k in first_row.keys() if self.is_phi_field(k)}
        
        # Track detections
        phi_count = 0
        value_phi_detected = False
        
        sanitized_data = []
        for row in data:
            sanitized_row = {}
            for key, value in row.items():
                if key in phi_fields:
                    sanitized_row[key] = self.mask_value(value, "FIELD")
                    phi_count += 1
                else:
                    phi_type = self.detect_phi_in_value(value)
                    if phi_type:
                        sanitized_row[key] = self.mask_value(value, phi_type)
                        phi_count += 1
                        value_phi_detected = True
                    else:
                        sanitized_row[key] = value
            
            sanitized_data.append(sanitized_row)
        
        phi_detected = len(phi_fields) > 0 or value_phi_detected
        
        if phi_detected:
            logger.warning(
                "PHI detected and sanitized",
                phi_fields=list(phi_fields),
                phi_count=phi_count,
            )
        
        return SanitizationResult(
            sanitized_data=sanitized_data,
            phi_detected=phi_detected,
            phi_fields=list(phi_fields),
            phi_count=phi_count,
        )
    
    def sanitize_schema_description(self, schema_text: str) -> str:
        """
        Sanitize field names in schema description.
        
        This is a lighter check - just flags potentially sensitive fields.
        """
        lines = schema_text.split("\n")
        sanitized_lines = []
        
        for line in lines:
            # Check if line contains a PHI field name
            for pattern in self.field_patterns:
                if pattern.search(line):
                    # Add warning marker
                    if "[PHI]" not in line:
                        line = line.rstrip() + " [PHI - MASKED IN DATA]"
                    break
            sanitized_lines.append(line)
        
        return "\n".join(sanitized_lines)


# =============================================================================
# Convenience Functions
# =============================================================================

# Global sanitizer instance with default settings
_default_sanitizer = PHISanitizer()


def sanitize_for_llm(data: List[Dict[str, Any]]) -> SanitizationResult:
    """Sanitize data before sending to LLM (convenience function)."""
    return _default_sanitizer.sanitize_data(data)


def sanitize_schema(schema_text: str) -> str:
    """Sanitize schema description (convenience function)."""
    return _default_sanitizer.sanitize_schema_description(schema_text)


def is_phi_field(field_name: str) -> bool:
    """Check if field name likely contains PHI (convenience function)."""
    return _default_sanitizer.is_phi_field(field_name)
