"""
aasmaa Query Execution - Pure Text-to-SQL Approach
Simplified architecture where LLM generates SQL directly, no parameter extraction.
Includes OptimizationAgent integration for optimization-related queries.
"""

import structlog
from typing import Dict, Any, List, Optional
from uuid import UUID

from backend.config.settings import get_settings
from backend.aasmaa.time_range import merge_time_range, TimeRangeResult
from backend.agents.optimization_agent import get_optimization_agent

logger = structlog.get_logger(__name__)
settings = get_settings()


def _is_explicit_comparison_cost_query(query: str, time_range_result: TimeRangeResult) -> bool:
    """Return True when query is clearly comparative cost analysis (not optimization)."""
    q = (query or "").lower()

    comparison_markers = [" vs ", " versus ", "compare", "comparison", "difference between"]
    has_comparison_text = any(marker in q for marker in comparison_markers)

    optimization_markers = [
        "optimiz", "quick win", "low-effort", "rightsiz", "savings plan",
        "reserved", "idle", "underutil", "opportunit"
    ]
    has_optimization_text = any(marker in q for marker in optimization_markers)

    # Time-range parser is the strongest signal for period-over-period comparison.
    if time_range_result and time_range_result.is_comparison_request and not has_optimization_text:
        return True

    return has_comparison_text and not has_optimization_text


def _is_explicit_cost_analysis_query(
    query: str,
    time_range_result: TimeRangeResult,
    previous_context: Optional[Dict[str, Any]] = None,
) -> bool:
    """Return True when query is clearly cost analytics/drill-down, not optimization."""
    q = (query or "").lower().strip()
    if not q:
        return False

    optimization_markers = [
        "optimiz", "quick win", "low-effort", "rightsiz", "savings plan",
        "reserved", "idle", "underutil", "opportunit", "recommendation",
        "reduce cost", "cut cost", "save money", "how can i save", "how do i save",
    ]
    has_optimization_text = any(marker in q for marker in optimization_markers)
    if has_optimization_text:
        return False

    # Existing explicit comparison logic remains a strong cost-analysis signal.
    if _is_explicit_comparison_cost_query(query, time_range_result):
        return True

    cost_terms = ["cost", "costs", "spend", "billing", "bill", "charge", "usage"]
    drilldown_terms = [
        "break down", "breakdown", "by region", "by service", "by account",
        "by usage", "by resource", "top ", "trend", "over time", "daily",
        "weekly", "monthly", "last 30 days", "last month", "this month",
    ]
    chart_terms = ["chart", "charts", "graph", "graphs", "plot", "visual"]
    continuation_terms = [
        "by region", "by service", "by account", "by usage", "by resource",
        "over time", "trend", "break down", "breakdown", "drill down",
    ]

    has_cost_terms = any(term in q for term in cost_terms)
    has_drilldown_terms = any(term in q for term in drilldown_terms)
    has_chart_terms = any(term in q for term in chart_terms)

    # Follow-up shorthand queries like "break down by region" should inherit prior cost intent.
    last_intent = str((previous_context or {}).get("last_intent", "")).lower()
    has_prior_cost_intent = any(
        token in last_intent
        for token in ("cost", "breakdown", "trend", "comparative", "top_n", "top")
    )
    has_continuation = any(term in q for term in continuation_terms)

    if has_cost_terms and (has_drilldown_terms or has_chart_terms):
        return True

    if has_prior_cost_intent and has_continuation:
        return True

    return False


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

    # Step 2: Check if this is an optimization-related query.
    # Use async classifier so LLM intent detection is applied (with keyword fallback).
    optimization_agent = get_optimization_agent(organization_id)
    is_optimization = await optimization_agent.is_optimization_query_async(query)

    # Deterministic override: explicit cost-analysis drill-downs should stay on text-to-sql.
    if is_optimization and _is_explicit_cost_analysis_query(query, time_range_result, previous_context):
        logger.info("Routing override applied: cost-analysis query forced to text-to-sql")
        is_optimization = False

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
