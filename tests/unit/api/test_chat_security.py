"""
Security tests for chat API endpoints.

CRIT-1 — Conversation Access/Deletion IDOR:
1. GET /conversations/{conversation_id} requires authentication
2. GET /conversations/{conversation_id} validates ownership (IDOR protection)
3. DELETE /conversations/{conversation_id} requires authentication
4. DELETE /conversations/{conversation_id} validates ownership (IDOR protection)
5. Both endpoints log audit events for access and unauthorized attempts
6. Proper error messages for 401, 403, and 404 scenarios

CRIT-10 — Unauthenticated Streaming Endpoint with Cross-Tenant Access:
7. POST /stream requires authentication (Depends(get_request_context))
8. POST /stream does NOT fall back to anonymous / IP-derived identity
9. POST /stream passes organization_id + account_ids to the agent workflow
10. POST /stream verifies ownership when a conversation_id is supplied
11. POST /stream creates new threads under the authenticated user_id
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch, MagicMock
from fastapi import HTTPException
from uuid import uuid4

from backend.api.chat import (
    get_conversation,
    delete_conversation,
    get_request_context,
    chat_stream,
    chat,
    require_conversation_owner,
    resolve_owned_conversation,
)
from backend.models.schemas import ChatRequest
from backend.services.request_context import RequestContext


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_conversation_manager():
    """Mock conversation manager for testing"""
    with patch('backend.api.chat.conversation_manager') as mock_cm:
        yield mock_cm


@pytest.fixture
def mock_database_service():
    """Mock database service for testing"""
    with patch('backend.services.database.DatabaseService') as mock_db:
        instance = Mock()
        mock_db.return_value = instance
        instance.initialize = AsyncMock()
        # Mock acquire as an async context manager
        mock_conn = AsyncMock()
        instance.acquire = MagicMock(return_value=mock_conn)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        yield instance, mock_conn


@pytest.fixture
def sample_thread_metadata():
    """Sample thread metadata for testing"""
    return {
        'thread_id': 'test-thread-123',
        'user_id': str(uuid4()),
        'title': 'Test Conversation',
        'metadata': {},
        'created_at': '2024-01-01T00:00:00',
        'updated_at': '2024-01-01T00:00:00',
        'is_active': True
    }


@pytest.fixture
def sample_request_context():
    """Sample request context for testing"""
    return RequestContext(
        user_id=uuid4(),
        user_email='test@example.com',
        is_admin=False,
        organization_id=uuid4(),
        allowed_account_ids=['123456789012']
    )


# ---------------------------------------------------------------------------
# GET /conversations/{conversation_id} - Authentication Tests
# ---------------------------------------------------------------------------

class TestGetConversationAuthentication:
    """Tests for authentication requirement on GET endpoint"""

    @pytest.mark.asyncio
    async def test_get_conversation_requires_context_parameter(self):
        """Endpoint signature must include context parameter from Depends"""
        import inspect
        sig = inspect.signature(get_conversation)
        assert 'context' in sig.parameters
        # Verify it has a default (which should be Depends(get_request_context))
        assert sig.parameters['context'].default is not inspect.Parameter.empty

    @pytest.mark.asyncio
    async def test_get_request_context_raises_401_without_auth(self):
        """get_request_context dependency should raise 401 if no auth"""
        mock_request = Mock()
        mock_request.state = Mock()
        # No context attached
        delattr(mock_request.state, 'context') if hasattr(mock_request.state, 'context') else None

        with pytest.raises(HTTPException) as exc_info:
            await get_request_context(mock_request)

        assert exc_info.value.status_code == 401
        assert "Authentication required" in exc_info.value.detail


# ---------------------------------------------------------------------------
# GET /conversations/{conversation_id} - Ownership Validation Tests
# ---------------------------------------------------------------------------

class TestGetConversationOwnership:
    """Tests for IDOR protection on GET endpoint"""

    @pytest.mark.asyncio
    async def test_returns_404_when_conversation_not_found(
        self, mock_conversation_manager, sample_request_context
    ):
        """Should return 404 if conversation doesn't exist"""
        mock_conversation_manager.get_thread_metadata.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation('nonexistent-id', 100, sample_request_context)

        assert exc_info.value.status_code == 404
        assert "Conversation not found" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_returns_403_when_user_not_owner(
        self, mock_conversation_manager, sample_thread_metadata, sample_request_context
    ):
        """Should return 403 if user doesn't own the conversation"""
        # Set different user_id in thread metadata
        different_user_id = str(uuid4())
        sample_thread_metadata['user_id'] = different_user_id
        mock_conversation_manager.get_thread_metadata.return_value = sample_thread_metadata

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation('test-thread-123', 100, sample_request_context)

        assert exc_info.value.status_code == 403
        assert "Access denied" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_logs_unauthorized_access_attempt(
        self, mock_conversation_manager, sample_thread_metadata, sample_request_context
    ):
        """Should log warning when unauthorized access is attempted"""
        sample_thread_metadata['user_id'] = str(uuid4())
        mock_conversation_manager.get_thread_metadata.return_value = sample_thread_metadata

        with patch('backend.api.chat.logger') as mock_logger:
            with pytest.raises(HTTPException):
                await get_conversation('test-thread-123', 100, sample_request_context)

            # Verify warning was logged via the centralized helper
            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            assert call_args[0][0] == "unauthorized_conversation_attempt"
            assert call_args[1]['action'] == "read"
            assert 'conversation_id' in call_args[1]
            assert 'requesting_user_id' in call_args[1]
            assert 'owner_user_id' in call_args[1]

    @pytest.mark.asyncio
    async def test_allows_access_when_user_is_owner(
        self, mock_conversation_manager, sample_thread_metadata, sample_request_context
    ):
        """Should allow access when user owns the conversation"""
        # Set same user_id in thread metadata
        sample_thread_metadata['user_id'] = str(sample_request_context.user_id)
        mock_conversation_manager.get_thread_metadata.return_value = sample_thread_metadata
        mock_conversation_manager.get_conversation_history.return_value = [
            {'id': '1', 'role': 'user', 'content': 'Hello'}
        ]

        result = await get_conversation('test-thread-123', 100, sample_request_context)

        assert result['conversation_id'] == 'test-thread-123'
        assert 'messages' in result
        assert result['count'] == 1
        mock_conversation_manager.get_conversation_history.assert_called_once_with('test-thread-123', limit=100)

    @pytest.mark.asyncio
    async def test_logs_successful_access(
        self, mock_conversation_manager, sample_thread_metadata, sample_request_context
    ):
        """Should log info when conversation is successfully accessed"""
        sample_thread_metadata['user_id'] = str(sample_request_context.user_id)
        mock_conversation_manager.get_thread_metadata.return_value = sample_thread_metadata
        mock_conversation_manager.get_conversation_history.return_value = []

        with patch('backend.api.chat.logger') as mock_logger:
            await get_conversation('test-thread-123', 100, sample_request_context)

            # Verify info log
            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args
            assert call_args[0][0] == "conversation_accessed"
            assert call_args[1]['conversation_id'] == 'test-thread-123'
            assert 'user_id' in call_args[1]
            # MED-28: user_email removed from success logs (PII minimization)
            assert 'user_email' not in call_args[1]


