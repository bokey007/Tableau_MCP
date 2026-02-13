# =============================================================================
# Dashboard Agent - LangGraph-Based Master Orchestrator
# =============================================================================
"""
Dashboard Agent using LangGraph for the Tableau Extension.
Leverages LangGraph's StateGraph for routing and MemorySaver for conversation memory.

Architecture:
    User Question → classify_intent → route_by_intent
                                         │
              ┌──────────┬───────────────┼───────────────┬──────────────┐
              ▼          ▼               ▼               ▼              ▼
           [chat]  [capability]  [dashboard_context] [clarify]    [data_query]
              │          │               │               │              │
              └──────────┴───────────────┴───────────────┴──────────────┘
                                         │
                                         ▼
                                       [END]
"""

import re
import uuid
import asyncio
from typing import Any, Dict, List, Optional, Annotated, TypedDict
from datetime import datetime
from operator import add

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, BaseMessage
from langchain_openai import ChatOpenAI, AzureChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from src.core.config import settings
from src.core.logging import get_logger
from src.agent.graph import TableauAgent  # Import existing Data Agent
from src.services.config_service import get_config_service, DashboardConfig

logger = get_logger(__name__)


# =============================================================================
# State Definition (LangGraph Native)
# =============================================================================

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
    
    # Metadata
    status: str
    error: Optional[str]
    processing_time_ms: float


# =============================================================================
# Prompts
# =============================================================================

INTENT_CLASSIFIER_PROMPT = """Classify the user's intent. Respond with exactly ONE word from:
- chat (greetings, thanks, casual conversation)
- capability (asking what you can do, help)
- dashboard_context (asking about current filters, selections, what's shown, what datasources are used, what worksheets exist)
- dashboard_action (requests to CHANGE the dashboard: "filter by", "filter dashboard by", "show only", "set parameter", "clear filters", "go to sheet". IMPORTANT: if the user says "filter" + a value/region/category, this is ALWAYS dashboard_action, even if they include the word "dashboard")
- clarification (vague question needing more detail: single words like "sales", "profit")
- comparison (comparing time periods, regions, categories: "Q1 vs Q2", "compare East and West", "year over year")
- anomaly (unusual patterns, outliers: "what's unusual", "anomalies", "outliers", "unexpected")
- storytelling (narrative summary, presentation: "summarize", "tell me the story", "executive summary")
- data_query (standard data analysis: "top 5 customers", "total sales by region". NOT for filter/action requests)

Question: {question}
Dashboard Context: {context}

Intent:"""


CHAT_RESPONSE_SYSTEM = """You are a friendly AI analytics assistant embedded in a Tableau dashboard. 
Keep responses brief (1-2 sentences). Be warm and helpful."""


CAPABILITY_RESPONSE_SYSTEM = """You are an AI analytics assistant in a Tableau dashboard. Explain your capabilities briefly.
Available datasources: {datasources}
Current dashboard: {dashboard_name}

You can:
- Answer data questions in natural language
- Analyze trends, aggregations, comparisons
- Explain current filters and selections
- Help understand the dashboard

Keep response to 3-4 sentences."""


CONTEXT_RESPONSE_SYSTEM = """You are an AI assistant explaining the current dashboard state.
Dashboard: {dashboard_name}
Active Filters: {filters}
Worksheets: {worksheets}
Datasources: {datasources}

Answer the user's question about what's currently shown/selected, including datasource names if asked."""


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

Supported actions:
1. apply_filter - Apply a filter to a worksheet
   {{"action": "apply_filter", "worksheet": "Sheet Name", "field": "Field Name", "values": ["value1", "value2"]}}
   
2. clear_filter - Clear a specific filter or all filters
   {{"action": "clear_filter", "worksheet": "Sheet Name", "field": "Field Name"}}  # specific filter
   {{"action": "clear_all_filters", "worksheet": "Sheet Name"}}  # all filters on worksheet
   
3. set_parameter - Set a parameter value
   {{"action": "set_parameter", "name": "Parameter Name", "value": "new value"}}

