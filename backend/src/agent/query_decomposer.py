"""
Query Decomposition Module

Handles complex questions that require multiple queries by:
1. Detecting if a question needs decomposition
2. Breaking it into sub-queries
3. Executing each sub-query
4. Merging results for final analysis
"""

import re
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class SubQuery:
    """Represents a decomposed sub-query."""
    id: str
    description: str
    question: str
    depends_on: List[str]  # IDs of queries this depends on
    merge_strategy: Optional[str] = None  # How to merge with previous results


class QueryDecomposer:
    """
    Decomposes complex questions into simpler sub-queries.
    
    Handles patterns like:
    - "Compare X to Y" -> Query X, Query Y, Compare
    - "X vs Y by Z" -> Query both with grouping
    - "Growth from period A to period B" -> Query A, Query B, Calculate growth
    - "Top N where condition AND other condition" -> Single query with multiple filters
    """
    
    # Patterns that indicate comparison queries
    COMPARISON_PATTERNS = [
        r'\bcompare\b.*\bto\b',
        r'\bvs\.?\b',
        r'\bversus\b',
        r'\bdifference\s+between\b',
        r'\bchange\s+from\b.*\bto\b',
    ]
    
    # Patterns that indicate time-based comparison
    TIME_COMPARISON_PATTERNS = [
        r'\b(this|current)\s+(year|month|quarter)\s+vs\.?\s+(last|previous)',
        r'\byear[\s-]over[\s-]year\b',
        r'\bmonth[\s-]over[\s-]month\b',
        r'\bgrowth\s+(from|between)\b',
        r'\btrend\s+over\b',
    ]
    
    # Patterns that indicate multi-dimensional analysis
    MULTI_DIM_PATTERNS = [
        r'\bby\s+(\w+)\s+and\s+(\w+)\b',
        r'\bfor\s+each\s+(\w+)\s+(by|per)\s+(\w+)\b',
        r'\bbreakdown\s+by\b',
    ]
    
    def __init__(self):
        self.compiled_comparison = [re.compile(p, re.IGNORECASE) for p in self.COMPARISON_PATTERNS]
        self.compiled_time = [re.compile(p, re.IGNORECASE) for p in self.TIME_COMPARISON_PATTERNS]
        self.compiled_multi = [re.compile(p, re.IGNORECASE) for p in self.MULTI_DIM_PATTERNS]
    
    def needs_decomposition(self, question: str) -> bool:
        """
        Check if a question needs to be decomposed into multiple queries.
        
        Most questions can be handled with a single VizQL query with filters.
        Decomposition is only needed for:
        - Time-based comparisons (this year vs last year)
        - Complex comparisons requiring separate aggregations
        """
        # Check for time-based comparison patterns
        for pattern in self.compiled_time:
            if pattern.search(question):
                return True
        
        # Check for explicit comparison patterns that require separate queries
        for pattern in self.compiled_comparison:
            if pattern.search(question):
                # Only decompose if it's a comparison that can't be done with filters
                # e.g., "Compare sales this year vs last year" needs two queries
                if any(p.search(question) for p in self.compiled_time):
                    return True
        
        return False
    
    def decompose(self, question: str) -> List[SubQuery]:
        """
        Decompose a complex question into sub-queries.
        
        Args:
            question: The original complex question
            
        Returns:
            List of SubQuery objects to execute
        """
        sub_queries = []
        
        # Check for year-over-year comparison
        yoy_pattern = re.compile(
            r'(compare|difference|growth|change).*'
            r'(this|current)\s+(year|month|quarter).*'
            r'(last|previous|prior)',
            re.IGNORECASE
        )
        
        if yoy_pattern.search(question):
            sub_queries = self._decompose_time_comparison(question)
        elif any(p.search(question) for p in self.compiled_comparison):
            sub_queries = self._decompose_comparison(question)
        else:
            # No decomposition needed - single query
            sub_queries = [SubQuery(
                id="q1",
                description="Main query",
                question=question,
                depends_on=[],
            )]
        
        logger.info(
            "Query decomposition result",
            original_question=question,
            num_sub_queries=len(sub_queries),
            sub_queries=[sq.description for sq in sub_queries]
        )
        
        return sub_queries
    
    def _decompose_time_comparison(self, question: str) -> List[SubQuery]:
        """Decompose time-based comparisons."""
        # Extract the base metric from the question
        metric_match = re.search(
            r'(sales|revenue|profit|orders|customers|quantity)',
            question,
            re.IGNORECASE
        )
        metric = metric_match.group(1) if metric_match else "value"
        
        # Extract dimensions
        dim_match = re.search(r'by\s+(\w+)', question, re.IGNORECASE)
        dimension = dim_match.group(1) if dim_match else None
        
        sub_queries = []
        
        # Query 1: Current period
        current_q = f"{metric}"
        if dimension:
            current_q += f" by {dimension}"
        current_q += " for current year"
        
        sub_queries.append(SubQuery(
            id="current_period",
            description=f"Current year {metric}",
            question=current_q,
            depends_on=[],
        ))
        
        # Query 2: Previous period
        previous_q = f"{metric}"
        if dimension:
            previous_q += f" by {dimension}"
        previous_q += " for last year"
        
        sub_queries.append(SubQuery(
            id="previous_period",
            description=f"Previous year {metric}",
            question=previous_q,
            depends_on=[],
        ))
        
        # Query 3: Merge and calculate
        sub_queries.append(SubQuery(
            id="comparison",
            description=f"Calculate year-over-year change",
            question=question,  # Original for context
            depends_on=["current_period", "previous_period"],
            merge_strategy="calculate_growth",
        ))
        
        return sub_queries
    
    def _decompose_comparison(self, question: str) -> List[SubQuery]:
        """Decompose general comparison queries."""
        # For most comparisons, a single query with SET filter works
        # Only decompose if truly needed
        return [SubQuery(
            id="q1",
            description="Comparison query with filters",
            question=question,
            depends_on=[],
        )]
    
    def merge_results(
        self,
        results: Dict[str, Dict[str, Any]],
        merge_strategy: str,
    ) -> Dict[str, Any]:
        """
        Merge results from multiple sub-queries.
        
        Args:
            results: Dict mapping query_id to query results
            merge_strategy: How to merge (calculate_growth, compare_side_by_side, etc.)
            
        Returns:
            Merged result data
        """
        if merge_strategy == "calculate_growth":
            return self._merge_growth(results)
        elif merge_strategy == "compare_side_by_side":
            return self._merge_side_by_side(results)
        else:
            # Default: return all results
            return {"sub_results": results}
    
    def _merge_growth(self, results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate growth between periods."""
        import pandas as pd
        
        current = results.get("current_period", {}).get("data", [])
        previous = results.get("previous_period", {}).get("data", [])
        
        if not current or not previous:
            return {"error": "Missing data for growth calculation"}
        
        df_current = pd.DataFrame(current)
        df_previous = pd.DataFrame(previous)
        
        # Find common columns
        common_cols = list(set(df_current.columns) & set(df_previous.columns))
        dimension_cols = [c for c in common_cols if not any(
            agg in c for agg in ['SUM', 'AVG', 'COUNT', 'MIN', 'MAX']
        )]
        metric_cols = [c for c in common_cols if c not in dimension_cols]
        
        if dimension_cols:
            # Merge on dimensions
            merged = df_current.merge(
                df_previous,
                on=dimension_cols,
                suffixes=('_current', '_previous'),
                how='outer'
            )
        else:
            # Just combine as single row comparison
            merged = pd.concat([
                df_current.add_suffix('_current'),
                df_previous.add_suffix('_previous')
            ], axis=1)
        
        # Calculate growth for numeric columns
        for col in metric_cols:
            if f"{col}_current" in merged.columns and f"{col}_previous" in merged.columns:
                merged[f"{col}_growth"] = (
                    (merged[f"{col}_current"] - merged[f"{col}_previous"]) /
                    merged[f"{col}_previous"].replace(0, float('nan'))
                ) * 100
        
        return {
            "data": merged.to_dict(orient="records"),
            "row_count": len(merged),
            "merge_type": "growth_calculation"
        }
    
    def _merge_side_by_side(self, results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Merge results side by side for comparison."""
        import pandas as pd
        
        all_dfs = []
        for query_id, result in results.items():
            if "data" in result:
                df = pd.DataFrame(result["data"])
                df["_source"] = query_id
                all_dfs.append(df)
        
        if not all_dfs:
            return {"error": "No data to merge"}
        
        merged = pd.concat(all_dfs, ignore_index=True)
        
        return {
            "data": merged.to_dict(orient="records"),
            "row_count": len(merged),
            "merge_type": "side_by_side"
        }


# Singleton instance
_decomposer: Optional[QueryDecomposer] = None


def get_query_decomposer() -> QueryDecomposer:
    """Get or create the query decomposer instance."""
    global _decomposer
    if _decomposer is None:
        _decomposer = QueryDecomposer()
    return _decomposer
