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
from langchain_core.runnables import RunnableConfig
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

User request: {question}

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
    
    async def _classify_intent(self, state: DashboardAgentState, config: RunnableConfig = None) -> DashboardAgentState:
        """Classify user intent using heuristics + LLM fallback.
        
        Uses accumulated messages (the only reliably persistent field via the
        'add' reducer) to detect scope follow-ups. If the previous AI response
        was a scope clarification question, the current user message is treated
        as a scope answer and the original query is re-executed.
        """
        question = state.get("question", "")
        context = state.get("dashboard_context", {})
        dashboard_config = state.get("dashboard_config")
        question_lower = question.lower().strip()
        
        # Get thread_id for logging
        thread_id = config.get("configurable", {}).get("thread_id", "unknown") if config else "unknown"
        logger.info("Classifying intent", question=question[:50], thread_id=thread_id)
        
        # ── Conversational follow-up resolution (message-based) ──
        # CRITICAL: Read history BEFORE we append the current message.
        history = state.get("messages", [])
        
        # 1) Check if this is a scope-clarification answer (narrow check)
        scope_followup = await self._detect_scope_followup(history, question, question_lower)
        
        if scope_followup:
            original_question, resolved_scope = scope_followup
            logger.info("Scope follow-up detected via history",
                       original_q=original_question[:50], scope=resolved_scope)
            state["context_scope"] = resolved_scope
            state["question"] = original_question
            question = original_question
            question_lower = question.lower().strip()
        else:
            # 2) Check if this is a broader conversational follow-up
            #    e.g. "and for tech category?" after a sales trend result
            resolved_q, prev_scope = await self._resolve_conversational_followup(
                history, question
            )
            if resolved_q != question:
                logger.info("Conversational follow-up resolved",
                           original=question[:40], resolved=resolved_q[:60],
                           carried_scope=prev_scope)
                state["question"] = resolved_q
                question = resolved_q
                question_lower = question.lower().strip()
                # Carry forward the scope from the previous exchange
                if prev_scope:
                    state["context_scope"] = prev_scope
        
        # NOW append user message to conversation history (appended via 'add' reducer)
        state["messages"] = [HumanMessage(content=question)]
        
        # Clear previous turn results to prevent ghosting in memory
        state["results"] = None
        state["visualization"] = None
        state["analysis"] = None
        state["error"] = None
        
        # If we didn't resolve scope from follow-up, reset it
        if not scope_followup and state.get("context_scope") is None:
            state["context_scope"] = None
        
        # LLM-powered intent classification (no heuristic fast-path)
        intent = await self._classify_by_llm(question, context, dashboard_config)
        
        state["intent"] = intent
        state["needs_clarification"] = False
        logger.info("Intent classified", intent=intent)
        return state
    
    async def _detect_scope_followup(
        self, history: List[BaseMessage], current_question: str, current_lower: str
    ) -> Optional[tuple]:
        """Check if the current message is a follow-up to a scope clarification.
        
        Scans history (BEFORE current message is added) for:
            HumanMessage (original question)
            AIMessage    (scope clarification)
        
        Returns (original_question, resolved_scope) or None.
        """
        if not history:
            return None
            
        # The history contains everything UP TO the current turn.
        # We need to find the last HumanMessage and the last AIMessage after it.
        last_ai = None
        last_human = None
        
        for msg in reversed(history):
            if isinstance(msg, AIMessage) and last_ai is None:
                last_ai = msg
            elif isinstance(msg, HumanMessage) and last_ai is not None:
                last_human = msg
                break
        
        if not last_ai or not last_human:
            return None
        
        # Verify it's a scope clarification
        scope_markers = ["Would you like results for", "Current view", "All data (global"]
        is_scope_clarification = any(marker in last_ai.content for marker in scope_markers)
        
        if not is_scope_clarification:
            return None
        
        # Use LLM to parse scope answer
        resolved_scope = await self._parse_scope_answer(current_lower, last_ai.content)
        return (last_human.content, resolved_scope) if resolved_scope else None
    
    async def _parse_scope_answer(self, user_reply: str, ai_clarification: str) -> Optional[str]:
        """Use LLM to interpret a user's reply to a scope clarification question.
        
        Returns 'global', 'filtered', or None if the reply is unrelated.
        """
        try:
            prompt = f"""You are interpreting a user's reply to a data scope question.

The AI previously asked:
\"\"\"{ai_clarification}\"\"\"

The user replied:
\"\"\"{user_reply}\"\"\"

Classify the user's intent. Respond with exactly ONE word:
- global  (user wants ALL data, ignoring dashboard filters — e.g. "all data", "everything", "complete data", "across all", "the whole thing", "option 2", "second one")
- filtered  (user wants the CURRENT VIEW with active filters — e.g. "current view", "as shown", "this view", "with the filter", "option 1", "first one", "yes the filtered one")
- unknown  (the reply is unrelated to scope — e.g. a completely new question, greeting, or gibberish)

Intent:"""
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            result = response.content.strip().lower()
            
            if result in ("global", "filtered"):
                logger.info("LLM scope answer parsed", reply=user_reply[:40], scope=result)
                return result
            
            logger.info("LLM scope answer: unknown/unrelated", reply=user_reply[:40], result=result)
            return None
            
        except Exception as e:
            logger.warning("LLM scope parsing failed, falling back", error=str(e))
            return None

    async def _resolve_conversational_followup(
        self, history: List[BaseMessage], current_question: str
    ) -> tuple:
        """Use LLM to detect conversational follow-ups and resolve them.
        
        Detects when the current message is a continuation of a previous exchange
        (e.g. "and for tech category?" after a sales trend answer) and rewrites
        it into a complete standalone question.
        
        Also extracts the scope preference from the previous exchange so it can
        be carried forward without re-asking the user.
        
        Returns:
            (resolved_question, previous_scope) — resolved_question equals
            current_question if no follow-up was detected; previous_scope is
            'global', 'filtered', or None.
        """
        if not history or len(history) < 2:
            return (current_question, None)
        
        # Build recent conversation context (last 6 messages max)
        recent = history[-6:]
        conv_lines = []
        for msg in recent:
            role = "User" if isinstance(msg, HumanMessage) else "AI"
            conv_lines.append(f"{role}: {msg.content[:300]}")
        conversation_context = "\n".join(conv_lines)
        
        try:
            prompt = f"""You are an expert data analyst assistant. Analyze whether the user's latest message is a follow-up to the ongoing conversation.

Recent conversation:
{conversation_context}

User's latest message: "{current_question}"

Determine:
1. Is this a FOLLOW-UP to a previous query (e.g. refining, extending, or asking for a variation)?
2. If yes, rewrite it as a COMPLETE standalone question that includes all necessary context from the conversation.
3. What data scope was used in the previous exchange? (global/filtered/none)

Examples of follow-ups:
- "and for tech category?" after sales trend → "What is the sales trend for the Technology category?"
- "what about East?" after region analysis → "Show me the same analysis for the East region"
- "now compare with last year" → "Compare the current results with last year's data"
- "break it down by month" → "Break down the sales trend by month"

Respond in EXACTLY this format (3 lines, no extra text):
IS_FOLLOWUP: yes/no
RESOLVED_QUESTION: <the complete standalone question, or the original if not a follow-up>
PREVIOUS_SCOPE: global/filtered/none"""

            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            lines = response.content.strip().split("\n")
            
            is_followup = False
            resolved = current_question
            prev_scope = None
            
            for line in lines:
                line = line.strip()
                if line.lower().startswith("is_followup:"):
                    is_followup = "yes" in line.lower()
                elif line.lower().startswith("resolved_question:"):
                    resolved = line.split(":", 1)[1].strip().strip('"')
                elif line.lower().startswith("previous_scope:"):
                    scope_val = line.split(":", 1)[1].strip().lower()
                    if scope_val in ("global", "filtered"):
                        prev_scope = scope_val
            
            if is_followup and resolved and resolved != current_question:
                logger.info("Follow-up resolved by LLM",
                           original=current_question[:40],
                           resolved=resolved[:60])
                return (resolved, prev_scope)
            
            return (current_question, prev_scope)
            
        except Exception as e:
            logger.warning("Follow-up resolution failed", error=str(e))
            return (current_question, None)

    
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
        filters = self._sanitize_filters(context.get("filters", []))
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
        
        # Sanitize filters to remove problematic fields before query planning
        filters = self._sanitize_filters(filters)
        
        logger.info("Delegating to Data Agent", question=question[:50])
        
        try:
            # Use pre-resolved scope (from follow-up answer) or detect it
            context_scope = state.get("context_scope")
            if not context_scope:
                context_scope = await self._detect_context_scope(question, filters, state.get("messages", []))
                state["context_scope"] = context_scope
            
            logger.info("Context scope resolved", scope=context_scope, filters_count=len(filters))
            
            # Handle ambiguous scope - ask user
            if context_scope == "ambiguous" and filters:
                state["needs_clarification"] = True
                clarification = self._create_scope_clarification(filters, "data")
                state["analysis"] = clarification
                state["messages"] = [AIMessage(content=clarification)]  # Persist via add reducer
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
        filters = self._sanitize_filters(context.get("filters", []))
        
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
            
            # Use pre-resolved scope or detect it
            context_scope = state.get("context_scope")
            if not context_scope:
                context_scope = await self._detect_context_scope(question, filters, state.get("messages", []))
                state["context_scope"] = context_scope
            
            # Handle ambiguous scope
            if context_scope == "ambiguous" and filters:
                state["needs_clarification"] = True
                clarification = self._create_scope_clarification(filters, "comparison")
                state["analysis"] = clarification
                state["messages"] = [AIMessage(content=clarification)]
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
        filters = self._sanitize_filters(context.get("filters", []))
        
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
            
            # Use pre-resolved scope or detect it
            context_scope = state.get("context_scope")
            if not context_scope:
                context_scope = await self._detect_context_scope(question, filters, state.get("messages", []))
                state["context_scope"] = context_scope
            
            # Handle ambiguous scope
            if context_scope == "ambiguous" and filters:
                state["needs_clarification"] = True
                clarification = self._create_scope_clarification(filters, "anomaly")
                state["analysis"] = clarification
                state["messages"] = [AIMessage(content=clarification)]
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
        filters = self._sanitize_filters(context.get("filters", []))
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
            
            # Use pre-resolved scope or detect it
            context_scope = state.get("context_scope")
            if not context_scope:
                context_scope = await self._detect_context_scope(question, filters, state.get("messages", []))
                state["context_scope"] = context_scope
            
            # Handle ambiguous scope
            if context_scope == "ambiguous" and filters:
                state["needs_clarification"] = True
                clarification = self._create_scope_clarification(filters, "storytelling")
                state["analysis"] = clarification
                state["messages"] = [AIMessage(content=clarification)]
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
- FILTERED: User wants results limited to the current dashboard filters
- GLOBAL: User wants all data, ignoring dashboard filters
- AMBIGUOUS: Cannot determine — BUT only if the user has NOT already expressed a scope preference in the conversation above

Key rules:
- If the user previously chose "all data" / "global" in the conversation, default to GLOBAL (don't re-ask)
- If the user previously chose "current view" / "filtered" in the conversation, default to FILTERED (don't re-ask)
- If the AI previously mentioned "Data Scope: All data" in a response, the user prefers GLOBAL
- If the AI previously mentioned "Data Scope: Filtered" in a response, the user prefers FILTERED
- Only return AMBIGUOUS if this is the FIRST time scope is unclear AND there's no prior preference
- Questions referencing "this view", "here", "current" suggest FILTERED
- Questions with "all", "overall", "across all" suggest GLOBAL

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
