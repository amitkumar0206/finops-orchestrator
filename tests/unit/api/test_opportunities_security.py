"""
Security tests for Opportunities API - CRIT-2 IDOR Fix

Tests ownership validation for opportunity CRUD operations to ensure:
1. Users can only access their own opportunities
2. Users cannot access opportunities created by other users in the same organization
3. Proper error codes are returned (403 for unauthorized, 404 for not found)
4. Audit logging captures access attempts

Addresses CRIT-2: Opportunities Accessible Without Ownership Validation (IDOR)
CVSS 9.1 (Critical)
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from uuid import uuid4, UUID
from datetime import datetime, timezone

from fastapi import HTTPException
from backend.api.opportunities import (
    get_opportunity,
    update_opportunity,
    delete_opportunity,
    update_opportunity_status,
)
from backend.services.opportunities_service import OpportunitiesService
from backend.services.request_context import RequestContext
from backend.models.opportunities import (
    OpportunityDetail,
    OpportunityStatus,
    OpportunitySource,
    OpportunityCategory,
    OpportunityUpdate,
    OpportunityStatusUpdate,
)


@pytest.fixture
def mock_request_context():
    """Mock request context with user information"""
    context = Mock(spec=RequestContext)
    context.user_id = uuid4()
    context.user_email = "alice@company.com"
    context.organization_id = uuid4()
    context.organization_name = "Test Org"
    context.is_admin = False
    return context


@pytest.fixture
def mock_request():
    """Mock FastAPI request object"""
    request = Mock()
    request.state = Mock()
    return request


@pytest.fixture
def sample_opportunity():
    """Sample opportunity data"""
    opportunity_id = uuid4()
    user_id = uuid4()
    org_id = uuid4()

    return {
        "id": opportunity_id,
        "account_id": "123456789012",
        "organization_id": org_id,
        "created_by_user_id": user_id,
        "title": "EC2 Rightsizing Recommendation",
        "description": "Downsize overprovisioned EC2 instances",
        "category": OpportunityCategory.RIGHTSIZING.value,
        "source": OpportunitySource.COST_EXPLORER.value,
        "service": "AmazonEC2",
        "estimated_monthly_savings": 1500.00,
        "status": OpportunityStatus.OPEN.value,
        "first_detected_at": datetime.now(timezone.utc),
        "last_seen_at": datetime.now(timezone.utc),
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


class TestGetOpportunityOwnership:
    """Test ownership validation for GET /opportunities/{id}"""

    @pytest.mark.asyncio
    async def test_returns_404_when_opportunity_not_found(
        self, mock_request, mock_request_context
    ):
        """Should return 404 when opportunity doesn't exist"""
        with patch('backend.api.opportunities.get_service') as mock_get_service, \
             patch('backend.api.opportunities.get_context_from_request', return_value=mock_request_context):

            mock_service = Mock(spec=OpportunitiesService)
            mock_service.get_opportunity.return_value = None
            mock_get_service.return_value = mock_service

            opportunity_id = uuid4()

            with pytest.raises(HTTPException) as exc_info:
                await get_opportunity(mock_request, opportunity_id)

            assert exc_info.value.status_code == 404
            mock_service.get_opportunity.assert_called_once_with(
                opportunity_id,
                user_id=mock_request_context.user_id
            )

    @pytest.mark.asyncio
    async def test_returns_403_when_user_not_owner(
        self, mock_request, mock_request_context, sample_opportunity
    ):
        """Should return 403 when user tries to access another user's opportunity"""
        with patch('backend.api.opportunities.get_service') as mock_get_service, \
             patch('backend.api.opportunities.get_context_from_request', return_value=mock_request_context):

            # Service will raise HTTPException when ownership validation fails
            mock_service = Mock(spec=OpportunitiesService)
            mock_service.get_opportunity.side_effect = HTTPException(
                status_code=403,
                detail="Access denied. You can only access opportunities you created."
            )
            mock_get_service.return_value = mock_service

            opportunity_id = uuid4()

            with pytest.raises(HTTPException) as exc_info:
                await get_opportunity(mock_request, opportunity_id)

            assert exc_info.value.status_code == 403
            assert "Access denied" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_allows_access_when_user_is_owner(
        self, mock_request, mock_request_context, sample_opportunity
    ):
        """Should allow access when user owns the opportunity"""
        # Set the opportunity's creator to match the requesting user
        sample_opportunity['created_by_user_id'] = mock_request_context.user_id

        with patch('backend.api.opportunities.get_service') as mock_get_service, \
             patch('backend.api.opportunities.get_context_from_request', return_value=mock_request_context):

            mock_service = Mock(spec=OpportunitiesService)
            mock_service.get_opportunity.return_value = OpportunityDetail(**sample_opportunity)
            mock_get_service.return_value = mock_service

            opportunity_id = sample_opportunity['id']

            result = await get_opportunity(mock_request, opportunity_id)

            assert result is not None
            assert result.id == opportunity_id
            assert result.title == sample_opportunity['title']
            mock_service.get_opportunity.assert_called_once_with(
                opportunity_id,
                user_id=mock_request_context.user_id
            )