4. navigate - Navigate to a different worksheet/sheet
   {{"action": "navigate", "worksheet": "Sheet Name"}}

User request: {question}

Respond with ONLY a valid JSON object. Include a "message" field with a friendly confirmation message.
If the request is unclear or the field/worksheet doesn't exist, respond with:
{{"action": "error", "message": "I couldn't find that field/worksheet. Available options are: ..."}}"""


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
    def get_checkpointer(cls) -> MemorySaver:
        """Get or create shared checkpointer for conversation memory."""
        if cls._checkpointer is None:
            cls._checkpointer = MemorySaver()
            logger.info("Initialized Dashboard Agent MemorySaver")
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
        
        # Add nodes
        graph.add_node("classify_intent", self._classify_intent)
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
        graph.set_entry_point("classify_intent")
        
        # Conditional routing based on intent
        graph.add_conditional_edges(
            "classify_intent",
            self._route_by_intent,
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
            }
        )
        
        # All handlers go to END
        graph.add_edge("handle_chat", END)
        graph.add_edge("handle_capability", END)
        graph.add_edge("handle_context", END)
        graph.add_edge("handle_clarification", END)
        graph.add_edge("handle_dashboard_action", END)
        graph.add_edge("handle_data_query", END)
        graph.add_edge("handle_comparison", END)
        graph.add_edge("handle_anomaly", END)
        graph.add_edge("handle_storytelling", END)
        
        return graph
    
    def _route_by_intent(self, state: DashboardAgentState) -> str:
        """Route to appropriate handler based on classified intent."""
        intent = state.get("intent", "data_query")
        
        # Map intent to node name
        intent_map = {
            "chat": "chat",
            "capability": "capability",
            "dashboard_context": "dashboard_context",
            "dashboard_action": "dashboard_action",
            "clarification_needed": "clarification",
            "clarification": "clarification",
            "data_query": "data_query",
            "comparison": "comparison",
            "anomaly": "anomaly",
            "storytelling": "storytelling",
        }
        
        return intent_map.get(intent, "data_query")
    
    # =========================================================================
    # Node Implementations
    # =========================================================================
    
    async def _classify_intent(self, state: DashboardAgentState) -> DashboardAgentState:
        """Classify user intent using heuristics + LLM fallback."""
        question = state.get("question", "")
        context = state.get("dashboard_context", {})
        config = state.get("dashboard_config")
        question_lower = question.lower().strip()
        
        logger.info("Classifying intent", question=question[:50])
        
        # Add user message to conversation history
        state["messages"] = [HumanMessage(content=question)]
        
        # Heuristic classification (fast path)
        intent = self._classify_by_heuristics(question_lower)
        
        if intent is None:
            # LLM fallback for ambiguous cases
            intent = await self._classify_by_llm(question, context, config)
        
        state["intent"] = intent
        logger.info("Intent classified", intent=intent)
        return state
    
    def _classify_by_heuristics(self, question_lower: str) -> Optional[str]:
        """Fast heuristic classification for common greetings/casual chatter."""
        
        # Chat patterns (simple greetings and polite phrases)
        chat_patterns = [
            r'^(hi|hello|hey|good morning|good afternoon|good evening)[\s!.,]*$',
            r'^(thanks|thank you|thx|ty)[\s!.,]*$',
            r'^(bye|goodbye|see you)[\s!.,]*$',
            r'^how are you',
        ]
        for pattern in chat_patterns:
            if re.match(pattern, question_lower):
                return "chat"
        
        # Capability patterns (asking "what can you do")
        capability_patterns = [
            r'what can you do',
            r'^help$',
            r'how does this work',
        ]
        for pattern in capability_patterns:
            if re.search(pattern, question_lower):
                return "capability"
        
        # Dashboard action patterns (filter/clear/set commands)
        action_patterns = [
            r'(?:filter|show only|switch to|go to|set)\s+(?:the\s+)?(?:dashboard\s+)?(?:by|to)\s+',
            r'filter\s+(?:the\s+)?dashboard',
            r'clear\s+(?:all\s+)?filters',
            r'remove\s+(?:all\s+)?filters',
        ]
        for pattern in action_patterns:
            if re.search(pattern, question_lower):
                return "dashboard_action"
        
        # Dashboard context patterns (asking about what's visible)
        context_patterns = [
            r'(?:what|which)\s+(?:is|are)\s+(?:the\s+)?(?:active\s+)?datasource',
            r'(?:what|which)\s+datasource',
            r'what\s+worksheets',
            r'what\s+sheets',
        ]
        for pattern in context_patterns:
            if re.search(pattern, question_lower):
                return "dashboard_context"
        
        # Note: All other analytical intents (queries, anomalies, storytelling) 
        # are intentionally left to the LLM classifier for better accuracy.
        
        return None  # Fallback to LLM
    
    async def _classify_by_llm(self, question: str, context: DashboardContext, config: Optional[Dict] = None) -> str:
        """Use LLM for ambiguous intent classification."""
        try:
            context_str = self._format_context_summary(context, config)
            prompt = INTENT_CLASSIFIER_PROMPT.format(
                question=question,
                context=context_str
            )
            
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            intent = response.content.strip().lower()
            
            valid_intents = [
                "chat", "capability", "dashboard_context", "dashboard_action",
                "clarification", "data_query", "comparison", "anomaly", "storytelling"
            ]
            if intent in valid_intents:
                return intent
            
            return "data_query"  # Default
            
        except Exception as e:
            logger.warning("LLM classification failed", error=str(e))
            return "data_query"
    
    async def _handle_chat(self, state: DashboardAgentState) -> DashboardAgentState:
        """Handle casual conversation with multi-turn memory."""
        question = state.get("question", "")
        
        try:
            # Build messages including conversation history
            messages = [SystemMessage(content=CHAT_RESPONSE_SYSTEM)]
            
            # Add conversation history from state (maintained by LangGraph checkpointer)
            history = state.get("messages", [])
            if history:
                # Include last 10 messages for context (5 turns)
                messages.extend(history[-10:])
            
            # Add current user message
            messages.append(HumanMessage(content=question))
            
            response = await self.llm.ainvoke(messages)
            
            state["analysis"] = response.content
            state["status"] = "complete"
            # Add both user message and response to conversation history
            state["messages"] = [
                HumanMessage(content=question),
                AIMessage(content=response.content)
            ]
            
        except Exception as e:
            logger.error("Chat handler error", error=str(e))
            state["analysis"] = "Hello! I'm here to help you analyze your dashboard data. What would you like to know?"
            state["status"] = "complete"
        
        return state
    
    async def _handle_capability(self, state: DashboardAgentState) -> DashboardAgentState:
        """Explain agent capabilities."""
        question = state.get("question", "")
        context = state.get("dashboard_context", {})
        
        dashboard_name = context.get("dashboard_name", "your dashboard")
        datasources = [ds.get("name", "data") for ds in context.get("datasources", [])]
        
        try:
            system_prompt = CAPABILITY_RESPONSE_SYSTEM.format(
                dashboard_name=dashboard_name,
                datasources=", ".join(datasources) if datasources else "connected datasources"
            )
            
            response = await self.llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=question)
            ])
            
            state["analysis"] = response.content
            state["status"] = "complete"
            
        except Exception as e:
            state["analysis"] = f"I can help analyze data in {dashboard_name}. Ask questions like 'Top 5 customers' or 'Sales trend by month'."
            state["status"] = "complete"
        
        return state
    
    async def _handle_context(self, state: DashboardAgentState) -> DashboardAgentState:
        """Answer questions about dashboard state."""
        question = state.get("question", "")
        context = state.get("dashboard_context", {})
        
        dashboard_name = context.get("dashboard_name", "Dashboard")
        filters = context.get("filters", [])
        worksheets = context.get("worksheets", [])
        
        filters_str = ", ".join([f"{f.get('field')}={f.get('value', 'All')}" for f in filters]) if filters else "None"
        worksheets_str = ", ".join([w.get("name", "") for w in worksheets]) if worksheets else "Unknown"
        datasources = context.get("datasources", [])
        datasources_str = ", ".join([ds.get("name", "") for ds in datasources]) if datasources else "Unknown"
        
        try:
            system_prompt = CONTEXT_RESPONSE_SYSTEM.format(
                dashboard_name=dashboard_name,
                filters=filters_str,
                worksheets=worksheets_str,
                datasources=datasources_str
            )
            
            response = await self.llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=question)
            ])
            
            state["analysis"] = response.content
            state["status"] = "complete"
            
        except Exception as e:
            state["analysis"] = f"Dashboard: {dashboard_name}. Filters: {filters_str}."
            state["status"] = "complete"
        
        return state
    
    async def _handle_clarification(self, state: DashboardAgentState) -> DashboardAgentState:
        """Ask for clarification on vague questions."""
        question = state.get("question", "")
        context = state.get("dashboard_context", {})
        
        dashboard_name = context.get("dashboard_name", "your dashboard")
        datasources = [ds.get("name", "") for ds in context.get("datasources", [])]
        
        try:
            system_prompt = CLARIFICATION_SYSTEM.format(
                dashboard_name=dashboard_name,
                datasources=", ".join(datasources) if datasources else "your data"
            )
            
            response = await self.llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"User said: '{question}'")
            ])
            
            state["analysis"] = response.content
            state["needs_clarification"] = True
            state["status"] = "complete"
            
        except Exception as e:
            state["analysis"] = "Could you be more specific? Try: 'Total sales by region' or 'Top 5 customers'"
            state["needs_clarification"] = True
            state["status"] = "complete"
        
        return state
    
    async def _handle_dashboard_action(self, state: DashboardAgentState) -> DashboardAgentState:
        """Handle requests to modify the dashboard (filters, parameters, navigation)."""
        question = state.get("question", "")
        context = state.get("dashboard_context", {})
        
        dashboard_name = context.get("dashboard_name", "Dashboard")
        worksheets = context.get("worksheets", [])
        filters = context.get("filters", [])
        parameters = context.get("parameters", [])
        
        worksheets_str = ", ".join([w.get("name", "") for w in worksheets]) if worksheets else "No worksheets detected"
        filters_str = ", ".join([f"{f.get('field')}={f.get('value', 'All')}" for f in filters]) if filters else "None"
        parameters_str = ", ".join([f"{p.get('name')}={p.get('value', '')}" for p in parameters]) if parameters else "None"
        
        if not worksheets:
            state["analysis"] = "I can't see any worksheets in your dashboard. If you're running this in Tableau, try refreshing the extension. If you're in standalone mode, some dashboard actions won't be available."
            state["intent"] = "clarification"
            state["status"] = "complete"
            return state

        try:
            system_prompt = DASHBOARD_ACTION_SYSTEM.format(
                dashboard_name=dashboard_name,
                worksheets=worksheets_str,
                filters=filters_str,
                parameters=parameters_str,
                question=question
            )
            
            response = await self.llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=question)
            ])
            
            # Parse the JSON response
            import json
            try:
                action_data = json.loads(response.content.strip())
            except json.JSONDecodeError:
                # Try to extract JSON from response
                import re
                json_match = re.search(r'\{.*\}', response.content, re.DOTALL)
                if json_match:
                    action_data = json.loads(json_match.group())
                else:
                    action_data = {
                        "action": "error",
                        "message": "I couldn't understand that action. Try 'filter by Region = West' or 'clear filters'."
                    }
            
            # Build response with action command for frontend
            state["analysis"] = action_data.get("message", "Action processed.")
            state["results"] = {
                "dashboard_action": action_data
            }
            state["status"] = "complete"
            
            logger.info("Dashboard action parsed", action=action_data.get("action"))
            
        except Exception as e:
            logger.error("Dashboard action handler error", error=str(e))
            state["analysis"] = "I couldn't process that action. Try: 'filter by Region = West' or 'clear all filters'."
            state["status"] = "complete"
        
        return state
    
    async def _handle_data_query(self, state: DashboardAgentState) -> DashboardAgentState:
        """Delegate data query to Data Agent (VizQL) with context scope handling."""
        question = state.get("question", "")
        context = state.get("dashboard_context", {})
        filters = context.get("filters", [])
        
        logger.info("Delegating to Data Agent", question=question[:50])
        
        try:
            # Detect context scope: filtered (use dashboard filters) or global (all data)
            context_scope = await self._detect_context_scope(question, filters)
            state["context_scope"] = context_scope
            
            logger.info("Context scope detected", scope=context_scope, filters_count=len(filters))
            
            # Handle ambiguous scope - ask user
            if context_scope == "ambiguous" and filters:
                state["needs_clarification"] = True
                state["analysis"] = self._create_scope_clarification(filters, "data")
                state["status"] = "clarification_needed"
                return state
            
            # Build filter context for query enhancement
            filter_context = None
            if context_scope == "filtered" and filters:
                filter_context = self._build_filter_context(filters)
                logger.info("Applying dashboard filters to query", filter_context=filter_context)
            
            # Enhance question with filter context if applicable
            enhanced_question = question
            if filter_context:
                enhanced_question = f"{question}\n\n[Dashboard Filter Context: {filter_context}. Apply these filters to the query.]"
            
            # Call Data Agent's execute_data_query
            result = await self.data_agent.execute_data_query(
                question=enhanced_question,
                datasource_id=None,
                filters=filters if context_scope == "filtered" else None
            )
            
            # Map result to state
            state["analysis"] = result.get("analysis", "")
            state["results"] = result.get("results")
            state["visualization"] = result.get("visualization")
            state["error"] = result.get("error")
            state["status"] = "complete" if result.get("success") else "error"
            
            # Enrich with dashboard context (scope indicator)
            if result.get("success") and state.get("analysis"):
                scope_indicator = "🔍 **Data Scope:** " + (
                    f"Filtered by {filter_context}" if context_scope == "filtered" and filter_context
                    else "All data (global)"
                )
                state["analysis"] = f"{scope_indicator}\n\n{state['analysis']}"
                # Only show dashboard context footer when filters were actually applied
                if context_scope == "filtered":
                    state["analysis"] = self._enrich_with_context(state["analysis"], context)
            
        except Exception as e:
            logger.error("Data query failed", error=str(e))
            state["error"] = str(e)
            state["analysis"] = f"Error analyzing data: {str(e)}"
            state["status"] = "error"
        
        return state
    
    async def _handle_comparison(self, state: DashboardAgentState) -> DashboardAgentState:
        """Handle comparison queries (Q1 vs Q2, year-over-year, region comparisons)."""
        question = state.get("question", "")
        context = state.get("dashboard_context", {})
        filters = context.get("filters", [])
        
        logger.info("Handling comparison query", question=question[:50])
        state["query_type"] = "comparison"
        
        try:
            # Enhance the question with comparison-specific instructions
            enhanced_question = f"""{question}

