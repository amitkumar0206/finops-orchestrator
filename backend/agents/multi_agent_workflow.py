"""
FinOps Query Execution - Pure Text-to-SQL Approach
Simplified architecture where LLM generates SQL directly, no parameter extraction.
Includes OptimizationAgent integration for optimization-related queries.
"""

import structlog
from typing import Dict, Any, List, Optional
from uuid import UUID

from backend.config.settings import get_settings
from backend.finops.time_range import merge_time_range, TimeRangeResult
from backend.agents.optimization_agent import OptimizationAgent, get_optimization_agent

logger = structlog.get_logger(__name__)
settings = get_settings()


async def execute_multi_agent_query(
    query: str,
    conversation_id: str,
    chat_history: List[Dict[str, Any]] = None,
    previous_context: Dict[str, Any] = None,
    organization_id: Optional[UUID] = None,
    account_ids: Optional[List[str]] = None,
    timezone: str = "UTC"
) -> Dict[str, Any]:
    """
    Execute a query using pure text-to-SQL approach with optimization detection.

    Flow:
    1. Parse/merge time range from context and query
    2. Detect if query is optimization-related
    3. Route to OptimizationAgent or Text-to-SQL as appropriate
    4. Return response with time_range in metadata

    Args:
        query: User query
        conversation_id: Conversation ID for context
        chat_history: Previous conversation history
        previous_context: Context from previous turns
        organization_id: Organization ID for multi-tenant scoping
        account_ids: Allowed AWS account IDs
        timezone: User timezone for time range parsing

    Returns:
        Response with message, charts, suggestions, and scope.time_range
    """
    logger.info(f"Executing query with text-to-SQL: {query[:100]}")

    from backend.agents.execute_query_v2 import execute_query_simple

    # Convert chat_history to conversation_history format
    conversation_history = chat_history if chat_history else []

    # Step 1: Parse and merge time range
    time_range_result: TimeRangeResult = merge_time_range(
        prev_context=previous_context,
        new_request=query,
        tz=timezone
    )

    logger.info(
        "Time range resolved",
        description=time_range_result.primary.description,
        source=time_range_result.primary.source,
        is_comparison=time_range_result.is_comparison_request
    )

    # Step 2: Check if this is an optimization-related query
    optimization_agent = get_optimization_agent(organization_id)
    is_optimization = optimization_agent.is_optimization_query(query)

    try:
        if is_optimization:
            # Step 3a: Route to OptimizationAgent
            logger.info("Routing to OptimizationAgent")

            response = await optimization_agent.process_query(
                query=query,
                account_ids=account_ids,
                conversation_context=previous_context
            )

            # Add time range to response metadata
            if "metadata" not in response:
                response["metadata"] = {}

            response["metadata"]["scope"] = {
                "time_range": time_range_result.to_scope_dict(),
                "account_ids": account_ids,
                "organization_id": str(organization_id) if organization_id else None
            }

            # Return in expected format
            return {
                "conversation_id": conversation_id,
                "final_response": response.get("message"),
                "message": response.get("message"),
                "summary": response.get("summary", ""),
                "insights": response.get("insights", []),
                "recommendations": response.get("recommendations", []),
                "results": response.get("results", []),
                "charts": response.get("charts", []),
                "suggestions": response.get("suggestions", [
                    "Show me the top 5 opportunities",
                    "What are the low-effort quick wins?",
                    "Show EC2 rightsizing recommendations"
                ]),
                "athena_query": None,  # Optimization queries don't use Athena
                "context": {
                    "time_range": time_range_result.primary.to_dict(),
                    "last_query": query,
                    "is_optimization": True
                },
                "metadata": response.get("metadata", {})
            }

        # Step 3b: Route to Text-to-SQL for cost queries
        # Enhance context with time range
        enhanced_context = previous_context.copy() if previous_context else {}
        enhanced_context["time_range"] = time_range_result.primary.to_dict()

        if time_range_result.comparison:
            enhanced_context["comparison_time_range"] = time_range_result.comparison.to_dict()

        response = await execute_query_simple(
            query=query,
            conversation_history=conversation_history,
            previous_context=enhanced_context
        )

        # Add time range to response metadata
        if "metadata" not in response:
            response["metadata"] = {}

        response["metadata"]["scope"] = {
            "time_range": time_range_result.to_scope_dict(),
            "account_ids": account_ids,
            "organization_id": str(organization_id) if organization_id else None
        }

        # Update context with time range
        response_context = response.get("context", {})
        response_context["time_range"] = time_range_result.primary.to_dict()

        # Return in expected format
        return {
            "conversation_id": conversation_id,
            "final_response": response.get("message"),
            "message": response.get("message"),
            "summary": response.get("summary", ""),
            "insights": response.get("insights", []),
            "recommendations": response.get("recommendations", []),
            "results": response.get("results", []),
            "charts": response.get("charts", []),
            "suggestions": response.get("suggestions", []),
            "athena_query": response.get("athena_query"),
            "context": response_context,
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
                "What are my top optimization opportunities?"
            ],
            "context": {
                "time_range": time_range_result.primary.to_dict() if time_range_result else {}
            },
            "metadata": {
                "error": str(e),
                "scope": {
                    "time_range": time_range_result.to_scope_dict() if time_range_result else {}
                }
            }
        }
