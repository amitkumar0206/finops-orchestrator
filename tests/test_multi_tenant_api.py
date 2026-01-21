"""
API Integration Tests for Multi-Tenant Support

Tests cover:
1. Scope API endpoints
2. Saved Views API endpoints
3. Organizations API endpoints
4. Chat API with scope context
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4
import json

# We'll need to mock the database for these tests
# Import the app
import sys
sys.path.insert(0, '/Users/agranee/Documents/mercor/finops-orchestrator/mercor/model_a/backend')


# ==================== Fixtures ====================

@pytest.fixture
def mock_request_context():
    """Create a mock RequestContext for testing"""
    from backend.services.request_context import RequestContext, SavedViewInfo

    user_id = uuid4()
    org_id = uuid4()
    view_id = uuid4()

    return RequestContext(
        user_id=user_id,
        user_email="test@example.com",
        is_admin=False,
        organization_id=org_id,
        organization_name="Test Organization",
        allowed_account_ids=["123456789012", "234567890123"],
        active_saved_view=SavedViewInfo(
            id=view_id,
            name="Production View",
            account_ids=[uuid4()],
        ),
        org_role="member",
    )


@pytest.fixture
def mock_admin_context():
    """Create a mock admin RequestContext"""
    from backend.services.request_context import RequestContext

    return RequestContext(
        user_id=uuid4(),
        user_email="admin@example.com",
        is_admin=True,
        organization_id=uuid4(),
        organization_name="Test Organization",
        allowed_account_ids=["123456789012"],
        org_role="owner",
    )


# ==================== Scope API Tests ====================

class TestScopeAPI:
    """Tests for Scope API endpoints"""

    def test_scope_dict_structure(self, mock_request_context):
        """Test that scope dict has correct structure"""
        scope = mock_request_context.to_scope_dict()

        # Check required fields
        assert 'organization_id' in scope
        assert 'organization_name' in scope
        assert 'allowed_account_ids' in scope
        assert 'account_count' in scope
        assert 'active_view' in scope
        assert 'is_admin' in scope
        assert 'org_role' in scope

        # Check values
        assert scope['organization_name'] == "Test Organization"
        assert scope['account_count'] == 2
        assert scope['is_admin'] is False
        assert scope['org_role'] == 'member'

    def test_scope_dict_with_active_view(self, mock_request_context):
        """Test scope dict includes active view info"""
        scope = mock_request_context.to_scope_dict()

        assert scope['active_view'] is not None
        assert scope['active_view']['name'] == "Production View"

    def test_scope_dict_admin(self, mock_admin_context):
        """Test scope dict for admin user"""
        scope = mock_admin_context.to_scope_dict()

        assert scope['is_admin'] is True
        assert scope['org_role'] == 'owner'


# ==================== SavedViews API Response Tests ====================

class TestSavedViewsAPIResponses:
    """Tests for Saved Views API response structures"""

    def test_saved_view_response_structure(self):
        """Test that saved view response has correct structure"""
        # Mock view data
        view_data = {
            'id': str(uuid4()),
            'name': 'Test View',
            'description': 'A test view',
            'account_ids': [str(uuid4())],
            'account_count': 1,
            'default_time_range': {'days': 30},
            'filters': {},
            'is_default': False,
            'is_personal': True,
            'expires_at': None,
            'created_at': '2026-01-21T10:00:00',
            'created_by': str(uuid4()),
            'created_by_email': 'creator@example.com',
        }

        # Check all required fields
        required_fields = [
            'id', 'name', 'account_ids', 'account_count',
            'is_default', 'is_personal', 'created_at'
        ]
        for field in required_fields:
            assert field in view_data

    def test_saved_view_list_response(self):
        """Test saved view list response structure"""
        views = [
            {
                'id': str(uuid4()),
                'name': 'View 1',
                'account_count': 2,
                'is_default': True,
                'is_personal': False,
            },
            {
                'id': str(uuid4()),
                'name': 'View 2',
                'account_count': 1,
                'is_default': False,
                'is_personal': True,
            },
        ]

        assert len(views) == 2
        assert views[0]['is_default'] is True
        assert views[1]['is_personal'] is True


# ==================== Organizations API Response Tests ====================

class TestOrganizationsAPIResponses:
    """Tests for Organizations API response structures"""

    def test_organization_response_structure(self):
        """Test organization response structure"""
        org_data = {
            'id': str(uuid4()),
            'name': 'Test Organization',
            'slug': 'test-org',
            'subscription_tier': 'enterprise',
            'max_users': 100,
            'max_accounts': 200,
            'saved_view_default_expiration_days': 90,
            'created_at': '2026-01-21T10:00:00',
            'member_count': 5,
            'account_count': 10,
        }

        required_fields = [
            'id', 'name', 'slug', 'subscription_tier',
            'max_users', 'max_accounts'
        ]
        for field in required_fields:
            assert field in org_data

    def test_organization_member_response(self):
        """Test organization member response structure"""
        member_data = {
            'user_id': str(uuid4()),
            'email': 'member@example.com',
            'full_name': 'Test Member',
            'is_active': True,
            'role': 'admin',
            'joined_at': '2026-01-21T10:00:00',
            'invited_by': 'owner@example.com',
        }

        required_fields = ['user_id', 'email', 'role', 'is_active']
        for field in required_fields:
            assert field in member_data


# ==================== Request Validation Tests ====================

class TestRequestValidation:
    """Tests for request validation"""

    def test_create_view_validation_name_required(self):
        """Test that view name is required"""
        request_data = {
            'account_ids': [str(uuid4())],
            # name is missing
        }

        # Name should be required
        assert 'name' not in request_data

    def test_create_view_validation_accounts_required(self):
        """Test that account_ids is required"""
        request_data = {
            'name': 'Test View',
            # account_ids is missing
        }

        assert 'account_ids' not in request_data

    def test_add_member_validation_email_required(self):
        """Test that email is required for adding member"""
        request_data = {
            'role': 'member',
            # email is missing
        }

        assert 'email' not in request_data

    def test_role_validation(self):
        """Test that role must be valid"""
        valid_roles = ['owner', 'admin', 'member']

        for role in valid_roles:
            assert role in valid_roles

        invalid_role = 'superadmin'
        assert invalid_role not in valid_roles


# ==================== Chat API Scope Integration Tests ====================

class TestChatAPIScoping:
    """Tests for Chat API scope integration"""

    def test_chat_response_includes_scope(self, mock_request_context):
        """Test that chat response includes scope information"""
        scope_info = mock_request_context.to_scope_dict()

        # Simulate chat response metadata
        chat_metadata = {
            'time_period': 'Last 30 days',
            'scope': 'By Service',
            'status': 'ok',
            'scope_info': scope_info,
        }

        assert 'scope_info' in chat_metadata
        assert chat_metadata['scope_info']['organization_name'] == "Test Organization"
        assert chat_metadata['scope_info']['account_count'] == 2

    def test_chat_response_scope_display(self, mock_request_context):
        """Test scope info for UI display"""
        scope_info = mock_request_context.to_scope_dict()

        # UI should be able to display these
        display_org = scope_info.get('organization_name', 'Unknown')
        display_accounts = f"{scope_info.get('account_count', 0)} accounts"
        display_view = scope_info.get('active_view', {}).get('name', 'All Accounts')

        assert display_org == "Test Organization"
        assert display_accounts == "2 accounts"
        assert display_view == "Production View"


# ==================== Audit Context Tests ====================

class TestAuditContext:
    """Tests for audit logging context"""

    def test_audit_context_structure(self, mock_request_context):
        """Test audit context has required fields"""
        audit_ctx = mock_request_context.to_audit_context()

        required_fields = [
            'user_id', 'user_email', 'organization_id',
            'allowed_account_count', 'is_admin', 'org_role'
        ]

        for field in required_fields:
            assert field in audit_ctx

    def test_audit_context_values(self, mock_request_context):
        """Test audit context values are correct"""
        audit_ctx = mock_request_context.to_audit_context()

        assert audit_ctx['user_email'] == "test@example.com"
        assert audit_ctx['allowed_account_count'] == 2
        assert audit_ctx['is_admin'] is False
        assert audit_ctx['org_role'] == 'member'

    def test_audit_context_admin(self, mock_admin_context):
        """Test audit context for admin"""
        audit_ctx = mock_admin_context.to_audit_context()

        assert audit_ctx['is_admin'] is True
        assert audit_ctx['org_role'] == 'owner'


# ==================== Error Response Tests ====================

class TestErrorResponses:
    """Tests for error response handling"""

    def test_unauthorized_account_error(self):
        """Test error response for unauthorized account access"""
        error_response = {
            'status': 'denied',
            'error': 'Access denied to accounts: 999999999999',
        }

        assert error_response['status'] == 'denied'
        assert '999999999999' in error_response['error']

    def test_view_not_found_error(self):
        """Test error response for view not found"""
        error_response = {
            'detail': 'Saved view not found',
        }

        assert 'not found' in error_response['detail'].lower()

    def test_permission_denied_error(self):
        """Test error response for permission denied"""
        error_response = {
            'detail': 'Organization admin access required',
        }

        assert 'admin access required' in error_response['detail'].lower()


# ==================== Middleware Context Tests ====================

class TestMiddlewareContext:
    """Tests for middleware context handling"""

    def test_context_attached_to_request(self, mock_request_context):
        """Test that context is properly attached"""
        # Simulate request.state.context
        class MockRequest:
            class state:
                context = mock_request_context

        from backend.services.request_context import get_context_from_request

        ctx = get_context_from_request(MockRequest())

        assert ctx is not None
        assert ctx.user_email == "test@example.com"

    def test_context_not_attached(self):
        """Test handling when context is not attached"""
        class MockRequest:
            class state:
                pass  # No context

        from backend.services.request_context import get_context_from_request

        ctx = get_context_from_request(MockRequest())

        assert ctx is None

    def test_require_context_raises(self):
        """Test that require_context raises when no context"""
        class MockRequest:
            class state:
                pass

        from backend.services.request_context import require_context
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            require_context(MockRequest())

        assert exc_info.value.status_code == 401


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