[COMPARISON ANALYSIS REQUIRED]
This is a comparison query. Please:
1. Identify the two or more elements being compared
2. Query data for each element separately if needed
3. Calculate differences and percentage changes
4. Structure the response with a clear comparison table
5. Highlight the winner/better performer
6. Note the biggest differences"""
            
            # Detect scope and execute
            context_scope = await self._detect_context_scope(question, filters)
            state["context_scope"] = context_scope
            
            # Handle ambiguous scope
            if context_scope == "ambiguous" and filters:
                state["needs_clarification"] = True
                state["analysis"] = self._create_scope_clarification(filters, "comparison")
                state["status"] = "clarification_needed"
                return state
            
            filter_context = self._build_filter_context(filters) if context_scope == "filtered" and filters else None
            if filter_context:
                enhanced_question += f"\n\n[Dashboard Filter Context: {filter_context}]"
            
            result = await self.data_agent.execute_data_query(
                question=enhanced_question,
                datasource_id=None,
                filters=filters if context_scope == "filtered" else None
            )
            
            # Map result with comparison badge
            if result.get("success") and result.get("analysis"):
                state["analysis"] = f"📊 **Comparison Analysis**\n\n{result.get('analysis', '')}"
            else:
                state["analysis"] = result.get("analysis", "")
            
            state["results"] = result.get("results")
            state["visualization"] = result.get("visualization")
            state["error"] = result.get("error")
            state["status"] = "complete" if result.get("success") else "error"
            
        except Exception as e:
            logger.error("Comparison query failed", error=str(e))
            state["error"] = str(e)
            state["analysis"] = f"Error in comparison analysis: {str(e)}"
            state["status"] = "error"
        
        return state
    
    async def _handle_anomaly(self, state: DashboardAgentState) -> DashboardAgentState:
        """Handle anomaly detection queries (outliers, unusual patterns)."""
        question = state.get("question", "")
        context = state.get("dashboard_context", {})
        filters = context.get("filters", [])
        
        logger.info("Handling anomaly detection query", question=question[:50])
        state["query_type"] = "anomaly"
        
        try:
            # Enhance the question with anomaly detection instructions
            enhanced_question = f"""{question}

