"""
Tests for per-user rate limiting fairness to prevent resource hogging.

Tests multi-layer rate limiting:
- Layer 1: Per-user limits (role-based) prevent single user from hogging
- Layer 2: Organization limits (tier-based) prevent org from exceeding quota
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from fastapi import Request, HTTPException

from backend.middleware.rate_limiting import (
    get_per_user_limit,
    check_athena_export_rate_limit,
    RateLimiter,
)
from backend.services.request_context import RequestContext, OrganizationInfo


class TestPerUserLimitRetrieval:
    """Test get_per_user_limit() function"""

    @pytest.mark.asyncio
    async def test_uses_default_settings_when_no_org_override(self):
        """Should use tier-specific defaults from settings when no DB override"""
        # No user_id or org_id means no database lookup
        limit = await get_per_user_limit(
            user_id=None,
            org_id=None,
            subscription_tier='enterprise',
            user_role='admin',
            endpoint='athena_export'
        )

        # Should match settings default: athena_export_per_user_limit_enterprise_admin
        assert limit == 100

    @pytest.mark.asyncio
    async def test_uses_default_for_different_roles(self):
        """Different roles should have different default limits"""
        # Enterprise tier
        owner_limit = await get_per_user_limit(None, None, 'enterprise', 'owner', 'athena_export')
        admin_limit = await get_per_user_limit(None, None, 'enterprise', 'admin', 'athena_export')
        member_limit = await get_per_user_limit(None, None, 'enterprise', 'member', 'athena_export')

        assert owner_limit == 100  # From settings
        assert admin_limit == 100
        assert member_limit == 50

    @pytest.mark.asyncio
    async def test_uses_default_for_different_tiers(self):
        """Different tiers should have different default limits"""
        enterprise = await get_per_user_limit(None, None, 'enterprise', 'member', 'athena_export')
        standard = await get_per_user_limit(None, None, 'standard', 'member', 'athena_export')
        free = await get_per_user_limit(None, None, 'free', 'member', 'athena_export')

        assert enterprise == 50  # Enterprise members
        assert standard == 15    # Standard members
        assert free == 3         # Free members

    @pytest.mark.asyncio
    @patch('backend.services.database.DatabaseService')
    async def test_uses_custom_limit_from_database(self, mock_db_service):
        """Should use organization-specific override from database if available"""
        # Mock database to return custom limit
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = [150]  # Custom limit: 150/hour
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_db_instance = MagicMock()
        mock_db_instance.engine = MagicMock()
        mock_db_instance.engine.begin = MagicMock()
        mock_db_instance.engine.begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_db_instance.engine.begin.return_value.__aexit__ = AsyncMock()
        mock_db_instance.initialize = AsyncMock()

        mock_db_service.return_value = mock_db_instance

        limit = await get_per_user_limit(
            user_id=None,
            org_id='test-org-id',
            subscription_tier='enterprise',
            user_role='admin',
            endpoint='athena_export'
        )

        # Should use custom limit from database, not default (100)
        assert limit == 150

    @pytest.mark.asyncio
    @patch('backend.services.database.DatabaseService')
    async def test_fallback_to_default_on_database_error(self, mock_db_service):
        """Should fallback to settings default if database query fails"""
        # Mock database to raise exception
        mock_db_service.side_effect = Exception("Database connection failed")

        limit = await get_per_user_limit(
            user_id=None,
            org_id='test-org-id',
            subscription_tier='enterprise',
            user_role='admin',
            endpoint='athena_export'
        )

        # Should fallback to default from settings
        assert limit == 100

    @pytest.mark.asyncio
    async def test_conservative_fallback_for_unknown_config(self):
        """Should use conservative fallback (10) for unknown tier/role combination"""
        # Non-existent tier and role combination
        limit = await get_per_user_limit(
            user_id=None,
            org_id=None,
            subscription_tier='unknown_tier',
            user_role='unknown_role',
            endpoint='athena_export'
        )

        # Should use conservative fallback
        assert limit == 10


class TestPerUserRateLimitingPreventsHogging:
    """Test that per-user limits prevent single user from hogging all resources"""

    @pytest.mark.asyncio
    async def test_single_user_cannot_exceed_personal_limit(self):
        """Single user should be blocked at their per-user limit, not org limit"""
        # Setup: Enterprise org (200/hour), Admin user (100/hour per user)

        limiter = RateLimiter(
            requests_per_window=100,  # Per-user limit
            window_seconds=3600,
            use_org_key=False  # Use user email as key
        )

        request = MagicMock(spec=Request)
        request.state.user_email = "alice@example.com"
        request.state.context = MagicMock()
        request.url.path = "/api/athena/export/csv"
        request.client.host = "127.0.0.1"

        # Alice makes 100 requests - should all succeed
        for i in range(100):
            allowed, _ = await limiter.is_allowed(request)
            assert allowed is True, f"Request {i+1} should be allowed"

        # 101st request should be blocked
        allowed, _ = await limiter.is_allowed(request)
        assert allowed is False, "101st request should be blocked by per-user limit"

    @pytest.mark.asyncio
    async def test_multiple_users_can_fairly_share_org_quota(self):
        """Multiple users should be able to fairly share organization quota"""
        # Setup: Standard tier (50/hour org), Member users (15/hour per user)

        per_user_limiter = RateLimiter(
            requests_per_window=15,  # Per-user limit
            window_seconds=3600,
            use_org_key=False
        )

        org_limiter = RateLimiter(
            requests_per_window=50,  # Organization limit
            window_seconds=3600,
            use_org_key=True
        )

        org_id = "test-org-123"

        # User 1 makes 15 requests
        request1 = MagicMock(spec=Request)
        request1.state.user_email = "user1@example.com"
        request1.state.context = MagicMock()
        request1.state.context.organization_id = org_id
        request1.url.path = "/api/athena/export/csv"
        request1.client.host = "127.0.0.1"

        for i in range(15):
            allowed, _ = await per_user_limiter.is_allowed(request1)
            assert allowed is True
            allowed, _ = await org_limiter.is_allowed(request1)
            assert allowed is True

        # User 1 tries 16th request - blocked by per-user limit
        allowed, _ = await per_user_limiter.is_allowed(request1)
        assert allowed is False

        # User 2 makes 15 requests (still within org limit: 30/50 used)
        request2 = MagicMock(spec=Request)
        request2.state.user_email = "user2@example.com"
        request2.state.context = MagicMock()
        request2.state.context.organization_id = org_id
        request2.url.path = "/api/athena/export/csv"
        request2.client.host = "127.0.0.1"

        for i in range(15):
            allowed, _ = await per_user_limiter.is_allowed(request2)
            assert allowed is True
            allowed, _ = await org_limiter.is_allowed(request2)
            assert allowed is True

        # User 3 makes 15 requests (45/50 used)
        request3 = MagicMock(spec=Request)
        request3.state.user_email = "user3@example.com"
        request3.state.context = MagicMock()
        request3.state.context.organization_id = org_id
        request3.url.path = "/api/athena/export/csv"
        request3.client.host = "127.0.0.1"

        for i in range(15):
            allowed, _ = await per_user_limiter.is_allowed(request3)
            assert allowed is True
            allowed, _ = await org_limiter.is_allowed(request3)
            assert allowed is True

        # User 4 can only make 5 requests (org limit: 50/50)
        request4 = MagicMock(spec=Request)
        request4.state.user_email = "user4@example.com"
        request4.state.context = MagicMock()
        request4.state.context.organization_id = org_id
        request4.url.path = "/api/athena/export/csv"
        request4.client.host = "127.0.0.1"

        for i in range(5):
            allowed, _ = await per_user_limiter.is_allowed(request4)
            assert allowed is True
            allowed, _ = await org_limiter.is_allowed(request4)
            assert allowed is True

        # 6th request blocked by org limit
        allowed, _ = await per_user_limiter.is_allowed(request4)
        assert allowed is True  # User still has capacity
        allowed, _ = await org_limiter.is_allowed(request4)
        assert allowed is False  # But org limit reached

    @pytest.mark.asyncio
    async def test_admins_have_higher_personal_limits_than_members(self):
        """Admin users should have higher per-user limits than regular members"""
        # Setup: Enterprise tier
        # Admin: 100/hour per user
        # Member: 50/hour per user

        admin_limiter = RateLimiter(
            requests_per_window=100,
            window_seconds=3600,
            use_org_key=False
        )

        member_limiter = RateLimiter(
            requests_per_window=50,
            window_seconds=3600,
            use_org_key=False
        )

        admin_request = MagicMock(spec=Request)
        admin_request.state.user_email = "admin@example.com"
        admin_request.state.context = MagicMock()
        admin_request.url.path = "/api/athena/export/csv"
        admin_request.client.host = "127.0.0.1"

        member_request = MagicMock(spec=Request)
        member_request.state.user_email = "member@example.com"
        member_request.state.context = MagicMock()
        member_request.url.path = "/api/athena/export/csv"
        member_request.client.host = "127.0.0.1"

        # Admin can make 100 requests
        for i in range(100):
            allowed, _ = await admin_limiter.is_allowed(admin_request)
            assert allowed is True

        # Member can only make 50 requests
        for i in range(50):
            allowed, _ = await member_limiter.is_allowed(member_request)
            assert allowed is True

        # Admin's 101st request blocked
        allowed, _ = await admin_limiter.is_allowed(admin_request)
        assert allowed is False

        # Member's 51st request blocked
        allowed, _ = await member_limiter.is_allowed(member_request)
        assert allowed is False


class TestMultiLayerRateLimitingIntegration:
    """Integration tests for check_athena_export_rate_limit() with both layers"""

    @pytest.mark.asyncio
    @patch('backend.middleware.rate_limiting.get_per_user_limit')
    @patch('backend.middleware.rate_limiting.check_rate_limit')
    @patch('backend.middleware.rate_limiting.get_athena_export_limiter')
    async def test_per_user_limit_checked_first(
        self, mock_get_limiter, mock_check_limit, mock_get_per_user_limit
    ):
        """Per-user limit should be checked before organization limit"""
        mock_get_per_user_limit.return_value = 100
        mock_check_limit.return_value = {"allowed": True}
        mock_get_limiter.return_value = MagicMock()

        request = MagicMock(spec=Request)
        request.state.context = MagicMock()
        request.state.context.organization_info = MagicMock(subscription_tier='enterprise')
        request.state.context.organization_id = 'test-org'
        request.state.context.org_role = 'admin'
        request.state.user_email = "user@example.com"
        request.url.path = "/api/athena/export/csv"

        await check_athena_export_rate_limit(request)

        # Both checks should have been called
        assert mock_check_limit.call_count == 2

        # First call should be for per-user limit
        first_call_endpoint = mock_check_limit.call_args_list[0][1]['endpoint']
        assert 'user' in first_call_endpoint.lower()

        # Second call should be for org limit
        second_call_endpoint = mock_check_limit.call_args_list[1][1]['endpoint']
        assert second_call_endpoint == 'athena_export'

    @pytest.mark.asyncio
    @patch('backend.middleware.rate_limiting.get_per_user_limit')
    @patch('backend.middleware.rate_limiting.check_rate_limit')
    async def test_per_user_limit_exceeded_returns_clear_message(
        self, mock_check_limit, mock_get_per_user_limit
    ):
        """When per-user limit exceeded, should return clear user-facing message"""
        mock_get_per_user_limit.return_value = 100

        # First call (per-user check) raises 429
        mock_check_limit.side_effect = HTTPException(
            status_code=429,
            detail="Rate limit exceeded"
        )

        request = MagicMock(spec=Request)
        request.state.context = MagicMock()
        request.state.context.organization_info = MagicMock(subscription_tier='enterprise')
        request.state.context.organization_id = 'test-org'
        request.state.context.org_role = 'admin'
        request.state.user_email = "user@example.com"
        request.url.path = "/api/athena/export/csv"

        with pytest.raises(HTTPException) as exc_info:
            await check_athena_export_rate_limit(request)

        assert exc_info.value.status_code == 429
        assert "User rate limit exceeded" in exc_info.value.detail
        assert "100" in exc_info.value.detail  # Mentions the limit
        assert "admin" in exc_info.value.detail  # Mentions the role

    @pytest.mark.asyncio
    @patch('backend.middleware.rate_limiting.get_per_user_limit')
    @patch('backend.middleware.rate_limiting.check_rate_limit')
    @patch('backend.middleware.rate_limiting.get_athena_export_limiter')
    async def test_org_limit_exceeded_returns_clear_message(
        self, mock_get_limiter, mock_check_limit, mock_get_per_user_limit
    ):
        """When org limit exceeded, should return clear org-facing message"""
        mock_get_per_user_limit.return_value = 100
        mock_get_limiter.return_value = MagicMock()

        # First call (per-user) succeeds, second call (org) fails
        mock_check_limit.side_effect = [
            {"allowed": True},  # Per-user check passes
            HTTPException(status_code=429, detail="Rate limit exceeded")  # Org check fails
        ]

        request = MagicMock(spec=Request)
        request.state.context = MagicMock()
        request.state.context.organization_info = MagicMock(subscription_tier='enterprise')
        request.state.context.organization_id = 'test-org'
        request.state.context.org_role = 'admin'
        request.state.user_email = "user@example.com"
        request.url.path = "/api/athena/export/csv"

        with pytest.raises(HTTPException) as exc_info:
            await check_athena_export_rate_limit(request)

        assert exc_info.value.status_code == 429
        assert "Organization rate limit exceeded" in exc_info.value.detail
        assert "enterprise" in exc_info.value.detail.lower()  # Mentions the tier

    @pytest.mark.asyncio
    @patch('backend.middleware.rate_limiting.get_per_user_limit')
    @patch('backend.middleware.rate_limiting.check_rate_limit')
    @patch('backend.middleware.rate_limiting.get_athena_export_limiter')
    async def test_both_limits_pass_request_succeeds(
        self, mock_get_limiter, mock_check_limit, mock_get_per_user_limit
    ):
        """When both per-user and org limits pass, request should succeed"""
        mock_get_per_user_limit.return_value = 100
        mock_get_limiter.return_value = MagicMock()
        mock_check_limit.return_value = {"allowed": True}

        request = MagicMock(spec=Request)
        request.state.context = MagicMock()
        request.state.context.organization_info = MagicMock(subscription_tier='enterprise')
        request.state.context.organization_id = 'test-org'
        request.state.context.org_role = 'admin'
        request.state.user_email = "user@example.com"
        request.url.path = "/api/athena/export/csv"

        result = await check_athena_export_rate_limit(request)

        assert result == {"allowed": True}
        assert mock_check_limit.call_count == 2  # Both layers checked


class TestDifferentOrganizationsSeparateLimits:
    """Test that different organizations have separate rate limits"""

    @pytest.mark.asyncio
    async def test_different_orgs_have_separate_pools(self):
        """Different organizations should have completely separate rate limit pools"""
        org_limiter = RateLimiter(
            requests_per_window=50,
            window_seconds=3600,
            use_org_key=True  # Use org_id as key
        )

        # Organization A
        request_org_a = MagicMock(spec=Request)
        request_org_a.state.user_email = "user@orga.com"
        request_org_a.state.context = MagicMock()
        request_org_a.state.context.organization_id = "org-a-id"
        request_org_a.url.path = "/api/athena/export/csv"
        request_org_a.client.host = "127.0.0.1"

        # Organization B
        request_org_b = MagicMock(spec=Request)
        request_org_b.state.user_email = "user@orgb.com"
        request_org_b.state.context = MagicMock()
        request_org_b.state.context.organization_id = "org-b-id"
        request_org_b.url.path = "/api/athena/export/csv"
        request_org_b.client.host = "127.0.0.1"

        # Org A uses all 50 requests
        for i in range(50):
            allowed, _ = await org_limiter.is_allowed(request_org_a)
            assert allowed is True

        # Org A's 51st request blocked
        allowed, _ = await org_limiter.is_allowed(request_org_a)
        assert allowed is False

        # Org B can still make all 50 requests (separate pool)
        for i in range(50):
            allowed, _ = await org_limiter.is_allowed(request_org_b)
            assert allowed is True

        # Org B's 51st request blocked
        allowed, _ = await org_limiter.is_allowed(request_org_b)
        assert allowed is False