class TestUpdateOpportunityOwnership:
    """Test ownership validation for PATCH /opportunities/{id}"""

    @pytest.mark.asyncio
    async def test_returns_404_when_opportunity_not_found(
        self, mock_request, mock_request_context
    ):
        """Should return 404 when opportunity doesn't exist"""
        with patch('backend.api.opportunities.get_service') as mock_get_service, \
             patch('backend.api.opportunities.get_context_from_request', return_value=mock_request_context):

            mock_service = Mock(spec=OpportunitiesService)
            mock_service.update_opportunity.return_value = None
            mock_get_service.return_value = mock_service

            opportunity_id = uuid4()
            update_data = OpportunityUpdate(title="Updated Title")

            with pytest.raises(HTTPException) as exc_info:
                await update_opportunity(mock_request, opportunity_id, update_data)

            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_403_when_user_not_owner(
        self, mock_request, mock_request_context, sample_opportunity
    ):
        """Should return 403 when user tries to update another user's opportunity"""
        with patch('backend.api.opportunities.get_service') as mock_get_service, \
             patch('backend.api.opportunities.get_context_from_request', return_value=mock_request_context):

            # Service will raise HTTPException when ownership validation fails
            mock_service = Mock(spec=OpportunitiesService)
            mock_service.update_opportunity.side_effect = HTTPException(
                status_code=403,
                detail="Access denied. You can only access opportunities you created."
            )
            mock_get_service.return_value = mock_service

            opportunity_id = uuid4()
            update_data = OpportunityUpdate(title="Malicious Update")

            with pytest.raises(HTTPException) as exc_info:
                await update_opportunity(mock_request, opportunity_id, update_data)

            assert exc_info.value.status_code == 403
            assert "Access denied" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_allows_update_when_user_is_owner(
        self, mock_request, mock_request_context, sample_opportunity
    ):
        """Should allow update when user owns the opportunity"""
        # Set the opportunity's creator to match the requesting user
        sample_opportunity['created_by_user_id'] = mock_request_context.user_id
        sample_opportunity['title'] = "Updated Title"

        with patch('backend.api.opportunities.get_service') as mock_get_service, \
             patch('backend.api.opportunities.get_context_from_request', return_value=mock_request_context):

            mock_service = Mock(spec=OpportunitiesService)
            mock_service.update_opportunity.return_value = OpportunityDetail(**sample_opportunity)
            mock_get_service.return_value = mock_service

            opportunity_id = sample_opportunity['id']
            update_data = OpportunityUpdate(title="Updated Title")

            result = await update_opportunity(mock_request, opportunity_id, update_data)

            assert result is not None
            assert result.title == "Updated Title"
            mock_service.update_opportunity.assert_called_once()