# ---------------------------------------------------------------------------
# DELETE /conversations/{conversation_id} - Authentication Tests
# ---------------------------------------------------------------------------

class TestDeleteConversationAuthentication:
    """Tests for authentication requirement on DELETE endpoint"""

    @pytest.mark.asyncio
    async def test_delete_conversation_requires_context_parameter(self):
        """Endpoint signature must include context parameter from Depends"""
        import inspect
        sig = inspect.signature(delete_conversation)
        assert 'context' in sig.parameters
        assert sig.parameters['context'].default is not inspect.Parameter.empty


# ---------------------------------------------------------------------------
# DELETE /conversations/{conversation_id} - Ownership Validation Tests
# ---------------------------------------------------------------------------

class TestDeleteConversationOwnership:
    """
    Tests for IDOR protection on DELETE endpoint.

    After centralization (2026-03-05), DELETE uses the same
    require_conversation_owner() helper as GET/stream — ownership is verified
    via conversation_manager.get_thread_metadata(), then the soft-delete
    UPDATE runs separately. No more raw SELECT for ownership checking.
    """

    @pytest.mark.asyncio
    async def test_returns_404_when_conversation_not_found_on_delete(
        self, mock_conversation_manager, sample_request_context
    ):
        """Should return 404 if conversation doesn't exist (via centralized helper)."""
        mock_conversation_manager.get_thread_metadata.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await delete_conversation('nonexistent-id', sample_request_context)

        assert exc_info.value.status_code == 404
        assert "Conversation not found" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_returns_403_when_user_not_owner_on_delete(
        self, mock_conversation_manager, sample_request_context
    ):
        """Should return 403 if user doesn't own the conversation."""
        mock_conversation_manager.get_thread_metadata.return_value = {
            'thread_id': 'test-thread-123',
            'user_id': str(uuid4()),  # ← different owner
            'is_active': True,
        }

        with pytest.raises(HTTPException) as exc_info:
            await delete_conversation('test-thread-123', sample_request_context)

        assert exc_info.value.status_code == 403
        assert "Access denied" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_logs_unauthorized_deletion_attempt(
        self, mock_conversation_manager, sample_request_context
    ):
        """Unauthorized delete emits the unified event with action='delete'."""
        mock_conversation_manager.get_thread_metadata.return_value = {
            'user_id': str(uuid4()),
        }

        with patch('backend.api.chat.logger') as mock_logger:
            with pytest.raises(HTTPException):
                await delete_conversation('test-thread-123', sample_request_context)

            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            # Unified event name — same across all endpoints
            assert call_args[0][0] == "unauthorized_conversation_attempt"
            assert call_args[1]['action'] == "delete"
            assert 'conversation_id' in call_args[1]
            assert 'requesting_user_id' in call_args[1]
            assert 'owner_user_id' in call_args[1]

    @pytest.mark.asyncio
    async def test_db_update_not_called_when_ownership_fails(
        self, mock_conversation_manager, mock_database_service, sample_request_context
    ):
        """Belt-and-braces: the soft-delete UPDATE must not run on 403."""
        _, mock_conn = mock_database_service
        mock_conn.execute = AsyncMock()
        mock_conversation_manager.get_thread_metadata.return_value = {
            'user_id': str(uuid4()),
        }

        with pytest.raises(HTTPException):
            await delete_conversation('test-thread-123', sample_request_context)

        mock_conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_allows_deletion_when_user_is_owner(
        self, mock_conversation_manager, mock_database_service, sample_request_context
    ):
        """Should allow deletion when user owns the conversation."""
        _, mock_conn = mock_database_service
        mock_conn.execute = AsyncMock()
        # Ownership check via conversation_manager (centralized)
        mock_conversation_manager.get_thread_metadata.return_value = {
            'thread_id': 'test-thread-123',
            'user_id': str(sample_request_context.user_id),
            'is_active': True,
        }

        result = await delete_conversation('test-thread-123', sample_request_context)

        assert result['success'] is True
        assert result['conversation_id'] == 'test-thread-123'
        assert result['status'] == 'deleted'

        # Verify UPDATE query was executed
        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert 'UPDATE conversation_threads' in call_args[0][0]
        assert 'is_active = FALSE' in call_args[0][0]

    @pytest.mark.asyncio
    async def test_logs_successful_deletion(
        self, mock_conversation_manager, mock_database_service, sample_request_context
    ):
        """Should log info when conversation is successfully deleted."""
        _, mock_conn = mock_database_service
        mock_conn.execute = AsyncMock()
        mock_conversation_manager.get_thread_metadata.return_value = {
            'user_id': str(sample_request_context.user_id),
        }

        with patch('backend.api.chat.logger') as mock_logger:
            await delete_conversation('test-thread-123', sample_request_context)

            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args
            assert call_args[0][0] == "conversation_deleted"
            assert call_args[1]['conversation_id'] == 'test-thread-123'
            assert 'user_id' in call_args[1]
            # MED-28: user_email removed from success logs (PII minimization)
            assert 'user_email' not in call_args[1]


