"""
ConversationManager - Threaded conversation and state management using PostgreSQL (psycopg2)

Responsibilities:
- Create and manage conversation threads and ordered messages
- Persist query intents and agent execution logs
- Provide contextual filters for follow-up queries (date_range, services, regions, accounts, drill_level)

Tables (from Alembic migrations):
- conversation_threads(thread_id, user_id, title, metadata, created_at, updated_at, is_active)
- conversation_messages(id, thread_id, role, content, message_type, metadata, ordering_index, created_at, updated_at)
- query_intents(id, thread_id, message_id, original_query, rewritten_query, intent_type, intent_confidence, extracted_dimensions, created_at)
- agent_executions(id, thread_id, message_id, agent_name, agent_type, input_query, output_response, tools_used, execution_time_ms, status, error_message, error_stack_trace, metadata, created_at, completed_at)

Notes:
- Uses psycopg2 connection pooling for efficiency
- Intentionally synchronous; FastAPI should run these in a threadpool if used in hot paths
- Provides small, well-scoped transactions with proper error handling
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import json
import threading
import uuid

from psycopg2.extras import Json, RealDictCursor, register_uuid
from psycopg2.pool import ThreadedConnectionPool
import structlog

from backend.config.settings import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

# Register UUID adapter for psycopg2 to handle UUID objects
register_uuid()

_pool_lock = threading.Lock()
_pool: Optional[ThreadedConnectionPool] = None


def _get_pool() -> ThreadedConnectionPool:
    """Initialize and return a global ThreadedConnectionPool."""
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is None:
            dsn = (
                f"host={settings.postgres_host} port={settings.postgres_port} "
                f"dbname={settings.postgres_db} user={settings.postgres_user} "
                f"password={settings.postgres_password} application_name=finops-conversation-manager"
            )
            _pool = ThreadedConnectionPool(minconn=1, maxconn=10, dsn=dsn)
            logger.info("Initialized PostgreSQL ThreadedConnectionPool for ConversationManager")
    return _pool


def _get_conn():
    pool = _get_pool()
    return pool.getconn()


def _put_conn(conn):
    pool = _get_pool()
    try:
        pool.putconn(conn)
    except Exception:
        try:
            conn.close()
        except Exception:
            pass


def _json(obj: Any) -> Json:
    return Json(obj, dumps=lambda o: json.dumps(o, default=str))


def _assert_thread_owner(cur, thread_id: str, user_id: str, *, for_update: bool = False) -> None:
    """
    HIGH-14 ownership guard for write paths. Raises PermissionError if the
    caller's user_id does not own thread_id (or the thread doesn't exist —
    we don't distinguish, so existence doesn't leak to non-owners).

    Runs inside the caller's transaction; `for_update=True` additionally
    locks the thread row (used by add_message for ordering_index safety).

    The API layer (F-33, require_conversation_owner) checks first, so
    production traffic never reaches a raise here. This is the floor for
    callers that bypass api/chat.py — scheduled jobs, admin tooling, new
    endpoints that forget the API check.
    """
    lock = " FOR UPDATE" if for_update else ""
    cur.execute(
        f"SELECT 1 FROM conversation_threads WHERE thread_id = %s AND user_id = %s{lock}",
        (thread_id, user_id),
    )
    if cur.fetchone() is None:
        raise PermissionError(
            "HIGH-14: user_id does not own thread_id (or thread does not exist)"
        )


# HIGH-14 — ownership predicate for SELECTs on child tables.
# conversation_messages / query_intents / agent_executions have no user_id
# column; ownership is FK'd through conversation_threads. The EXISTS subquery
# short-circuits to 0 rows for non-owners (silent filter — reads return empty,
# which is the "WHERE user_id = $N" remediation semantic for reads).
_OWNED_THREAD = (
    "EXISTS (SELECT 1 FROM conversation_threads ct "
    "WHERE ct.thread_id = %s AND ct.user_id = %s)"
)


class ConversationManager:
    """Thread-aware conversation persistence and context extraction."""

    # region Threads and messages
    def create_thread(self, user_id: str, title: str | None = None) -> str:
        sql = (
            "INSERT INTO conversation_threads (user_id, title, metadata) "
            "VALUES (%s, %s, %s) RETURNING thread_id"
        )
        conn = _get_conn()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(sql, (user_id, title, _json({})))
                    thread_id = cur.fetchone()[0]
                    return str(thread_id)
        except Exception as e:
            logger.error("Failed to create thread", error=str(e))
            raise
        finally:
            _put_conn(conn)

    def add_message(
        self,
        thread_id: str,
        user_id: str,
        role: str,
        content: str,
        message_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        conn = _get_conn()
        try:
            with conn:
                with conn.cursor() as cur:
                    # HIGH-14 — the FOR UPDATE lock was already here for ordering_index
                    # race-safety; it now also carries the ownership check. Non-owners
                    # (and nonexistent threads) raise before any write.
                    _assert_thread_owner(cur, thread_id, user_id, for_update=True)
                    cur.execute(
                        "SELECT COALESCE(MAX(ordering_index), 0) FROM conversation_messages WHERE thread_id = %s",
                        (thread_id,),
                    )
                    next_index = (cur.fetchone()[0] or 0) + 1

                    cur.execute(
                        (
                            "INSERT INTO conversation_messages "
                            "(thread_id, role, content, message_type, metadata, ordering_index) "
                            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id"
                        ),
                        (thread_id, role, content, message_type, _json(metadata or {}), next_index),
                    )
                    message_id = cur.fetchone()[0]
                    return str(message_id)
        except Exception as e:
            logger.error("Failed to add_message", thread_id=thread_id, error=str(e))
            raise
        finally:
            _put_conn(conn)

    def get_conversation_history(self, thread_id: str, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        # HIGH-14 — conversation_messages has no user_id column; ownership is
        # enforced via EXISTS on conversation_threads. Non-owners get [] (the
        # thread simply doesn't exist from their perspective). F-33's API-layer
        # require_conversation_owner() checks first and 403s with an audit log;
        # this is the defense-in-depth floor for bypassing callers.
        sql = (
            "SELECT id, thread_id, role, content, message_type, metadata, ordering_index, created_at, updated_at "
            f"FROM conversation_messages WHERE thread_id = %s AND {_OWNED_THREAD} "
            "ORDER BY ordering_index DESC LIMIT %s"
        )
        conn = _get_conn()
        try:
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, (thread_id, thread_id, user_id, limit))
                    rows = cur.fetchall() or []
                    rows.reverse()
                    for r in rows:
                        if isinstance(r.get("metadata"), str):
                            try:
                                r["metadata"] = json.loads(r["metadata"]) if r["metadata"] else {}
                            except Exception:
                                r["metadata"] = {}
                    return rows
        except Exception as e:
            logger.error("Failed to get_conversation_history", thread_id=thread_id, error=str(e))
            raise
        finally:
            _put_conn(conn)

    def get_thread_metadata(self, thread_id: str) -> Optional[Dict[str, Any]]:
        """
        Get thread metadata including user_id for ownership validation.
        Returns None if thread doesn't exist.

        HIGH-14 — INTENTIONALLY UNSCOPED. This is the ownership-lookup primitive:
        require_conversation_owner() at api/chat.py:65 calls this to FETCH the
        owner's user_id and compare it against the caller's. Adding a user_id
        filter here would make that comparison circular (caller would need to
        already know they're the owner to look up whether they're the owner)
        and would collapse F-33's 404/403 distinction. Every OTHER method in
        this class is scoped — this is the one exempted by design. The CI
        tripwire at test_conversation_manager_isolation.py explicitly asserts
        this exemption so a well-meaning "fix" doesn't break the API layer.
        """
        sql = (
            "SELECT thread_id, user_id, title, metadata, created_at, updated_at, is_active "
            "FROM conversation_threads WHERE thread_id = %s"
        )
        conn = _get_conn()
        try:
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, (thread_id,))
                    row = cur.fetchone()
                    if not row:
                        return None
                    # Parse metadata if it's a string
                    if isinstance(row.get("metadata"), str):
                        try:
                            row["metadata"] = json.loads(row["metadata"]) if row["metadata"] else {}
                        except Exception:
                            row["metadata"] = {}
                    return dict(row)
        except Exception as e:
            logger.error("Failed to get_thread_metadata", thread_id=thread_id, error=str(e))
            raise
        finally:
            _put_conn(conn)

    # endregion

    # region Intents and executions
    def save_query_intent(
        self,
        thread_id: str,
        user_id: str,
        message_id: str,
        original_query: str,
        rewritten_query: Optional[str],
        intent_type: str,
        intent_confidence: float,
        extracted_dimensions: Optional[Dict[str, Any]],
        rewriter_confidence: Optional[float] = None,
    ) -> str:
        intent_confidence = max(0.0, min(1.0, float(intent_confidence)))
        dims = dict(extracted_dimensions or {})
        if rewriter_confidence is not None:
            dims.setdefault("metadata", {})["rewriter_confidence"] = float(rewriter_confidence)

        sql = (
            "INSERT INTO query_intents "
            "(thread_id, message_id, original_query, rewritten_query, intent_type, intent_confidence, extracted_dimensions) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id"
        )
        conn = _get_conn()
        try:
            with conn:
                with conn.cursor() as cur:
                    _assert_thread_owner(cur, thread_id, user_id)  # HIGH-14
                    cur.execute(
                        sql,
                        (
                            thread_id,
                            message_id,
                            original_query,
                            rewritten_query,
                            intent_type,
                            intent_confidence,
                            _json(dims),
                        ),
                    )
                    intent_id = cur.fetchone()[0]
                    return str(intent_id)
        except Exception as e:
            logger.error("Failed to save_query_intent", thread_id=thread_id, error=str(e))
            raise
        finally:
            _put_conn(conn)

    def save_agent_execution(
        self,
        thread_id: str,
        user_id: str,
        agent_name: str,
        agent_type: str,
        input_query: str,
        output_response: Optional[Dict[str, Any]],
        tools_used: Optional[List[str]],
        execution_time_ms: int,
        status: str,
        error_message: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> str:
        sql = (
            "INSERT INTO agent_executions "
            "(thread_id, message_id, agent_name, agent_type, input_query, output_response, tools_used, execution_time_ms, status, error_message) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id"
        )
        conn = _get_conn()
        try:
            with conn:
                with conn.cursor() as cur:
                    _assert_thread_owner(cur, thread_id, user_id)  # HIGH-14
                    cur.execute(
                        sql,
                        (
                            thread_id,
                            uuid.UUID(message_id) if message_id else None,
                            agent_name,
                            agent_type,
                            input_query,
                            _json(output_response or {}),
                            _json(tools_used or []),
                            int(execution_time_ms),
                            status,
                            error_message,
                        ),
                    )
                    exec_id = cur.fetchone()[0]
                    return str(exec_id)
        except Exception as e:
            logger.error("Failed to save_agent_execution", thread_id=thread_id, error=str(e))
            raise
        finally:
            _put_conn(conn)

    # endregion

    # region Context extraction
    def get_context_for_query(self, thread_id: str, user_id: str) -> Dict[str, Any]:
        intents = self._fetch_recent_intents(thread_id, user_id, limit=25)
        messages = self._fetch_recent_messages(thread_id, user_id, limit=20)

        context: Dict[str, Any] = {
            "time_range": None,  # Changed from date_range to time_range for consistency with multi_agent_workflow
            "services": [],
            "regions": [],
            "accounts": [],
            "tags": {},
            "exclude_line_item_types": None,
            "include_line_item_types": None,
            "purchase_options": None,
            "platforms": None,
            "database_engines": None,
            "drill_level": 0,
            "conversation_history": [],  # Add for intent classifier follow-up detection
            "last_intent": None,  # Add for intent classifier follow-up detection
            "last_query": None,  # Add for intent classifier context
        }

        def _merge_dims(dims: Dict[str, Any]):
            if not dims:
                return
            tr = dims.get("time_range") or dims.get("date_range")
            if tr and not context["time_range"]:
                # CRITICAL FIX: Ensure time_range is a dict, not a JSON string (can happen from nested serialization)
                if isinstance(tr, str):
                    try:
                        context["time_range"] = json.loads(tr)
                        logger.warning("Deserialized time_range from JSON string in context merge")
                    except:
                        logger.error(f"Failed to parse time_range string from context: {tr[:100]}")
                        context["time_range"] = {}
                elif isinstance(tr, dict):
                    context["time_range"] = tr
                else:
                    context["time_range"] = {}
            for key in ("services", "regions", "accounts"):
                vals = dims.get(key)
                if vals:
                    existing = set(context[key])
                    for v in vals:
                        if v not in existing:
                            context[key].append(v)
                            existing.add(v)
            tag_filters = dims.get("tags") or {}
            if tag_filters:
                target_tag_dict = context.setdefault("tags", {})
                for tag_key, tag_values in tag_filters.items():
                    normalized_values = tag_values if isinstance(tag_values, list) else [tag_values]
                    merged_values = set(target_tag_dict.get(tag_key, []))
                    for val in normalized_values:
                        if val not in merged_values:
                            merged_values.add(val)
                    target_tag_dict[tag_key] = list(merged_values)

            for advanced_key in (
                "exclude_line_item_types",
                "include_line_item_types",
                "purchase_options",
                "platforms",
                "database_engines",
            ):
                adv_vals = dims.get(advanced_key)
                if not adv_vals:
                    continue
                if isinstance(adv_vals, list):
                    existing_vals = set(context.get(advanced_key) or [])
                    for val in adv_vals:
                        if val not in existing_vals:
                            existing_vals.add(val)
                    context[advanced_key] = list(existing_vals)
                else:
                    context[advanced_key] = adv_vals
            dims_list = dims.get("dimensions") or []
            if dims_list:
                context["drill_level"] = max(context["drill_level"], len(dims_list))

        for rec in intents:
            _merge_dims(rec.get("extracted_dimensions") or {})

        # Always check messages for additional dimensions (not just as fallback)
        for msg in messages:
            md = msg.get("metadata") or {}
            _merge_dims(md.get("extracted_dimensions") or md)
        
        # Build conversation_history for intent classifier
        # Include last 10 messages in chronological order
        recent_msgs = sorted(messages[:10], key=lambda m: m.get("ordering_index", 0))
        for msg in recent_msgs:
            context["conversation_history"].append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", "")
            })
        
        # Get last intent and query from most recent intent record
        if intents:
            latest_intent = intents[0]
            context["last_intent"] = latest_intent.get("intent_type")
            # Try to find the corresponding user message
            if messages:
                # Find most recent user message
                for msg in messages:
                    if msg.get("role") == "user":
                        context["last_query"] = msg.get("content", "")
                        break

        return context

    def _fetch_recent_intents(self, thread_id: str, user_id: str, limit: int) -> List[Dict[str, Any]]:
        sql = (
            "SELECT id, intent_type, intent_confidence, extracted_dimensions, created_at "
            f"FROM query_intents WHERE thread_id = %s AND {_OWNED_THREAD} "
            "ORDER BY created_at DESC LIMIT %s"
        )
        conn = _get_conn()
        try:
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, (thread_id, thread_id, user_id, limit))
                    rows = cur.fetchall() or []
                    for r in rows:
                        if isinstance(r.get("extracted_dimensions"), str):
                            try:
                                r["extracted_dimensions"] = json.loads(r["extracted_dimensions"]) or {}
                            except Exception:
                                r["extracted_dimensions"] = {}
                    return rows
        except Exception as e:
            logger.error("Failed to fetch recent intents", thread_id=thread_id, error=str(e))
            return []
        finally:
            _put_conn(conn)

    def _fetch_recent_messages(self, thread_id: str, user_id: str, limit: int) -> List[Dict[str, Any]]:
        sql = (
            "SELECT id, role, content, message_type, metadata, ordering_index, created_at "
            f"FROM conversation_messages WHERE thread_id = %s AND {_OWNED_THREAD} "
            "ORDER BY ordering_index DESC LIMIT %s"
        )
        conn = _get_conn()
        try:
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, (thread_id, thread_id, user_id, limit))
                    rows = cur.fetchall() or []
                    for r in rows:
                        if isinstance(r.get("metadata"), str):
                            try:
                                r["metadata"] = json.loads(r["metadata"]) or {}
                            except Exception:
                                r["metadata"] = {}
                    return rows
        except Exception as e:
            logger.error("Failed to fetch recent messages", thread_id=thread_id, error=str(e))
            return []
        finally:
            _put_conn(conn)

    # endregion


conversation_manager = ConversationManager()