[ANOMALY DETECTION REQUIRED]
This is an anomaly detection query. Please:
1. Retrieve relevant data with sufficient rows to detect patterns
2. Calculate statistical measures (mean, std dev, percentiles)
3. Identify values that deviate significantly (>2 standard deviations or outside IQR*1.5)
4. Check for sudden spikes or drops compared to previous periods
5. Note any missing or unexpected patterns
6. Rate each anomaly by severity (High/Medium/Low)
7. Suggest possible root causes"""
            
            # Detect scope and execute
            context_scope = await self._detect_context_scope(question, filters)
            state["context_scope"] = context_scope
            
            # Handle ambiguous scope
            if context_scope == "ambiguous" and filters:
                state["needs_clarification"] = True
                state["analysis"] = self._create_scope_clarification(filters, "anomaly")
                state["status"] = "clarification_needed"
                return state
            
            filter_context = self._build_filter_context(filters) if context_scope == "filtered" and filters else None
            if filter_context:
                enhanced_question += f"\n\n[Dashboard Filter Context: {filter_context}]"
            
            result = await self.data_agent.execute_data_query(
                question=enhanced_question,
                datasource_id=None,
                filters=filters if context_scope == "filtered" else None
            )
            
            # Map result with anomaly badge
            if result.get("success") and result.get("analysis"):
                state["analysis"] = f"🔍 **Anomaly Detection Results**\n\n{result.get('analysis', '')}"
            else:
                state["analysis"] = result.get("analysis", "")
            
            state["results"] = result.get("results")
            state["visualization"] = result.get("visualization")
            state["error"] = result.get("error")
            state["status"] = "complete" if result.get("success") else "error"
            
        except Exception as e:
            logger.error("Anomaly detection failed", error=str(e))
            state["error"] = str(e)
            state["analysis"] = f"Error in anomaly detection: {str(e)}"
            state["status"] = "error"
        
        return state
    
    async def _handle_storytelling(self, state: DashboardAgentState) -> DashboardAgentState:
        """Handle storytelling/narrative queries (executive summaries, presentations)."""
        question = state.get("question", "")
        context = state.get("dashboard_context", {})
        filters = context.get("filters", [])
        dashboard_name = context.get("dashboard_name", "Dashboard")
        
        logger.info("Handling storytelling query", question=question[:50])
        state["query_type"] = "storytelling"
        
        try:
            # Enhance the question with storytelling instructions
            filter_context = self._build_filter_context(filters) if filters else "No filters applied"
            
            enhanced_question = f"""{question}

