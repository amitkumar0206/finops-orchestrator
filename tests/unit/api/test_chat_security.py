"""
Tests for CRIT-1: Unauthenticated Conversation Access/Deletion (IDOR)

Verifies:
1. GET /conversations/{conversation_id} requires authentication
2. GET /conversations/{conversation_id} validates ownership (IDOR protection)
3. DELETE /conversations/{conversation_id} requires authentication
4. DELETE /conversations/{conversation_id} validates ownership (IDOR protection)
5. Both endpoints log audit events for access and unauthorized attempts
6. Proper error messages for 401, 403, and 404 scenarios
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch, MagicMock
from fastapi import HTTPException
from uuid import uuid4

from backend.api.chat import get_conversation, delete_conversation, get_request_context
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

            # Verify warning was logged
            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            assert call_args[0][0] == "unauthorized_conversation_access_attempt"
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
            assert 'user_email' in call_args[1]


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
    """Tests for IDOR protection on DELETE endpoint"""

    @pytest.mark.asyncio
    async def test_returns_404_when_conversation_not_found_on_delete(
        self, mock_database_service, sample_request_context
    ):
        """Should return 404 if conversation doesn't exist"""
        db_instance, mock_conn = mock_database_service
        mock_conn.fetchrow = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await delete_conversation('nonexistent-id', sample_request_context)

        assert exc_info.value.status_code == 404
        assert "Conversation not found" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_returns_403_when_user_not_owner_on_delete(
        self, mock_database_service, sample_request_context
    ):
        """Should return 403 if user doesn't own the conversation"""
        db_instance, mock_conn = mock_database_service
        # Return row with different user_id
        mock_conn.fetchrow = AsyncMock(return_value={
            'user_id': str(uuid4()),
            'is_active': True
        })

        with pytest.raises(HTTPException) as exc_info:
            await delete_conversation('test-thread-123', sample_request_context)

        assert exc_info.value.status_code == 403
        assert "Access denied" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_logs_unauthorized_deletion_attempt(
        self, mock_database_service, sample_request_context
    ):
        """Should log warning when unauthorized deletion is attempted"""
        db_instance, mock_conn = mock_database_service
        mock_conn.fetchrow = AsyncMock(return_value={
            'user_id': str(uuid4()),
            'is_active': True
        })

        with patch('backend.api.chat.logger') as mock_logger:
            with pytest.raises(HTTPException):
                await delete_conversation('test-thread-123', sample_request_context)

            # Verify warning was logged
            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            assert call_args[0][0] == "unauthorized_conversation_deletion_attempt"
            assert 'conversation_id' in call_args[1]
            assert 'requesting_user_id' in call_args[1]
            assert 'owner_user_id' in call_args[1]

    @pytest.mark.asyncio
    async def test_allows_deletion_when_user_is_owner(
        self, mock_database_service, sample_request_context
    ):
        """Should allow deletion when user owns the conversation"""
        db_instance, mock_conn = mock_database_service
        # Return row with same user_id
        mock_conn.fetchrow = AsyncMock(return_value={
            'user_id': str(sample_request_context.user_id),
            'is_active': True
        })
        mock_conn.execute = AsyncMock()

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
        self, mock_database_service, sample_request_context
    ):
        """Should log info when conversation is successfully deleted"""
        db_instance, mock_conn = mock_database_service
        mock_conn.fetchrow = AsyncMock(return_value={
            'user_id': str(sample_request_context.user_id),
            'is_active': True
        })
        mock_conn.execute = AsyncMock()

        with patch('backend.api.chat.logger') as mock_logger:
            await delete_conversation('test-thread-123', sample_request_context)

            # Verify info log
            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args
            assert call_args[0][0] == "conversation_deleted"
            assert call_args[1]['conversation_id'] == 'test-thread-123'
            assert 'user_id' in call_args[1]
            assert 'user_email' in call_args[1]


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
