"""
Dashboard Agent using LangGraph for the Tableau Extension.
Leverages LangGraph's StateGraph for a Plan-and-Execute workflow.

Architecture:
    User Question → orchestrate (Planner)
                      │
                      ▼
               ┌─── replan (Adaptive) ───┐
               │         │               │
               ▼         ▼               ▼
           [Expert 1] [Expert 2] ... [Expert N]
               │         │               │
               └─────────┴───────┬───────┘
                                 │
                                 ▼
                             synthesize (Final Story)
                                 │
                                 ▼
                               [END]
"""

import json
import re
import uuid
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from typing import Any, AsyncIterator, Dict, List, Optional, Annotated, TypedDict
from datetime import datetime
from operator import add

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI, AzureChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres import PostgresSaver

from src.core.config import settings
from src.core.logging import get_logger
from src.agent.graph import TableauAgent  # Import existing Data Agent
from src.services.config_service import get_config_service, DashboardConfig
from src.agent.trust_layer import (
    build_citation_from_result, format_citation, format_citations,
    validate_data_response, compute_confidence, SourceCitation,
)
from src.agent.data_dictionary import get_data_dictionary

logger = get_logger(__name__)


# =============================================================================
# Custom Reducers for Plan-Execution State
# =============================================================================

def reduce_step_results(existing: List, new: List) -> List:
    """
    Custom reducer for step_results:
    - If new value is an empty list [], RESET (start of a new query)
    - Otherwise APPEND (accumulate within a query's execution)
    """
    if not new:  # Orchestrator sends [] to signal new query
        return []
    return (existing or []) + new


def reduce_step_index(existing: int, new: int) -> int:
    """
    Custom reducer for current_step_index:
    - If new value is -1, RESET to 0 (start of a new query)
    - Otherwise ADD (accumulate within a query's execution)
    """
    if new == -1:  # Orchestrator sends -1 to signal reset
        return 0
    return (existing or 0) + new


class DashboardContext(TypedDict, total=False):
    """Context captured from Tableau dashboard."""
    dashboard_name: str
    worksheets: List[Dict[str, Any]]
    filters: List[Dict[str, Any]]
    parameters: List[Dict[str, Any]]
    datasources: List[Dict[str, Any]]
    selected_marks: List[Dict[str, Any]]


class DashboardAgentState(TypedDict, total=False):
    """LangGraph state for Dashboard Agent."""
    # Input
    question: str
    username: str
    dashboard_context: DashboardContext
    dashboard_config: Optional[Dict[str, Any]]  # Config enrichment from YAML
    pending_question: Optional[str] # To track original question during scope clarification
    
    # Processing
    intent: str  # chat, capability, dashboard_context, clarification, data_query, comparison, anomaly, storytelling
    query_type: str  # For data queries: 'standard', 'comparison', 'anomaly', 'storytelling'
    context_scope: str  # 'filtered' (use dashboard filters) or 'global' (all data)
    messages: Annotated[List[BaseMessage], add]  # Conversation history
    
    # Output
    response: str
    analysis: str
    results: Optional[Dict[str, Any]]
    visualization: Optional[Dict[str, Any]]
    needs_clarification: bool
    
    # Orchestration & Planning (Thinking Expert Analyst)
    plan: Optional[List[Dict[str, Any]]] # List of steps [{"expert": "node", "question": "..."}]
    step_results: Annotated[List[Dict[str, Any]], reduce_step_results] # Smart reset+accumulate
    current_step_index: Annotated[int, reduce_step_index] # Smart reset+accumulate
    pending_observations: List[str] # Insights generated during execution to inform the re-planner
    
    # Metadata
    status: str
    error: Optional[str]
    processing_time_ms: float


# =============================================================================
# Prompts
# =============================================================================

ORCHESTRATOR_SYSTEM = """You are the Lead Expert Analyst for a Tableau Dashboard. Your ONLY job is to PLAN which expert(s) should handle the user's question.

Available Experts (use EXACTLY these names):
- chat: ONLY for greetings, thanks, casual conversation ("hi", "thanks", "bye")
- capability: ONLY for "what can you do?" or "help" questions
- dashboard_context: ONLY for questions about the CURRENT STATE of the dashboard UI ("what filters are active?", "what worksheets exist?", "what datasources are connected?")
- dashboard_action: ONLY for requests to CHANGE the dashboard ("filter by X", "clear filters", "navigate to sheet Y")
- clarification: ONLY when the question is a single vague word like "sales" or "profit" with no verb
- data_query: For ANY question requiring DATA RETRIEVAL from Tableau ("total sales by region", "top 5 customers", "what is the profit?", "show me revenue trends")
- comparison: For comparing two or more things using data ("compare East vs West", "Q1 vs Q2")
- anomaly: For finding outliers or unusual patterns in data ("any anomalies?", "what's unusual?")
- storytelling: For narrative summaries requiring data ("summarize this dashboard", "executive summary")

CRITICAL RULES:
1. `data_query` is the DEFAULT for any analytical question. If it asks about numbers, totals, trends, rankings, or anything that needs actual data — use `data_query`.
2. `dashboard_context` is ONLY for UI state questions (filters, worksheets, datasources). NEVER use it for data analysis.
3. `comparison`, `anomaly`, and `storytelling` ALL require fetching real data from Tableau — they are specialized data queries.
4. For multi-part requests (e.g., "Filter to East and check anomalies"), create multiple steps.
5. If the user answered a previous scope clarification with a filter (e.g., "for West region"), plan: [dashboard_action, data_query].

EXAMPLES:
- "Hello" → {{"plan": [{{"expert": "chat", "question": "Hello", "reasoning": "Greeting"}}]}}  
- "What can you do?" → {{"plan": [{{"expert": "capability", "question": "What can you do?", "reasoning": "Asking about capabilities"}}]}}
- "What filters are active?" → {{"plan": [{{"expert": "dashboard_context", "question": "What filters are active?", "reasoning": "Asking about current dashboard state"}}]}}
- "Total sales by region" → {{"plan": [{{"expert": "data_query", "question": "Total sales by region", "reasoning": "Needs data from Tableau"}}]}}
- "Top 5 customers by profit" → {{"plan": [{{"expert": "data_query", "question": "Top 5 customers by profit", "reasoning": "Ranking query needs data"}}]}}
- "Compare East vs West sales" → {{"plan": [{{"expert": "comparison", "question": "Compare East vs West sales", "reasoning": "Comparison of two regions"}}]}}
- "Any anomalies in profit?" → {{"plan": [{{"expert": "anomaly", "question": "Any anomalies in profit?", "reasoning": "Looking for outliers"}}]}}
- "Filter to West and show top products" → {{"plan": [{{"expert": "dashboard_action", "question": "Filter to West region", "reasoning": "Apply filter first"}}, {{"expert": "data_query", "question": "Top products", "reasoning": "Then query data"}}]}}

Context:
Dashboard: {dashboard_name}
Active Filters: {filters}
Worksheets: {worksheets}
Conversation History: {history}

Question: "{question}"

Respond with ONLY a JSON object:
{{"plan": [{{"expert": "expert_name", "question": "question for this expert", "reasoning": "why"}}]}}"""


SYNTHESIS_SYSTEM = """You are a senior data analyst synthesizing results from multiple queries.

Question: {question}
Results: {results}

RULES:
1. Lead with the direct answer — numbers first, narrative second.
2. Cite exact values from the results. NEVER invent numbers.
3. Use markdown tables for comparisons. Use bold for key figures.
4. Be concise: max 3-4 paragraphs. No filler or boilerplate.
5. If results contain errors or empty data, say so plainly.
6. End with exactly 2-3 actionable follow-up suggestions prefixed with 💡.

Format:
[Direct answer with key numbers]
[Supporting analysis — 2-3 paragraphs max]

💡 **Next steps:**
- [Specific data-driven follow-up]
- [Related metric to investigate]"""


CHAT_RESPONSE_SYSTEM = """You are an AI data analyst in a Tableau dashboard.
Respond in 1-2 sentences max. Be direct and professional. No essays."""


CAPABILITY_RESPONSE_SYSTEM = """You are an AI data analyst in the "{dashboard_name}" dashboard.
Datasources: {datasources}

Respond with a SHORT bullet list (max 6 bullets). No paragraphs, no elaboration.
Capabilities:
- Answer data questions (top N, totals, trends)
- Compare regions, periods, categories
- Detect anomalies and outliers
- Apply filters and navigate the dashboard
- Generate executive summaries

Limit response to the bullet list only."""


CONTEXT_RESPONSE_SYSTEM = """You are an AI assistant reporting the current state of the Tableau dashboard.

Dashboard Name: {dashboard_name}
Active Filters: {filters}
Worksheets: {worksheets}
Datasources: {datasources}

RESPOND WITH A CONCISE BULLET LIST. Do NOT write essays or narratives.
Format:
- **Dashboard:** name
- **Active Filters:** list each filter as Field = Value
- **Worksheets:** list names
- **Datasources:** list names

If a filter value is "Null - Null" or empty, say "No date filter applied" instead.
Only include sections the user asked about. Be brief."""


