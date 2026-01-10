# =============================================================================
# LangGraph Agent Workflow
# =============================================================================
"""Main LangGraph workflow for Tableau AI Agent."""

import json
import re
from typing import Any, Dict, List, Optional, TypedDict

import pandas as pd

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

from src.core.config import settings
from src.core.exceptions import ValidationError
from src.core.logging import get_logger
from src.mcp.client import MCPClient
from src.mcp.models import Datasource, DatasourceMetadata, QueryResult

logger = get_logger(__name__)


# =============================================================================
# State Definition
# =============================================================================

class AgentState(TypedDict, total=False):
    """State for the agent graph."""
    question: str
    selected_datasource: Optional[Datasource]
    datasources: List[Datasource]
    metadata: Optional[DatasourceMetadata]
    plan: Dict[str, Any]
    query: Dict[str, Any]
    query_result: Optional[QueryResult]
    analysis: str
    visualization: Dict[str, Any]
    status: str
    error: Optional[str]


# =============================================================================
# Prompts
# =============================================================================

SYSTEM_PROMPT = """You are an expert Tableau data analyst AI assistant. Your role is to help users 
analyze data from Tableau datasources by understanding their questions, constructing appropriate 
VizQL queries, and providing insightful analysis of the results.

## VizQL Query Structure:
{
  "fields": [
    {"fieldCaption": "DimensionName"},
    {"fieldCaption": "MeasureName", "function": "SUM", "sortDirection": "DESC"}
  ],
  "filters": [
    {"field": {"fieldCaption": "Field"}, "filterType": "SET", "values": ["value1"]}
  ]
}

Be precise, analytical, and helpful."""


QUERY_BUILDER_PROMPT = """Build a VizQL query to answer this question: {question}

Available fields in the datasource:
{fields}

CRITICAL RULES - Follow exactly:
1. Use EXACT field names from the list above (case-sensitive)
2. For measures (numeric values), ALWAYS include "function": "SUM" (or "AVG", "COUNT", "MIN", "MAX" as appropriate)
3. For dimensions (categories, dates), do NOT include a function
4. The query aggregates data: measures are summed/averaged BY dimensions
5. Include "sortDirection": "DESC" or "ASC" inside the measure field if ordering is needed
6. ONLY use "fields" key - do NOT use "filters", "sort", or "limit" (filtering will be done after query)
7. For time-based questions (last year, this month, etc.), include the date field and filter in Python later

Example for "sales by year":
{{
  "fields": [
    {{"fieldCaption": "Order Date"}},
    {{"fieldCaption": "Sales", "function": "SUM", "sortDirection": "DESC"}}
  ]
}}

Example for "total profit" (just get all profit data):
{{
  "fields": [
    {{"fieldCaption": "Profit", "function": "SUM"}}
  ]
}}

Return ONLY a valid JSON object with "fields" array. No filters, no explanation, no markdown."""


ANALYZER_PROMPT = """Analyze these query results to answer: {question}

Data:
{results}

Provide a comprehensive analysis including:
1. **Direct Answer**: Clearly answer the original question
2. **Key Findings**: Highlight the most important patterns or values
3. **Insights**: Provide actionable business insights based on the data
4. **Context**: Note any limitations or considerations

Be concise but thorough."""


# =============================================================================
# Agent Class
# =============================================================================

