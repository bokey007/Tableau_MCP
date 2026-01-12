# =============================================================================
# Agent Routes
# =============================================================================
"""Agent information and visualization endpoints."""

from fastapi import APIRouter, Query as QueryParam
from fastapi.responses import Response
import base64

from src.core.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.get("/graph")
async def get_agent_graph(
    format: str = QueryParam(default="mermaid", regex="^(mermaid|png|ascii)$"),
):
    """
    Get a visualization of the agent's LangGraph workflow.
    
    Args:
        format: Output format - 'mermaid' (default), 'png', or 'ascii'
    
    Returns:
        - mermaid: Mermaid diagram code that can be rendered
        - png: Base64 encoded PNG image
        - ascii: Simple ASCII representation
    """
    from src.agent import TableauAgent
    
    agent = TableauAgent()
    
    try:
        graph = agent.graph
        
        if format == "mermaid":
            # Get Mermaid diagram
            mermaid_code = graph.get_graph().draw_mermaid()
            return {
                "format": "mermaid",
                "diagram": mermaid_code,
                "render_url": f"https://mermaid.live/edit#pako:{base64.urlsafe_b64encode(mermaid_code.encode()).decode()}",
            }
        
        elif format == "png":
            # Generate PNG (requires graphviz)
            try:
                png_bytes = graph.get_graph().draw_mermaid_png()
                return Response(
                    content=png_bytes,
                    media_type="image/png",
                    headers={"Content-Disposition": "inline; filename=agent_graph.png"}
                )
            except Exception as e:
                return {
                    "format": "png",
                    "error": f"PNG generation failed (requires graphviz/mermaid-cli): {e}",
                    "fallback": "Use format=mermaid instead"
                }
        
        elif format == "ascii":
            # Simple ASCII representation
            g = graph.get_graph()
            nodes = list(g.nodes.keys())
            edges = [(e[0], e[1]) for e in g.edges]
            
            ascii_repr = "Agent Graph Structure\n"
            ascii_repr += "=" * 40 + "\n\n"
            ascii_repr += "NODES:\n"
            for node in nodes:
                ascii_repr += f"  • {node}\n"
            ascii_repr += "\nEDGES:\n"
            for src, dst in edges:
                ascii_repr += f"  {src} → {dst}\n"
            
            return {
                "format": "ascii",
                "nodes": nodes,
                "edges": [{"from": e[0], "to": e[1]} for e in edges],
                "diagram": ascii_repr,
            }
        
    except Exception as e:
        logger.error("Graph visualization failed", error=str(e))
        return {
            "error": f"Failed to generate graph: {e}",
            "format": format,
        }


@router.get("/info")
async def get_agent_info():
    """Get information about the agent configuration."""
    from src.agent import TableauAgent
    from src.core.config import settings
    
    return {
        "agent_type": "TableauAgent",
        "framework": "LangGraph",
        "llm_model": settings.openai_model,
        "features": [
            "Natural language to VizQL query generation",
            "Query review and refinement",
            "MCP error feedback loop",
            "Conversation memory",
            "Data analysis and visualization",
        ],
        "max_retries": 2,
        "timeout_seconds": settings.mcp_request_timeout,
    }
