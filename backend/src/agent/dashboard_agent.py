# =============================================================================
# Dashboard Agent - Master Orchestrator for Tableau Extension
# =============================================================================
"""
Dashboard Agent that serves as the entry point for the Tableau Extension.
It handles routing between:
- Chat/Greeting responses (handled locally)
- Dashboard context queries (answered from Tableau context)
- Clarification requests (ambiguous questions)
- Data queries (delegated to Data Agent)
"""

import json
import re
from typing import Any, Dict, List, Optional, TypedDict
from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI, AzureChatOpenAI

from src.core.config import settings
from src.core.logging import get_logger
from src.agent.graph import TableauAgent  # Import existing Data Agent

logger = get_logger(__name__)


# =============================================================================
# State Definition
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
    """State for the Dashboard Agent."""
    question: str
    dashboard_context: DashboardContext
    intent: str  # chat, context, clarification, data_query
    response: str
    data: List[Dict[str, Any]]
    visualization: Dict[str, Any]
    error: Optional[str]


# =============================================================================
# Intent Classification Prompts
# =============================================================================

INTENT_CLASSIFIER_PROMPT = """You are an intent classifier for a Tableau dashboard AI assistant.

The user is viewing a Tableau dashboard and has asked a question. Classify the intent into one of these categories:

1. **chat** - Greetings, thanks, pleasantries, or general conversation
   Examples: "Hello", "Hi there", "Thanks!", "How are you?", "Goodbye"

2. **capability** - Questions about what the assistant can do
   Examples: "What can you do?", "Help me", "How do I use this?", "What features do you have?"

3. **dashboard_context** - Questions about current dashboard state, filters, or what's visible
   Examples: "What filter is applied?", "What's currently selected?", "Which region am I looking at?", "What data is shown?"

4. **clarification_needed** - Vague or ambiguous questions that need more detail
   Examples: "sales", "show me data", "analyze this", "what about customers?"

5. **data_query** - Specific data analysis questions that need to query the datasource
   Examples: "What are total sales?", "Top 5 customers by revenue", "Sales trend since 2020", "Compare regions"

Current Dashboard Context:
{context}

User Question: {question}

Respond with ONLY one of: chat, capability, dashboard_context, clarification_needed, data_query
"""


CHAT_RESPONSE_PROMPT = """You are a friendly AI assistant embedded in a Tableau dashboard. The user has sent a conversational message.

User message: {question}

Respond naturally and briefly. If greeted, respond warmly and offer to help analyze the dashboard data.
Keep your response to 1-2 sentences maximum."""


CAPABILITY_RESPONSE_PROMPT = """You are an AI assistant embedded in a Tableau dashboard. Explain your capabilities briefly.

Current dashboard: {dashboard_name}
Available datasources: {datasources}

User asked: {question}

Explain that you can:
- Answer questions about the data in natural language
- Analyze trends, comparisons, and aggregations
- Explain what filters are currently applied
- Help understand the dashboard

Keep response to 3-4 sentences maximum."""


CONTEXT_RESPONSE_PROMPT = """You are an AI assistant embedded in a Tableau dashboard. Answer questions about the current dashboard state.

Dashboard Name: {dashboard_name}

Current Filters Applied:
{filters}

Worksheets in Dashboard:
{worksheets}

User Question: {question}

Provide a clear, concise answer about the current dashboard state."""


CLARIFICATION_PROMPT = """You are an AI assistant embedded in a Tableau dashboard. The user's question is too vague to answer directly.

Dashboard: {dashboard_name}
Available data topics: {datasources}

User's vague question: "{question}"

Ask a clarifying question to understand what they want. Suggest 2-3 specific options they might mean.
Keep response brief and helpful."""


# =============================================================================
# Dashboard Agent Implementation
# =============================================================================