# ---------------------------------------------------------------------------
# ConversationManager.get_thread_metadata Tests
# ---------------------------------------------------------------------------

class TestConversationManagerMetadata:
    """Tests for the new get_thread_metadata method"""

    def test_get_thread_metadata_method_exists(self):
        """ConversationManager must have get_thread_metadata method"""
        from backend.services.conversation_manager import ConversationManager
        assert hasattr(ConversationManager, 'get_thread_metadata')

    def test_get_thread_metadata_returns_user_id(self):
        """get_thread_metadata must return user_id field"""
        from backend.services.conversation_manager import ConversationManager
        import inspect

        # Check method signature
        sig = inspect.signature(ConversationManager.get_thread_metadata)
        assert 'thread_id' in sig.parameters

        # Check it returns Optional[Dict]
        return_annotation = sig.return_annotation
        assert 'Optional' in str(return_annotation) or 'Dict' in str(return_annotation)


# ---------------------------------------------------------------------------
# Integration Test - End-to-End Security Flow
# ---------------------------------------------------------------------------

class TestEndToEndSecurityFlow:
    """Integration tests for complete security flow"""

    @pytest.mark.asyncio
    async def test_complete_security_flow_unauthorized_access(
        self, mock_conversation_manager, sample_thread_metadata
    ):
        """Test complete flow: user tries to access another user's conversation"""
        # Setup: Thread belongs to user A
        owner_id = str(uuid4())
        sample_thread_metadata['user_id'] = owner_id
        mock_conversation_manager.get_thread_metadata.return_value = sample_thread_metadata

        # User B tries to access
        attacker_context = RequestContext(
            user_id=uuid4(),
            user_email='attacker@example.com',
            is_admin=False
        )

        # Attempt access - should be denied
        with pytest.raises(HTTPException) as exc_info:
            await get_conversation('test-thread-123', 100, attacker_context)

        assert exc_info.value.status_code == 403

        # Verify no messages were retrieved
        mock_conversation_manager.get_conversation_history.assert_not_called()

    @pytest.mark.asyncio
    async def test_complete_security_flow_authorized_access(
        self, mock_conversation_manager, sample_thread_metadata
    ):
        """Test complete flow: user accesses their own conversation"""
        # Setup: Thread belongs to user
        owner_id = uuid4()
        sample_thread_metadata['user_id'] = str(owner_id)
        mock_conversation_manager.get_thread_metadata.return_value = sample_thread_metadata
        mock_conversation_manager.get_conversation_history.return_value = [
            {'id': '1', 'role': 'user', 'content': 'My query'}
        ]

        # User accesses their own thread
        owner_context = RequestContext(
            user_id=owner_id,
            user_email='owner@example.com',
            is_admin=False
        )

        result = await get_conversation('test-thread-123', 100, owner_context)

        # Verify success
        assert result['conversation_id'] == 'test-thread-123'
        assert len(result['messages']) == 1
        mock_conversation_manager.get_conversation_history.assert_called_once()