[EXECUTIVE SUMMARY / DATA STORY REQUIRED]
Dashboard: {dashboard_name}
Filters: {filter_context}

Please create a compelling data story:
1. Start with "The Big Picture" - 2-3 sentences a CEO could understand in 10 seconds
2. Identify the main takeaway, overall performance trend, key concern, and opportunity
3. List 3-5 key metrics with values and trends
4. Explain what the data means for the business
5. Provide 3 actionable next steps
6. Keep it concise but insightful - suitable for an exec presentation"""
            
            # Detect scope and execute
            context_scope = await self._detect_context_scope(question, filters)
            state["context_scope"] = context_scope
            
            # Handle ambiguous scope
            if context_scope == "ambiguous" and filters:
                state["needs_clarification"] = True
                state["analysis"] = self._create_scope_clarification(filters, "storytelling")
                state["status"] = "clarification_needed"
                return state
            
            result = await self.data_agent.execute_data_query(
                question=enhanced_question,
                datasource_id=None,
                filters=filters if context_scope == "filtered" else None
            )
            
            # Map result with storytelling badge
            if result.get("success") and result.get("analysis"):
                state["analysis"] = f"📖 **Dashboard Story: {dashboard_name}**\n\n{result.get('analysis', '')}"
            else:
                state["analysis"] = result.get("analysis", "")
            
            state["results"] = result.get("results")
            state["visualization"] = result.get("visualization")
            state["error"] = result.get("error")
            state["status"] = "complete" if result.get("success") else "error"
            
        except Exception as e:
            logger.error("Storytelling query failed", error=str(e))
            state["error"] = str(e)
            state["analysis"] = f"Error generating story: {str(e)}"
            state["status"] = "error"
        
        return state
    
    async def _detect_context_scope(self, question: str, filters: List[Dict]) -> str:
        """
        Detect whether user wants filtered (dashboard context) or global (all data) results.
        Uses LLM for intelligent classification when keywords don't clearly indicate intent.
        
        Returns:
            'filtered' - Apply dashboard filters to query
            'global' - Search all data ignoring filters
            'ambiguous' - Unclear even to LLM, should ask user
        """
        question_lower = question.lower()
        
        # No filters = always global
        if not filters:
            return "global"
        
        # Fast path: Explicit keywords (avoid LLM call for obvious cases)
        
        # Explicit global keywords
        global_patterns = [
            "across all", "all regions", "all categories", "all time",
            "overall", "total across", "globally", "ignoring filter",
            "without filter", "entire dataset", "all data", "company-wide",
            "organization-wide", "regardless of filter", "everywhere"
        ]
        for pattern in global_patterns:
            if pattern in question_lower:
                return "global"
        
        # Explicit filtered keywords
        filtered_patterns = [
            "this region", "current filter", "as filtered", "what's shown",
            "in this view", "with these filters", "selected", "currently applied",
            "filtered data", "current view", "here", "current scope", "within scope"
        ]
        for pattern in filtered_patterns:
            if pattern in question_lower:
                return "filtered"
        
        # LLM-based classification for ambiguous queries
        try:
            filter_context = self._build_filter_context(filters)
            
            scope_prompt = f"""You are analyzing a user's query to determine their data scope intent.

