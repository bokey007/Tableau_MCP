# =============================================================================
# LangGraph Agent Workflow
# =============================================================================
"""Main LangGraph workflow for Tableau AI Agent."""

import asyncio
import json
import re
import time
import uuid
from typing import Any, Dict, List, Optional, TypedDict, Annotated
from operator import add

import pandas as pd

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, BaseMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.checkpoint.memory import MemorySaver

from src.core.config import settings
from src.core.exceptions import ValidationError
from src.core.logging import get_logger
from src.mcp.client import MCPClient
from src.mcp.models import Datasource, DatasourceMetadata, QueryResult

# Enterprise features
from src.agent.phi_sanitizer import PHISanitizer, sanitize_for_llm
from src.agent.data_dictionary import DataDictionary, get_data_dictionary
from src.agent.query_decomposer import QueryDecomposer, get_query_decomposer

logger = get_logger(__name__)


# =============================================================================
# State Definition
# =============================================================================

class AgentState(TypedDict, total=False):
    """State for the agent graph with LangGraph native memory."""
    # Conversation messages (LangGraph native - automatically persisted)
    messages: Annotated[List[BaseMessage], add]  # Appends messages automatically
    
    # Intent classification
    intent: str  # "data_query" or "chat"
    
    # Core query fields
    question: str
    selected_datasource: Optional[Datasource]
    datasources: List[Datasource]
    metadata: Optional[DatasourceMetadata]
    metadata_id: Optional[str]  # helper to track which datasource the metadata is for
    sample_data: List[Dict[str, Any]]  # sample rows for LLM context (PHI sanitized)
    plan: Dict[str, Any]
    query: Dict[str, Any]  # legacy/internal
    vizql_query: Dict[str, Any]  # strict vizql
    query_result: Optional[QueryResult]
    analyzed_data: Dict[str, Any]  # what the LLM actually analyzed (for validation)
    analysis: str
    visualization: Dict[str, Any]
    status: str
    error: Optional[str]
    # Review workflow
    critique: Optional[str]
    retry_count: int


# =============================================================================
# Prompts
# =============================================================================

SYSTEM_PROMPT = """You are an expert Tableau data analyst AI assistant. Your role is to help users 
analyze data from Tableau datasources by understanding their questions, constructing appropriate 
VizQL queries, and providing insightful analysis of the results.

## Conversation Support:
- You maintain context across multiple turns in a conversation
- For follow-up questions like "what about by region?" or "show me the top 10", refer to the previous query context
- When users say "that", "those", "it", etc., understand they refer to the previous result
- If a question is ambiguous, use conversation history to infer intent

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

Be precise, analytical, and helpful. Reference previous conversation when relevant."""