# ---------------------------------------------------------------------------
# CRIT-10 — POST /stream: Authentication & Tenant Isolation
# ---------------------------------------------------------------------------
# Fixed: 2026-03-05.  /stream previously had zero auth (IP/anon fallback) and
# called execute_multi_agent_query without organization_id or account_ids,
# allowing any unauthenticated caller to query cost data across ALL tenants.
# ---------------------------------------------------------------------------

@pytest.fixture
def tenant_context():
    """Authenticated user with full tenant scope (org + AWS accounts)."""
    return RequestContext(
        user_id=uuid4(),
        user_email="finops@tenant.example",
        is_admin=False,
        organization_id=uuid4(),
        allowed_account_ids=["111122223333", "444455556666"],
    )


@pytest.fixture
def chat_request_no_conversation():
    """Chat request with no conversation_id (endpoint must create one)."""
    return ChatRequest(message="Show me EC2 costs for last 30 days")


@pytest.fixture
def chat_request_with_conversation():
    """Chat request referencing an existing conversation_id."""
    return ChatRequest(
        message="And what about S3?",
        conversation_id="existing-thread-abc",
    )


async def _drain_sse(streaming_response) -> str:
    """Consume a StreamingResponse body and return concatenated text."""
    chunks = []
    async for chunk in streaming_response.body_iterator:
        chunks.append(chunk if isinstance(chunk, str) else chunk.decode())
    return "".join(chunks)