Current dashboard filters: {filter_context}

User question: "{question}"

Based on the question, determine if the user wants:
- FILTERED: Results limited to the current dashboard filters ({filter_context})
- GLOBAL: Results from all data, ignoring the dashboard filters
- AMBIGUOUS: Cannot determine intent, need to ask user

Consider:
- Questions about "top", "best", "highest" without context specifiers are typically AMBIGUOUS
- Questions referencing "current", "this view", "selected", "here" suggest FILTERED
- Questions with "all", "overall", "entire", "company-wide" suggest GLOBAL
- Questions that are conversational or off-topic (greetings, personal) should return GLOBAL

Respond with exactly one word: FILTERED, GLOBAL, or AMBIGUOUS"""

            response = await self.llm.ainvoke([{"role": "user", "content": scope_prompt}])
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
    
    def _build_filter_context(self, filters: List[Dict]) -> str:
        """Build a human-readable filter context string."""
        if not filters:
            return ""
        
        filter_parts = []
        for f in filters:
            field = f.get("field", "")
            value = f.get("value")
            if field and value:
                filter_parts.append(f"{field}='{value}'")
        
        return ", ".join(filter_parts) if filter_parts else ""
    
    # =========================================================================
    # Helper Methods
    # =========================================================================
    
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
        filters = context.get("filters", [])
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
            "needs_clarification": False,
        }
        
        # Thread for conversation memory
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