QUERY_BUILDER_PROMPT = """Build a VizQL query to answer this question: {question}

Available fields in the datasource:
{fields}

{feedback_section}

== CRITICAL RULES ==
1. Use EXACT field names from the list above (case-sensitive)
2. For measures (numeric values), ALWAYS include "function": "SUM" (or AVG, COUNT, COUNTD, MIN, MAX, MEDIAN)
3. For dimensions (categories, names), do NOT include a function
4. Use "sortDirection": "DESC" or "ASC" inside fields for ordering
5. Use "sortPriority": 1, 2, 3... when sorting multiple fields
6. Use "fieldAlias" to give meaningful names to calculated results
7. **NO DUPLICATE FIELDS**: Each fieldCaption can only appear ONCE in the fields array. Even with different functions/aliases, Tableau rejects duplicate fieldCaption values. For trends, pick ONE date granularity (YEAR or TRUNC_MONTH, not both).
8. **NO TABLE CALCULATIONS**: VizQL Data Service does NOT support table calculations like LOOKUP, RUNNING_SUM, RUNNING_AVG, WINDOW_SUM, WINDOW_AVG, INDEX, FIRST, LAST, PREVIOUS_VALUE. For year-over-year comparisons, simply query sales by year and the analysis will compute the comparison.

== FIELD OPTIONS ==

**Basic Field**: {{"fieldCaption": "Customer Name"}}

**Aggregated Field**: {{"fieldCaption": "Sales", "function": "SUM", "maxDecimalPlaces": 2}}

**Aliased Field**: {{"fieldCaption": "Sales", "function": "SUM", "fieldAlias": "Total Revenue"}}

**Calculated Field** (ONLY for row-level or aggregate calculations, NOT table calculations):
{{"fieldCaption": "Profit Margin", "calculation": "SUM([Profit])/SUM([Sales])", "maxDecimalPlaces": 2}}
NOTE: Do NOT use LOOKUP, RUNNING_SUM, or any window functions - they are not supported!

**Date Aggregations**:
- YEAR, QUARTER, MONTH, WEEK, DAY - extract part of date
- TRUNC_YEAR, TRUNC_MONTH, TRUNC_DAY - truncate to period
Example: {{"fieldCaption": "Order Date", "function": "YEAR", "fieldAlias": "Order Year"}}

== FILTER TYPES ==

**1. TOP N FILTER** (for "top 5", "bottom 10"):
{{"field": {{"fieldCaption": "Customer Name"}}, "filterType": "TOP", "howMany": 5, "direction": "TOP", "fieldToMeasure": {{"fieldCaption": "Sales", "function": "SUM"}}}}

**2. QUANTITATIVE FILTER** (for "> 10000", "< 500", "between"):
{{"field": {{"fieldCaption": "Sales", "function": "SUM"}}, "filterType": "QUANTITATIVE_NUMERICAL", "quantitativeFilterType": "MIN", "min": 10000}}
- quantitativeFilterType: MIN (>), MAX (<), RANGE (between), ONLY_NULL, ONLY_NON_NULL

**3. SET FILTER** (include/exclude specific values):
{{"field": {{"fieldCaption": "Region"}}, "filterType": "SET", "values": ["West", "East"], "exclude": false}}

**4. DATE FILTER** (relative dates):
{{"field": {{"fieldCaption": "Order Date"}}, "filterType": "DATE", "periodType": "YEARS", "dateRangeType": "LAST"}}
- periodType: DAYS, WEEKS, MONTHS, QUARTERS, YEARS
- dateRangeType: LAST, CURRENT, NEXT, LASTN (+ rangeN), NEXTN (+ rangeN), TODATE

**5. DATE RANGE FILTER** (specific date range):
{{"field": {{"fieldCaption": "Order Date"}}, "filterType": "QUANTITATIVE_DATE", "quantitativeFilterType": "RANGE", "minDate": "2024-01-01", "maxDate": "2024-12-31"}}

**6. MATCH FILTER** (pattern matching):
{{"field": {{"fieldCaption": "Product Name"}}, "filterType": "MATCH", "contains": "Chair", "exclude": false}}
- Options: startsWith, endsWith, contains

**7. CONTEXT FILTER** (scope other filters - add "context": true):
{{"field": {{"fieldCaption": "Category"}}, "filterType": "SET", "values": ["Furniture"], "exclude": false, "context": true}}

== COMPLEX EXAMPLES ==

Q: "Top 5 customers by sales in West region"
{{
  "fields": [
    {{"fieldCaption": "Customer Name"}},
    {{"fieldCaption": "Sales", "function": "SUM", "sortDirection": "DESC", "sortPriority": 1}}
  ],
  "filters": [
    {{"field": {{"fieldCaption": "Region"}}, "filterType": "SET", "values": ["West"], "exclude": false, "context": true}},
    {{"field": {{"fieldCaption": "Customer Name"}}, "filterType": "TOP", "howMany": 5, "direction": "TOP", "fieldToMeasure": {{"fieldCaption": "Sales", "function": "SUM"}}}}
  ]
}}

Q: "Profit margin by category for products with sales > $50000"
{{
  "fields": [
    {{"fieldCaption": "Category"}},
    {{"fieldCaption": "Sales", "function": "SUM", "fieldAlias": "Total Sales"}},
    {{"fieldCaption": "Profit", "function": "SUM", "fieldAlias": "Total Profit"}},
    {{"fieldCaption": "Profit Margin", "calculation": "SUM([Profit])/SUM([Sales])", "maxDecimalPlaces": 2}}
  ],
  "filters": [
    {{"field": {{"fieldCaption": "Sales", "function": "SUM"}}, "filterType": "QUANTITATIVE_NUMERICAL", "quantitativeFilterType": "MIN", "min": 50000}}
  ]
}}

Q: "Monthly sales trend for last 12 months"
{{
  "fields": [
    {{"fieldCaption": "Order Date", "function": "TRUNC_MONTH", "fieldAlias": "Month", "sortPriority": 1}},
    {{"fieldCaption": "Sales", "function": "SUM", "fieldAlias": "Monthly Sales"}}
  ],
  "filters": [
    {{"field": {{"fieldCaption": "Order Date"}}, "filterType": "DATE", "periodType": "MONTHS", "dateRangeType": "LASTN", "rangeN": 12}}
  ]
}}

Q: "Compare Furniture vs Technology sales by region"
{{
  "fields": [
    {{"fieldCaption": "Region"}},
    {{"fieldCaption": "Category"}},
    {{"fieldCaption": "Sales", "function": "SUM", "sortDirection": "DESC"}}
  ],
  "filters": [
    {{"field": {{"fieldCaption": "Category"}}, "filterType": "SET", "values": ["Furniture", "Technology"], "exclude": false}}
  ]
}}

Q: "Sales trend since 2020" or "Yearly sales from 2020"
{{
  "fields": [
    {{"fieldCaption": "Order Date", "function": "YEAR", "fieldAlias": "Year", "sortPriority": 1}},
    {{"fieldCaption": "Sales", "function": "SUM", "fieldAlias": "Total Sales"}}
  ],
  "filters": [
    {{"field": {{"fieldCaption": "Order Date"}}, "filterType": "QUANTITATIVE_DATE", "quantitativeFilterType": "MIN", "minDate": "2020-01-01"}}
  ]
}}

Q: "Year over year sales comparison" or "YoY growth"
NOTE: For YoY comparisons, just query sales by year - the analysis will calculate the growth rates.
{{
  "fields": [
    {{"fieldCaption": "Order Date", "function": "YEAR", "fieldAlias": "Year", "sortPriority": 1, "sortDirection": "ASC"}},
    {{"fieldCaption": "Sales", "function": "SUM", "fieldAlias": "Total Sales"}}
  ]
}}

Return ONLY a valid JSON object. No explanation, no markdown."""


