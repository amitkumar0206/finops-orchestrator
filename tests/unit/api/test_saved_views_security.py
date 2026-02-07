"""
Security tests for Saved Views API - CRIT-3 IDOR vulnerability fix

Tests ownership validation for GET, UPDATE, DELETE operations on saved views.
Ensures users can only access their own personal views or properly shared views.
"""

import pytest
from uuid import UUID, uuid4
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

from backend.api.saved_views import get_saved_view, update_saved_view, delete_saved_view
from backend.services.saved_views_service import SavedViewsService
from backend.services.request_context import RequestContext


# Fixtures

@pytest.fixture
def sample_user_a_id():
    """User A UUID"""
    return uuid4()


@pytest.fixture
def sample_user_b_id():
    """User B UUID"""
    return uuid4()


@pytest.fixture
def sample_org_id():
    """Organization UUID"""
    return uuid4()


@pytest.fixture
def sample_view_id():
    """Saved view UUID"""
    return uuid4()


@pytest.fixture
def mock_request():
    """Mock FastAPI request"""
    return MagicMock()


@pytest.fixture
def context_user_a(sample_user_a_id, sample_org_id):
    """Request context for User A"""
    return RequestContext(
        user_id=sample_user_a_id,
        user_email="alice@company.com",
        organization_id=sample_org_id,
        is_admin=False,
        org_role="member",
    )


@pytest.fixture
def context_user_b(sample_user_b_id, sample_org_id):
    """Request context for User B (same org)"""
    return RequestContext(
        user_id=sample_user_b_id,
        user_email="bob@company.com",
        organization_id=sample_org_id,
        is_admin=False,
        org_role="member",
    )


@pytest.fixture
def context_admin(sample_user_b_id, sample_org_id):
    """Request context for Admin user"""
    return RequestContext(
        user_id=sample_user_b_id,
        user_email="admin@company.com",
        organization_id=sample_org_id,
        is_admin=True,
        org_role="admin",
    )


@pytest.fixture
def personal_view_user_a(sample_view_id, sample_user_a_id, sample_org_id):
    """Personal saved view created by User A"""
    return {
        'id': str(sample_view_id),
        'name': 'Alice Personal View',
        'description': 'My personal view',
        'account_ids': ['123456789012'],
        'account_count': 1,
        'default_time_range': None,
        'filters': {},
        'is_default': False,
        'is_personal': True,
        'shared_with_users': [],
        'shared_with_roles': [],
        'expires_at': None,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'created_by': str(sample_user_a_id),
        'created_by_email': 'alice@company.com',
    }


@pytest.fixture
def org_default_view(sample_view_id, sample_user_a_id, sample_org_id):
    """Organization default view (accessible to all)"""
    return {
        'id': str(sample_view_id),
        'name': 'Org Default View',
        'description': 'Organization default',
        'account_ids': ['123456789012'],
        'account_count': 1,
        'default_time_range': None,
        'filters': {},
        'is_default': True,
        'is_personal': False,
        'shared_with_users': [],
        'shared_with_roles': [],
        'expires_at': None,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'created_by': str(sample_user_a_id),
        'created_by_email': 'alice@company.com',
    }


@pytest.fixture
def shared_view(sample_view_id, sample_user_a_id, sample_user_b_id, sample_org_id):
    """Shared view - User A shared with User B"""
    return {
        'id': str(sample_view_id),
        'name': 'Shared View',
        'description': 'Shared with Bob',
        'account_ids': ['123456789012'],
        'account_count': 1,
        'default_time_range': None,
        'filters': {},
        'is_default': False,
        'is_personal': False,
        'shared_with_users': [str(sample_user_b_id)],
        'shared_with_roles': [],
        'expires_at': None,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'created_by': str(sample_user_a_id),
        'created_by_email': 'alice@company.com',
    }


# Test Classes

