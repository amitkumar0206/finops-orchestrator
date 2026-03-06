"""
Chat API endpoints for natural language cost analysis
Handles conversation management and agent orchestration with conversation history tracking
"""

import asyncio
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Request
import json
from fastapi.responses import StreamingResponse
import structlog

from backend.models.schemas import ChatRequest, ChatResponse, MessageRole
from backend.services.conversation_manager import conversation_manager
from backend.agents.multi_agent_workflow import execute_multi_agent_query
from backend.config.settings import get_settings
from backend.services.request_context import require_context, RequestContext

router = APIRouter()
logger = structlog.get_logger(__name__)
settings = get_settings()

logger.info("Chat API initialized with Multi-Agent System")


# ─────────────────────────────────────────────────────────────────────────────
# Security dependencies & helpers
# All chat endpoints use these to enforce authentication and conversation
# ownership uniformly.  Single source of truth → one implementation to test,
# one place to change the policy (e.g., "admins can access any conversation").
# ─────────────────────────────────────────────────────────────────────────────

async def get_request_context(request: Request) -> RequestContext:
    """FastAPI dependency — enforces authentication. Raises 401 if no auth."""
    return require_context(request)


def require_conversation_owner(
    conversation_id: str,
    context: RequestContext,
    *,
    action: str = "access",
) -> str:
    """
    Centralized conversation-ownership check (IDOR protection).

    Used by every chat endpoint that touches an existing conversation.
    Single source of truth for the policy, the 404/403 semantics, and the
    audit-log event shape.

    Args:
        conversation_id: Thread ID to verify.
        context: Authenticated request context (provides user_id).
        action: Short label for the audit event (e.g., "read", "delete", "stream").

    Returns:
        The validated conversation_id (unchanged).

    Raises:
        HTTPException: 404 if the thread does not exist, 403 if the caller
            is not the owner.
    """
    metadata = conversation_manager.get_thread_metadata(conversation_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Conversation not found")

    owner_id = metadata.get("user_id")
    if owner_id != str(context.user_id):
        logger.warning(
            "unauthorized_conversation_attempt",
            action=action,
            conversation_id=conversation_id,
            requesting_user_id=str(context.user_id),
            owner_user_id=owner_id,
        )
        raise HTTPException(status_code=403, detail="Access denied")

    return conversation_id


def resolve_owned_conversation(
    supplied_conversation_id: Optional[str],
    context: RequestContext,
    *,
    action: str,
) -> str:
    """
    Helper for POST endpoints (/chat, /stream):
      • If the client supplied a conversation_id → verify ownership, reuse it.
      • Otherwise → create a new thread owned by the authenticated user.

    Threads are ALWAYS owned by a real authenticated user — there is no
    IP/anon fallback path.
    """
    if supplied_conversation_id:
        return require_conversation_owner(supplied_conversation_id, context, action=action)
    return conversation_manager.create_thread(user_id=str(context.user_id), title=None)


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    context: RequestContext = Depends(get_request_context),
):
    """
    Main chat endpoint for natural language cost analysis.

    Requires authentication. Uses the Multi-Agent system for intelligent routing
    and better follow-ups. All queries scoped to the caller's organization and
    allowed AWS accounts.
    """
    scope_info = context.to_scope_dict()
    conversation_id = resolve_owned_conversation(
        request.conversation_id, context, action="chat"
    )
    start_time = datetime.utcnow()

    logger.info(
        "Processing chat request with Multi-Agent System",
        conversation_id=conversation_id,
        user_id=str(context.user_id),
        message_length=len(request.message),
        account_count=len(context.allowed_account_ids),
    )

    try:
        # Persist user message and build context
        user_message_id = conversation_manager.add_message(
            thread_id=conversation_id,
            role="user",
            content=request.message,
            message_type="query",
            metadata={"include_reasoning": request.include_reasoning},
        )
        derived_context = conversation_manager.get_context_for_query(conversation_id)

        # Execute multi-agent workflow with tenant scoping
        response = await execute_multi_agent_query(
            query=request.message,
            conversation_id=conversation_id,
            chat_history=request.chat_history or [],
            previous_context={**derived_context, **(request.context or {})},
            organization_id=context.organization_id,
            account_ids=context.allowed_account_ids,
            timezone=request.context.get("timezone", "UTC") if request.context else "UTC",
        )

        # Extract response components
        # Multi-agent workflow returns 'final_response' key, not 'message'
        message_text = response.get("final_response") or response.get("message", "")
        charts = response.get("charts", [])
        suggestions = response.get("suggestions", [])
        context_data = response.get("context", {})
        metadata = response.get("metadata", {})
        athena_query = response.get("athena_query")  # SQL query from cost analysis

        # If no message and we have error/clarification status, construct a helpful message
        if not message_text and metadata:
            status = metadata.get("status")
            clarifications = metadata.get("clarification", [])
            if status == "llm_error":
                message_text = "I encountered an issue generating a reliable query for your request. " + (
                    clarifications[0] if clarifications else
                    "Please try rephrasing or provide more specific details (e.g., time period, service name)."
                )
            elif status == "needs_clarification":
                message_text = (clarifications[0] if clarifications else
                    "I need more information to proceed. Could you specify a time period or breakdown preference?")
            else:
                message_text = "I apologize, but I couldn't process your request."

        execution_time = (datetime.utcnow() - start_time).total_seconds()

        logger.info(
            "Multi-agent chat completed",
            conversation_id=conversation_id,
            execution_time=execution_time,
            charts_count=len(charts),
        )

        # Merge scope info into metadata
        response_metadata = response.get("metadata", {})
        response_metadata["scope"] = scope_info

        chat_response = ChatResponse(
            message=message_text,
            conversation_id=conversation_id,
            charts=charts,
            insights=[],
            action_items=[],
            suggestions=suggestions,
            agent_responses=[],
            reasoning=None,
            context=context_data,
            user_intent=metadata.get("supervisor_reasoning", "unknown"),
            athena_query=athena_query,  # Include SQL query for transparency
            summary=response.get("summary", ""),  # Structured summary
            structuredInsights=response.get("insights", []),  # Structured insights
            recommendations=response.get("recommendations", []),  # Structured recommendations
            results=response.get("results", []),  # Data table
            metadata=response_metadata,  # Query metadata with scope
            execution_time=execution_time,
            timestamp=datetime.utcnow(),
        )

        # Persist assistant message and execution logs in background
        def _persist_multi_agent_default():
            try:
                assistant_message_id = conversation_manager.add_message(
                    thread_id=conversation_id,
                    role="assistant",
                    content=message_text,
                    message_type="response",
                    metadata={"charts_count": len(charts), "metadata": metadata},
                )
                conversation_manager.save_agent_execution(
                    thread_id=conversation_id,
                    agent_name="MultiAgentSupervisor",
                    agent_type="supervisor",
                    input_query=request.message,
                    output_response={"message": message_text, "charts_count": len(charts)},
                    tools_used=metadata.get("agent_routing", []),
                    execution_time_ms=int(execution_time * 1000),
                    status="success",
                    message_id=assistant_message_id,
                )
            except Exception as e:
                logger.error("Failed to persist multi-agent conversation", error=str(e))

        background_tasks.add_task(_persist_multi_agent_default)

        return chat_response

    except HTTPException:
        raise
    except Exception as e:
        # SECURITY (HIGH-34 / F-33 regression): do NOT log request content.
        # ChatRequest.message, .chat_history, and .context routinely contain
        # PII (emails, names, AWS account IDs, cost figures, project codenames)
        # and this handler fires on ANY exception — a DB timeout, an Anthropic
        # 5xx, a serialization bug. With 7-day CloudWatch retention (MED-22)
        # and broad logs:FilterLogEvents IAM (HIGH-25), logging request.dict()
        # here exposes all-tenant chat content to anyone with log access.
        #
        # Log SHAPE (lengths, booleans, type names) — never CONTENT.
        # exc_info=True gives structlog the traceback; processors can gate it.
        # error_type (not str(e)) because upstream exceptions — LLM client,
        # agent workflow, asyncpg — may embed request fragments in messages.
        logger.error(
            "Chat request failed",
            conversation_id=conversation_id,
            user_id=str(context.user_id),
            organization_id=str(context.organization_id),
            message_length=len(request.message or ""),
            has_history=bool(request.chat_history),
            has_context=bool(request.context),
            error_type=type(e).__name__,
            exc_info=True,
        )
        execution_time = (datetime.utcnow() - start_time).total_seconds()
        return ChatResponse(
            message="I apologize, but I encountered an error processing your request. Please try again or rephrase your question.",
            conversation_id=conversation_id,
            charts=[],
            insights=[],
            action_items=[],
            suggestions=[
                "Try asking about your AWS costs",
                "Request a cost summary or breakdown by service",
                "Request cost optimization recommendations",
            ],
            agent_responses=[],
            execution_time=execution_time,
            timestamp=datetime.utcnow(),
        )


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    limit: int = 100,
    context: RequestContext = Depends(get_request_context),
):
    """Get conversation history by thread ID with optional limit (default 100)."""
    try:
        require_conversation_owner(conversation_id, context, action="read")

        messages = conversation_manager.get_conversation_history(conversation_id, limit=limit)

        logger.info(
            "conversation_accessed",
            conversation_id=conversation_id,
            user_id=str(context.user_id),
            message_count=len(messages),
        )

        return {
            "conversation_id": conversation_id,
            "messages": messages,
            "count": len(messages),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to fetch conversation history", conversation_id=conversation_id, error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch conversation history")


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    context: RequestContext = Depends(get_request_context),
):
    """Soft-delete a conversation thread by marking it inactive."""
    try:
        require_conversation_owner(conversation_id, context, action="delete")

        # Perform soft delete
        from backend.services.database import DatabaseService
        db = DatabaseService()
        await db.initialize()
        async with db.acquire() as conn:
            await conn.execute(
                "UPDATE conversation_threads SET is_active = FALSE, updated_at = NOW() WHERE thread_id = $1",
                conversation_id,
            )

        logger.info(
            "conversation_deleted",
            conversation_id=conversation_id,
            user_id=str(context.user_id),
        )

        return {"success": True, "conversation_id": conversation_id, "status": "deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete conversation", conversation_id=conversation_id, error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete conversation")


@router.get("/suggestions")
async def get_query_suggestions():
    """Get suggested queries for users"""

    suggestions = [
        {
            "text": "Show me my AWS costs for the last 30 days",
            "category": "cost_analysis",
            "description": "Get a comprehensive breakdown of your recent AWS spending",
        },
        {
            "text": "What are my top 5 most expensive AWS services?",
            "category": "service_analysis",
            "description": "Identify your biggest cost drivers",
        },
        {
            "text": "How can I optimize my EC2 costs?",
            "category": "optimization",
            "description": "Get specific recommendations for compute cost reduction",
        },
        {
            "text": "Show me cost trends over the last quarter",
            "category": "trend_analysis",
            "description": "Analyze spending patterns and identify trends",
        },
        {
            "text": "Generate a cost optimization report",
            "category": "reports",
            "description": "Create a comprehensive optimization analysis",
        },
        {
            "text": "What cost anomalies were detected this week?",
            "category": "anomaly_detection",
            "description": "Review unusual spending patterns and alerts",
        },
    ]

    return {"suggestions": suggestions}


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    context: RequestContext = Depends(get_request_context),
):
    """
    Streaming chat endpoint for real-time response generation.

    Requires authentication. All responses are scoped to the caller's
    organization and allowed AWS accounts (multi-tenant isolation).
    Returns server-sent events with incremental updates.
    """
    conversation_id = resolve_owned_conversation(
        request.conversation_id, context, action="stream"
    )

    # Tenant scope (captured for the streaming closure)
    organization_id = context.organization_id
    account_ids = context.allowed_account_ids

    logger.info(
        "chat_stream_started",
        conversation_id=conversation_id,
        user_id=str(context.user_id),
        organization_id=str(organization_id) if organization_id else None,
        account_count=len(account_ids),
    )

    async def generate_stream():
        """Generate streaming response events scoped to the caller's tenant."""
        yield f"data: {{'type': 'start', 'conversation_id': '{conversation_id}'}}\n\n"

        try:
            yield f"data: {{'type': 'status', 'message': 'Analyzing your query (multi-agent)...'}}\n\n"
            # Non-incremental streaming: emit final results as a set of events
            response = await execute_multi_agent_query(
                query=request.message,
                conversation_id=conversation_id,
                chat_history=request.chat_history or [],
                previous_context=request.context or {},
                organization_id=organization_id,
                account_ids=account_ids,
                timezone=(request.context or {}).get("timezone", "UTC"),
            )

            yield f"data: {{'type': 'message', 'content': {json.dumps(response.get('message', ''))}}}\n\n"
            if response.get("charts"):
                yield f"data: {{'type': 'charts', 'data': {json.dumps(response['charts'])}}}\n\n"
            if response.get("suggestions"):
                yield f"data: {{'type': 'suggestions', 'data': {json.dumps(response['suggestions'])}}}\n\n"
            yield f"data: {{'type': 'complete'}}\n\n"

        except Exception as e:
            logger.error(
                "chat_stream_error",
                conversation_id=conversation_id,
                user_id=str(context.user_id),
                error=str(e),
                exc_info=True,
            )
            yield "data: {'type': 'error', 'message': 'An error occurred processing your request.'}\n\n"

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/health")
async def chat_health():
    """Health check for chat services (multi-agent)."""
    try:
        # Lightweight health: ensure settings load and return static ok
        _ = settings.app_name
        return {
            "status": "healthy",
            "system": "multi-agent",
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error(f"Chat health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }


async def _store_conversation(
    conversation_id: str,
    user_message: str,
    assistant_message: str,
):
    """Store conversation in database (background task)"""

    try:
        from services.database import DatabaseService
        db = DatabaseService()
        await db.initialize()
        async with db.get_session() as session:
            await session.execute(
                """
                INSERT INTO conversation_history (conversation_id, user_message, assistant_message, created_at)
                VALUES (:conversation_id, :user_message, :assistant_message, NOW())
                """,
                {
                    "conversation_id": conversation_id,
                    "user_message": user_message,
                    "assistant_message": assistant_message,
                },
            )
            await session.commit()
        logger.info(
            "Conversation stored in database",
            conversation_id=conversation_id,
            user_message_length=len(user_message),
            assistant_message_length=len(assistant_message),
        )
    except Exception as e:
        logger.error(f"Failed to store conversation: {e}")