QUERY_REVIEW_PROMPT = """You are a Senior QA Engineer validating a VizQL query against the user's question and schema.

Question: {question}

Query Generated:
{query}

Schema Valid Fields:
{fields}

== VALIDATION CHECKS ==

1. **Field Validity**: Are all fieldCaption values actually in the schema?
   - Exception: Calculated fields can have any fieldCaption if they have a "calculation" property

2. **Logic Check**: Does the query actually answer the question?

3. **Aggregation**: Are measures aggregated correctly (SUM, AVG, COUNT, COUNTD, MIN, MAX, MEDIAN)?

4. **Calculated Fields** (if present):
   - Must have "calculation" property with valid Tableau syntax
   - Field references in calculation must exist in schema: e.g., "[Sales]", "[Profit]"
   - Must have "fieldCaption" for the result name

5. **Filter Syntax** (if filters present):
   - TOP filter: "field", "filterType": "TOP", "howMany", "direction", "fieldToMeasure"
   - QUANTITATIVE_NUMERICAL: "field", "filterType", "quantitativeFilterType", "min"/"max"
   - SET filter: "field", "filterType": "SET", "values" array, "exclude" boolean
   - DATE filter: "field", "filterType": "DATE", "periodType", "dateRangeType"
   - QUANTITATIVE_DATE: "field", "filterType", "quantitativeFilterType", "minDate"/"maxDate"
   - MATCH filter: "field", "filterType": "MATCH", at least one of "startsWith"/"endsWith"/"contains"
   - Context filters: "context": true scopes subsequent filters

6. **Question Match**: 
   - If question asks for "top N", is there a TOP filter with correct howMany?
   - If question mentions specific values (e.g., "West region"), is there a SET filter?
   - If question mentions time period, is there a DATE filter?

7. **No Duplicate Fields**: 
   - Each fieldCaption MUST appear only ONCE in the fields array
   - Even with different functions/aliases, duplicate fieldCaptions will cause Tableau to reject the query
   - For date trends, use only ONE aggregation level (YEAR or TRUNC_MONTH, not both)

If the query is GOOD, return exactly: "APPROVED"
If the query is BAD, return a concise critique explaining EXACTLY what to fix.

Example Critiques:
- "Field 'Total Sales' does not exist. Use 'Sales' instead."
- "TOP filter missing fieldToMeasure. Add fieldToMeasure with the measure field."
- "Question asks for 'West region' but no SET filter for Region. Add filter."
- "Calculation references [Revenue] but field is called 'Sales'. Fix to [Sales]."
- "Duplicate fieldCaption 'Order Date' in fields array. Use only one date aggregation (YEAR or TRUNC_MONTH, not both)."
"""


ANALYZER_PROMPT = """Analyze these query results to answer: {question}

Data:
{results}

Provide a comprehensive analysis including:
1. **Direct Answer**: Clearly answer the original question
2. **Key Findings**: Highlight the most important patterns or values
3. **Insights**: Provide actionable business insights based on the data
4. **Context**: Note any limitations or considerations

Be concise but thorough."""


INTENT_CLASSIFIER_PROMPT = """You are an intent classifier for a Tableau data analysis assistant.

Classify the user's message into one of these categories:
- **data_query**: The user wants to query, analyze, or visualize data from Tableau datasources
  - Examples: "Show me sales by region", "What are the top customers?", "Sales trend since 2020"
  - Also includes follow-ups about data: "Break that down by month", "Show me the details"
  
- **chat**: General conversation, greetings, questions about capabilities, or help requests
  - Examples: "Hello", "How are you?", "What can you do?", "Thanks!", "Help me understand this system"
  - Also includes meta questions: "Who made you?", "What data do you have access to?"

User message: {question}

Respond with ONLY one word: either "data_query" or "chat"
"""


CHAT_RESPONSE_PROMPT = """You are a friendly AI assistant for Tableau data analysis. The user has sent a conversational message (not a data query).

User message: {question}

Respond naturally and helpfully. If asked about your capabilities, explain that you can:
- Query and analyze data from connected Tableau datasources
- Create visualizations and charts
- Answer questions about sales, customers, products, regions, and other business metrics
- Provide insights and trends from the data

If greeted, respond warmly and offer to help with data analysis.
If thanked, acknowledge and offer further assistance.

Keep your response concise and friendly. Don't make up data - if asked about specific numbers, suggest running a data query instead."""


# =============================================================================
# Agent Class
# =============================================================================