class TestGetSavedViewOwnership:
    """Test ownership validation for GET /views/{view_id}"""

    @pytest.mark.asyncio
    async def test_returns_404_when_view_not_found(
        self, mock_request, context_user_a, sample_view_id
    ):
        """Should return 404 when view doesn't exist"""
        with patch('backend.api.saved_views.saved_views_service') as mock_service:
            mock_service.get_saved_view = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as exc_info:
                await get_saved_view(sample_view_id, mock_request, context_user_a)

            assert exc_info.value.status_code == 404
            assert "not found" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_returns_403_when_accessing_other_user_personal_view(
        self, mock_request, context_user_b, sample_view_id, personal_view_user_a
    ):
        """Should return 403 when User B tries to access User A's personal view"""
        with patch('backend.api.saved_views.saved_views_service') as mock_service:
            # Service will raise HTTPException when validation fails
            mock_service.get_saved_view = AsyncMock(
                side_effect=HTTPException(
                    status_code=403,
                    detail="Access denied. You can only access your own personal views or shared views."
                )
            )

            with pytest.raises(HTTPException) as exc_info:
                await get_saved_view(sample_view_id, mock_request, context_user_b)

            assert exc_info.value.status_code == 403
            assert "access denied" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_allows_owner_to_access_personal_view(
        self, mock_request, context_user_a, sample_view_id, personal_view_user_a
    ):
        """Should allow User A to access their own personal view"""
        with patch('backend.api.saved_views.saved_views_service') as mock_service:
            mock_service.get_saved_view = AsyncMock(return_value=personal_view_user_a)

            result = await get_saved_view(sample_view_id, mock_request, context_user_a)

            assert result.id == personal_view_user_a['id']
            assert result.name == personal_view_user_a['name']
            mock_service.get_saved_view.assert_called_once_with(
                context=context_user_a, view_id=sample_view_id
            )

    @pytest.mark.asyncio
    async def test_allows_any_org_member_to_access_default_view(
        self, mock_request, context_user_b, sample_view_id, org_default_view
    ):
        """Should allow any org member to access organization default view"""
        with patch('backend.api.saved_views.saved_views_service') as mock_service:
            mock_service.get_saved_view = AsyncMock(return_value=org_default_view)

            result = await get_saved_view(sample_view_id, mock_request, context_user_b)

            assert result.id == org_default_view['id']
            assert result.is_default is True

    @pytest.mark.asyncio
    async def test_allows_access_to_shared_view(
        self, mock_request, context_user_b, sample_view_id, shared_view
    ):
        """Should allow User B to access view shared with them"""
        with patch('backend.api.saved_views.saved_views_service') as mock_service:
            mock_service.get_saved_view = AsyncMock(return_value=shared_view)

            result = await get_saved_view(sample_view_id, mock_request, context_user_b)

            assert result.id == shared_view['id']
            assert result.name == shared_view['name']

    @pytest.mark.asyncio
    async def test_allows_admin_to_access_any_view(
        self, mock_request, context_admin, sample_view_id, personal_view_user_a
    ):
        """Should allow admin to access any view"""
        with patch('backend.api.saved_views.saved_views_service') as mock_service:
            mock_service.get_saved_view = AsyncMock(return_value=personal_view_user_a)

            result = await get_saved_view(sample_view_id, mock_request, context_admin)

            assert result.id == personal_view_user_a['id']