class TestChatStreamAuthentication:
    """CRIT-10: /stream must require authentication via Depends(get_request_context)."""

    def test_stream_signature_requires_context_dependency(self):
        """
        chat_stream must declare `context` bound to the auth dependency.
        Regression guard — the vulnerable version had no context parameter.
        """
        import inspect
        sig = inspect.signature(chat_stream)
        assert "context" in sig.parameters, (
            "chat_stream must declare a `context` parameter — CRIT-10 regression"
        )
        default = sig.parameters["context"].default
        assert default is not inspect.Parameter.empty, (
            "`context` must be bound to Depends(get_request_context)"
        )
        # FastAPI Depends() objects carry a .dependency attribute pointing at
        # the wrapped callable. Confirm it wraps get_request_context.
        assert getattr(default, "dependency", None) is get_request_context, (
            "`context` must use Depends(get_request_context) — enforces 401 on unauth"
        )

    def test_stream_signature_no_longer_uses_raw_http_request(self):
        """
        The vulnerable version took a raw `http_request: Request` and derived
        an anonymous/IP identity from it. Ensure that parameter is gone.
        """
        import inspect
        sig = inspect.signature(chat_stream)
        assert "http_request" not in sig.parameters, (
            "chat_stream must not accept raw http_request — anonymous fallback "
            "was the root cause of CRIT-10"
        )

    def test_stream_source_has_no_anonymous_fallback(self):
        """
        Static guard: the IP/anon identity patterns must not exist in the source.
        This is the regression tripwire that would have caught CRIT-10 originally.
        """
        import inspect
        source = inspect.getsource(chat_stream)
        assert 'f"ip:' not in source and "f'ip:" not in source, (
            "IP-derived user_id fallback detected in /stream — CRIT-10 regression"
        )
        assert 'f"anon:' not in source and "f'anon:" not in source, (
            "Anonymous user_id fallback detected in /stream — CRIT-10 regression"
        )
        assert "http_request.client.host" not in source, (
            "Client-IP introspection detected in /stream — CRIT-10 regression"
        )


class TestChatStreamTenantIsolation:
    """CRIT-10: /stream must pass organization_id + account_ids to the agent workflow."""

    @pytest.mark.asyncio
    async def test_stream_passes_organization_and_accounts_to_agent(
        self, mock_conversation_manager, tenant_context, chat_request_no_conversation
    ):
        """
        The core tenant-isolation fix: execute_multi_agent_query MUST receive
        the caller's organization_id and allowed_account_ids. Without these,
        the workflow returns data from ALL tenants.
        """
        mock_conversation_manager.create_thread.return_value = "new-thread-001"
        agent_response = {"message": "EC2 cost: $1,234.56", "charts": [], "suggestions": []}

        with patch("backend.api.chat.execute_multi_agent_query", new=AsyncMock(return_value=agent_response)) as mock_agent:
            resp = await chat_stream(chat_request_no_conversation, tenant_context)
            body = await _drain_sse(resp)

        mock_agent.assert_awaited_once()
        kwargs = mock_agent.await_args.kwargs
        # ── THE critical assertions for CRIT-10 ──
        assert kwargs["organization_id"] == tenant_context.organization_id, (
            "organization_id must be forwarded for tenant isolation"
        )
        assert kwargs["account_ids"] == tenant_context.allowed_account_ids, (
            "account_ids must be forwarded for tenant isolation"
        )
        assert kwargs["account_ids"] == ["111122223333", "444455556666"]
        # Sanity: the rest of the contract is preserved
        assert kwargs["query"] == chat_request_no_conversation.message
        assert kwargs["conversation_id"] == "new-thread-001"
        # Response stream shape
        assert "'type': 'start'" in body
        assert "'type': 'complete'" in body

    @pytest.mark.asyncio
    async def test_stream_new_thread_owned_by_authenticated_user(
        self, mock_conversation_manager, tenant_context, chat_request_no_conversation
    ):
        """
        New threads must be created under context.user_id, NOT an ip:/anon: value.
        """
        mock_conversation_manager.create_thread.return_value = "new-thread-002"

        with patch("backend.api.chat.execute_multi_agent_query", new=AsyncMock(return_value={"message": ""})):
            resp = await chat_stream(chat_request_no_conversation, tenant_context)
            await _drain_sse(resp)

        mock_conversation_manager.create_thread.assert_called_once()
        created_user_id = mock_conversation_manager.create_thread.call_args.kwargs["user_id"]
        assert created_user_id == str(tenant_context.user_id), (
            f"Thread created under wrong user: {created_user_id!r} — "
            f"expected authenticated user {tenant_context.user_id}"
        )
        assert not created_user_id.startswith("ip:")
        assert not created_user_id.startswith("anon:")

    @pytest.mark.asyncio
    async def test_stream_empty_account_list_still_forwarded(
        self, mock_conversation_manager, chat_request_no_conversation
    ):
        """
        Even if a user has zero accounts, that empty list must be passed (not None).
        An empty account_ids list means "no accounts accessible" — very different
        from None which the downstream workflow interprets as "no restriction".
        """
        ctx = RequestContext(
            user_id=uuid4(),
            user_email="newuser@tenant.example",
            organization_id=uuid4(),
            allowed_account_ids=[],  # ← freshly-provisioned user, no accounts yet
        )
        mock_conversation_manager.create_thread.return_value = "new-thread-003"

        with patch("backend.api.chat.execute_multi_agent_query", new=AsyncMock(return_value={"message": ""})) as mock_agent:
            resp = await chat_stream(chat_request_no_conversation, ctx)
            await _drain_sse(resp)

        assert mock_agent.await_args.kwargs["account_ids"] == []
        assert mock_agent.await_args.kwargs["account_ids"] is not None