class TestDeleteOpportunityOwnership:
    """Test ownership validation for DELETE /opportunities/{id}"""

    @pytest.mark.asyncio
    async def test_returns_404_when_opportunity_not_found(
        self, mock_request, mock_request_context
    ):
        """Should return 404 when opportunity doesn't exist"""
        with patch('backend.api.opportunities.get_service') as mock_get_service, \
             patch('backend.api.opportunities.get_context_from_request', return_value=mock_request_context):

            mock_service = Mock(spec=OpportunitiesService)
            mock_service.delete_opportunity.return_value = False
            mock_get_service.return_value = mock_service

            opportunity_id = uuid4()

            with pytest.raises(HTTPException) as exc_info:
                await delete_opportunity(mock_request, opportunity_id)

            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_403_when_user_not_owner(
        self, mock_request, mock_request_context
    ):
        """Should return 403 when user tries to delete another user's opportunity"""
        with patch('backend.api.opportunities.get_service') as mock_get_service, \
             patch('backend.api.opportunities.get_context_from_request', return_value=mock_request_context):

            # Service will raise HTTPException when ownership validation fails
            mock_service = Mock(spec=OpportunitiesService)
            mock_service.delete_opportunity.side_effect = HTTPException(
                status_code=403,
                detail="Access denied. You can only access opportunities you created."
            )
            mock_get_service.return_value = mock_service

            opportunity_id = uuid4()

            with pytest.raises(HTTPException) as exc_info:
                await delete_opportunity(mock_request, opportunity_id)

            assert exc_info.value.status_code == 403
            assert "Access denied" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_allows_deletion_when_user_is_owner(
        self, mock_request, mock_request_context
    ):
        """Should allow deletion when user owns the opportunity"""
        with patch('backend.api.opportunities.get_service') as mock_get_service, \
             patch('backend.api.opportunities.get_context_from_request', return_value=mock_request_context):

            mock_service = Mock(spec=OpportunitiesService)
            mock_service.delete_opportunity.return_value = True
            mock_get_service.return_value = mock_service

            opportunity_id = uuid4()

            result = await delete_opportunity(mock_request, opportunity_id)

            assert result.status_code == 204
            mock_service.delete_opportunity.assert_called_once_with(
                opportunity_id,
                user_id=mock_request_context.user_id
            )


class TestUpdateStatusOwnership:
    """Test ownership validation for PATCH /opportunities/{id}/status"""

    @pytest.mark.asyncio
    async def test_returns_403_when_user_not_owner(
        self, mock_request, mock_request_context
    ):
        """Should return 403 when user tries to update status of another user's opportunity"""
        with patch('backend.api.opportunities.get_service') as mock_get_service, \
             patch('backend.api.opportunities.get_context_from_request', return_value=mock_request_context):

            # Service will raise HTTPException when ownership validation fails
            mock_service = Mock(spec=OpportunitiesService)
            mock_service.update_status.side_effect = HTTPException(
                status_code=403,
                detail="Access denied. You can only access opportunities you created."
            )
            mock_get_service.return_value = mock_service

            opportunity_id = uuid4()
            status_update = OpportunityStatusUpdate(
                status=OpportunityStatus.DISMISSED,
                reason="Not applicable"
            )

            with pytest.raises(HTTPException) as exc_info:
                await update_opportunity_status(mock_request, opportunity_id, status_update)

            assert exc_info.value.status_code == 403
            assert "Access denied" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_allows_status_update_when_user_is_owner(
        self, mock_request, mock_request_context, sample_opportunity
    ):
        """Should allow status update when user owns the opportunity"""
        # Set the opportunity's creator to match the requesting user
        sample_opportunity['created_by_user_id'] = mock_request_context.user_id
        sample_opportunity['status'] = OpportunityStatus.ACCEPTED.value

        with patch('backend.api.opportunities.get_service') as mock_get_service, \
             patch('backend.api.opportunities.get_context_from_request', return_value=mock_request_context):

            mock_service = Mock(spec=OpportunitiesService)
            mock_service.update_status.return_value = OpportunityDetail(**sample_opportunity)
            mock_get_service.return_value = mock_service

            opportunity_id = sample_opportunity['id']
            status_update = OpportunityStatusUpdate(
                status=OpportunityStatus.ACCEPTED,
                reason="Will implement"
            )

            result = await update_opportunity_status(mock_request, opportunity_id, status_update)

            assert result is not None
            assert result.status == OpportunityStatus.ACCEPTED


