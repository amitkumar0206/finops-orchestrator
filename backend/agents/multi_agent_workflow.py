"""
FinOps Query Execution - Pure Text-to-SQL Approach
Simplified architecture where LLM generates SQL directly, no parameter extraction.
"""

import structlog
from typing import Dict, Any, List

from backend.config.settings import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()


async def execute_multi_agent_query(
    query: str,
    conversation_id: str,
    chat_history: List[Dict[str, Any]] = None,
    previous_context: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Execute a query using pure text-to-SQL approach.
    LLM directly generates SQL, no parameter extraction needed.
    
    Args:
        query: User query
        conversation_id: Conversation ID for context
        chat_history: Previous conversation history
        previous_context: Context from previous turns
        
    Returns:
        Response with message, charts, suggestions, etc.
    """
    logger.info(f"Executing query with text-to-SQL: {query[:100]}")
    
    from backend.agents.execute_query_v2 import execute_query_simple
    
    # Convert chat_history to conversation_history format
    conversation_history = chat_history if chat_history else []
    
    try:
        response = await execute_query_simple(
            query=query,
            conversation_history=conversation_history,
            previous_context=previous_context
        )
        
        # Return in expected format
        return {
            "conversation_id": conversation_id,
            "final_response": response.get("message"),
            "message": response.get("message"),  # Alias for backwards compatibility
            "summary": response.get("summary", ""),  # Structured summary
            "insights": response.get("insights", []),  # Structured insights
            "recommendations": response.get("recommendations", []),  # Structured recommendations
            "results": response.get("results", []),  # Data table
            "charts": response.get("charts", []),
            "suggestions": response.get("suggestions", []),
            "athena_query": response.get("athena_query"),
            "context": response.get("context", {}),
            "metadata": response.get("metadata", {})
        }
    except Exception as e:
        logger.error(f"Query execution failed: {e}", exc_info=True)
        return {
            "conversation_id": conversation_id,
            "message": f"I encountered an error: {str(e)}. Please try rephrasing your question.",
            "final_response": f"I encountered an error: {str(e)}. Please try rephrasing your question.",
            "charts": [],
            "suggestions": [
                "Show me my AWS costs for the last 30 days",
                "What are my top 5 most expensive services?",
                "How can I optimize my costs?"
            ],
            "context": {},
            "metadata": {"error": str(e)}
        }
