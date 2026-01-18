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
    
    # Processing
    intent: str  # chat, capability, dashboard_context, clarification, data_query
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
- dashboard_context (asking about current filters, selections, what's shown)
- clarification (vague question needing more detail: single words like "sales", "profit")
- data_query (specific data analysis: "top 5 customers", "total sales by region")

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

Answer the user's question about what's currently shown/selected."""


CLARIFICATION_SYSTEM = """The user's question is too vague. Ask for clarification with 2-3 specific suggestions.
Dashboard: {dashboard_name}
Available data: {datasources}

Be brief and helpful."""


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
        graph.add_node("handle_data_query", self._handle_data_query)
        
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
                "data_query": "handle_data_query",
            }
        )
        
        # All handlers go to END
        graph.add_edge("handle_chat", END)
        graph.add_edge("handle_capability", END)
        graph.add_edge("handle_context", END)
        graph.add_edge("handle_clarification", END)
        graph.add_edge("handle_data_query", END)
        
        return graph
    
    def _route_by_intent(self, state: DashboardAgentState) -> str:
        """Route to appropriate handler based on classified intent."""
        intent = state.get("intent", "data_query")
        
        # Map intent to node name
        intent_map = {
            "chat": "chat",
            "capability": "capability",
            "dashboard_context": "dashboard_context",
            "clarification_needed": "clarification",
            "clarification": "clarification",
            "data_query": "data_query",
        }
        
        return intent_map.get(intent, "data_query")
    
    # =========================================================================
    # Node Implementations
    # =========================================================================
    
    async def _classify_intent(self, state: DashboardAgentState) -> DashboardAgentState:
        """Classify user intent using heuristics + LLM fallback."""
        question = state.get("question", "")
        context = state.get("dashboard_context", {})
        question_lower = question.lower().strip()
        
        logger.info("Classifying intent", question=question[:50])
        
        # Add user message to conversation history
        state["messages"] = [HumanMessage(content=question)]
        
        # Heuristic classification (fast path)
        intent = self._classify_by_heuristics(question_lower)
        
        if intent is None:
            # LLM fallback for ambiguous cases
            intent = await self._classify_by_llm(question, context)
        
        state["intent"] = intent
        logger.info("Intent classified", intent=intent)
        return state
    
    def _classify_by_heuristics(self, question_lower: str) -> Optional[str]:
        """Fast heuristic classification for common patterns."""
        
        # Chat patterns
        chat_patterns = [
            r'^(hi|hello|hey|good morning|good afternoon|good evening)[\s!.,]*$',
            r'^(thanks|thank you|thx|ty)[\s!.,]*$',
            r'^(bye|goodbye|see you)[\s!.,]*$',
            r'^how are you',
        ]
        for pattern in chat_patterns:
            if re.match(pattern, question_lower):
                return "chat"
        
        # Capability patterns
        capability_patterns = [
            r'what can you do',
            r'how do (i|you) use',
            r'help me',
            r'^help$',
            r'what (are your|features)',
            r'how does this work',
        ]
        for pattern in capability_patterns:
            if re.search(pattern, question_lower):
                return "capability"
        
        # Dashboard context patterns
        context_patterns = [
            r'what (filter|filters)',
            r'which (filter|region|segment)',
            r'current(ly)? (filter|select)',
            r'what.*(selected|applied|shown)',
            r'what am i (looking at|viewing)',
        ]
        for pattern in context_patterns:
            if re.search(pattern, question_lower):
                return "dashboard_context"
        
        # Clarification needed (very short/vague)
        if len(question_lower.split()) <= 2:
            vague_words = ['sales', 'profit', 'revenue', 'customers', 'data', 'show', 'analyze']
            if question_lower.strip('?!. ') in vague_words:
                return "clarification"
        
        # Explicit data query patterns
        data_patterns = [
            r'(top|bottom)\s+\d+',
            r'(total|sum|average|avg|count|max|min)\s+',
            r'(trend|over time|by year|by month)',
            r'(compare|comparison|vs|versus)',
            r'how (much|many)',
            r'what (is|are|was|were) (the|our)',
        ]
        for pattern in data_patterns:
            if re.search(pattern, question_lower):
                return "data_query"
        
        return None  # Needs LLM classification
    
    async def _classify_by_llm(self, question: str, context: DashboardContext) -> str:
        """Use LLM for ambiguous intent classification."""
        try:
            context_str = self._format_context_summary(context)
            prompt = INTENT_CLASSIFIER_PROMPT.format(
                question=question,
                context=context_str
            )
            
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            intent = response.content.strip().lower()
            
            valid_intents = ["chat", "capability", "dashboard_context", "clarification", "data_query"]
            if intent in valid_intents:
                return intent
            
            return "data_query"  # Default
            
        except Exception as e:
            logger.warning("LLM classification failed", error=str(e))
            return "data_query"
    
    async def _handle_chat(self, state: DashboardAgentState) -> DashboardAgentState:
        """Handle casual conversation."""
        question = state.get("question", "")
        
        try:
            response = await self.llm.ainvoke([
                SystemMessage(content=CHAT_RESPONSE_SYSTEM),
                HumanMessage(content=question)
            ])
            
            state["analysis"] = response.content
            state["status"] = "complete"
            state["messages"] = [AIMessage(content=response.content)]
            
        except Exception as e:
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
        
        try:
            system_prompt = CONTEXT_RESPONSE_SYSTEM.format(
                dashboard_name=dashboard_name,
                filters=filters_str,
                worksheets=worksheets_str
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
    
    async def _handle_data_query(self, state: DashboardAgentState) -> DashboardAgentState:
        """Delegate data query to Data Agent (VizQL)."""
        question = state.get("question", "")
        context = state.get("dashboard_context", {})
        
        logger.info("Delegating to Data Agent", question=question[:50])
        
        try:
            # Call Data Agent's execute_data_query (skips intent classification)
            result = await self.data_agent.execute_data_query(
                question=question,
                datasource_id=None
            )
            
            # Map result to state
            state["analysis"] = result.get("analysis", "")
            state["results"] = result.get("results")
            state["visualization"] = result.get("visualization")
            state["error"] = result.get("error")
            state["status"] = "complete" if result.get("success") else "error"
            
            # Enrich with dashboard context
            if result.get("success") and state.get("analysis"):
                state["analysis"] = self._enrich_with_context(state["analysis"], context)
            
        except Exception as e:
            logger.error("Data query failed", error=str(e))
            state["error"] = str(e)
            state["analysis"] = f"Error analyzing data: {str(e)}"
            state["status"] = "error"
        
        return state
    
    # =========================================================================
    # Helper Methods
    # =========================================================================
    
    def _format_context_summary(self, context: DashboardContext) -> str:
        """Format context for LLM prompts."""
        if not context:
            return "No dashboard context"
        
        parts = []
        if context.get("dashboard_name"):
            parts.append(f"Dashboard: {context['dashboard_name']}")
        if context.get("filters"):
            filters = [f"{f.get('field')}={f.get('value', 'All')}" for f in context["filters"]]
            parts.append(f"Filters: {', '.join(filters)}")
        
        return "; ".join(parts) if parts else "Minimal context"
    
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
        
        # Build initial state
        initial_state: DashboardAgentState = {
            "question": question.strip(),
            "username": username,
            "dashboard_context": dashboard_context or {},
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