CLARIFICATION_SYSTEM = """The user's question is too vague. Ask for clarification with 2-3 specific suggestions.
Dashboard: {dashboard_name}
Available data: {datasources}
Current filters: {filters}

Also ask if they want to:
1. Search within the current filter context (e.g., "only West region")
2. Search across all data (global/unfiltered)

Be brief and helpful."""


DASHBOARD_ACTION_SYSTEM = """You are an AI assistant that can control a Tableau dashboard.
Parse the user's request and return a JSON object with the action to perform.

Dashboard: {dashboard_name}
Available Worksheets: {worksheets}
Current Filters: {filters}
Available Parameters: {parameters}

CRITICAL RULES:
1. You MUST ONLY use worksheet names from the "Available Worksheets" list above.
2. Do NOT invent worksheet names like "Overview", "Sheet1", or anything not in the list.
3. When the user says "filter dashboard by X" or "filter by X", use worksheet "all" to apply across ALL worksheets.
4. When the user says "clear all filters" without specifying a worksheet, use worksheet "all".
5. For "Region" filters, the field name is "Region". For date filters, use "Order Date".

Supported actions:
1. apply_filter - Apply a filter to one or ALL worksheets
   {{"action": "apply_filter", "worksheet": "all", "field": "Region", "values": ["East"], "message": "Filter applied..."}}
   {{"action": "apply_filter", "worksheet": "Sale Map", "field": "Region", "values": ["West"], "message": "Filter applied..."}}
   
2. clear_filter - Clear a specific filter
   {{"action": "clear_filter", "worksheet": "all", "field": "Region", "message": "Filter cleared..."}}

3. clear_all_filters - Clear all filters on one or all worksheets
   {{"action": "clear_all_filters", "worksheet": "all", "message": "All filters cleared..."}}
   
4. set_parameter - Set a parameter value
   {{"action": "set_parameter", "name": "Parameter Name", "value": "new value", "message": "Parameter set..."}}

5. navigate - Navigate to a different worksheet/sheet
   {{"action": "navigate", "worksheet": "Sheet Name", "message": "Navigating..."}}

Respond with ONLY a valid JSON object. Include a "message" field with a friendly confirmation message.
If the request is unclear, respond with:
{{"action": "error", "message": "I couldn't understand that. Available worksheets: {worksheets}. Try 'filter by Region = West' or 'clear all filters'."}}"""



CONTEXT_SCOPE_SYSTEM = """You are analyzing if a user's data query should use dashboard filters or search globally.

Dashboard Filters: {filters}

Based on the question, determine the scope:
- 'filtered' = Use current dashboard filters (default for most queries)
- 'global' = Ignore filters, search all data

Explicit global keywords: "all", "across all", "overall", "total", "globally", "ignoring filters", "without filter", "entire dataset"
Explicit filtered keywords: "this region", "current filter", "as filtered", "what's shown", "in this view"

Question: {question}

Respond with exactly one word: 'filtered' or 'global'"""


# Specialized analysis prompts
COMPARISON_ANALYSIS_PROMPT = """You are analyzing a COMPARISON query. Structure your response as:

## Comparison: {comparison_elements}

### Executive Summary
[One sentence comparing the key difference]

### Detailed Comparison
| Metric | {element_1} | {element_2} | Difference | % Change |
|--------|-------------|-------------|------------|----------|
[Fill with actual data]

### Key Insights
1. **Winner:** [Which performed better overall]
2. **Biggest Gap:** [Where the largest difference exists]
3. **Trend:** [Is the gap growing or shrinking, if temporal]

### Recommendation
[Actionable insight based on comparison]

Data: {data}
Question: {question}
Filters Applied: {filters}"""


ANOMALY_DETECTION_PROMPT = """You are analyzing data for ANOMALIES and OUTLIERS. Structure your response as:

## 🔍 Anomaly Detection Results

### Summary
[X anomalies found in Y data points]

### Detected Anomalies

| Item | Expected | Actual | Deviation | Severity |
|------|----------|--------|-----------|----------|
[List each anomaly with severity: 🔴 High, 🟡 Medium, 🟢 Low]

### Pattern Analysis
1. **Outliers:** [Data points significantly outside normal range]
2. **Sudden Changes:** [Unexpected spikes or drops]
3. **Missing Patterns:** [Expected trends that didn't occur]

### Root Cause Hypotheses
- [Possible explanation 1]
- [Possible explanation 2]

### Recommended Actions
1. [Investigation needed]
2. [Immediate action if critical]

Data: {data}
Question: {question}
Statistical context: Calculate Z-scores, IQR, or percentage deviation as appropriate."""


STORYTELLING_PROMPT = """You are creating a DATA STORY / EXECUTIVE SUMMARY. Structure your response as:

## 📊 Dashboard Story: {dashboard_name}

### The Big Picture
[2-3 sentence executive summary a CEO could understand in 10 seconds]

### Key Headlines
🎯 **Main Takeaway:** [Single most important insight]
📈 **Performance:** [Overall trend - up/down/stable]
⚠️ **Watch Out:** [Key concern or risk]
💡 **Opportunity:** [Actionable opportunity]

### By The Numbers
- **{metric_1}:** {value_1} ({trend})
- **{metric_2}:** {value_2} ({trend})
- **{metric_3}:** {value_3} ({trend})

### What This Means
[Narrative explanation connecting the data to business impact]

### Recommended Next Steps
1. [Action item 1]
2. [Action item 2]
3. [Action item 3]

---
📋 *Report generated from: {dashboard_name}*
📅 *Filters: {filters}*

Data: {data}
Dashboard Context: {context}"""


# =============================================================================
# Dashboard Agent (LangGraph Implementation)
# =============================================================================