class DashboardAgent:
    """
    Master orchestrator for Tableau Extension.
    
    Routes requests between:
    - Local handling (chat, context, clarification)
    - Data Agent delegation (complex data queries)
    """
    
    def __init__(self):
        """Initialize the Dashboard Agent."""
        self._llm = None
        self._data_agent = None
        logger.info("Dashboard Agent initialized")
    
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
    
    async def process(
        self,
        question: str,
        dashboard_context: Optional[DashboardContext] = None,
        username: str = "dashboard_user"
    ) -> Dict[str, Any]:
        """
        Main entry point for processing user questions.
        
        Args:
            question: User's natural language question
            dashboard_context: Context from Tableau dashboard (filters, worksheets, etc.)
            username: User identifier
            
        Returns:
            Response dict with analysis, data, and visualization info
        """
        start_time = datetime.now()
        context = dashboard_context or {}
        
        logger.info(
            "Processing dashboard question",
            question=question[:50],
            has_context=bool(context)
        )
        
        try:
            # Step 1: Classify intent
            intent = await self._classify_intent(question, context)
            logger.info("Intent classified", intent=intent)
            
            # Step 2: Route based on intent
            if intent == "chat":
                result = await self._handle_chat(question)
                
            elif intent == "capability":
                result = await self._handle_capability(question, context)
                
            elif intent == "dashboard_context":
                result = await self._handle_context_query(question, context)
                
            elif intent == "clarification_needed":
                result = await self._handle_clarification(question, context)
                
            elif intent == "data_query":
                # Delegate to Data Agent
                result = await self._delegate_to_data_agent(question, context, username)
                
            else:
                # Default to data query
                result = await self._delegate_to_data_agent(question, context, username)
            
            # Add metadata
            result["intent"] = intent
            result["processing_time_ms"] = (datetime.now() - start_time).total_seconds() * 1000
            
            return result
            
        except Exception as e:
            logger.error("Dashboard Agent error", error=str(e))
            return {
                "success": False,
                "error": str(e),
                "intent": "error",
                "analysis": f"I encountered an error processing your request: {str(e)}"
            }
    
    async def _classify_intent(
        self,
        question: str,
        context: DashboardContext
    ) -> str:
        """Classify user intent using heuristics first, then LLM if needed."""
        
        question_lower = question.lower().strip()
        
        # Quick heuristic checks for common patterns
        
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
        
        # Very short/vague queries that need clarification
        if len(question_lower.split()) <= 2:
            vague_words = ['sales', 'profit', 'revenue', 'customers', 'data', 'show', 'analyze']
            if question_lower.strip('?!. ') in vague_words:
                return "clarification_needed"
        
        # Data query patterns (explicit)
        data_patterns = [
            r'(top|bottom)\s+\d+',
            r'(total|sum|average|avg|count|max|min)\s+',
            r'(trend|over time|by year|by month)',
            r'(compare|comparison|vs|versus)',
            r'(sales|profit|revenue|quantity)\s+(by|for|in)',
            r'how (much|many)',
            r'what (is|are|was|were) (the|our)',
        ]
        for pattern in data_patterns:
            if re.search(pattern, question_lower):
                return "data_query"
        
        # If no heuristic matched, use LLM for classification
        try:
            context_str = self._format_context_for_prompt(context)
            prompt = INTENT_CLASSIFIER_PROMPT.format(
                context=context_str,
                question=question
            )
            
            response = await self.llm.ainvoke([
                SystemMessage(content="You are an intent classifier. Respond with exactly one word."),
                HumanMessage(content=prompt)
            ])
            
            intent = response.content.strip().lower()
            
            # Validate response
            valid_intents = ["chat", "capability", "dashboard_context", "clarification_needed", "data_query"]
            if intent in valid_intents:
                return intent
            
            # Default to data_query if LLM gives unexpected response
            return "data_query"
            
        except Exception as e:
            logger.warning("LLM intent classification failed, defaulting to data_query", error=str(e))
            return "data_query"
    
    async def _handle_chat(self, question: str) -> Dict[str, Any]:
        """Handle casual conversation."""
        try:
            response = await self.llm.ainvoke([
                SystemMessage(content="You are a friendly AI assistant. Keep responses very brief (1-2 sentences)."),
                HumanMessage(content=CHAT_RESPONSE_PROMPT.format(question=question))
            ])
            
            return {
                "success": True,
                "analysis": response.content,
                "results": None,
                "visualization": None
            }
        except Exception as e:
            return {
                "success": True,
                "analysis": "Hello! I'm here to help you analyze your dashboard data. What would you like to know?",
                "results": None,
                "visualization": None
            }
    
    async def _handle_capability(
        self,
        question: str,
        context: DashboardContext
    ) -> Dict[str, Any]:
        """Explain capabilities with dashboard awareness."""
        
        dashboard_name = context.get("dashboard_name", "your dashboard")
        datasources = [ds.get("name", "Unknown") for ds in context.get("datasources", [])]
        datasources_str = ", ".join(datasources) if datasources else "connected datasources"
        
        prompt = CAPABILITY_RESPONSE_PROMPT.format(
            dashboard_name=dashboard_name,
            datasources=datasources_str,
            question=question
        )
        
        try:
            response = await self.llm.ainvoke([
                SystemMessage(content="You are a helpful AI assistant. Be concise."),
                HumanMessage(content=prompt)
            ])
            
            return {
                "success": True,
                "analysis": response.content,
                "results": None,
                "visualization": None
            }
        except Exception as e:
            return {
                "success": True,
                "analysis": f"I can help you analyze the data in {dashboard_name}. Ask me questions like 'What are total sales?' or 'Show me the top 5 customers'. I can also explain what filters are currently applied.",
                "results": None,
                "visualization": None
            }
    
    async def _handle_context_query(
        self,
        question: str,
        context: DashboardContext
    ) -> Dict[str, Any]:
        """Answer questions about current dashboard state."""
        
        dashboard_name = context.get("dashboard_name", "Dashboard")
        
        # Format filters
        filters = context.get("filters", [])
        if filters:
            filters_str = "\n".join([
                f"- {f.get('field', 'Unknown')}: {f.get('value', 'All')}"
                for f in filters
            ])
        else:
            filters_str = "No filters currently applied"
        
        # Format worksheets
        worksheets = context.get("worksheets", [])
        if worksheets:
            worksheets_str = ", ".join([w.get("name", "Unknown") for w in worksheets])
        else:
            worksheets_str = "Unknown"
        
        prompt = CONTEXT_RESPONSE_PROMPT.format(
            dashboard_name=dashboard_name,
            filters=filters_str,
            worksheets=worksheets_str,
            question=question
        )
        
        try:
            response = await self.llm.ainvoke([
                SystemMessage(content="You are an AI assistant explaining dashboard state. Be specific and helpful."),
                HumanMessage(content=prompt)
            ])
            
            return {
                "success": True,
                "analysis": response.content,
                "results": None,
                "visualization": None,
                "dashboard_state": {
                    "filters": filters,
                    "worksheets": worksheets
                }
            }
        except Exception as e:
            # Fallback to simple response
            return {
                "success": True,
                "analysis": f"You're viewing '{dashboard_name}'. {filters_str}.",
                "results": None,
                "visualization": None
            }
    
    async def _handle_clarification(
        self,
        question: str,
        context: DashboardContext
    ) -> Dict[str, Any]:
        """Ask for clarification on vague questions."""
        
        dashboard_name = context.get("dashboard_name", "your dashboard")
        datasources = [ds.get("name", "Unknown") for ds in context.get("datasources", [])]
        datasources_str = ", ".join(datasources) if datasources else "your data"
        
        prompt = CLARIFICATION_PROMPT.format(
            dashboard_name=dashboard_name,
            datasources=datasources_str,
            question=question
        )
        
        try:
            response = await self.llm.ainvoke([
                SystemMessage(content="You are a helpful AI assistant. Ask clarifying questions briefly."),
                HumanMessage(content=prompt)
            ])
            
            return {
                "success": True,
                "analysis": response.content,
                "results": None,
                "visualization": None,
                "needs_clarification": True
            }
        except Exception as e:
            return {
                "success": True,
                "analysis": f"Could you be more specific? For example, you could ask:\n- 'What are total sales?'\n- 'Top 5 customers by revenue'\n- 'Sales trend by month'",
                "results": None,
                "visualization": None,
                "needs_clarification": True
            }
    
    async def _delegate_to_data_agent(
        self,
        question: str,
        context: DashboardContext,
        username: str
    ) -> Dict[str, Any]:
        """
        Delegate data query to the Data Agent.
        
        Uses execute_data_query() which skips intent classification since
        Dashboard Agent has already classified this as a data_query.
        """
        
        logger.info("Delegating to Data Agent (VizQL)", question=question[:50])
        
        try:
            # Call execute_data_query - skips intent classification
            # Dashboard Agent already determined this is a data_query
            result = await self.data_agent.execute_data_query(
                question=question,
                datasource_id=None,  # Let Data Agent discover datasources
            )
            
            # Enrich response with dashboard context
            enriched_result = self._enrich_with_context(result, context)
            
            return enriched_result
            
        except Exception as e:
            logger.error("Data Agent delegation failed", error=str(e))
            return {
                "success": False,
                "error": str(e),
                "analysis": f"I encountered an error while analyzing the data: {str(e)}"
            }
    
    def _enrich_with_context(
        self,
        result: Dict[str, Any],
        context: DashboardContext
    ) -> Dict[str, Any]:
        """Enrich Data Agent response with dashboard context."""
        
        # Add filter context to analysis if filters are applied
        filters = context.get("filters", [])
        if filters and result.get("success") and result.get("analysis"):
            filter_note = "\n\n📋 **Dashboard Context:** "
            filter_parts = [f"{f.get('field')} = {f.get('value')}" for f in filters if f.get('value')]
            if filter_parts:
                filter_note += f"Currently filtered by: {', '.join(filter_parts)}"
                result["analysis"] = result["analysis"] + filter_note
        
        return result
    
    def _format_context_for_prompt(self, context: DashboardContext) -> str:
        """Format dashboard context for LLM prompts."""
        if not context:
            return "No dashboard context available"
        
        parts = []
        
        if context.get("dashboard_name"):
            parts.append(f"Dashboard: {context['dashboard_name']}")
        
        if context.get("filters"):
            filters_str = ", ".join([
                f"{f.get('field')}={f.get('value', 'All')}"
                for f in context["filters"]
            ])
            parts.append(f"Filters: {filters_str}")
        
        if context.get("datasources"):
            ds_names = [ds.get("name") for ds in context["datasources"]]
            parts.append(f"Datasources: {', '.join(ds_names)}")
        
        return "; ".join(parts) if parts else "Dashboard context minimal"


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
