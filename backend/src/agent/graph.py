# =============================================================================
# LangGraph Agent Workflow
# =============================================================================
"""Main LangGraph workflow for Tableau AI Agent."""

import json
import re
from typing import Any, Dict, List, Optional, TypedDict

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

Important rules:
1. Use exact field names from the list above
2. For measures, include a "function" like "SUM", "AVG", "COUNT", "MIN", "MAX"
3. Add "sortDirection": "DESC" or "ASC" inside field definitions if ordering is needed
4. Only use fields that exist in the schema
5. Do NOT include "sort" or "limit" keys at the top level of the JSON

Return ONLY a valid JSON object with this structure:
{{
  "fields": [
    {{"fieldCaption": "ExactFieldName"}},
    {{"fieldCaption": "MeasureName", "function": "SUM"}}
  ]
}}"""


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
            logger.info("Generated query", fields=len(query.get("fields", [])))
            
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
        
        # Generate analysis
        try:
            prompt = ANALYZER_PROMPT.format(
                question=question,
                results=result.to_markdown_table(max_rows=50),
            )
            
            response = await self.llm.ainvoke([
                SystemMessage(content="You are a senior data analyst providing clear, actionable insights."),
                HumanMessage(content=prompt),
            ])
            
            state["analysis"] = response.content
            
        except Exception as e:
            logger.error("Analysis failed", error=str(e))
            state["analysis"] = f"Analysis generation failed: {e}\n\nRaw data returned: {result.row_count} rows."
        
        # Recommend visualization
        state["visualization"] = self._recommend_visualization(result)
        state["status"] = "complete"
        
        return state
    
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