class TableauAgent:
    """LangGraph-based agent for Tableau data analysis with native memory."""
    
    # Class-level checkpointer (shared across instances for persistence)
    _checkpointer = None
    # Class-level metadata cache to avoid redundant API calls
    _metadata_cache: Dict[str, DatasourceMetadata] = {}
    _cache_ttl_seconds: int = 300  # 5 minutes
    _cache_timestamps: Dict[str, float] = {}
    
    def __init__(self, mcp_client: Optional[MCPClient] = None):
        """
        Initialize the agent.
        
        Args:
            mcp_client: Optional MCP client instance
        """
        self.mcp_client = mcp_client or MCPClient()
        self._llm: Optional[ChatOpenAI] = None
        self._compiled_graph = None
    
    @classmethod
    def get_checkpointer(cls) -> MemorySaver:
        """Get or create the shared checkpointer instance."""
        if cls._checkpointer is None:
            # Use MemorySaver for now (can switch to PostgresSaver for full persistence)
            # For PostgresSaver: from langgraph.checkpoint.postgres import PostgresSaver
            cls._checkpointer = MemorySaver()
            logger.info("Initialized LangGraph MemorySaver checkpointer")
        return cls._checkpointer
    
    async def get_cached_metadata(self, datasource_id: str) -> Optional[DatasourceMetadata]:
        """Get datasource metadata with caching to reduce API calls."""
        # Check cache
        if datasource_id in self._metadata_cache:
            cache_time = self._cache_timestamps.get(datasource_id, 0)
            if time.time() - cache_time < self._cache_ttl_seconds:
                logger.info("Using cached metadata", datasource_id=datasource_id)
                return self._metadata_cache[datasource_id]
        
        # Fetch fresh metadata
        try:
            metadata = await self.mcp_client.get_datasource_metadata(datasource_id)
            self._metadata_cache[datasource_id] = metadata
            self._cache_timestamps[datasource_id] = time.time()
            logger.info("Cached metadata", datasource_id=datasource_id, fields=len(metadata.fields))
            return metadata
        except Exception as e:
            logger.error("Failed to get metadata", datasource_id=datasource_id, error=str(e))
            return None
    
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
        graph.add_node("classify_intent", self._classify_intent)
        graph.add_node("chat", self._handle_chat)
        graph.add_node("clarification", self._handle_clarification)
        graph.add_node("discover", self._discover_datasources)
        graph.add_node("plan", self._plan_query)
        graph.add_node("review", self._review_query)
        graph.add_node("execute", self._execute_query)
        graph.add_node("analyze", self._analyze_results)
        
        # Define edges - start with intent classification
        graph.set_entry_point("classify_intent")
        
        # Route based on intent
        graph.add_conditional_edges(
            "classify_intent",
            self._route_by_intent,
        )
        
        # Data query workflow
        graph.add_edge("discover", "plan")
        graph.add_edge("plan", "review")
        
        graph.add_conditional_edges(
            "review",
            self._check_review_outcome,
        )
        
        graph.add_conditional_edges(
            "execute",
            self._should_analyze,
        )
        graph.add_edge("analyze", END)
        
        # Chat and clarification go directly to END
        graph.add_edge("chat", END)
        graph.add_edge("clarification", END)
        
        return graph
    
    def _route_by_intent(self, state: AgentState) -> str:
        """Route based on classified intent."""
        intent = state.get("intent", "data_query")
        if intent == "chat":
            return "chat"
        if intent == "clarification":
            return "clarification"
        return "discover"
    
    def _check_review_outcome(self, state: AgentState) -> str:
        """Determine next step based on critique."""
        if state.get("error"):
            return END
        if state.get("critique") and state.get("critique") != "APPROVED":
            # HARD LIMIT: Max 2 total retries (critique + execution combined)
            retry_count = state.get("retry_count", 0)
            if retry_count < 2:
                logger.info("Query critique, will retry", retry_count=retry_count)
                return "plan"
            else:
                logger.warning("Max retries reached on critique, proceeding to execute anyway")
        return "execute"
    
    def _should_analyze(self, state: AgentState) -> str:
        """Determine if we should analyze, retry, or end."""
        if state.get("error"):
            # HARD LIMIT: Max 2 total retries (critique + execution combined)
            retry_count = state.get("retry_count", 0)
            if retry_count < 2:
                logger.info("Execution error, routing back to plan for fix", 
                           error=state.get("error")[:100], retry_count=retry_count)
                return "plan"
            else:
                logger.warning("Max retries reached, ending with error", 
                              error=state.get("error")[:100])
                return END
        return "analyze"
    
    async def _classify_intent(self, state: AgentState) -> AgentState:
        """Classify user intent to route appropriately."""
        question = state.get("question", "")
        logger.info("Classifying intent", question=question[:50])
        
        # Quick heuristics for obvious cases (saves an LLM call)
        question_lower = question.lower().strip()
        
        # Obvious greetings
        greetings = ["hi", "hello", "hey", "good morning", "good afternoon", "good evening", 
                     "howdy", "what's up", "whats up", "sup"]
        if question_lower in greetings or any(question_lower.startswith(g + " ") for g in greetings[:3]):
            state["intent"] = "chat"
            logger.info("Intent classified as chat (greeting heuristic)")
            return state
        
        # Obvious thanks/acknowledgements
        thanks = ["thanks", "thank you", "thx", "ty", "cheers", "great", "awesome", "perfect", "ok", "okay"]
        if question_lower in thanks or question_lower.startswith("thanks"):
            state["intent"] = "chat"
            logger.info("Intent classified as chat (thanks heuristic)")
            return state
        
        # Obvious capability questions
        capability_phrases = ["what can you do", "how do you work", "help me", "who are you", 
                             "what are you", "your capabilities", "can you help"]
        if any(phrase in question_lower for phrase in capability_phrases):
            state["intent"] = "chat"
            logger.info("Intent classified as chat (capability heuristic)")
            return state
        
        # AMBIGUOUS QUESTIONS: Too vague to execute - ask for clarification
        # These are questions that contain data keywords but lack specificity
        ambiguous_patterns = [
            # Single-word or very short queries
            (len(question_lower.split()) <= 2 and not any(q in question_lower for q in ["top", "total", "count", "sum", "average", "how many"])),
            # Vague analysis requests
            question_lower in ["sales", "profit", "revenue", "data", "analysis", "insights", "performance", "results"],
            # "Show me everything" type
            any(phrase in question_lower for phrase in ["show me everything", "everything", "all data", "all the data", "give me everything"]),
            # Very vague requests
            any(phrase in question_lower for phrase in ["what's the story", "tell me about", "analyze the", "give me insights", "analyze performance"]),
        ]
        
        if any(ambiguous_patterns):
            state["intent"] = "clarification"
            logger.info("Intent classified as clarification (ambiguous question)")
            return state
        
        # Data-related keywords suggest data query
        data_keywords = ["sales", "revenue", "profit", "customer", "product", "region", "trend",
                        "top", "bottom", "show me", "what is", "how many", "total", "average",
                        "sum", "count", "by", "breakdown", "compare", "analysis", "data"]
        if any(kw in question_lower for kw in data_keywords):
            state["intent"] = "data_query"
            logger.info("Intent classified as data_query (keyword heuristic)")
            return state
        
        # Use LLM for ambiguous cases
        try:
            prompt = INTENT_CLASSIFIER_PROMPT.format(question=question)
            response = await self.llm.ainvoke(prompt)
            intent = response.content.strip().lower()
            
            if "chat" in intent:
                state["intent"] = "chat"
            elif "clarif" in intent:
                state["intent"] = "clarification"
            else:
                state["intent"] = "data_query"  # Default to data query
            
            logger.info("Intent classified by LLM", intent=state["intent"])
            
        except Exception as e:
            logger.warning(f"Intent classification failed, defaulting to data_query: {e}")
            state["intent"] = "data_query"
        
        return state
    
    async def _handle_chat(self, state: AgentState) -> AgentState:
        """Handle conversational messages without data queries."""
        question = state.get("question", "")
        logger.info("Handling chat message", question=question[:50])
        
        try:
            prompt = CHAT_RESPONSE_PROMPT.format(question=question)
            response = await self.llm.ainvoke([
                SystemMessage(content="You are a friendly, helpful AI assistant for Tableau data analysis."),
                HumanMessage(content=prompt)
            ])
            
            state["analysis"] = response.content
            state["status"] = "complete"
            state["messages"] = [AIMessage(content=response.content)]
            
            logger.info("Chat response generated")
            
        except Exception as e:
            logger.error(f"Chat response failed: {e}")
            state["analysis"] = "I apologize, but I'm having trouble responding right now. Please try again or ask me about your data!"
            state["status"] = "error"
            state["error"] = str(e)
        
        return state
    
    async def _handle_clarification(self, state: AgentState) -> AgentState:
        """Handle ambiguous questions by asking for clarification."""
        question = state.get("question", "")
        logger.info("Handling clarification request", question=question[:50])
        
        # Generate a helpful clarification response
        clarification_response = f"""I'd be happy to help you analyze your data, but I need a bit more specifics to give you the best results.

Your question "{question}" could mean different things. Could you please clarify:

**For Sales/Revenue Analysis:**
- "What are the total sales?" (overall total)
- "Sales by region" (breakdown by geography)
- "Top 10 customers by sales" (ranking)
- "Monthly sales trend" (over time)

**For Profit Analysis:**
- "Average profit by category"
- "Which products have the highest profit margin?"

**For Customer Analysis:**
- "How many unique customers do we have?"
- "Top 5 customers by revenue"

**What specific question would you like me to answer?**"""
        
        state["analysis"] = clarification_response
        state["status"] = "complete"
        state["messages"] = [AIMessage(content=clarification_response)]
        
        logger.info("Clarification response generated")
        return state
    
    @property
    def graph(self):
        """Get compiled graph with checkpointer for conversation memory."""
        if self._compiled_graph is None:
            checkpointer = self.get_checkpointer()
            self._compiled_graph = self._build_graph().compile(checkpointer=checkpointer)
            logger.info("Compiled graph with LangGraph checkpointer")
        return self._compiled_graph
        
    async def get_state(self, thread_id: str) -> Dict[str, Any]:
        """Get the current state for a thread."""
        config = {"configurable": {"thread_id": thread_id}}
        state_values = await self.graph.aget_state(config)
        return state_values.values if state_values else {}
    
    async def _discover_datasources(self, state: AgentState) -> AgentState:
        """Discover available datasources."""
        logger.info("Discovering datasources")
        
        # Initialize retry count
        state["retry_count"] = 0
        state["critique"] = None
        
        try:
            datasources = await self.mcp_client.list_datasources()
            state["datasources"] = datasources
            state["status"] = "discovered"
            
            logger.info("Discovered datasources", count=len(datasources))
            
            # Auto-select if only one
            if len(datasources) == 1:
                state["selected_datasource"] = datasources[0]
                metadata = await self.get_cached_metadata(datasources[0].id)
                if metadata:
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
        critique = state.get("critique")
        
        logger.info("Planning query", question=question[:50], critique=critique)
        
        # Increment retry count if retrying due to critique OR execution error
        execution_error = state.get("error")
        if (critique and critique != "APPROVED") or execution_error:
            state["retry_count"] = state.get("retry_count", 0) + 1
            logger.info("Retrying query generation", 
                       attempt=state["retry_count"], 
                       reason="execution_error" if execution_error else "critique")
        
        # Select datasource if not selected
        if not state.get("selected_datasource") and datasources:
            if len(datasources) == 1:
                state["selected_datasource"] = datasources[0]
                logger.info("Auto-selected single available datasource", name=datasources[0].name)
            else:
                # Use LLM to select best datasource
                ds_list = "\n".join([
                    f"- {ds.name}: {ds.description or 'No description'}" 
                    for ds in datasources
                ])
                
                try:
                    # Provide clearer instructions for datasource selection
                    system_prompt = (
                        "Select the best datasource for the question. "
                        "Prioritize data sources that sound like they contain business data (sales, customers, orders). "
                        "If the question is general or refers to 'Superstore' data, prefer 'Superstore Datasource'. "
                        "Return ONLY the exact datasource name from the list below."
                    )
                    
                    response = await self.llm.ainvoke([
                        SystemMessage(content=system_prompt),
                        HumanMessage(content=f"Question: {question}\n\nAvailable Datasources:\n{ds_list}"),
                    ])
                    
                    selected_name = response.content.strip()
                    logger.info("LLM selected datasource", selected=selected_name)
                    
                    # Try exact match first
                    for ds in datasources:
                        if ds.name == selected_name:
                            state["selected_datasource"] = ds
                            break
                    
                    # Try case-insensitive fuzzy match if no exact match
                    if not state.get("selected_datasource"):
                        selected_name_lower = selected_name.lower()
                        for ds in datasources:
                            if ds.name.lower() in selected_name_lower or selected_name_lower in ds.name.lower():
                                state["selected_datasource"] = ds
                                break
                    
                    # Fallback for general questions if Superstore exists
                    if not state.get("selected_datasource"):
                        for ds in datasources:
                            if "superstore" in ds.name.lower():
                                state["selected_datasource"] = ds
                                logger.info("Fallback to Superstore datasource")
                                break
                    
                    # Final fallback
                    if not state.get("selected_datasource"):
                        state["selected_datasource"] = datasources[0]
                        logger.warning("Could not match datasource, using first")
                        
                except Exception as e:
                    logger.error("Datasource selection failed", error=str(e))
                    # Fallback: try Superstore first, then first datasource
                    for ds in datasources:
                        if "superstore" in ds.name.lower():
                            state["selected_datasource"] = ds
                            logger.info("Exception fallback to Superstore datasource")
                            break
                    if not state.get("selected_datasource") and datasources:
                        state["selected_datasource"] = datasources[0]
                        logger.warning("Exception fallback to first datasource")
        
        # FINAL SAFETY: If still no datasource but we have datasources available, pick one
        if not state.get("selected_datasource") and datasources:
            for ds in datasources:
                if "superstore" in ds.name.lower():
                    state["selected_datasource"] = ds
                    logger.info("Safety fallback to Superstore datasource")
                    break
            if not state.get("selected_datasource"):
                state["selected_datasource"] = datasources[0]
                logger.warning("Safety fallback to first datasource")
        
        if not state.get("selected_datasource"):
            state["error"] = "No datasource selected"
            return state
            
        # Get metadata if needed (using cache)
        ds = state["selected_datasource"]
        if "metadata" not in state or state.get("metadata_id") != ds.id:
            metadata = await self.get_cached_metadata(ds.id)
            if not metadata:
                state["error"] = f"Failed to get metadata for {ds.name}"
                return state
            state["metadata"] = metadata
            state["metadata_id"] = ds.id
            logger.info("Got metadata", datasource=ds.name, fields=len(metadata.fields))
        
        # Generate schema description
        fields_str = state["metadata"].to_schema_description()
        
        # Optional: Enrich with data dictionary if available
        data_dict = get_data_dictionary()
        if data_dict and not data_dict.is_empty():
            fields_str = data_dict.enrich_schema(fields_str)
            logger.info("Enriched schema with data dictionary")
        
        # Fetch sample data for better LLM context (CRITICAL for accuracy)
        sample_data_section = ""
        if "sample_data" not in state:
            try:
                sample_rows = await self.mcp_client.get_sample_data(ds.id, num_rows=5)
                if sample_rows:
                    # Apply PHI sanitization before including in prompt
                    sanitized = sanitize_for_llm(sample_rows)
                    state["sample_data"] = sanitized.sanitized_data
                    
                    if sanitized.phi_detected:
                        logger.warning(
                            "PHI detected in sample data and sanitized",
                            phi_fields=sanitized.phi_fields,
                            count=sanitized.phi_count
                        )
                    
                    # Format sample data for prompt
                    if sanitized.sanitized_data:
                        sample_lines = ["Sample Data (first 5 rows):"]
                        headers = list(sanitized.sanitized_data[0].keys())
                        sample_lines.append("| " + " | ".join(headers) + " |")
                        sample_lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
                        for row in sanitized.sanitized_data[:5]:
                            values = [str(row.get(h, ""))[:30] for h in headers]  # Truncate long values
                            sample_lines.append("| " + " | ".join(values) + " |")
                        sample_data_section = "\n".join(sample_lines)
                    
            except Exception as e:
                logger.warning(f"Could not fetch sample data: {e}")
                state["sample_data"] = []
        else:
            # Reuse cached sample data
            if state.get("sample_data"):
                sample_lines = ["Sample Data (first 5 rows):"]
                headers = list(state["sample_data"][0].keys())
                sample_lines.append("| " + " | ".join(headers) + " |")
                sample_lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
                for row in state["sample_data"][:5]:
                    values = [str(row.get(h, ""))[:30] for h in headers]
                    sample_lines.append("| " + " | ".join(values) + " |")
                sample_data_section = "\n".join(sample_lines)
        
        # Add feedback to prompt if retrying (from critique OR execution error)
        feedback_section = ""
        if critique and critique != "APPROVED":
            feedback_section = f"\nPREVIOUS ATTEMPT CRITIQUE (FIX THIS): \n{critique}\n"
        
        # Also include execution error if present (e.g., MCP rejected the query)
        execution_error = state.get("error")
        if execution_error:
            feedback_section += f"\nEXECUTION ERROR (FIX THIS): \n{execution_error}\n"
            # Clear the error so we can try again
            state["error"] = None
        
        # Build the full prompt with sample data
        full_fields_context = fields_str
        if sample_data_section:
            full_fields_context += f"\n\n{sample_data_section}"
        
        prompt = QUERY_BUILDER_PROMPT.format(
            question=question,
            fields=full_fields_context,
            feedback_section=feedback_section
        )

        try:
            response = await self.llm.ainvoke(prompt)
            content = response.content.strip()
            
            # Robust JSON extraction
            query = self._extract_json(content)
            if query:
                # POST-PROCESSING: Ensure no duplicate fields by fieldCaption
                # Tableau rejects queries with duplicate fieldCaption entries
                if "fields" in query and isinstance(query["fields"], list):
                    seen_captions = {}
                    unique_fields = []
                    for field in query["fields"]:
                        caption = field.get("fieldCaption")
                        if not caption:
                            continue
                        
                        # If we haven't seen this caption, or if this new instance 
                        # has a function (making it more specific), take it.
                        if caption not in seen_captions:
                            seen_captions[caption] = field
                            unique_fields.append(field)
                        elif field.get("function") and not seen_captions[caption].get("function"):
                            # Replace existing with one that has a function
                            idx = unique_fields.index(seen_captions[caption])
                            unique_fields[idx] = field
                            seen_captions[caption] = field
                    
                    if len(unique_fields) < len(query["fields"]):
                        logger.info(
                            "Deduplicated fields in query", 
                            original=len(query["fields"]), 
                            unique=len(unique_fields)
                        )
                        query["fields"] = unique_fields

                state["vizql_query"] = query
                logger.info("Generated VizQL query", query=query)
            else:
                state["error"] = f"Failed to parse query JSON. LLM response: {content[:200]}"
                logger.warning("JSON extraction failed", response_preview=content[:200])
                
        except Exception as e:
            error_msg = f"Query generation failed: {e}"
            if state.get("retry_count", 0) == 0:
                state["error"] = error_msg
            else:
                logger.error("Retry failed", error=str(e))
                state["error"] = error_msg  # Always set error so retry loop can handle
        
        return state

    async def _review_query(self, state: AgentState) -> AgentState:
        """Review the generated query for correctness."""
        query = state.get("vizql_query")
        metadata = state.get("metadata")
        question = state.get("question")
        
        if not query or not metadata:
            state["critique"] = "Missing query or metadata"
            return state
            
        logger.info("Reviewing query")
        
        # Programmatic check for duplicate fields (Tableau rejects these)
        fields = query.get("fields", [])
        field_captions = [f.get("fieldCaption") for f in fields if f.get("fieldCaption")]
        duplicates = [cap for cap in set(field_captions) if field_captions.count(cap) > 1]
        if duplicates:
            state["critique"] = f"Duplicate fieldCaption values detected: {duplicates}. Each fieldCaption can only appear ONCE. For date trends, use only ONE aggregation (YEAR or TRUNC_MONTH, not both)."
            logger.warning("Query has duplicate fields", duplicates=duplicates)
            return state
        
        fields_str = metadata.to_schema_description()
        query_str = json.dumps(query, indent=2)
        
        prompt = QUERY_REVIEW_PROMPT.format(
            question=question,
            query=query_str,
            fields=fields_str
        )
        
        try:
            response = await self.llm.ainvoke(prompt)
            critique = response.content.strip()
            
            # Simple heuristic: If it doesn't say "APPROVED", treat as critique
            if "APPROVED" in critique.upper() and len(critique) < 20:
                logger.info("Query APPROVED")
                state["critique"] = "APPROVED"
            else:
                logger.info("Query REJECTED", critique=critique)
                state["critique"] = critique
                
        except Exception as e:
            logger.warning(
                "Query review LLM call failed - proceeding with execution",
                error=str(e),
                query_preview=json.dumps(query)[:200] if query else None
            )
            # Proceed to execution - let MCP validate the query instead
            state["critique"] = "APPROVED"
            
        return state
    
    async def _execute_query(self, state: AgentState) -> AgentState:
        """Execute the VizQL query."""
        question = state.get("question", "")
        metadata = state.get("metadata")
        query = state.get("vizql_query")
        
        logger.info("Executing query")
        
        if not metadata:
            state["error"] = "No datasource metadata available"
            return state
        
        if not query:
             state["error"] = "No VizQL query available to execute"
             return state

        # Execute query
        try:
            result = await self.mcp_client.query_datasource(
                datasource_id=state["selected_datasource"].id,
                query=query,
            )
            state["query_result"] = result
            logger.info("Query executed successfully", rows=len(result.data))
            
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
            
            # Store the analyzed data for validation purposes
            state["analyzed_data"] = {
                "row_count": len(llm_df),
                "original_row_count": total_rows,
                "data": llm_df.to_dict(orient="records"),
                "description": f"Aggregated from {total_rows} to {len(llm_df)} rows based on question type"
            }
            
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
        
        # Add assistant response to conversation history (LangGraph native)
        state["messages"] = [AIMessage(content=state.get("analysis", ""))]
        
        return state
    
    def _prepare_data_for_llm(self, df: pd.DataFrame, question: str) -> pd.DataFrame:
        """
        Prepare data specifically for LLM analysis.
        This may aggregate or sample data, but does NOT affect the display data.
        """
        return self._pre_aggregate_data(df, question)
    
    def _pre_aggregate_data(self, df: pd.DataFrame, question: str) -> pd.DataFrame:
        """
        Pre-aggregate data based on the question to ensure accurate LLM analysis.
        
        This is a FALLBACK mechanism. If VDS filters worked correctly, the data
        should already be filtered. This catches cases where:
        1. VDS filters failed or weren't applied
        2. Complex filtering not supported by VDS
        3. Post-processing aggregation is needed
        """
        import pandas as pd
        import re
        from datetime import datetime, timedelta
        
        question_lower = question.lower()
        original_row_count = len(df)
        
        # ========================================
        # Check if VDS already filtered appropriately
        # ========================================
        top_n_match = re.search(r'\b(?:top|bottom)\s+(\d+)\b', question_lower)
        if top_n_match:
            expected_n = int(top_n_match.group(1))
            # If we got roughly the right number of rows, VDS filtering worked
            if len(df) <= expected_n * 2:  # Allow some buffer
                logger.info(
                    "VDS filtering appears to have worked",
                    expected=expected_n,
                    got=len(df)
                )
                return df  # Data already filtered by VDS
        
        # ========================================
        # If data is small enough, no aggregation needed
        # ========================================
        if len(df) <= 50:
            logger.info("Data small enough for direct analysis", rows=len(df))
            return df
        
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
        # 1. Handle "top N" / "bottom N" requests with optional value filters
        # ========================================
        top_n_match = re.search(r'\b(top|bottom|first|last|highest|lowest)\s*(\d+)\b', question_lower)
        if top_n_match:
            direction = top_n_match.group(1)
            n = int(top_n_match.group(2))
            ascending = direction in ['bottom', 'last', 'lowest']
            
            logger.info(f"Detected Top N request", direction=direction, n=n)
            
            # Detect value filter (e.g., "> $10000", "above 5000", "more than 1000")
            value_filter_match = re.search(
                r'(?:>|greater than|above|more than|over|exceeding)\s*\$?\s*([\d,]+)', 
                question_lower
            )
            min_value = None
            if value_filter_match:
                min_value = float(value_filter_match.group(1).replace(',', ''))
                logger.info(f"Detected value filter: > {min_value}")
            
            value_filter_max_match = re.search(
                r'(?:<|less than|below|under)\s*\$?\s*([\d,]+)', 
                question_lower
            )
            max_value = None
            if value_filter_max_match:
                max_value = float(value_filter_max_match.group(1).replace(',', ''))
                logger.info(f"Detected value filter: < {max_value}")
            
            # Determine which column to aggregate/sort on
            # Look for keywords like "by sales", "by profit", "by revenue"
            sort_col = None
            for col in numeric_cols:
                col_lower = col.lower()
                # Check if this column is mentioned in the question
                if any(word in question_lower for word in [col_lower, col_lower.replace('sum(', '').replace(')', '')]):
                    sort_col = col
                    break
            
            # Default to first numeric column if not found
            if not sort_col and numeric_cols:
                sort_col = numeric_cols[0]
            
            if not sort_col:
                logger.warning("No numeric column found for Top N sorting")
                return df
            
            # Determine the dimension column (customer, product, etc.)
            dimension_col = None
            for keyword in ['customer', 'product', 'category', 'region', 'city', 'state', 'segment', 'name']:
                for col in string_cols:
                    if keyword in col.lower():
                        dimension_col = col
                        break
                if dimension_col:
                    break
            
            # If no specific dimension found, use first string column
            if not dimension_col and string_cols:
                dimension_col = string_cols[0]
            
            # CRITICAL: Aggregate by dimension first (sum all values for each customer/entity)
            if dimension_col:
                logger.info(f"Aggregating by dimension: {dimension_col}")
                agg_dict = {col: 'sum' for col in numeric_cols}
                df = df.groupby(dimension_col).agg(agg_dict).reset_index()
            
            # Apply value filter AFTER aggregation
            if min_value is not None:
                before_count = len(df)
                df = df[df[sort_col] > min_value]
                logger.info(f"Applied filter > {min_value}", before=before_count, after=len(df))
            
            if max_value is not None:
                before_count = len(df)
                df = df[df[sort_col] < max_value]
                logger.info(f"Applied filter < {max_value}", before=before_count, after=len(df))
            
            # Sort and take top N
            result = df.sort_values(sort_col, ascending=ascending).head(n)
            logger.info(f"Extracted {direction} {n}", sort_col=sort_col, rows=len(result))
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
        thread_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Answer a question about Tableau data.
        
        Args:
            question: Natural language question
            datasource_id: Optional datasource ID to use
            thread_id: Thread ID for LangGraph conversation memory
            
        Returns:
            Result dictionary with analysis and data
        """
        if not question or len(question.strip()) < 3:
            return {
                "success": False,
                "question": question,
                "error": "Question is too short",
            }
        
        # Build initial state with user message
        initial_state: AgentState = {
            "question": question.strip(),
            "status": "started",
            "messages": [HumanMessage(content=question.strip())],  # LangGraph native
        }
        
        if datasource_id:
            initial_state["selected_datasource"] = Datasource(
                id=datasource_id,
                name=datasource_id,
            )
        
        # Configure thread for conversation memory (always required by checkpointer)
        effective_thread_id = thread_id or str(uuid.uuid4())
        config = {"configurable": {"thread_id": effective_thread_id}}
        if thread_id:
            logger.info("Using provided LangGraph thread", thread_id=thread_id)
        else:
            logger.info("Generated ephemeral thread", thread_id=effective_thread_id)
        
        # Request-level timeout to prevent hanging queries
        QUERY_TIMEOUT_SECONDS = 240  # 4 minutes max per query (increased for complex trend queries)
        
        try:
            # Wrap graph execution in timeout
            final_state = await asyncio.wait_for(
                self.graph.ainvoke(initial_state, config=config),
                timeout=QUERY_TIMEOUT_SECONDS
            )
            
            result_data = None
            analyzed_data = None
            
            if final_state.get("query_result"):
                qr = final_state["query_result"]
                result_data = {
                    "row_count": qr.row_count,
                    "data": qr.data,  # Return ALL data for validation (no limit)
                    "execution_time_ms": qr.execution_time_ms,
                }
                
                # Include what the LLM actually analyzed (for validation)
            
            # Debug: Log available keys in final_state
            logger.info("Final state keys", keys=list(final_state.keys()))
            
            if final_state.get("analyzed_data"):
                analyzed_data = final_state["analyzed_data"]
                logger.info("Analyzed data found", rows=analyzed_data.get("row_count"))
            else:
                logger.warning("No analyzed_data in final_state")
            
            # Build result
            result = {
                "success": final_state.get("status") == "complete" and not final_state.get("error"),
                "question": question,
                "thread_id": thread_id,  # Return thread_id for frontend
                "datasource": {
                    "id": final_state.get("selected_datasource").id,
                    "name": final_state.get("selected_datasource").name,
                } if final_state.get("selected_datasource") else None,
                "analysis": final_state.get("analysis"),
                "query": final_state.get("vizql_query"),  # Return the VizQL query
                "results": result_data,
                "analyzed_data": analyzed_data,  # Data the LLM actually analyzed
                "visualization": final_state.get("visualization"),
                "error": final_state.get("error"),
                "message_count": len(final_state.get("messages", [])),  # Conversation length
            }
            
            # LangGraph checkpointer automatically persists state with thread_id
            if thread_id and result["success"]:
                logger.info(
                    "Conversation persisted via LangGraph checkpointer",
                    thread_id=thread_id,
                    messages=len(final_state.get("messages", []))
                )
            
            return result
        
        except asyncio.TimeoutError:
            logger.error("Query timed out", question=question[:50], timeout_seconds=QUERY_TIMEOUT_SECONDS)
            return {
                "success": False,
                "question": question,
                "error": f"Query timed out after {QUERY_TIMEOUT_SECONDS} seconds. Try simplifying your question.",
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