class TestUpdateSavedViewOwnership:
    """Test ownership validation for PUT /views/{view_id}"""

    @pytest.mark.asyncio
    async def test_returns_403_when_updating_other_user_view(
        self, mock_request, context_user_b, sample_view_id
    ):
        """Should return 403 when User B tries to update User A's view"""
        from backend.api.saved_views import UpdateSavedViewRequest

        update_payload = UpdateSavedViewRequest(name="Malicious Update")

        with patch('backend.api.saved_views.saved_views_service') as mock_service:
            # Service will raise HTTPException when validation fails
            mock_service.update_saved_view = AsyncMock(
                side_effect=HTTPException(
                    status_code=403,
                    detail="Access denied. You can only modify views you created."
                )
            )

            with pytest.raises(HTTPException) as exc_info:
                await update_saved_view(
                    sample_view_id, update_payload, mock_request, context_user_b
                )

            assert exc_info.value.status_code == 403
            assert "access denied" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_allows_owner_to_update_their_view(
        self, mock_request, context_user_a, sample_view_id, personal_view_user_a
    ):
        """Should allow User A to update their own view"""
        from backend.api.saved_views import UpdateSavedViewRequest

        update_payload = UpdateSavedViewRequest(name="Updated Name")
        updated_view = {**personal_view_user_a, 'name': 'Updated Name'}

        with patch('backend.api.saved_views.saved_views_service') as mock_service:
            with patch('backend.api.saved_views.audit_log_service') as mock_audit:
                mock_service.update_saved_view = AsyncMock(return_value=updated_view)
                mock_audit.log_saved_view_updated = AsyncMock()

                result = await update_saved_view(
                    sample_view_id, update_payload, mock_request, context_user_a
                )

                assert result.name == "Updated Name"
                mock_service.update_saved_view.assert_called_once()

    @pytest.mark.asyncio
    async def test_allows_admin_to_update_any_view(
        self, mock_request, context_admin, sample_view_id, personal_view_user_a
    ):
        """Should allow admin to update any view"""
        from backend.api.saved_views import UpdateSavedViewRequest

        update_payload = UpdateSavedViewRequest(name="Admin Update")
        updated_view = {**personal_view_user_a, 'name': 'Admin Update'}

        with patch('backend.api.saved_views.saved_views_service') as mock_service:
            with patch('backend.api.saved_views.audit_log_service') as mock_audit:
                mock_service.update_saved_view = AsyncMock(return_value=updated_view)
                mock_audit.log_saved_view_updated = AsyncMock()

                result = await update_saved_view(
                    sample_view_id, update_payload, mock_request, context_admin
                )

                assert result.name == "Admin Update"


class TestDeleteSavedViewOwnership:
    """Test ownership validation for DELETE /views/{view_id}"""

    @pytest.mark.asyncio
    async def test_returns_404_when_view_not_found(
        self, mock_request, context_user_a, sample_view_id
    ):
        """Should return 404 when deleting non-existent view"""
        with patch('backend.api.saved_views.saved_views_service') as mock_service:
            mock_service.get_saved_view = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as exc_info:
                await delete_saved_view(sample_view_id, mock_request, context_user_a)

            assert exc_info.value.status_code == 404
            assert "not found" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_returns_403_when_deleting_other_user_view(
        self, mock_request, context_user_b, sample_view_id, personal_view_user_a
    ):
        """Should return 403 when User B tries to delete User A's view"""
        with patch('backend.api.saved_views.saved_views_service') as mock_service:
            # First call returns the view (for fetching name)
            mock_service.get_saved_view = AsyncMock(return_value=personal_view_user_a)
            # Delete call raises HTTPException
            mock_service.delete_saved_view = AsyncMock(
                side_effect=HTTPException(
                    status_code=403,
                    detail="Access denied. You can only modify views you created."
                )
            )

            with pytest.raises(HTTPException) as exc_info:
                await delete_saved_view(sample_view_id, mock_request, context_user_b)

            assert exc_info.value.status_code == 403
            assert "access denied" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_allows_owner_to_delete_their_view(
        self, mock_request, context_user_a, sample_view_id, personal_view_user_a
    ):
        """Should allow User A to delete their own view"""
        with patch('backend.api.saved_views.saved_views_service') as mock_service:
            with patch('backend.api.saved_views.audit_log_service') as mock_audit:
                mock_service.get_saved_view = AsyncMock(return_value=personal_view_user_a)
                mock_service.delete_saved_view = AsyncMock(return_value=True)
                mock_audit.log_saved_view_deleted = AsyncMock()

                result = await delete_saved_view(
                    sample_view_id, mock_request, context_user_a
                )

                assert result['success'] is True
                assert result['deleted_id'] == str(sample_view_id)
                mock_service.delete_saved_view.assert_called_once()

    @pytest.mark.asyncio
    async def test_allows_admin_to_delete_any_view(
        self, mock_request, context_admin, sample_view_id, personal_view_user_a
    ):
        """Should allow admin to delete any view"""
        with patch('backend.api.saved_views.saved_views_service') as mock_service:
            with patch('backend.api.saved_views.audit_log_service') as mock_audit:
                mock_service.get_saved_view = AsyncMock(return_value=personal_view_user_a)
                mock_service.delete_saved_view = AsyncMock(return_value=True)
                mock_audit.log_saved_view_deleted = AsyncMock()

                result = await delete_saved_view(
                    sample_view_id, mock_request, context_admin
                )

                assert result['success'] is True