class TestChatStreamConversationOwnership:
    """CRIT-10: when a conversation_id is supplied, /stream must verify ownership."""

    @pytest.mark.asyncio
    async def test_stream_404_when_conversation_does_not_exist(
        self, mock_conversation_manager, tenant_context, chat_request_with_conversation
    ):
        mock_conversation_manager.get_thread_metadata.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await chat_stream(chat_request_with_conversation, tenant_context)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_stream_403_when_conversation_owned_by_another_user(
        self, mock_conversation_manager, tenant_context, chat_request_with_conversation
    ):
        """IDOR protection — can't stream into someone else's conversation."""
        mock_conversation_manager.get_thread_metadata.return_value = {
            "thread_id": "existing-thread-abc",
            "user_id": str(uuid4()),  # ← different owner
            "is_active": True,
        }

        with pytest.raises(HTTPException) as exc_info:
            await chat_stream(chat_request_with_conversation, tenant_context)
        assert exc_info.value.status_code == 403
        assert "Access denied" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_stream_logs_unauthorized_conversation_attempt(
        self, mock_conversation_manager, tenant_context, chat_request_with_conversation
    ):
        attacker_owner = str(uuid4())
        mock_conversation_manager.get_thread_metadata.return_value = {
            "thread_id": "existing-thread-abc",
            "user_id": attacker_owner,
        }

        with patch("backend.api.chat.logger") as mock_logger:
            with pytest.raises(HTTPException):
                await chat_stream(chat_request_with_conversation, tenant_context)

        mock_logger.warning.assert_called_once()
        evt = mock_logger.warning.call_args
        # Unified event name from require_conversation_owner()
        assert evt[0][0] == "unauthorized_conversation_attempt"
        assert evt[1]["action"] == "stream"
        assert evt[1]["requesting_user_id"] == str(tenant_context.user_id)
        assert evt[1]["owner_user_id"] == attacker_owner

    @pytest.mark.asyncio
    async def test_stream_allows_owner_and_scopes_query(
        self, mock_conversation_manager, tenant_context, chat_request_with_conversation
    ):
        """Happy path: owner reuses existing conversation — tenant scope still applied."""
        mock_conversation_manager.get_thread_metadata.return_value = {
            "thread_id": "existing-thread-abc",
            "user_id": str(tenant_context.user_id),  # ← caller is owner
            "is_active": True,
        }

        with patch("backend.api.chat.execute_multi_agent_query", new=AsyncMock(return_value={"message": "ok"})) as mock_agent:
            resp = await chat_stream(chat_request_with_conversation, tenant_context)
            await _drain_sse(resp)

        # Existing thread reused — no new thread created
        mock_conversation_manager.create_thread.assert_not_called()
        # Tenant scope still enforced
        kwargs = mock_agent.await_args.kwargs
        assert kwargs["conversation_id"] == "existing-thread-abc"
        assert kwargs["organization_id"] == tenant_context.organization_id
        assert kwargs["account_ids"] == tenant_context.allowed_account_ids

    @pytest.mark.asyncio
    async def test_stream_agent_not_called_on_ownership_failure(
        self, mock_conversation_manager, tenant_context, chat_request_with_conversation
    ):
        """Belt-and-braces: ensure the expensive agent call never happens on 403."""
        mock_conversation_manager.get_thread_metadata.return_value = {
            "user_id": str(uuid4()),
        }

        with patch("backend.api.chat.execute_multi_agent_query", new=AsyncMock()) as mock_agent:
            with pytest.raises(HTTPException):
                await chat_stream(chat_request_with_conversation, tenant_context)

        mock_agent.assert_not_awaited()