class TableauAgent:
    """LangGraph-based agent for Tableau data analysis."""
    
    def __init__(self, mcp_client: Optional[MCPClient] = None):
        """
        Initialize the agent.
        
        Args:
            mcp_client: Optional MCP client instance
        """
        self.mcp_client = mcp_client or MCPClient()
        self._llm: Optional[ChatOpenAI] = None
        self._compiled_graph = None
    
    @property
    def llm(self) -> ChatOpenAI:
        """Get LLM instance (lazy initialization)."""
        if self._llm is None:
            if not settings.openai_configured:
                raise ValidationError("OpenAI API key not configured")
            
            self._llm = ChatOpenAI(
                model=settings.openai_model,
                temperature=settings.openai_temperature,
                api_key=settings.openai_api_key,
                max_retries=settings.openai_max_retries,
            )
        return self._llm
    
    @property
    def llm_with_calculator(self) -> ChatOpenAI:
        """Get LLM with calculator tools bound for accurate math."""
        from src.agent.tools import CALCULATOR_TOOLS
        return self.llm.bind_tools(CALCULATOR_TOOLS)
    
    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow."""
        graph = StateGraph(AgentState)
        
        # Add nodes
        graph.add_node("discover", self._discover_datasources)
        graph.add_node("plan", self._plan_query)
        graph.add_node("execute", self._execute_query)
        graph.add_node("analyze", self._analyze_results)
        
        # Define edges
        graph.set_entry_point("discover")
        graph.add_edge("discover", "plan")
        graph.add_conditional_edges(
            "plan",
            self._should_execute,
        )
        graph.add_conditional_edges(
            "execute",
            self._should_analyze,
        )
        graph.add_edge("analyze", END)
        
        return graph
    
    def _should_execute(self, state: AgentState) -> str:
        """Determine if we should execute or end."""
        if state.get("error"):
            return END
        return "execute"
    
    def _should_analyze(self, state: AgentState) -> str:
        """Determine if we should analyze or end."""
        if state.get("error"):
            return END
        return "analyze"
    
    @property
    def graph(self):
        """Get compiled graph."""
        if self._compiled_graph is None:
            self._compiled_graph = self._build_graph().compile()
        return self._compiled_graph
    
    async def _discover_datasources(self, state: AgentState) -> AgentState:
        """Discover available datasources."""
        logger.info("Discovering datasources")
        
        try:
            datasources = await self.mcp_client.list_datasources()
            state["datasources"] = datasources
            state["status"] = "discovered"
            
            logger.info("Discovered datasources", count=len(datasources))
            
            # Auto-select if only one
            if len(datasources) == 1:
                state["selected_datasource"] = datasources[0]
                metadata = await self.mcp_client.get_datasource_metadata(datasources[0].id)
                state["metadata"] = metadata
                logger.info("Auto-selected datasource", name=datasources[0].name)
            elif len(datasources) == 0:
                state["error"] = "No datasources available. Check Tableau connection."
                state["status"] = "error"
            
        except Exception as e:
            logger.error("Discovery failed", error=str(e))
            state["error"] = f"Failed to discover datasources: {e}"
            state["status"] = "error"
        
        return state
    
    async def _plan_query(self, state: AgentState) -> AgentState:
        """Plan and select datasource."""
        question = state.get("question", "")
        datasources = state.get("datasources", [])
        
        logger.info("Planning query", question=question[:50])
        
        # Select datasource if not selected
        if not state.get("selected_datasource") and datasources:
            if len(datasources) == 1:
                state["selected_datasource"] = datasources[0]
            else:
                # Use LLM to select best datasource
                ds_list = "\n".join([
                    f"- {ds.name}: {ds.description or 'No description'}" 
                    for ds in datasources
                ])
                
                try:
                    response = await self.llm.ainvoke([
                        SystemMessage(content="Select the best datasource for the question. Return only the exact datasource name."),
                        HumanMessage(content=f"Question: {question}\n\nAvailable Datasources:\n{ds_list}"),
                    ])
                    
                    selected_name = response.content.strip().lower()
                    for ds in datasources:
                        if ds.name.lower() in selected_name or selected_name in ds.name.lower():
                            state["selected_datasource"] = ds
                            break
                    
                    if not state.get("selected_datasource"):
                        # Default to first datasource
                        state["selected_datasource"] = datasources[0]
                        logger.warning("Could not match datasource, using first")
                        
                except Exception as e:
                    logger.error("Datasource selection failed", error=str(e))
                    state["selected_datasource"] = datasources[0]
        
        # Get metadata
        if state.get("selected_datasource") and not state.get("metadata"):
            try:
                metadata = await self.mcp_client.get_datasource_metadata(
                    state["selected_datasource"].id
                )
                state["metadata"] = metadata
                logger.info(
                    "Got metadata", 
                    datasource=state["selected_datasource"].name,
                    fields=len(metadata.fields)
                )
            except Exception as e:
                logger.error("Failed to get metadata", error=str(e))
                state["error"] = f"Failed to get datasource schema: {e}"
                return state
        
        state["plan"] = {
            "datasource_id": state["selected_datasource"].id if state.get("selected_datasource") else None,
            "datasource_name": state["selected_datasource"].name if state.get("selected_datasource") else None,
        }
        state["status"] = "planned"
        
        return state
    
    async def _execute_query(self, state: AgentState) -> AgentState:
        """Build and execute the VizQL query."""
        question = state.get("question", "")
        metadata = state.get("metadata")
        
        logger.info("Executing query")
        
        if not metadata:
            state["error"] = "No datasource metadata available"
            return state
        
        if not metadata.fields:
            state["error"] = "Datasource has no queryable fields"
            return state
        
        # Build query using LLM
        prompt = QUERY_BUILDER_PROMPT.format(
            question=question,
            fields=metadata.to_schema_description(),
        )
        
        try:
            response = await self.llm.ainvoke([
                SystemMessage(content="You are a VizQL query builder. Return ONLY valid JSON, no explanation or markdown."),
                HumanMessage(content=prompt),
            ])
            
            # Parse query
            query = self._extract_json(response.content)
            
            if not query:
                logger.error("Failed to parse query", response=response.content[:200])
                state["error"] = "Failed to generate valid query"
                return state
            
            # Validate query structure
            if "fields" not in query or not query["fields"]:
                state["error"] = "Generated query is missing fields"
                return state
            
            state["query"] = query
            logger.info(
                "Generated VizQL query",
                fields=len(query.get("fields", [])),
                query=query,  # Log the full query for debugging
            )
            
        except Exception as e:
            logger.error("Query generation failed", error=str(e))
            state["error"] = f"Failed to generate query: {e}"
            return state
        
        # Execute query
        try:
            result = await self.mcp_client.query_datasource(
                datasource_id=state["selected_datasource"].id,
                query=query,
            )
            state["query_result"] = result
            state["status"] = "executed"
            logger.info("Query executed", rows=result.row_count)
            
        except Exception as e:
            logger.error("Query execution failed", error=str(e))
            state["error"] = f"Query execution failed: {e}"
        
        return state
    
    async def _analyze_results(self, state: AgentState) -> AgentState:
        """Analyze query results and generate insights."""
        question = state.get("question", "")
        result = state.get("query_result")
        
        logger.info("Analyzing results")
        
        if not result or not result.data:
            state["analysis"] = "The query returned no data. This could mean:\n- No records match the criteria\n- The datasource is empty\n- The query needs adjustment"
            state["status"] = "complete"
            return state
        
        # NOTE: Keep ALL data in result for display and visualization
        # Only prepare a summary/sample for LLM analysis
        import pandas as pd
        
        try:
            df = pd.DataFrame(result.data)
            total_rows = len(df)
            
            # Prepare data for LLM (aggregated or sampled)
            # This does NOT modify the actual result.data
            llm_df = self._prepare_data_for_llm(df.copy(), question)
            
            # Convert to markdown for LLM
            MAX_ROWS_FOR_LLM = 50
            is_truncated = len(llm_df) > MAX_ROWS_FOR_LLM or len(llm_df) < total_rows
            
            if len(llm_df) > MAX_ROWS_FOR_LLM:
                summary_text = llm_df.head(MAX_ROWS_FOR_LLM).to_markdown(index=False)
                summary_text += f"\n\n⚠️ **Note**: Showing {MAX_ROWS_FOR_LLM} of {len(llm_df)} aggregated rows"
            else:
                summary_text = llm_df.to_markdown(index=False)
            
            # Add data context
            if total_rows != len(llm_df):
                summary_text += f"\n\n📊 **Data Context**: Original query returned {total_rows:,} rows, aggregated to {len(llm_df)} rows for analysis."
            
            # Add summary statistics (calculated from FULL data, not sample)
            numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
            if numeric_cols:
                stats_text = "\n\n**Summary Statistics (from complete dataset):**\n"
                for col in numeric_cols[:3]:
                    stats_text += f"- {col}: Total = {df[col].sum():,.2f}, Avg = {df[col].mean():,.2f}, Min = {df[col].min():,.2f}, Max = {df[col].max():,.2f}\n"
                summary_text += stats_text
            
            analysis_data = summary_text
            
        except Exception as e:
            logger.warning("Pre-aggregation failed, using raw sample", error=str(e))
            analysis_data = result.to_markdown_table(max_rows=30)
            analysis_data += f"\n\n⚠️ Note: Showing sample of {min(30, result.row_count)} rows from {result.row_count} total rows."
        
        # Generate analysis with prepared data
        try:
            from src.agent.tools import calculate, calculate_percentage, calculate_growth
            
            prompt = ANALYZER_PROMPT.format(
                question=question,
                results=analysis_data,
            )
            
            system_msg = """You are a senior data analyst. Important notes:
1. The data shown may be aggregated or sampled from a larger dataset
2. Summary statistics shown are from the COMPLETE dataset - use these for totals
3. If you need to perform ANY calculations (percentages, growth rates, ratios, etc.), 
   use the calculator tools provided - do NOT calculate in your head
4. If data is truncated, acknowledge this in your analysis
5. Provide clear, actionable insights based on the patterns shown

Available calculator tools:
- calculate("expression"): For any math like "1500000 + 2500000" or "(45000 / 12) * 100"
- calculate_percentage(value, total): Get what % value is of total
- calculate_growth(old_value, new_value): Get growth rate between two values"""
            
            # Use LLM with calculator tools
            messages = [
                SystemMessage(content=system_msg),
                HumanMessage(content=prompt),
            ]
            
            # First call - may include tool calls
            response = await self.llm_with_calculator.ainvoke(messages)
            
            # Handle tool calls if any
            if hasattr(response, 'tool_calls') and response.tool_calls:
                from langchain_core.messages import AIMessage, ToolMessage
                
                # Execute each tool call
                tool_results = []
                for tool_call in response.tool_calls:
                    tool_name = tool_call['name']
                    tool_args = tool_call['args']
                    
                    logger.info(f"Executing calculator tool", tool=tool_name, args=tool_args)
                    
                    # Execute the tool
                    if tool_name == 'calculate':
                        result_val = calculate.invoke(tool_args['expression'])
                    elif tool_name == 'calculate_percentage':
                        result_val = calculate_percentage.invoke(tool_args)
                    elif tool_name == 'calculate_growth':
                        result_val = calculate_growth.invoke(tool_args)
                    else:
                        result_val = f"Unknown tool: {tool_name}"
                    
                    tool_results.append(ToolMessage(
                        content=str(result_val),
                        tool_call_id=tool_call['id']
                    ))
                
                # Add tool results and get final response
                messages.append(response)
                messages.extend(tool_results)
                
                final_response = await self.llm.ainvoke(messages)
                state["analysis"] = final_response.content
            else:
                # No tool calls, use direct response
                state["analysis"] = response.content
            
        except Exception as e:
            logger.error("Analysis failed", error=str(e))
            state["analysis"] = f"Analysis generation failed: {e}\n\nRaw data returned: {result.row_count} rows."
        
        # Visualization uses FULL data (result.data is unchanged)
        state["visualization"] = self._recommend_visualization(result)
        state["status"] = "complete"
        
        return state
    
    def _prepare_data_for_llm(self, df: pd.DataFrame, question: str) -> pd.DataFrame:
        """
        Prepare data specifically for LLM analysis.
        This may aggregate or sample data, but does NOT affect the display data.
        """
        return self._pre_aggregate_data(df, question)
    
    def _pre_aggregate_data(self, df: pd.DataFrame, question: str) -> pd.DataFrame:
        """Pre-aggregate data based on the question to avoid LLM calculation errors."""
        import pandas as pd
        import re
        from datetime import datetime, timedelta
        
        question_lower = question.lower()
        original_row_count = len(df)
        
        # Detect date columns
        date_cols = []
        for col in df.columns:
            if any(keyword in col.lower() for keyword in ['date', 'time', 'year', 'month', 'day']):
                try:
                    df[col] = pd.to_datetime(df[col])
                    date_cols.append(col)
                except:
                    pass
        
        # Detect numeric columns (likely measures)
        numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
        
        # Detect string columns (likely dimensions)
        string_cols = df.select_dtypes(include=['object']).columns.tolist()
        string_cols = [c for c in string_cols if c not in date_cols]
        
        # ========================================
        # 0. Apply date-based filtering (done in Python since MCP filters are complex)
        # ========================================
        if date_cols:
            date_col = date_cols[0]
            now = datetime.now()
            current_year = now.year
            
            # Filter for "last year" / "previous year"
            if any(phrase in question_lower for phrase in ['last year', 'previous year']):
                df = df[df[date_col].dt.year == (current_year - 1)]
                logger.info(f"Filtered to last year ({current_year - 1})", rows_after=len(df))
            
            # Filter for "this year" / "current year"
            elif any(phrase in question_lower for phrase in ['this year', 'current year']):
                df = df[df[date_col].dt.year == current_year]
                logger.info(f"Filtered to this year ({current_year})", rows_after=len(df))
            
            # Filter for "last month"
            elif 'last month' in question_lower:
                last_month = now.replace(day=1) - timedelta(days=1)
                df = df[(df[date_col].dt.year == last_month.year) & 
                        (df[date_col].dt.month == last_month.month)]
                logger.info(f"Filtered to last month", rows_after=len(df))
            
            # Filter for "this month"
            elif 'this month' in question_lower:
                df = df[(df[date_col].dt.year == now.year) & 
                        (df[date_col].dt.month == now.month)]
                logger.info(f"Filtered to this month", rows_after=len(df))
            
            # Filter for specific year mentioned (e.g., "in 2025", "for 2024")
            year_match = re.search(r'\b(20\d{2})\b', question_lower)
            if year_match and not any(phrase in question_lower for phrase in 
                ['last year', 'this year', 'previous year', 'current year', 'by year']):
                target_year = int(year_match.group(1))
                df = df[df[date_col].dt.year == target_year]
                logger.info(f"Filtered to year {target_year}", rows_after=len(df))
        
        # ========================================
        # 1. Handle "top N" / "bottom N" requests
        # ========================================
        top_n_match = re.search(r'\b(top|bottom|first|last)\s*(\d+)\b', question_lower)
        if top_n_match:
            direction = top_n_match.group(1)
            n = int(top_n_match.group(2))
            
            if numeric_cols:
                sort_col = numeric_cols[0]
                ascending = direction in ['bottom', 'last']
                
                # If there are duplicates in the dimension, aggregate first
                if string_cols and df[string_cols[0]].duplicated().any():
                    agg_dict = {col: 'sum' for col in numeric_cols}
                    df = df.groupby(string_cols[0]).agg(agg_dict).reset_index()
                
                result = df.sort_values(sort_col, ascending=ascending).head(n)
                logger.info(f"Extracted {direction} {n}", rows=len(result))
                return result
        
        # ========================================
        # 2. Date-based aggregations
        # ========================================
        if date_cols and numeric_cols:
            date_col = date_cols[0]
            
            # Aggregate by year
            if any(word in question_lower for word in ['by year', 'yearly', 'annual', 'per year', 'each year']):
                df['Year'] = df[date_col].dt.year
                agg_dict = {col: 'sum' for col in numeric_cols}
                result = df.groupby('Year').agg(agg_dict).reset_index()
                result = result.sort_values('Year')
                logger.info("Pre-aggregated by year", rows=len(result))
                return result
            
            # Aggregate by month
            if any(word in question_lower for word in ['by month', 'monthly', 'per month', 'each month']):
                df['Month'] = df[date_col].dt.to_period('M').astype(str)
                agg_dict = {col: 'sum' for col in numeric_cols}
                result = df.groupby('Month').agg(agg_dict).reset_index()
                result = result.sort_values('Month')
                logger.info("Pre-aggregated by month", rows=len(result))
                return result
            
            # Aggregate by quarter
            if any(word in question_lower for word in ['by quarter', 'quarterly', 'per quarter', 'each quarter']):
                df['Quarter'] = df[date_col].dt.to_period('Q').astype(str)
                agg_dict = {col: 'sum' for col in numeric_cols}
                result = df.groupby('Quarter').agg(agg_dict).reset_index()
                result = result.sort_values('Quarter')
                logger.info("Pre-aggregated by quarter", rows=len(result))
                return result
            
            # Trends - aggregate by date
            if any(word in question_lower for word in ['trend', 'over time', 'time series']):
                df['Date'] = df[date_col].dt.date
                agg_dict = {col: 'sum' for col in numeric_cols}
                result = df.groupby('Date').agg(agg_dict).reset_index()
                result = result.sort_values('Date')
                logger.info("Pre-aggregated by date", rows=len(result))
                return result
        
        # ========================================
        # 3. Dimension-based aggregation (by category, product, customer, etc.)
        # ========================================
        for keyword in ['by category', 'by product', 'by customer', 'by region', 'by segment', 'by state', 'by city']:
            if keyword in question_lower:
                dimension_name = keyword.replace('by ', '')
                # Find matching column
                for col in string_cols:
                    if dimension_name in col.lower():
                        if numeric_cols:
                            agg_dict = {c: 'sum' for c in numeric_cols}
                            result = df.groupby(col).agg(agg_dict).reset_index()
                            result = result.sort_values(numeric_cols[0], ascending=False)
                            logger.info(f"Pre-aggregated by {col}", rows=len(result))
                            return result
        
        # ========================================
        # 4. Handle large datasets (>50 rows) - Smart summarization
        # ========================================
        MAX_ROWS_FOR_LLM = 50
        
        if len(df) > MAX_ROWS_FOR_LLM:
            logger.info(f"Large dataset detected ({len(df)} rows), applying smart summarization")
            
            # Option A: If we have dimensions, aggregate by the first one
            if string_cols and numeric_cols:
                agg_dict = {col: 'sum' for col in numeric_cols}
                result = df.groupby(string_cols[0]).agg(agg_dict).reset_index()
                result = result.sort_values(numeric_cols[0], ascending=False).head(MAX_ROWS_FOR_LLM)
                logger.info(f"Aggregated by {string_cols[0]}", original=original_row_count, final=len(result))
                return result
            
            # Option B: If only numeric data, return statistical summary
            if numeric_cols and not string_cols:
                # Create a summary instead of raw data
                summary_data = []
                for col in numeric_cols:
                    summary_data.append({
                        'Metric': col,
                        'Total': df[col].sum(),
                        'Average': df[col].mean(),
                        'Min': df[col].min(),
                        'Max': df[col].max(),
                        'Count': len(df)
                    })
                result = pd.DataFrame(summary_data)
                logger.info("Created statistical summary", metrics=len(numeric_cols))
                return result
            
            # Option C: Just take first N rows with a warning
            result = df.head(MAX_ROWS_FOR_LLM)
            logger.warning(f"Truncated to {MAX_ROWS_FOR_LLM} rows", original=original_row_count)
            return result
        
        return df
    
    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract JSON from LLM response text."""
        # Try direct parse
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass
        
        # Try code blocks
        code_block_pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
        matches = re.findall(code_block_pattern, text)
        for match in matches:
            try:
                return json.loads(match.strip())
            except json.JSONDecodeError:
                continue
        
        # Try to find JSON object
        json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
        matches = re.findall(json_pattern, text, re.DOTALL)
        for match in matches:
            try:
                return json.loads(match)
            except json.JSONDecodeError:
                continue
        
        return None
    
    def _recommend_visualization(self, result: QueryResult) -> Dict[str, Any]:
        """Recommend visualization type based on data."""
        if not result.data:
            return {"chart_type": "none", "reason": "No data"}
        
        columns = list(result.data[0].keys())
        
        # Analyze column types
        numeric_cols = []
        string_cols = []
        date_cols = []
        
        sample = result.data[0]
        for col in columns:
            val = sample.get(col)
            if val is None:
                continue
            
            str_val = str(val)
            
            # Check for date patterns
            if any(pattern in col.lower() for pattern in ['date', 'time', 'year', 'month', 'day']):
                date_cols.append(col)
            elif str_val.replace('.', '').replace('-', '').isdigit():
                numeric_cols.append(col)
            else:
                string_cols.append(col)
        
        # Recommendation logic
        if date_cols and numeric_cols:
            return {
                "chart_type": "line",
                "x_axis": date_cols[0],
                "y_axis": numeric_cols[0],
                "reason": "Time series data detected"
            }
        elif string_cols and numeric_cols:
            if result.row_count <= 10:
                return {
                    "chart_type": "bar",
                    "x_axis": string_cols[0],
                    "y_axis": numeric_cols[0],
                    "reason": "Categorical comparison"
                }
            else:
                return {
                    "chart_type": "bar",
                    "x_axis": string_cols[0],
                    "y_axis": numeric_cols[0],
                    "reason": "Categorical data with many values"
                }
        elif len(numeric_cols) >= 2:
            return {
                "chart_type": "scatter",
                "x_axis": numeric_cols[0],
                "y_axis": numeric_cols[1],
                "reason": "Correlation analysis"
            }
        else:
            return {
                "chart_type": "table",
                "reason": "Data best displayed as table"
            }
    
    async def query(
        self,
        question: str,
        datasource_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Answer a question about Tableau data.
        
        Args:
            question: Natural language question
            datasource_id: Optional datasource ID to use
            
        Returns:
            Result dictionary with analysis and data
        """
        if not question or len(question.strip()) < 3:
            return {
                "success": False,
                "question": question,
                "error": "Question is too short",
            }
        
        initial_state: AgentState = {
            "question": question.strip(),
            "status": "started",
        }
        
        if datasource_id:
            initial_state["selected_datasource"] = Datasource(
                id=datasource_id,
                name=datasource_id,
            )
        
        try:
            final_state = await self.graph.ainvoke(initial_state)
            
            result_data = None
            if final_state.get("query_result"):
                qr = final_state["query_result"]
                result_data = {
                    "row_count": qr.row_count,
                    "data": qr.data[:100],  # Limit to 100 rows
                    "execution_time_ms": qr.execution_time_ms,
                }
            
            return {
                "success": final_state.get("status") == "complete" and not final_state.get("error"),
                "question": question,
                "datasource": {
                    "id": final_state.get("selected_datasource").id,
                    "name": final_state.get("selected_datasource").name,
                } if final_state.get("selected_datasource") else None,
                "analysis": final_state.get("analysis"),
                "query": final_state.get("query"),
                "results": result_data,
                "visualization": final_state.get("visualization"),
                "error": final_state.get("error"),
            }
            
        except Exception as e:
            logger.exception("Agent execution failed", error=str(e))
            return {
                "success": False,
                "question": question,
                "error": f"Agent execution failed: {e}",
            }
    
    async def close(self) -> None:
        """Close resources."""
        await self.mcp_client.close()


def create_agent(mcp_client: Optional[MCPClient] = None) -> TableauAgent:
    """Create a configured TableauAgent instance."""
    return TableauAgent(mcp_client=mcp_client)