class DashboardAgent:
    """
    LangGraph-based Dashboard Agent for Tableau Extension.
    
    Uses LangGraph's StateGraph for workflow management and MemorySaver
    for multi-turn conversation support.
    """
    
    # Class-level checkpointer (shared for conversation memory)
    _checkpointer = None
    
    def __init__(self):
        """Initialize the Dashboard Agent with LangGraph."""
        self._llm = None
        self._data_agent = None
        self._compiled_graph = None
        logger.info("Dashboard Agent (LangGraph) initialized")
    
    @classmethod
    def get_checkpointer(cls):
        """Get or create shared checkpointer for persistent conversation memory.
        
        Uses PostgreSQL for persistence (survives container restarts).
        Falls back to MemorySaver if Postgres is unavailable.
        """
        if cls._checkpointer is None:
            try:
                from src.core.config import settings
                db_url = settings.sync_database_url
                cls._checkpointer = PostgresSaver.from_conn_string(db_url)
                cls._checkpointer.setup()  # Create tables if they don't exist
                logger.info("Initialized PostgreSQL-backed checkpointer for persistent memory")
            except Exception as e:
                logger.warning(f"PostgreSQL checkpointer failed, falling back to MemorySaver: {e}")
                cls._checkpointer = MemorySaver()
        return cls._checkpointer
    
    @property
    def llm(self):
        """Get LLM instance (lazy initialization)."""
        if self._llm is None:
            if settings.llm_provider == "azure":
                if not settings.azure_openai_configured:
                    raise ValueError("Azure OpenAI not configured")
                self._llm = AzureChatOpenAI(
                    azure_deployment=settings.azure_openai_deployment,
                    azure_endpoint=settings.azure_openai_endpoint,
                    api_key=settings.azure_openai_api_key,
                    api_version=settings.azure_openai_api_version,
                    temperature=settings.openai_temperature,
                )
            else:
                if not settings.openai_configured:
                    raise ValueError("OpenAI not configured")
                self._llm = ChatOpenAI(
                    model=settings.openai_model,
                    temperature=settings.openai_temperature,
                    api_key=settings.openai_api_key,
                )
        return self._llm
    
    @property
    def data_agent(self) -> TableauAgent:
        """Get Data Agent instance (lazy initialization)."""
        if self._data_agent is None:
            self._data_agent = TableauAgent()
        return self._data_agent
    
    @property
    def graph(self):
        """Get compiled LangGraph (lazy initialization)."""
        if self._compiled_graph is None:
            workflow = self._build_graph()
            self._compiled_graph = workflow.compile(checkpointer=self.get_checkpointer())
            logger.info("Dashboard Agent graph compiled")
        return self._compiled_graph
    
    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow for Dashboard Agent."""
        graph = StateGraph(DashboardAgentState)
        
        # Add core orchestration nodes
        graph.add_node("orchestrate", self._orchestrate)
        graph.add_node("replan", self._replan)
        graph.add_node("synthesize", self._synthesize)
        
        # Add expert nodes (workers)
        graph.add_node("handle_chat", self._handle_chat)
        graph.add_node("handle_capability", self._handle_capability)
        graph.add_node("handle_context", self._handle_context)
        graph.add_node("handle_clarification", self._handle_clarification)
        graph.add_node("handle_dashboard_action", self._handle_dashboard_action)
        graph.add_node("handle_data_query", self._handle_data_query)
        graph.add_node("handle_comparison", self._handle_comparison)
        graph.add_node("handle_anomaly", self._handle_anomaly)
        graph.add_node("handle_storytelling", self._handle_storytelling)
        
        # Entry point
        graph.set_entry_point("orchestrate")
        
        # Routing from orchestrator (starts the loop)
        graph.add_conditional_edges(
            "orchestrate",
            self._get_next_step,
            {
                "chat": "handle_chat",
                "capability": "handle_capability",
                "dashboard_context": "handle_context",
                "clarification": "handle_clarification",
                "dashboard_action": "handle_dashboard_action",
                "data_query": "handle_data_query",
                "comparison": "handle_comparison",
                "anomaly": "handle_anomaly",
                "storytelling": "handle_storytelling",
                "complete": "synthesize"
            }
        )

        # Expert nodes always go to replan
        graph.add_edge("handle_chat", "replan")
        graph.add_edge("handle_capability", "replan")
        graph.add_edge("handle_context", "replan")
        graph.add_edge("handle_clarification", "replan")
        graph.add_edge("handle_dashboard_action", "replan")
        graph.add_edge("handle_data_query", "replan")
        graph.add_edge("handle_comparison", "replan")
        graph.add_edge("handle_anomaly", "replan")
        graph.add_edge("handle_storytelling", "replan")

        # Replanner goes back to dispatcher
        graph.add_conditional_edges(
            "replan",
            self._get_next_step,
            {
                "chat": "handle_chat",
                "capability": "handle_capability",
                "dashboard_context": "handle_context",
                "clarification": "handle_clarification",
                "dashboard_action": "handle_dashboard_action",
                "data_query": "handle_data_query",
                "comparison": "handle_comparison",
                "anomaly": "handle_anomaly",
                "storytelling": "handle_storytelling",
                "complete": "synthesize"
            }
        )
        
        # Final synthesis ends the graph
        graph.add_edge("synthesize", END)
        
        return graph

    def _get_next_step(self, state: DashboardAgentState) -> str:
        """Conditional edge that determines the next expert to invoke or if it's time to synthesize."""
        plan = state.get("plan", [])
        idx = state.get("current_step_index", 0)
        
        if not plan or idx >= len(plan):
            logger.info("Plan complete or empty, routing to synthesis")
            return "complete"
            
        next_task = plan[idx]
        expert = next_task.get("expert")
        
        logger.info(f"Routing to next expert: {expert}", step=idx + 1, total=len(plan))
        
        # Map expert names to edge keys
        expert_map = {
            "chat": "chat",
            "capability": "capability",
            "dashboard_context": "dashboard_context",
            "dashboard_action": "dashboard_action",
            "clarification": "clarification",
            "data_query": "data_query",
            "comparison": "comparison",
            "anomaly": "anomaly",
            "storytelling": "storytelling",
        }
        
        return expert_map.get(expert, "complete")
    
    # =========================================================================
    # Node Implementations
    # =========================================================================
    
    async def _orchestrate(self, state: DashboardAgentState, config: RunnableConfig = None) -> DashboardAgentState:
        """The Planning node: Analyzes intent and context to build a multi-step plan."""
        question = state.get("question", "")
        context = state.get("dashboard_context", {})
        history = state.get("messages", [])
        
        # Build history string for LLM
        history_str = ""
        if history:
            recent = history[-6:]
            history_str = "\n".join([f"{'User' if isinstance(m, HumanMessage) else 'AI'}: {m.content[:200]}" for m in recent])
            
        logger.info("Orchestrating analysis", question=question[:50])
        
        # --- Phase 2: Enrich orchestrator with domain knowledge ---
        enrichment_parts = []
        
        # (a) Data Dictionary context
        data_dict = get_data_dictionary()
        if data_dict and not data_dict.is_empty():
            dd_context = data_dict.to_prompt_context()
            if dd_context:
                enrichment_parts.append(dd_context)
                logger.info("Data dictionary injected into orchestrator", field_count=len(data_dict._fields))
        
        # (b) Dashboard config (KPIs, glossary, ai_instructions)
        dashboard_name = context.get("dashboard_name", "")
        if dashboard_name:
            config_service = get_config_service()
            dash_config = config_service.get_config(dashboard_name)
            if dash_config:
                config_context = self._build_config_context({
                    "kpis": [{"name": k.name, "field": k.field, "description": k.description, "target": k.target} for k in dash_config.kpis],
                    "glossary": dash_config.glossary,
                    "ai_instructions": dash_config.ai_instructions,
                })
                if config_context:
                    enrichment_parts.append(config_context)
                    logger.info("Dashboard config injected into orchestrator", dashboard=dashboard_name)
        
        enrichment_str = ""
        if enrichment_parts:
            enrichment_str = "\n\n--- Domain Knowledge ---\n" + "\n\n".join(enrichment_parts)
        
        # (c) Cross-datasource awareness
        datasources = context.get("datasources", [])
        if len(datasources) > 1:
            ds_names = [d.get("name", "Unknown") for d in datasources]
            enrichment_str += f"\n\nAvailable datasources: {', '.join(ds_names)}. You may plan queries across different datasources for richer cross-cutting analysis."
        
        # (d) Feedback-driven learning
        feedback_ctx = await self._get_feedback_context(question)
        if feedback_ctx:
            enrichment_str += feedback_ctx
        
        prompt = ORCHESTRATOR_SYSTEM.format(
            dashboard_name=context.get("dashboard_name", "Unknown"),
            filters=json.dumps(context.get("filters", [])),
            worksheets=", ".join([w.get("name", "") for w in context.get("worksheets", [])]),
            history=history_str,
            question=question
        )
        
        # Append domain knowledge after the prompt
        if enrichment_str:
            prompt = prompt + enrichment_str
        
        try:
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            content = response.content.strip()
            
            # --- Phase 3: Robust JSON extraction ---
            plan_data = self._extract_json(content)
            plan = plan_data.get("plan", [])
            
            if not plan:
                logger.warning("Orchestrator returned empty plan, defaulting to data_query")
                plan = [{"expert": "data_query", "question": question, "reasoning": "Fallback"}]
                
            logger.info("Plan generated", steps=len(plan), plan=[p['expert'] for p in plan])
            
            return {
                "plan": plan,
                "current_step_index": -1,  # Sentinel: custom reducer resets to 0
                "step_results": [],          # Sentinel: custom reducer clears old results
                "messages": [HumanMessage(content=question)] # Persists via add reducer
            }
            
        except Exception as e:
            logger.error("Orchestration failed", error=str(e))
            # Fallback to simple data query
            return {
                "plan": [{"expert": "data_query", "question": question, "reasoning": "Error fallback"}],
                "current_step_index": -1,  # Sentinel: reset
                "step_results": [],
                "messages": [HumanMessage(content=question)]
            }

    async def _replan(self, state: DashboardAgentState) -> DashboardAgentState:
        """The Adaptive node: Reviews progress and adjusts the plan if needed."""
        step_results = state.get("step_results", [])
        if not step_results:
            return state
            
        last_result = step_results[-1]
        
        # 1. If the last expert flagged that clarification is needed, stop the plan early
        if last_result.get("needs_clarification"):
            logger.info("Clarification needed, truncating plan")
            state["current_step_index"] = len(state.get("plan", []))
            
        # 2. If the last step was a critical data error, stop the pipeline
        # Don't run anomaly/comparison on top of a failed data query
        if last_result.get("error") and last_result.get("expert") in [
            "data_query", "comparison", "anomaly", "storytelling"
        ]:
            logger.warning(
                "Data pipeline error, stopping plan execution",
                expert=last_result.get("expert"),
                error=str(last_result.get("error"))[:100]
            )
            state["current_step_index"] = len(state.get("plan", []))

        return state

    async def _synthesize(self, state: DashboardAgentState) -> DashboardAgentState:
        """The Final node: Merges all expert outputs into a single premium narrative."""
        question = state.get("question", "")
        step_results = state.get("step_results", [])
        
        if not step_results:
            state["analysis"] = "I couldn't gather enough data to answer that."
            state["status"] = "complete"
            return state
            
        logger.info("Synthesizing final response", step_count=len(step_results))
        
        # --- Aggregate technical fields from ALL steps ---
        for res in reversed(step_results):
            if res.get("results") and not state.get("results"):
                state["results"] = res["results"]
            if res.get("visualization") and not state.get("visualization"):
                state["visualization"] = res["visualization"]
            if res.get("needs_clarification"):
                state["needs_clarification"] = True
            
            # If we have a dashboard action, merge it into results
            if res.get("dashboard_action") and not state.get("results", {}).get("dashboard_action"):
                if not state.get("results"): state["results"] = {}
                state["results"]["dashboard_action"] = res["dashboard_action"]
        
        # --- Map expert name to user-facing intent ---
        expert_to_intent = {
            "chat": "chat",
            "capability": "capability",
            "dashboard_context": "dashboard_context",
            "dashboard_action": "dashboard_action",
            "clarification": "clarification",
            "data_query": "data_query",
            "comparison": "comparison",
            "anomaly": "anomaly",
            "storytelling": "storytelling",
        }
        if step_results:
            primary_expert = step_results[0].get("expert", "data_query")
            state["intent"] = expert_to_intent.get(primary_expert, "data_query")
        
        # --- NON-DATA EXPERT BYPASS: Return raw handler output for chat/capability/context/action ---
        NON_DATA_EXPERTS = {"chat", "capability", "dashboard_context", "dashboard_action", "clarification"}
        DATA_EXPERTS = {"data_query", "comparison", "anomaly", "storytelling"}
        
        primary_expert = step_results[0].get("expert", "") if step_results else ""
        all_non_data = all(r.get("expert") in NON_DATA_EXPERTS for r in step_results)
        
        if all_non_data:
            # For non-data intents, return the handler's analysis directly — no LLM synthesis
            analysis = step_results[-1].get("analysis", "")
            state["analysis"] = analysis
            state["status"] = "complete"
            state["messages"] = [AIMessage(content=analysis)]
            logger.info("Non-data expert: bypassing synthesis", expert=primary_expert)
            return state
        
        # --- SINGLE-STEP DATA BYPASS: Skip LLM re-synthesis for single data expert ---
        if len(step_results) == 1 and primary_expert in DATA_EXPERTS:
            single = step_results[0]
            analysis = single.get("analysis", "")
            
            # Generate proactive insights for data-oriented responses
            analysis = await self._generate_proactive_insight(analysis, question)
            
            # Append trust footer (citation + confidence)
            citation = single.get("citation")
            if citation and isinstance(citation, SourceCitation):
                citation_str = format_citation(citation)
                if citation_str:
                    analysis = f"{analysis}\n\n---\n{citation_str}"
                confidence = single.get("confidence", "")
                confidence_reason = single.get("confidence_reason", "")
                if confidence:
                    analysis = f"{analysis}\n{confidence} **Confidence** — {confidence_reason}"
            
            state["analysis"] = analysis
            state["status"] = "complete"
            state["messages"] = [AIMessage(content=state["analysis"])]
            logger.info("Single-step data plan: bypassing synthesis LLM call")
            return state
        
        # --- MULTI-STEP: Synthesize results from multiple experts ---
        results_str = "\n---\n".join([
            f"Expert: {res.get('expert')}\nQuestion: {res.get('question')}\nResult: {res.get('analysis') or 'Action completed'}"
            for res in step_results
        ])
        
        prompt = SYNTHESIS_SYSTEM.format(
            question=question,
            results=results_str
        )
        
        try:
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            analysis = response.content.strip()
            
            # Append aggregated trust footer for multi-step plans
            citations = [r.get("citation") for r in step_results if isinstance(r.get("citation"), SourceCitation)]
            if citations:
                citations_str = format_citations(citations)
                if citations_str:
                    analysis = f"{analysis}\n\n---\n{citations_str}"
            
            state["analysis"] = analysis
            state["status"] = "complete"
            
            # Persistent AIMessage
            state["messages"] = [AIMessage(content=state["analysis"])]
            
        except Exception as e:
            logger.error("Synthesis failed", error=str(e))
            # Fallback: concatenate raw expert outputs
            state["analysis"] = "\n\n---\n\n".join([r.get("analysis", "") for r in step_results])
            state["status"] = "complete"
            
        return state
    
    
    async def _handle_chat(self, state: DashboardAgentState) -> Dict[str, Any]:
        """Handle conversational messages without data queries."""
        plan = state.get("plan", [])
        idx = state.get("current_step_index", 0)
        task = plan[idx] if idx < len(plan) else {}
        question = task.get("question", state.get("question", ""))
        
        logger.info("Handling chat worker", question=question[:50])
        
        try:
            response = await self.llm.ainvoke([
                SystemMessage(content=CHAT_RESPONSE_SYSTEM),
                HumanMessage(content=question)
            ])
            analysis = response.content
        except Exception as e:
            analysis = "I'm here to help! What would you like to know about your data?"
            
        return {
            "step_results": [{
                "expert": "chat",
                "question": question,
                "analysis": analysis
            }],
            "current_step_index": 1
        }
    
    async def _handle_capability(self, state: DashboardAgentState) -> Dict[str, Any]:
        """Explain capabilities briefly."""
        plan = state.get("plan", [])
        idx = state.get("current_step_index", 0)
        task = plan[idx] if idx < len(plan) else {}
        question = task.get("question", state.get("question", ""))
        context = state.get("dashboard_context", {})
        
        dashboard_name = context.get("dashboard_name", "your dashboard")
        datasources = [ds.get("name", "") for ds in context.get("datasources", [])]
        
        logger.info("Handling capability worker")
        
        try:
            system_prompt = CAPABILITY_RESPONSE_SYSTEM.format(
                dashboard_name=dashboard_name,
                datasources=", ".join(datasources) if datasources else "your data"
            )
            
            response = await self.llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=question)
            ])
            analysis = response.content
        except Exception as e:
            analysis = "I can analyze your data, find trends, and help you navigate this dashboard."
            
        return {
            "step_results": [{
                "expert": "capability",
                "question": question,
                "analysis": analysis
            }],
            "current_step_index": 1
        }
    
    async def _handle_context(self, state: DashboardAgentState) -> Dict[str, Any]:
        """Explain the current dashboard state."""
        plan = state.get("plan", [])
        idx = state.get("current_step_index", 0)
        task = plan[idx] if idx < len(plan) else {}
        question = task.get("question", state.get("question", ""))
        context = state.get("dashboard_context", {})
        
        dashboard_name = context.get("dashboard_name", "Dashboard")
        worksheets = [w.get("name", "") for w in context.get("worksheets", [])]
        filters = [f"{f.get('field')}={f.get('value')}" for f in context.get("filters", [])]
        datasources = [ds.get("name", "") for ds in context.get("datasources", [])]
        
        logger.info("Handling context worker")
        
        try:
            system_prompt = CONTEXT_RESPONSE_SYSTEM.format(
                dashboard_name=dashboard_name,
                filters=", ".join(filters) if filters else "None",
                worksheets=", ".join(worksheets) if worksheets else "None",
                datasources=", ".join(datasources) if datasources else "None"
            )
            
            response = await self.llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=question)
            ])
            analysis = response.content
        except Exception as e:
            analysis = f"You are viewing '{dashboard_name}'."
            
        return {
            "step_results": [{
                "expert": "dashboard_context",
                "question": question,
                "analysis": analysis
            }],
            "current_step_index": 1
        }
    
    async def _handle_clarification(self, state: DashboardAgentState) -> Dict[str, Any]:
        """Ask for clarification on vague questions."""
        plan = state.get("plan", [])
        idx = state.get("current_step_index", 0)
        task = plan[idx] if idx < len(plan) else {}
        question = task.get("question", state.get("question", ""))
        context = state.get("dashboard_context", {})
        
        dashboard_name = context.get("dashboard_name", "your dashboard")
        datasources = [ds.get("name", "") for ds in context.get("datasources", [])]
        
        logger.info("Handling clarification worker")
        
        try:
            system_prompt = CLARIFICATION_SYSTEM.format(
                dashboard_name=dashboard_name,
                datasources=", ".join(datasources) if datasources else "your data",
                filters=", ".join([f"{f.get('field')}={f.get('value')}" for f in context.get("filters", [])]) if context.get("filters") else "None"
            )
            
            response = await self.llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"User said: '{question}'")
            ])
            
            analysis = response.content
        except Exception as e:
            analysis = "Could you be more specific? Try: 'Total sales by region' or 'Top 5 customers'"
            
        return {
            "step_results": [{
                "expert": "clarification",
                "question": question,
                "analysis": analysis,
                "needs_clarification": True
            }],
            "current_step_index": 1
        }
    
    async def _handle_dashboard_action(self, state: DashboardAgentState) -> Dict[str, Any]:
        """Handle requests to modify the dashboard (filters, parameters, navigation)."""
        plan = state.get("plan", [])
        idx = state.get("current_step_index", 0)
        task = plan[idx] if idx < len(plan) else {}
        question = task.get("question", state.get("question", ""))
        context = state.get("dashboard_context", {})
        
        dashboard_name = context.get("dashboard_name", "Dashboard")
        worksheets = context.get("worksheets", [])
        filters = context.get("filters", [])
        parameters = context.get("parameters", [])
        
        worksheets_str = ", ".join([w.get("name", "") for w in worksheets]) if worksheets else "No worksheets detected"
        filters_str = ", ".join([f"{f.get('field')}={f.get('value', 'All')}" for f in filters]) if filters else "None"
        parameters_str = ", ".join([f"{p.get('name')}={p.get('value', '')}" for p in parameters]) if parameters else "None"
        
        logger.info("Handling dashboard action worker")
        
        if not worksheets:
            return {
                "step_results": [{
                    "expert": "dashboard_action",
                    "question": question,
                    "analysis": "I can't see any worksheets in your dashboard. If you're running this in Tableau, try refreshing the extension.",
                    "error": "No worksheets detected"
                }],
                "current_step_index": 1
            }

        try:
            system_prompt = DASHBOARD_ACTION_SYSTEM.format(
                dashboard_name=dashboard_name,
                worksheets=worksheets_str,
                filters=filters_str,
                parameters=parameters_str
            )
            
            response = await self.llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=question)
            ])
            
            # Parse JSON action
            content = response.content.strip()
            if content.startswith("```json"):
                content = content[7:-3].strip()
            
            action_data = json.loads(content)
            
            # Clean action message badge
            if action_data.get("message"):
                 action_data["message"] = f"⚡ **Dashboard Action:** {action_data['message']}"
            
            logger.info("Dashboard action parsed", action=action_data.get("action"))
            
            return {
                "step_results": [{
                    "expert": "dashboard_action",
                    "question": question,
                    "analysis": action_data.get("message", "Dashboard action triggered."),
                    "dashboard_action": action_data
                }],
                "current_step_index": 1
            }
            
        except Exception as e:
            logger.error("Dashboard action worker failed", error=str(e))
            return {
                "step_results": [{
                    "expert": "dashboard_action",
                    "question": question,
                    "analysis": f"Failed to perform dashboard action: {str(e)}",
                    "error": str(e)
                }],
                "current_step_index": 1
            }
    
    async def _handle_data_query(self, state: DashboardAgentState) -> Dict[str, Any]:
        """Delegate data query to Data Agent (VizQL) with context scope handling."""
        plan = state.get("plan", [])
        idx = state.get("current_step_index", 0)
        task = plan[idx] if idx < len(plan) else {}
        question = task.get("question", state.get("question", ""))
        context = state.get("dashboard_context", {})
        
        # Aggregate base filters and orchestrated filters
        base_filters = self._sanitize_filters(context.get("filters", []))
        orch_filters = self._get_orchestrated_filters(state)
        filters = self._merge_filters(base_filters, orch_filters)
        
        logger.info("Handling data query worker", question=question[:50], orch_filters=len(orch_filters))
        
        try:
            # Use pre-resolved scope or detect it
            context_scope = state.get("context_scope")
            if not context_scope:
                context_scope = await self._detect_context_scope(question, filters, state.get("messages", []))
            
            # Handle ambiguous scope
            if context_scope == "ambiguous" and filters:
                clarification = self._create_scope_clarification(filters, "data")
                return {
                    "step_results": [{
                        "expert": "data_query",
                        "question": question,
                        "analysis": clarification,
                        "needs_clarification": True
                    }],
                    "current_step_index": 1
                }
            
            filter_context = None
            if context_scope == "filtered" and filters:
                filter_context = self._build_filter_context(filters)
            
            enhanced_question = question
            if filter_context:
                enhanced_question = f"{question}\n\n[Dashboard Filter Context: {filter_context}. Apply these filters to the query.]"
            
            result = await self._execute_with_retry(
                question=enhanced_question,
                datasource_id=None,
                filters=filters if context_scope == "filtered" else None
            )
            
            # --- Trust Layer: validate and cite ---
            citation = build_citation_from_result(result, filters)
            confidence_level, confidence_reason = compute_confidence(result)
            analysis = validate_data_response(result.get("analysis", ""), result)
            
            if citation.data_grounded and analysis:
                scope_indicator = "🔍 **Data Scope:** " + (
                    f"Filtered by {filter_context}" if context_scope == "filtered" and filter_context
                    else "All data (global)"
                )
                analysis = f"{scope_indicator}\n\n{analysis}"
                if context_scope == "filtered":
                    analysis = self._enrich_with_context(analysis, context)
            
            return {
                "step_results": [{
                    "expert": "data_query",
                    "question": question,
                    "analysis": analysis,
                    "results": result.get("results"),
                    "visualization": result.get("visualization"),
                    "error": result.get("error"),
                    "status": "complete" if result.get("success") else "error",
                    "citation": citation,
                    "confidence": confidence_level,
                    "confidence_reason": confidence_reason,
                }],
                "current_step_index": 1
            }
            
        except Exception as e:
            logger.error("Data query worker failed", error=str(e))
            return {
                "step_results": [{
                    "expert": "data_query",
                    "question": question,
                    "analysis": f"⚠️ **Data Unavailable:** Failed to query Tableau data.\n\n**Reason:** {str(e)}\n\nI will not generate a response without verified data.",
                    "error": str(e)
                }],
                "current_step_index": 1
            }

    async def _handle_comparison(self, state: DashboardAgentState) -> Dict[str, Any]:
        """Handle comparison queries."""
        plan = state.get("plan", [])
        idx = state.get("current_step_index", 0)
        task = plan[idx] if idx < len(plan) else {}
        question = task.get("question", state.get("question", ""))
        context = state.get("dashboard_context", {})
        
        # Aggregate base filters and orchestrated filters
        base_filters = self._sanitize_filters(context.get("filters", []))
        orch_filters = self._get_orchestrated_filters(state)
        filters = self._merge_filters(base_filters, orch_filters)
        
        logger.info("Handling comparison worker", question=question[:50], orch_filters=len(orch_filters))
        
        try:
            enhanced_question = f"""{question}

[COMPARISON ANALYSIS REQUIRED]
Please identify elements being compared, calculate differences, and highlight performers."""
            
            context_scope = state.get("context_scope") or await self._detect_context_scope(question, filters, state.get("messages", []))
            
            if context_scope == "ambiguous" and filters:
                return {
                    "step_results": [{
                        "expert": "comparison",
                        "question": question,
                        "analysis": self._create_scope_clarification(filters, "comparison"),
                        "needs_clarification": True
                    }],
                    "current_step_index": 1
                }
            
            result = await self._execute_with_retry(
                question=enhanced_question,
                datasource_id=None,
                filters=filters if context_scope == "filtered" else None
            )
            
            # --- Trust Layer ---
            citation = build_citation_from_result(result, filters)
            confidence_level, confidence_reason = compute_confidence(result)
            analysis = validate_data_response(result.get("analysis", ""), result)
            
            if citation.data_grounded and analysis:
                analysis = f"📊 **Comparison Analysis**\n\n{analysis}"
            
            return {
                "step_results": [{
                    "expert": "comparison",
                    "question": question,
                    "analysis": analysis,
                    "results": result.get("results"),
                    "visualization": result.get("visualization"),
                    "error": result.get("error"),
                    "citation": citation,
                    "confidence": confidence_level,
                    "confidence_reason": confidence_reason,
                }],
                "current_step_index": 1
            }
        except Exception as e:
            return {
                "step_results": [{
                    "expert": "comparison",
                    "question": question,
                    "analysis": f"⚠️ **Data Unavailable:** Failed to run comparison.\n\n**Reason:** {str(e)}"
                }],
                "current_step_index": 1
            }

    async def _handle_anomaly(self, state: DashboardAgentState) -> Dict[str, Any]:
        """Handle anomaly detection queries (outliers, unusual patterns)."""
        plan = state.get("plan", [])
        idx = state.get("current_step_index", 0)
        task = plan[idx] if idx < len(plan) else {}
        question = task.get("question", state.get("question", ""))
        context = state.get("dashboard_context", {})
        
        # Aggregate base filters and orchestrated filters
        base_filters = self._sanitize_filters(context.get("filters", []))
        orch_filters = self._get_orchestrated_filters(state)
        filters = self._merge_filters(base_filters, orch_filters)
        
        logger.info("Handling anomaly worker", question=question[:50], orch_filters=len(orch_filters))
        
        try:
            enhanced_question = f"""{question}

[ANOMALY DETECTION REQUIRED]
Please identify outliers, sudden spikes/drops, and rate their severity."""
            
            context_scope = state.get("context_scope") or await self._detect_context_scope(question, filters, state.get("messages", []))
            
            if context_scope == "ambiguous" and filters:
                return {
                    "step_results": [{
                        "expert": "anomaly",
                        "question": question,
                        "analysis": self._create_scope_clarification(filters, "anomaly"),
                        "needs_clarification": True
                    }],
                    "current_step_index": 1
                }
            
            result = await self._execute_with_retry(
                question=enhanced_question,
                datasource_id=None,
                filters=filters if context_scope == "filtered" else None
            )
            
            # --- Trust Layer ---
            citation = build_citation_from_result(result, filters)
            confidence_level, confidence_reason = compute_confidence(result)
            analysis = validate_data_response(result.get("analysis", ""), result)
            
            if citation.data_grounded and analysis:
                analysis = f"🔍 **Anomaly Detection**\n\n{analysis}"
            
            return {
                "step_results": [{
                    "expert": "anomaly",
                    "question": question,
                    "analysis": analysis,
                    "results": result.get("results"),
                    "visualization": result.get("visualization"),
                    "error": result.get("error"),
                    "citation": citation,
                    "confidence": confidence_level,
                    "confidence_reason": confidence_reason,
                }],
                "current_step_index": 1
            }
        except Exception as e:
            return {
                "step_results": [{
                    "expert": "anomaly",
                    "question": question,
                    "analysis": f"⚠️ **Data Unavailable:** Failed to run anomaly detection.\n\n**Reason:** {str(e)}"
                }],
                "current_step_index": 1
            }

    async def _handle_storytelling(self, state: DashboardAgentState) -> Dict[str, Any]:
        """Handle narrative summary/storytelling queries."""
        plan = state.get("plan", [])
        idx = state.get("current_step_index", 0)
        task = plan[idx] if idx < len(plan) else {}
        question = task.get("question", state.get("question", ""))
        context = state.get("dashboard_context", {})
        
        # Aggregate base filters and orchestrated filters
        base_filters = self._sanitize_filters(context.get("filters", []))
        orch_filters = self._get_orchestrated_filters(state)
        filters = self._merge_filters(base_filters, orch_filters)
        
        logger.info("Handling storytelling worker", orch_filters=len(orch_filters))
        
        try:
            # For storytelling, we usually want significant context
            enhanced_question = f"""{question}

[STORYTELLING/NARRATIVE REQUIRED]
Please provide a comprehensive narrative summary of the data."""
            
            context_scope = state.get("context_scope") or await self._detect_context_scope(question, filters, state.get("messages", []))
            
            if context_scope == "ambiguous" and filters:
                return {
                    "step_results": [{
                        "expert": "storytelling",
                        "question": question,
                        "analysis": self._create_scope_clarification(filters, "storytelling"),
                        "needs_clarification": True
                    }],
                    "current_step_index": 1
                }
            
            result = await self._execute_with_retry(
                question=enhanced_question,
                datasource_id=None,
                filters=filters if context_scope == "filtered" else None
            )
            
            # --- Trust Layer ---
            citation = build_citation_from_result(result, filters)
            confidence_level, confidence_reason = compute_confidence(result)
            analysis = validate_data_response(result.get("analysis", ""), result)
            
            if citation.data_grounded and analysis:
                analysis = f"📖 **Dashboard Story**\n\n{analysis}"
            
            return {
                "step_results": [{
                    "expert": "storytelling",
                    "question": question,
                    "analysis": analysis,
                    "results": result.get("results"),
                    "visualization": result.get("visualization"),
                    "error": result.get("error"),
                    "citation": citation,
                    "confidence": confidence_level,
                    "confidence_reason": confidence_reason,
                }],
                "current_step_index": 1
            }
        except Exception as e:
            return {
                "step_results": [{
                    "expert": "storytelling",
                    "question": question,
                    "analysis": f"⚠️ **Data Unavailable:** Failed to generate story.\n\n**Reason:** {str(e)}"
                }],
                "current_step_index": 1
            }

    def _get_orchestrated_filters(self, state: DashboardAgentState) -> List[Dict]:
        """Aggregate filters from previous dashboard actions in the current plan execution."""
        step_results = state.get("step_results", [])
        orch_filters = []
        
        for res in step_results:
            if res.get("expert") == "dashboard_action" and res.get("dashboard_action"):
                action = res["dashboard_action"]
                if action.get("action") == "apply_filter":
                    field = action.get("field")
                    values = action.get("values", [])
                    if field and values:
                        # Convert to DashboardContext filter format
                        orch_filters.append({
                            "field": field,
                            "value": values[0] if isinstance(values, list) else values,
                            "is_orchestrated": True
                        })
                elif action.get("action") == "clear_all_filters":
                    orch_filters = [] # Simplification: clear overrides
                    
        return orch_filters

    def _merge_filters(self, base: List[Dict], orch: List[Dict]) -> List[Dict]:
        """Merge base filters with orchestrated filters (orch takes precedence)."""
        if not orch: return base
        
        merged = {f["field"]: f for f in base}
        for f in orch:
            merged[f["field"]] = f
            
        return list(merged.values())
    
    async def _detect_context_scope(self, question: str, filters: List[Dict], history: List[BaseMessage] = None) -> str:
        """
        Detect whether user wants filtered (dashboard context) or global (all data) results.
        Fully LLM-powered. Uses conversation history for scope memory so users
        aren't repeatedly asked the same scope question.
        
        Returns:
            'filtered' - Apply dashboard filters to query
            'global' - Search all data ignoring filters
            'ambiguous' - Unclear, should ask user (only on first ambiguous query)
        """
        # No filters = always global (logical shortcut)
        if not filters:
            return "global"
        
        # Recent dashboard action context is handled by LLM rules below
        pass
        
        # Build conversation context for scope memory
        conv_context = ""
        if history:
            recent = history[-6:]
            conv_lines = []
            for msg in recent:
                role = "User" if isinstance(msg, HumanMessage) else "AI"
                # Truncate long messages but keep scope indicators
                content = msg.content[:200]
                conv_lines.append(f"{role}: {content}")
            conv_context = "\nRecent conversation:\n" + "\n".join(conv_lines)
        
        # LLM-based classification with conversation memory
        try:
            filter_context = self._build_filter_context(filters)
            
            scope_prompt = f"""You are determining what data scope a user wants for their query.

Current dashboard filters: {filter_context}
{conv_context}

User's current question: "{question}"

Determine the user's data scope intent. Respond with exactly one word:
- FILTERED: User explicitly wants results limited to the current dashboard filters
- GLOBAL: User explicitly wants all data, ignoring dashboard filters
- AMBIGUOUS: User has NOT specified a scope preference

CRITICAL rules (follow in order):
1. If the question contains explicit global signals ("all data", "complete data", "across all", "overall", "entire dataset", "globally", "whole data", "ignoring filters", "without filters"), return GLOBAL
2. If the question contains explicit filtered signals ("this view", "here", "current view", "as filtered", "with these filters", "in this scope"), return FILTERED
3. If conversation history shows the most recent AI message was a dashboard action (marker: "[DASHBOARD_ACTION]"), return FILTERED
4. If conversation history shows the user previously chose a scope, carry that preference forward
5. For ANY other case — including generic questions like "top 5 products" or "show me sales" — return FILTERED. An expert analyst always uses the active dashboard context.
6. NEVER return AMBIGUOUS. Always make a decision.

Respond with exactly one word: FILTERED, GLOBAL, or AMBIGUOUS"""

            response = await self.llm.ainvoke([HumanMessage(content=scope_prompt)])
            result = response.content.strip().upper()
            
            if "FILTERED" in result:
                logger.info("LLM scope detection: filtered", question=question[:30])
                return "filtered"
            elif "GLOBAL" in result:
                logger.info("LLM scope detection: global", question=question[:30])
                return "global"
            else:
                logger.info("LLM scope detection: ambiguous", question=question[:30])
                return "ambiguous"
                
        except Exception as e:
            logger.warning("LLM scope detection failed, defaulting to ambiguous", error=str(e))
            return "ambiguous"
    
    def _create_scope_clarification(self, filters: List[Dict], query_type: str = "data") -> str:
        """Create a clarification message when scope is ambiguous."""
        filter_context = self._build_filter_context(filters)
        
        type_examples = {
            "data": ('Top 5 customers', 'Top 5 customers'),
            "comparison": ('Compare Q1 vs Q2', 'Compare Q1 vs Q2'),
            "anomaly": ('Find anomalies', 'Find anomalies'),
            "storytelling": ('Summarize the data', 'Summarize the data'),
        }
        example = type_examples.get(query_type, type_examples["data"])
        
        return (
            f"📊 **I notice you have filters applied:** {filter_context}\n\n"
            f"Would you like results for:\n"
            f"- **Current view** (filtered by {filter_context})\n"
            f"- **All data** (global, ignoring filters)\n\n"
            f"💡 **Tip:** You can say:\n"
            f'- "{example[0]} **in this view**" for filtered results\n'
            f'- "{example[1]} **across all data**" for global results'
        )
    
    def _sanitize_filters(self, filters: List[Dict]) -> List[Dict]:
        """Remove filters with problematic field names that VizQL cannot process.
        
        Strips out:
        - Action filters (e.g. 'Action (MONTH(Order Date), Segment)')
        - Computed aggregates (e.g. 'AGG(Profit Ratio)')
        - Boolean calc fields ending with '?' (e.g. 'Order Profitable?')
        - Filters with null/empty/None values
        """
        if not filters:
            return []
        
        clean = []
        for f in filters:
            field = f.get("field", "")
            value = f.get("value")
            
            # Skip filters with no value
            if not value or str(value).lower() in ("none", "null", "null - null"):
                continue
            
            # Skip Action filters (Tableau internal)
            if field.startswith("Action ") or field.startswith("Action("):
                continue
            
            # Skip computed aggregates like AGG(Profit Ratio)
            if field.startswith("AGG(") or field.startswith("SUM(") or field.startswith("AVG("):
                continue
            
            # Skip boolean calc fields ending with '?'
            if field.endswith("?"):
                continue
            
            clean.append(f)
        
        return clean
    
    def _build_filter_context(self, filters: List[Dict]) -> str:
        """Build a human-readable filter context string."""
        if not filters:
            return ""
        
        # Sanitize first to remove problematic fields
        clean_filters = self._sanitize_filters(filters)
        
        filter_parts = []
        for f in clean_filters:
            field = f.get("field", "")
            value = f.get("value")
            if field and value:
                filter_parts.append(f"{field}='{value}'")
        
        return ", ".join(filter_parts) if filter_parts else ""
    
    # =========================================================================
    # Helper Methods
    # =========================================================================
    
    def _extract_json(self, text: str) -> Dict[str, Any]:
        """
        Robustly extract JSON from LLM output.
        
        Handles:
        - Clean JSON: {"plan": [...]}
        - Markdown wrapped: ```json\n{...}\n```
        - Extra text before/after: "Here is the plan:\n{...}\nLet me know"
        - Regex fallback for edge cases
        """
        text = text.strip()
        
        # 1. Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        
        # 2. Try stripping markdown code blocks
        if "```" in text:
            # Match ```json ... ``` or ``` ... ```
            match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1).strip())
                except json.JSONDecodeError:
                    pass
        
        # 3. Try finding JSON object with regex
        match = re.search(r'\{[^{}]*"plan"\s*:\s*\[.*?\]\s*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        
        # 4. Try finding any JSON object
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        
        # 5. All parsing failed
        logger.error("JSON extraction failed completely", raw_text=text[:200])
        raise ValueError(f"Could not extract valid JSON from LLM output: {text[:100]}...")
    
    async def _execute_with_retry(self, question: str, datasource_id=None, filters=None) -> Dict[str, Any]:
        """
        Execute a data query with retry logic for transient failures.
        
        Retries up to 2 times on connection/timeout errors with exponential backoff.
        Does NOT retry on query logic errors (wrong field names, etc).
        """
        last_error = None
        for attempt in range(3):  # 1 initial + 2 retries
            try:
                result = await self.data_agent.execute_data_query(
                    question=question,
                    datasource_id=datasource_id,
                    filters=filters
                )
                
                # If the result itself indicates a transient error, retry
                error = result.get("error", "")
                if error and attempt < 2 and any(t in error.lower() for t in ["timeout", "connection", "unavailable", "502", "503"]):
                    logger.warning(f"Transient data query error (attempt {attempt+1}/3), retrying...", error=error[:100])
                    await asyncio.sleep(1.5 ** attempt)  # exponential backoff: 1s, 1.5s
                    last_error = error
                    continue
                
                # Auto-discover schema on success (Fix 4: self-learning)
                if result.get("success"):
                    self._auto_discover_schema(result)
                
                return result
                
            except (ConnectionError, TimeoutError, asyncio.TimeoutError) as e:
                last_error = str(e)
                if attempt < 2:
                    logger.warning(f"Transient error (attempt {attempt+1}/3), retrying...", error=str(e)[:100])
                    await asyncio.sleep(1.5 ** attempt)
                else:
                    logger.error("All retry attempts exhausted", error=str(e)[:100])
                    return {"success": False, "error": f"Failed after 3 attempts: {e}", "results": {}}
        
        return {"success": False, "error": f"Failed after 3 attempts: {last_error}", "results": {}}
    
    def _auto_discover_schema(self, result: Dict[str, Any]) -> None:
        """
        Auto-populate data dictionary from successful query results.
        
        This makes the system self-learning: the first successful query teaches
        the agent what fields exist in the datasource, improving future queries.
        """
        from src.agent.data_dictionary import get_data_dictionary, set_data_dictionary, DataDictionary, FieldDefinition
        
        dd = get_data_dictionary()
        if dd and not dd.is_empty():
            return  # Already populated, skip
        
        # Extract field names from result data
        data = result.get("results", {}).get("data", [])
        if not data:
            return
        
        # Build field definitions from the column names we see
        fields = []
        sample_row = data[0]
        for col_name, value in sample_row.items():
            data_type = "number" if isinstance(value, (int, float)) else "text"
            fields.append(FieldDefinition(
                field_name=col_name,
                business_name=col_name,  # Same as field name initially
                description=f"Auto-discovered from query results",
                data_type=data_type,
                example_values=[str(value)][:3] if value is not None else [],
            ))
        
        if fields:
            new_dd = DataDictionary(fields=fields)
            set_data_dictionary(new_dd)
            ds_name = result.get("datasource", {}).get("name", "Unknown")
            logger.info(f"Auto-discovered schema from {ds_name}", field_count=len(fields))
    
    def _build_trust_metadata(self, state_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build structured trust metadata for frontend rendering.
        
        Returns a dict with:
        - citations: list of source citation dicts
        - confidence: {level, emoji, reason}
        - datasources_used: list of datasource names
        - row_count: total rows analyzed
        """
        step_results = state_data.get("step_results", [])
        citations = []
        total_rows = 0
        datasources = set()
        confidence_level = "unknown"
        confidence_emoji = "⚪"
        confidence_reason = ""
        
        for res in step_results:
            citation = res.get("citation")
            if citation and isinstance(citation, SourceCitation):
                citations.append({
                    "datasource": citation.datasource_name,
                    "row_count": citation.row_count,
                    "filters_applied": citation.filters_applied,
                    "timestamp": citation.timestamp,
                    "query_time_ms": citation.query_time_ms,
                    "data_grounded": citation.data_grounded,
                })
                total_rows += citation.row_count
                datasources.add(citation.datasource_name)
            
            # Extract confidence from step results
            if res.get("confidence"):
                confidence_level = "high" if "🟢" in res["confidence"] else "medium" if "🟡" in res["confidence"] else "low"
                confidence_emoji = res["confidence"].split(" ")[0] if res["confidence"] else "⚪"
                confidence_reason = res.get("confidence_reason", "")
        
        return {
            "citations": citations,
            "confidence": {
                "level": confidence_level,
                "emoji": confidence_emoji,
                "reason": confidence_reason,
            },
            "datasources_used": list(datasources),
            "total_rows_analyzed": total_rows,
        }
    
    async def _generate_proactive_insight(self, analysis: str, question: str) -> str:
        """
        Generate proactive insight for single-step responses.
        
        For single-step plans (which skip synthesis), the ANALYZER_PROMPT
        doesn't include proactive insights. This method adds them via a
        lightweight LLM call.
        """
        # Skip for non-data intents
        if not analysis or len(analysis) < 50:
            return analysis
        
        try:
            insight_prompt = f"""Based on this data analysis, suggest 2-3 proactive follow-up insights.

Question asked: {question}
Analysis provided: {analysis[:500]}

Respond with ONLY:
💡 **You might also want to explore:**
- [Observation about a pattern worth investigating]
- [A follow-up question that would deepen understanding]
- [A related metric or dimension the user should check]

Be specific to the data discussed. No generic suggestions."""
            
            response = await self.llm.ainvoke([HumanMessage(content=insight_prompt)])
            insight_text = response.content.strip()
            
            if insight_text and "💡" in insight_text:
                return f"{analysis}\n\n{insight_text}"
            return analysis
            
        except Exception as e:
            logger.warning("Proactive insight generation failed", error=str(e))
            return analysis
    
    async def _get_feedback_context(self, question: str) -> str:
        """
        Retrieve relevant past feedback to inform query planning.
        
        Queries the QueryFeedback table for similar past queries and their
        feedback, returning a context string that helps the orchestrator
        learn from past mistakes and successes.
        """
        try:
            from src.db.database import get_session
            from src.db.models import Query as QueryModel, QueryFeedback, FeedbackType
            from sqlalchemy import select, desc
            
            async with get_session() as session:
                # Get recent disliked queries to learn from failures
                stmt = (
                    select(QueryModel.question, QueryModel.response_text, QueryFeedback.comment)
                    .join(QueryFeedback, QueryModel.id == QueryFeedback.query_id)
                    .where(QueryFeedback.feedback_type == FeedbackType.DISLIKE)
                    .order_by(desc(QueryFeedback.created_at))
                    .limit(3)
                )
                result = await session.execute(stmt)
                disliked = result.all()
                
                if not disliked:
                    return ""
                
                feedback_lines = []
                for q, resp, comment in disliked:
                    line = f"- Question: \"{q[:60]}\" was DISLIKED"
                    if comment:
                        line += f" (reason: {comment[:50]})"
                    feedback_lines.append(line)
                
                return (
                    "\n\n== LEARNING FROM PAST FEEDBACK ==\n"
                    "The following past responses were rated poorly. Avoid similar approaches:\n"
                    + "\n".join(feedback_lines)
                )
                
        except Exception as e:
            logger.debug("Feedback context retrieval skipped", error=str(e))
            return ""
    
    def _build_config_context(self, config: Optional[Dict]) -> str:
        """Build prompt context from dashboard config."""
        if not config:
            return ""
        
        parts = []
        
        # KPIs
        kpis = config.get("kpis", [])
        if kpis:
            kpi_lines = []
            for kpi in kpis:
                name = kpi.get("name", "")
                field = kpi.get("field", "")
                desc = kpi.get("description", "")
                target = kpi.get("target")
                if name:
                    line = f"- {name}"
                    if field:
                        line += f" (field: {field})"
                    if desc:
                        line += f": {desc}"
                    if target:
                        line += f" [target: {target}]"
                    kpi_lines.append(line)
            if kpi_lines:
                parts.append("KEY METRICS:\n" + "\n".join(kpi_lines))
        
        # Glossary
        glossary = config.get("glossary", {})
        if glossary:
            glossary_lines = []
            for term, definition in glossary.items():
                if isinstance(definition, dict):
                    field = definition.get("field", "")
                    desc = definition.get("description", "")
                    glossary_lines.append(f"- {term} → {field}" + (f" ({desc})" if desc else ""))
                else:
                    glossary_lines.append(f"- {term} → {definition}")
            if glossary_lines:
                parts.append("BUSINESS TERMS:\n" + "\n".join(glossary_lines))
        
        # AI Instructions
        ai_instructions = config.get("ai_instructions")
        if ai_instructions:
            parts.append(f"SPECIAL INSTRUCTIONS:\n{ai_instructions.strip()}")
        
        return "\n\n".join(parts)
    
    def _format_context_summary(self, context: DashboardContext, config: Optional[Dict] = None) -> str:
        """Format context for LLM prompts, including config enrichment."""
        if not context:
            return "No dashboard context"
        
        parts = []
        if context.get("dashboard_name"):
            parts.append(f"Dashboard: {context['dashboard_name']}")
        if context.get("filters"):
            filters = [f"{f.get('field')}={f.get('value', 'All')}" for f in context["filters"]]
            parts.append(f"Filters: {', '.join(filters)}")
        
        base_context = "; ".join(parts) if parts else "Minimal context"
        
        # Add config enrichment
        if config:
            config_context = self._build_config_context(config)
            if config_context:
                return f"{base_context}\n\n--- Dashboard Configuration ---\n{config_context}"
        
        return base_context
    
    def _enrich_with_context(self, analysis: str, context: DashboardContext) -> str:
        """Add filter context to analysis."""
        filters = self._sanitize_filters(context.get("filters", []))
        if not filters:
            return analysis
        
        filter_parts = [f"{f.get('field')}={f.get('value')}" for f in filters if f.get('value')]
        if filter_parts:
            return f"{analysis}\n\n📋 **Dashboard Context:** Filtered by: {', '.join(filter_parts)}"
        
        return analysis
    
    # =========================================================================
    # Public API
    # =========================================================================
    
    async def process(
        self,
        question: str,
        dashboard_context: Optional[DashboardContext] = None,
        username: str = "dashboard_user",
        thread_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process a question through the LangGraph workflow.
        
        Args:
            question: User's natural language question
            dashboard_context: Context from Tableau dashboard
            username: User identifier
            thread_id: Optional thread ID for conversation continuity
            
        Returns:
            Response dict with analysis, data, and metadata
        """
        start_time = datetime.now()
        
        # Lookup dashboard config (if exists)
        dashboard_name = (dashboard_context or {}).get("dashboard_name", "")
        config_service = get_config_service()
        dashboard_cfg = config_service.get_config(dashboard_name)
        
        # Convert config to dict for state (if found)
        config_dict = None
        if dashboard_cfg:
            config_dict = {
                "name": dashboard_cfg.name,
                "kpis": [{"name": k.name, "field": k.field, "description": k.description, 
                         "target": k.target, "format": k.format} for k in dashboard_cfg.kpis],
                "glossary": dashboard_cfg.glossary,
                "ai_instructions": dashboard_cfg.ai_instructions,
                "suggested_questions": dashboard_cfg.suggested_questions,
                "anomaly_thresholds": dashboard_cfg.anomaly_thresholds,
            }
            logger.info("Dashboard config found", dashboard=dashboard_name, config_file=dashboard_cfg._source_file)
        
        # Build initial state
        initial_state: DashboardAgentState = {
            "question": question.strip(),
            "username": username,
            "dashboard_context": dashboard_context or {},
            "dashboard_config": config_dict,
            "status": "started",
            # We don't set "needs_clarification": False here because we want 
            # to preserve its value from the previous turn in multi-turn mode
        }
        
        # Thread for conversation memory
        # Use session thread_id for multi-turn memory. Safe because custom reducers
        # reset per-query ephemeral state (step_results, current_step_index) on each call.
        effective_thread_id = thread_id or str(uuid.uuid4())
        config = {"configurable": {"thread_id": effective_thread_id}}
        
        try:
            # Run the LangGraph workflow
            final_state = await asyncio.wait_for(
                self.graph.ainvoke(initial_state, config=config),
                timeout=240  # 4 minute timeout
            )
            
            processing_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return {
                "success": final_state.get("status") == "complete",
                "intent": final_state.get("intent"),
                "analysis": final_state.get("analysis"),
                "results": final_state.get("results"),
                "visualization": final_state.get("visualization"),
                "needs_clarification": final_state.get("needs_clarification", False),
                "error": final_state.get("error"),
                "processing_time_ms": processing_time,
                "thread_id": effective_thread_id,
            }
            
        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": "Request timed out",
                "analysis": "The request took too long. Please try a simpler question.",
            }
        except Exception as e:
            logger.exception("Dashboard Agent error", error=str(e))
            return {
                "success": False,
                "error": str(e),
                "analysis": f"Error: {str(e)}",
            }

    async def process_stream(
        self,
        question: str,
        dashboard_context: Optional[DashboardContext] = None,
        username: str = "dashboard_user",
        thread_id: Optional[str] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Process a question and yield real-time orchestrated events using LangGraph's streaming.
        """
        dashboard_name = (dashboard_context or {}).get("dashboard_name", "")
        config_service = get_config_service()
        dashboard_cfg = config_service.get_config(dashboard_name)
        
        config_dict = None
        if dashboard_cfg:
            config_dict = {
                "name": dashboard_cfg.name,
                "kpis": [{"name": k.name, "field": k.field} for k in dashboard_cfg.kpis],
                "ai_instructions": dashboard_cfg.ai_instructions,
            }
            
        initial_state: DashboardAgentState = {
            "question": question.strip(),
            "username": username,
            "dashboard_context": dashboard_context or {},
            "dashboard_config": config_dict,
            "status": "started",
            "step_results": [],
            "current_step_index": 0
        }
        
        # Use session thread_id for multi-turn memory. Safe because custom reducers
        # reset per-query ephemeral state (step_results, current_step_index) on each call.
        effective_thread_id = thread_id or str(uuid.uuid4())
        config = {"configurable": {"thread_id": effective_thread_id}}
        
        try:
            # Stream the graph execution
            async for event in self.graph.astream(initial_state, config=config, stream_mode="updates"):
                # 'event' is a dict mapping node names to their updates
                node_name = list(event.keys())[0]
                update = event[node_name]
                
                if node_name == "orchestrate":
                    plan = update.get("plan", [])
                    # Show full reasoning chain for transparency
                    plan_desc = []
                    for i, p in enumerate(plan, 1):
                        reason = p.get("reasoning", "")
                        plan_desc.append(f"Step {i}: {p.get('expert')} — {p.get('question', '')[:60]}")
                    yield {
                        "event": "thinking",
                        "message": f"📋 Plan ({len(plan)} steps):\\n" + "\\n".join(plan_desc),
                        "plan": plan
                    }
                elif node_name == "synthesize":
                    yield {
                        "event": "analyzing",
                        "message": "📝 Synthesizing final response with source citations..."
                    }
                elif node_name in ["handle_data_query", "handle_comparison", "handle_anomaly", "handle_storytelling"]:
                    # Extract step details from update
                    step_results = update.get("step_results", [])
                    last_step = step_results[-1] if step_results else {}
                    citation = last_step.get("citation")
                    confidence = last_step.get("confidence", "")
                    expert_name = node_name.replace("handle_", "")
                    
                    # Build rich status message
                    msg = f"🔬 Expert '{expert_name}' completed"
                    if citation and hasattr(citation, 'data_grounded') and citation.data_grounded:
                        msg += f" — {citation.row_count:,} rows from {citation.datasource_name}"
                    if confidence:
                        msg += f" | {confidence}"
                    if last_step.get("error"):
                        msg = f"⚠️ Expert '{expert_name}' failed: {str(last_step.get('error'))[:80]}"
                    
                    yield {
                        "event": "querying",
                        "message": msg
                    }
                elif node_name == "handle_dashboard_action":
                    yield {
                        "event": "thinking",
                        "message": "Preparing dashboard action..."
                    }
            
            # Final result from history/state
            # We pull the final state from the checkpointer
            final_state_ref = await self.graph.aget_state(config)
            state_data = final_state_ref.values
            
            yield {
                "event": "complete",
                "data": {
                    "success": state_data.get("status") == "complete",
                    "intent": state_data.get("intent"),
                    "query_type": state_data.get("query_type"),
                    "context_scope": state_data.get("context_scope"),
                    "analysis": state_data.get("analysis"),
                    "results": state_data.get("results"),
                    "visualization": state_data.get("visualization"),
                    "needs_clarification": state_data.get("needs_clarification", False),
                    "error": state_data.get("error"),
                    "thread_id": effective_thread_id,
                    # Structured trust metadata for frontend rendering
                    "trust": self._build_trust_metadata(state_data),
                }
            }
        except Exception as e:
            logger.exception("process_stream failed", error=str(e))
            yield {
                "event": "error",
                "data": {
                    "success": False,
                    "error": str(e)
                }
            }


# =============================================================================
# Singleton Instance
# =============================================================================

_dashboard_agent_instance = None

def get_dashboard_agent() -> DashboardAgent:
    """Get singleton Dashboard Agent instance."""
    global _dashboard_agent_instance
    if _dashboard_agent_instance is None:
        _dashboard_agent_instance = DashboardAgent()
    return _dashboard_agent_instance