class TestChatStreamAuditLogging:
    """CRIT-10: /stream must emit audit logs for successful access."""

    @pytest.mark.asyncio
    async def test_stream_logs_start_event_with_tenant_context(
        self, mock_conversation_manager, tenant_context, chat_request_no_conversation
    ):
        mock_conversation_manager.create_thread.return_value = "new-thread-004"

        with patch("backend.api.chat.execute_multi_agent_query", new=AsyncMock(return_value={"message": ""})):
            with patch("backend.api.chat.logger") as mock_logger:
                resp = await chat_stream(chat_request_no_conversation, tenant_context)
                await _drain_sse(resp)

        # Find the chat_stream_started event among info calls
        info_events = [c for c in mock_logger.info.call_args_list if c[0] and c[0][0] == "chat_stream_started"]
        assert len(info_events) == 1, "expected exactly one chat_stream_started log event"
        evt = info_events[0][1]
        assert evt["user_id"] == str(tenant_context.user_id)
        assert evt["organization_id"] == str(tenant_context.organization_id)
        assert evt["account_count"] == 2
        # Audit logs must NOT leak raw email (MED-16/MED-28 regression tripwire)
        assert "user_email" not in evt


# ─────────────────────────────────────────────────────────────────────────────
# Centralized ownership helpers — direct tests
# All four chat endpoints delegate to these.  Testing them directly ensures
# the policy (404/403/event shape) is correct at the source.
# ─────────────────────────────────────────────────────────────────────────────

class TestRequireConversationOwner:
    """Direct unit tests for the centralized IDOR guard."""

    def test_returns_conversation_id_when_owner(
        self, mock_conversation_manager, sample_request_context
    ):
        mock_conversation_manager.get_thread_metadata.return_value = {
            "user_id": str(sample_request_context.user_id),
        }
        result = require_conversation_owner("abc", sample_request_context, action="read")
        assert result == "abc"

    def test_raises_404_when_thread_missing(
        self, mock_conversation_manager, sample_request_context
    ):
        mock_conversation_manager.get_thread_metadata.return_value = None
        with pytest.raises(HTTPException) as exc:
            require_conversation_owner("missing", sample_request_context, action="read")
        assert exc.value.status_code == 404

    def test_raises_403_when_not_owner(
        self, mock_conversation_manager, sample_request_context
    ):
        mock_conversation_manager.get_thread_metadata.return_value = {
            "user_id": str(uuid4()),
        }
        with pytest.raises(HTTPException) as exc:
            require_conversation_owner("abc", sample_request_context, action="delete")
        assert exc.value.status_code == 403

    def test_action_label_appears_in_audit_event(
        self, mock_conversation_manager, sample_request_context
    ):
        """The `action` kwarg drives the audit-event field, differentiating read/delete/stream/chat."""
        mock_conversation_manager.get_thread_metadata.return_value = {"user_id": str(uuid4())}

        with patch("backend.api.chat.logger") as mock_logger:
            with pytest.raises(HTTPException):
                require_conversation_owner("abc", sample_request_context, action="custom-op")

        assert mock_logger.warning.call_args[1]["action"] == "custom-op"
        assert mock_logger.warning.call_args[0][0] == "unauthorized_conversation_attempt"

    def test_string_coercion_of_user_id(
        self, mock_conversation_manager
    ):
        """UUID user_id in context is compared as str against DB-stored string."""
        uid = uuid4()
        ctx = RequestContext(user_id=uid, user_email="u@e.com")
        mock_conversation_manager.get_thread_metadata.return_value = {
            "user_id": str(uid),  # DB stores as string
        }
        # Should NOT raise — str(uid) == str(uid)
        assert require_conversation_owner("abc", ctx, action="read") == "abc"