class TestSavedViewsServiceOwnershipValidation:
    """Test service layer ownership validation methods"""

    @pytest.mark.asyncio
    async def test_validate_ownership_for_read_allows_owner(
        self, context_user_a, sample_user_a_id
    ):
        """Should allow owner to read their own view"""
        service = SavedViewsService()
        view = {
            'id': 'test-id',
            'created_by': sample_user_a_id,
            'is_default': False,
            'is_personal': True,
            'shared_with_users': [],
        }

        # Should not raise exception
        service._validate_ownership_for_read(view, context_user_a)

    @pytest.mark.asyncio
    async def test_validate_ownership_for_read_denies_non_owner_personal_view(
        self, context_user_b, sample_user_a_id
    ):
        """Should deny non-owner from reading personal view"""
        service = SavedViewsService()
        view = {
            'id': 'test-id',
            'created_by': sample_user_a_id,
            'is_default': False,
            'is_personal': True,
            'shared_with_users': [],
        }

        with pytest.raises(HTTPException) as exc_info:
            service._validate_ownership_for_read(view, context_user_b)

        assert exc_info.value.status_code == 403
        assert "access denied" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_validate_ownership_for_read_allows_org_default(
        self, context_user_b, sample_user_a_id
    ):
        """Should allow any org member to read org default view"""
        service = SavedViewsService()
        view = {
            'id': 'test-id',
            'created_by': sample_user_a_id,
            'is_default': True,
            'is_personal': False,
            'shared_with_users': [],
        }

        # Should not raise exception
        service._validate_ownership_for_read(view, context_user_b)

    @pytest.mark.asyncio
    async def test_validate_ownership_for_read_allows_shared_view(
        self, context_user_b, sample_user_a_id, sample_user_b_id
    ):
        """Should allow user to read view shared with them"""
        service = SavedViewsService()
        view = {
            'id': 'test-id',
            'created_by': sample_user_a_id,
            'is_default': False,
            'is_personal': False,
            'shared_with_users': [sample_user_b_id],
        }

        # Should not raise exception
        service._validate_ownership_for_read(view, context_user_b)

    @pytest.mark.asyncio
    async def test_validate_ownership_for_modify_allows_owner(
        self, context_user_a, sample_user_a_id
    ):
        """Should allow owner to modify their own view"""
        service = SavedViewsService()
        view = {
            'id': 'test-id',
            'created_by': sample_user_a_id,
            'is_personal': True,
        }

        # Should not raise exception
        service._validate_ownership_for_modify(view, context_user_a)

    @pytest.mark.asyncio
    async def test_validate_ownership_for_modify_denies_non_owner(
        self, context_user_b, sample_user_a_id
    ):
        """Should deny non-owner from modifying view"""
        service = SavedViewsService()
        view = {
            'id': 'test-id',
            'created_by': sample_user_a_id,
            'is_personal': True,
        }

        with pytest.raises(HTTPException) as exc_info:
            service._validate_ownership_for_modify(view, context_user_b)

        assert exc_info.value.status_code == 403
        assert "access denied" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_validate_ownership_for_modify_allows_admin(
        self, context_admin, sample_user_a_id
    ):
        """Should allow admin to modify any view"""
        service = SavedViewsService()
        view = {
            'id': 'test-id',
            'created_by': sample_user_a_id,
            'is_personal': True,
        }

        # Should not raise exception
        service._validate_ownership_for_modify(view, context_admin)