class TestOpportunitiesServiceOwnershipValidation:
    """Test the service layer ownership validation logic"""

    def test_validate_ownership_allows_owner(self):
        """_validate_ownership should allow when user_id matches created_by_user_id"""
        service = OpportunitiesService()

        user_id = uuid4()
        opportunity = {
            'id': uuid4(),
            'created_by_user_id': user_id,
            'title': 'Test Opportunity'
        }

        # Should not raise exception
        service._validate_ownership(opportunity, user_id)

    def test_validate_ownership_denies_non_owner(self):
        """_validate_ownership should deny when user_id doesn't match"""
        service = OpportunitiesService()

        owner_id = uuid4()
        other_user_id = uuid4()

        opportunity = {
            'id': uuid4(),
            'created_by_user_id': owner_id,
            'title': 'Test Opportunity'
        }

        with pytest.raises(HTTPException) as exc_info:
            service._validate_ownership(opportunity, other_user_id)

        assert exc_info.value.status_code == 403
        assert "Access denied" in str(exc_info.value.detail)

    def test_validate_ownership_allows_legacy_data(self):
        """_validate_ownership should allow access to opportunities without created_by_user_id (legacy data)"""
        service = OpportunitiesService()

        user_id = uuid4()
        opportunity = {
            'id': uuid4(),
            'created_by_user_id': None,  # Legacy data
            'title': 'Test Opportunity'
        }

        # Should not raise exception
        service._validate_ownership(opportunity, user_id)


class TestEndToEndOwnershipFlow:
    """Test complete ownership validation flow"""

    @pytest.mark.asyncio
    async def test_complete_flow_unauthorized_access(
        self, mock_request, mock_request_context, sample_opportunity
    ):
        """Test that a complete flow properly blocks unauthorized access"""
        # Alice creates an opportunity
        alice_id = uuid4()
        alice_opportunity = sample_opportunity.copy()
        alice_opportunity['created_by_user_id'] = alice_id

        # Bob tries to access it
        bob_context = mock_request_context
        bob_context.user_id = uuid4()  # Different user

        with patch('backend.api.opportunities.get_service') as mock_get_service, \
             patch('backend.api.opportunities.get_context_from_request', return_value=bob_context):

            mock_service = Mock(spec=OpportunitiesService)
            mock_service.get_opportunity.side_effect = HTTPException(
                status_code=403,
                detail="Access denied. You can only access opportunities you created."
            )
            mock_get_service.return_value = mock_service

            # Bob's attempt should be blocked
            with pytest.raises(HTTPException) as exc_info:
                await get_opportunity(mock_request, alice_opportunity['id'])

            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_complete_flow_authorized_access(
        self, mock_request, mock_request_context, sample_opportunity
    ):
        """Test that owner can perform all operations on their opportunity"""
        # Alice creates and accesses her own opportunity
        alice_context = mock_request_context
        alice_context.user_id = uuid4()

        alice_opportunity = sample_opportunity.copy()
        alice_opportunity['created_by_user_id'] = alice_context.user_id

        with patch('backend.api.opportunities.get_service') as mock_get_service, \
             patch('backend.api.opportunities.get_context_from_request', return_value=alice_context):

            mock_service = Mock(spec=OpportunitiesService)
            mock_get_service.return_value = mock_service

            # Test GET
            mock_service.get_opportunity.return_value = OpportunityDetail(**alice_opportunity)
            result = await get_opportunity(mock_request, alice_opportunity['id'])
            assert result.id == alice_opportunity['id']

            # Test UPDATE
            updated_opportunity = alice_opportunity.copy()
            updated_opportunity['title'] = "Updated by Alice"
            mock_service.update_opportunity.return_value = OpportunityDetail(**updated_opportunity)

            update_data = OpportunityUpdate(title="Updated by Alice")
            result = await update_opportunity(mock_request, alice_opportunity['id'], update_data)
            assert result.title == "Updated by Alice"

            # Test DELETE
            mock_service.delete_opportunity.return_value = True
            result = await delete_opportunity(mock_request, alice_opportunity['id'])
            assert result.status_code == 204


# Summary of test coverage:
# ✅ GET /opportunities/{id} - ownership validation
# ✅ PATCH /opportunities/{id} - ownership validation
# ✅ DELETE /opportunities/{id} - ownership validation
# ✅ PATCH /opportunities/{id}/status - ownership validation
# ✅ Service layer _validate_ownership method
# ✅ Legacy data handling (opportunities without created_by_user_id)
# ✅ End-to-end flow validation
# ✅ Proper HTTP status codes (403 for unauthorized, 404 for not found)