class TestResolveOwnedConversation:
    """Direct tests for the supplied→verify, absent→create helper."""

    def test_creates_new_thread_when_none_supplied(
        self, mock_conversation_manager, sample_request_context
    ):
        mock_conversation_manager.create_thread.return_value = "new-001"

        result = resolve_owned_conversation(None, sample_request_context, action="chat")

        assert result == "new-001"
        mock_conversation_manager.create_thread.assert_called_once_with(
            user_id=str(sample_request_context.user_id), title=None
        )
        # Ownership check NOT called for new threads
        mock_conversation_manager.get_thread_metadata.assert_not_called()

    def test_verifies_ownership_when_id_supplied(
        self, mock_conversation_manager, sample_request_context
    ):
        mock_conversation_manager.get_thread_metadata.return_value = {
            "user_id": str(sample_request_context.user_id),
        }

        result = resolve_owned_conversation("existing-001", sample_request_context, action="chat")

        assert result == "existing-001"
        mock_conversation_manager.get_thread_metadata.assert_called_once_with("existing-001")
        mock_conversation_manager.create_thread.assert_not_called()

    def test_propagates_403_when_supplied_id_not_owned(
        self, mock_conversation_manager, sample_request_context
    ):
        mock_conversation_manager.get_thread_metadata.return_value = {"user_id": str(uuid4())}

        with pytest.raises(HTTPException) as exc:
            resolve_owned_conversation("stolen-001", sample_request_context, action="chat")
        assert exc.value.status_code == 403
        mock_conversation_manager.create_thread.assert_not_called()

    def test_empty_string_treated_as_no_conversation(
        self, mock_conversation_manager, sample_request_context
    ):
        """Falsy conversation_id ("") triggers the create-new path, not the verify path."""
        mock_conversation_manager.create_thread.return_value = "new-002"
        result = resolve_owned_conversation("", sample_request_context, action="chat")
        assert result == "new-002"
        mock_conversation_manager.get_thread_metadata.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# POST /chat — auth enforcement (hardened alongside CRIT-10 fix)
# Previously /chat used get_context_from_request() with an IP/anon fallback.
# After centralization it uses Depends(get_request_context) like /stream.
# ─────────────────────────────────────────────────────────────────────────────

class TestChatEndpointAuthentication:
    """POST /chat must require authentication (no more IP/anon fallback)."""

    def test_chat_signature_requires_context_dependency(self):
        import inspect
        sig = inspect.signature(chat)
        assert "context" in sig.parameters, (
            "/chat must declare a `context` parameter — auth is mandatory"
        )
        default = sig.parameters["context"].default
        assert getattr(default, "dependency", None) is get_request_context, (
            "/chat `context` must use Depends(get_request_context) — enforces 401"
        )

    def test_chat_signature_no_raw_http_request(self):
        """The optional-auth path took a raw Request. Ensure it's gone."""
        import inspect
        sig = inspect.signature(chat)
        assert "http_request" not in sig.parameters, (
            "/chat must not accept raw http_request — was the anon-fallback hook"
        )

    def test_chat_source_has_no_anonymous_fallback(self):
        """Same tripwire as /stream — no IP/anon identity patterns."""
        import inspect
        source = inspect.getsource(chat)
        assert 'f"ip:' not in source and "f'ip:" not in source
        assert 'f"anon:' not in source and "f'anon:" not in source
        assert "http_request.client.host" not in source
        assert "get_context_from_request" not in source, (
            "/chat must use require_context (via Depends), not the Optional variant"
        )

    def test_chat_uses_resolve_owned_conversation(self):
        """Ownership check + thread creation go through the centralized helper."""
        import inspect
        source = inspect.getsource(chat)
        assert "resolve_owned_conversation" in source, (
            "/chat must use resolve_owned_conversation() for ownership + thread creation"
        )


class TestChatModuleNoOptionalAuthImport:
    """
    Regression tripwire at module level: the Optional-returning auth helper
    (get_context_from_request) must not be imported. Only the fail-closed
    require_context should be present.
    """

    def test_chat_module_does_not_import_get_context_from_request(self):
        import backend.api.chat as chat_module
        # The import should not exist in the module namespace
        assert not hasattr(chat_module, "get_context_from_request"), (
            "chat.py must not import get_context_from_request — it returns None "
            "on missing auth instead of raising 401"
        )

    def test_chat_module_imports_require_context(self):
        import backend.api.chat as chat_module
        assert hasattr(chat_module, "require_context"), (
            "chat.py must import require_context (the fail-closed 401 variant)"
        )