class TestEndToEndOwnershipFlow:
    """Test complete end-to-end ownership scenarios"""

    @pytest.mark.asyncio
    async def test_complete_flow_unauthorized_access(
        self, mock_request, context_user_a, context_user_b, sample_view_id
    ):
        """
        Complete flow: User A creates personal view, User B blocked from access/modify/delete
        """
        from backend.api.saved_views import UpdateSavedViewRequest

        personal_view = {
            'id': str(sample_view_id),
            'name': 'Alice Personal',
            'created_by': str(context_user_a.user_id),
            'is_personal': True,
            'is_default': False,
            'shared_with_users': [],
        }

        with patch('backend.api.saved_views.saved_views_service') as mock_service:
            # User B tries to GET - should be blocked
            mock_service.get_saved_view = AsyncMock(
                side_effect=HTTPException(status_code=403, detail="Access denied")
            )
            with pytest.raises(HTTPException) as exc_info:
                await get_saved_view(sample_view_id, mock_request, context_user_b)
            assert exc_info.value.status_code == 403

            # User B tries to UPDATE - should be blocked
            mock_service.update_saved_view = AsyncMock(
                side_effect=HTTPException(status_code=403, detail="Access denied")
            )
            update_payload = UpdateSavedViewRequest(name="Hack")
            with pytest.raises(HTTPException) as exc_info:
                await update_saved_view(
                    sample_view_id, update_payload, mock_request, context_user_b
                )
            assert exc_info.value.status_code == 403

            # User B tries to DELETE - should be blocked
            mock_service.get_saved_view = AsyncMock(return_value=personal_view)
            mock_service.delete_saved_view = AsyncMock(
                side_effect=HTTPException(status_code=403, detail="Access denied")
            )
            with pytest.raises(HTTPException) as exc_info:
                await delete_saved_view(sample_view_id, mock_request, context_user_b)
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_complete_flow_authorized_access(
        self, mock_request, context_user_a, sample_view_id
    ):
        """
        Complete flow: User A creates personal view, can access/modify/delete it
        """
        from backend.api.saved_views import UpdateSavedViewRequest

        personal_view = {
            'id': str(sample_view_id),
            'name': 'Alice Personal',
            'description': 'My view',
            'account_ids': ['123456789012'],
            'account_count': 1,
            'default_time_range': None,
            'filters': {},
            'is_default': False,
            'is_personal': True,
            'shared_with_users': [],
            'shared_with_roles': [],
            'expires_at': None,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat(),
            'created_by': str(context_user_a.user_id),
            'created_by_email': 'alice@company.com',
        }

        with patch('backend.api.saved_views.saved_views_service') as mock_service:
            with patch('backend.api.saved_views.audit_log_service') as mock_audit:
                mock_service.return_value = mock_service
                mock_audit.return_value = mock_audit

                # User A can GET their view
                mock_service.get_saved_view = AsyncMock(return_value=personal_view)
                result = await get_saved_view(sample_view_id, mock_request, context_user_a)
                assert result.id == str(sample_view_id)

                # User A can UPDATE their view
                updated_view = {**personal_view, 'name': 'Updated Name'}
                mock_service.update_saved_view = AsyncMock(return_value=updated_view)
                mock_audit.log_saved_view_updated = AsyncMock()
                update_payload = UpdateSavedViewRequest(name="Updated Name")
                result = await update_saved_view(
                    sample_view_id, update_payload, mock_request, context_user_a
                )
                assert result.name == "Updated Name"

                # User A can DELETE their view
                mock_service.get_saved_view = AsyncMock(return_value=personal_view)
                mock_service.delete_saved_view = AsyncMock(return_value=True)
                mock_audit.log_saved_view_deleted = AsyncMock()
                result = await delete_saved_view(sample_view_id, mock_request, context_user_a)
                assert result['success'] is True
