# =============================================================================
# Trust & Provenance Layer
# =============================================================================
"""
Production-grade trust layer for the Decision Support System.

Every data-driven response must be:
1. GROUNDED: Backed by actual data from Tableau (never hallucinated)
2. CITED: Source, row count, filters, and timestamp visible to user
3. SCORED: Confidence level so decision-makers know how much to trust it
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class SourceCitation:
    """Provenance record for a data-driven response."""
    datasource_name: str = ""
    row_count: int = 0
    query_time_ms: float = 0.0
    filters_applied: List[str] = field(default_factory=list)
    timestamp: str = ""
    query_executed: Optional[Dict[str, Any]] = None  # The actual VizQL query
    data_grounded: bool = False  # Was real data returned?

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S %Z").strip()


def build_citation_from_result(result: Dict[str, Any], filters: List[Dict] = None) -> SourceCitation:
    """
    Build a SourceCitation from a data_agent.execute_data_query() result.
    
    Args:
        result: The dict returned by TableauAgent.execute_data_query()
        filters: Optional list of applied filters
    """
    ds = result.get("datasource") or {}
    results_data = result.get("results") or {}
    
    filter_strs = []
    if filters:
        for f in filters:
            fld = f.get("field", "")
            val = f.get("value", "")
            if fld and val and str(val).lower() not in ("none", "null", "null - null"):
                filter_strs.append(f"{fld}='{val}'")

    return SourceCitation(
        datasource_name=ds.get("name", "Unknown"),
        row_count=results_data.get("row_count", 0),
        query_time_ms=results_data.get("execution_time_ms", 0.0),
        filters_applied=filter_strs,
        timestamp=datetime.now().strftime("%H:%M %Z").strip(),
        query_executed=result.get("query"),
        data_grounded=result.get("success", False) and results_data.get("row_count", 0) > 0,
    )


def format_citation(citation: SourceCitation) -> str:
    """
    Format a SourceCitation into a human-readable footer.
    
    Example output:
        📋 Source: Superstore (1,245 rows) | Filtered by: Region='West' | 19:31 IST | ⏱ 842ms
    """
    if not citation.data_grounded:
        return ""
    
    parts = [f"📋 **Source:** {citation.datasource_name}"]
    
    if citation.row_count > 0:
        parts.append(f"({citation.row_count:,} rows)")
    
    if citation.filters_applied:
        parts.append(f"| **Filtered by:** {', '.join(citation.filters_applied)}")
    
    if citation.timestamp:
        parts.append(f"| {citation.timestamp}")
    
    if citation.query_time_ms > 0:
        parts.append(f"| ⏱ {citation.query_time_ms:.0f}ms")
    
    return " ".join(parts)


def format_citations(citations: List[SourceCitation]) -> str:
    """Format multiple citations (for multi-step plans)."""
    grounded = [c for c in citations if c.data_grounded]
    if not grounded:
        return ""
    
    if len(grounded) == 1:
        return format_citation(grounded[0])
    
    lines = ["📋 **Data Sources:**"]
    for i, c in enumerate(grounded, 1):
        line = f"  {i}. {c.datasource_name}"
        if c.row_count > 0:
            line += f" ({c.row_count:,} rows)"
        if c.filters_applied:
            line += f" — Filtered by: {', '.join(c.filters_applied)}"
        lines.append(line)
    
    return "\n".join(lines)


# =============================================================================
# Anti-Hallucination Validation
# =============================================================================

def validate_data_response(analysis: str, result: Dict[str, Any]) -> str:
    """
    Validate that a data-driven response is grounded in actual data.
    If no real data was returned, prepend a clear warning.
    
    Args:
        analysis: The LLM-generated analysis text
        result: The result dict from execute_data_query
        
    Returns:
        Validated analysis (with warning prepended if ungrounded)
    """
    success = result.get("success", False)
    has_data = bool(result.get("results", {}).get("data"))
    error = result.get("error")
    
    if success and has_data:
        # Data is grounded — return as-is
        return analysis
    
    if error:
        # Query failed with an explicit error
        logger.warning("Data query failed, blocking hallucination", error=error)
        return (
            f"⚠️ **Data Unavailable:** I was unable to retrieve data from Tableau.\n\n"
            f"**Reason:** {error}\n\n"
            f"Please check the Tableau connection or try rephrasing your question. "
            f"I will not generate a response without verified data."
        )
    
    if not has_data:
        # Query succeeded but returned no rows
        logger.warning("Query returned no data")
        return (
            f"⚠️ **No Data Found:** The query executed successfully but returned 0 rows.\n\n"
            f"This may mean the applied filters are too restrictive, or the data "
            f"doesn't exist for the requested criteria.\n\n"
            f"💡 Try broadening your question or clearing some filters."
        )
    
    return analysis


# =============================================================================
# Confidence Scoring
# =============================================================================

def compute_confidence(result: Dict[str, Any]) -> tuple:
    """
    Compute a confidence level for a data-driven response.
    
    Returns:
        (level: str, reason: str)
        level is one of: "🟢 High", "🟡 Medium", "🔴 Low"
    """
    success = result.get("success", False)
    results_data = result.get("results") or {}
    row_count = results_data.get("row_count", 0)
    error = result.get("error")
    
    if not success or error:
        return ("🔴 Low", "Data query failed or returned an error")
    
    if row_count == 0:
        return ("🔴 Low", "No data rows returned")
    
    if row_count < 3:
        return ("🟡 Medium", f"Based on only {row_count} data point(s) — interpret with caution")
    
    if row_count < 10:
        return ("🟡 Medium", f"Based on {row_count} data points — reasonable sample")
    
    return ("🟢 High", f"Based on {row_count:,} data points from Tableau")
