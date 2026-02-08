"""
Tests for Tier-Based and Organization-Level Rate Limiting

Tests the enhanced rate limiting system that supports:
- Organization-level rate limiting (not per-user)
- Subscription tier-based limits (free, standard, enterprise)
- Configuration via settings
"""

import pytest
from uuid import uuid4
from unittest.mock import MagicMock, Mock
from fastapi import Request

from backend.middleware.rate_limiting import (
    RateLimiter,
    get_athena_export_limiter,
    check_athena_export_rate_limit,
)
from backend.services.request_context import RequestContext, OrganizationInfo


@pytest.fixture
def mock_request_with_org():
    """Create a mock request with organization context"""
    def _create_request(subscription_tier='standard', org_id=None):
        if org_id is None:
            org_id = uuid4()

        # Create organization info
        org_info = OrganizationInfo(
            id=org_id,
            name="Test Organization",
            slug="test-org",
            subscription_tier=subscription_tier,
            settings={},
        )

        # Create request context
        context = RequestContext(
            user_id=uuid4(),
            user_email="test@example.com",
            organization_id=org_id,
            organization_info=org_info,
            is_admin=False,
            allowed_account_ids=[],
        )

        # Create mock request
        request = MagicMock(spec=Request)
        request.state = Mock()
        request.state.context = context
        request.state.auth_user = Mock(email="test@example.com", is_authenticated=True)
        request.client = Mock(host="127.0.0.1")
        request.headers = {}

        return request

    return _create_request


class TestOrganizationLevelRateLimiting:
    """Test that rate limiting works at organization level, not per-user"""

    @pytest.mark.asyncio
    async def test_organization_key_generation(self, mock_request_with_org):
        """Organization-level limiter should use org ID in key"""
        org_id = uuid4()
        request = mock_request_with_org(org_id=org_id)

        limiter = RateLimiter(
            requests_per_window=10,
            window_seconds=3600,
            use_org_key=True
        )

        # Generate key
        key = limiter._get_organization_key(request, "test_endpoint")

        # Should include org ID
        assert str(org_id) in key
        assert "rate_limit:org:test_endpoint" in key
        assert "test@example.com" not in key  # Should NOT include user email

    @pytest.mark.asyncio
    async def test_multiple_users_share_org_limit(self, mock_request_with_org):
        """Multiple users in same org should share the same rate limit pool"""
        org_id = uuid4()
        limiter = RateLimiter(
            requests_per_window=5,
            window_seconds=3600,
            use_org_key=True
        )

        # Create requests from different users in same org
        request1 = mock_request_with_org(org_id=org_id)
        request1.state.context.user_email = "user1@example.com"

        request2 = mock_request_with_org(org_id=org_id)
        request2.state.context.user_email = "user2@example.com"

        # User 1 makes 3 requests
        for _ in range(3):
            allowed, info = await limiter.is_allowed(request1, "test")
            assert allowed

        # User 2 should only be able to make 2 more (5 total for org)
        allowed, info = await limiter.is_allowed(request2, "test")
        assert allowed  # 4th request
        assert info['remaining'] == 1

        allowed, info = await limiter.is_allowed(request2, "test")
        assert allowed  # 5th request
        assert info['remaining'] == 0

        # 6th request from either user should be blocked
        allowed, info = await limiter.is_allowed(request2, "test")
        assert not allowed

    @pytest.mark.asyncio
    async def test_different_orgs_have_separate_limits(self, mock_request_with_org):
        """Different organizations should have separate rate limit pools"""
        org1_id = uuid4()
        org2_id = uuid4()

        limiter = RateLimiter(
            requests_per_window=5,
            window_seconds=3600,
            use_org_key=True
        )

        request_org1 = mock_request_with_org(org_id=org1_id)
        request_org2 = mock_request_with_org(org_id=org2_id)

        # Org 1 uses up all 5 requests
        for _ in range(5):
            allowed, info = await limiter.is_allowed(request_org1, "test")
            assert allowed

        # Org 1 should be rate limited
        allowed, info = await limiter.is_allowed(request_org1, "test")
        assert not allowed

        # Org 2 should still have full limit available
        for i in range(5):
            allowed, info = await limiter.is_allowed(request_org2, "test")
            assert allowed
            assert info['remaining'] == 4 - i

    @pytest.mark.asyncio
    async def test_fallback_to_user_key_without_org_context(self):
        """Should fallback to user-level key if org context not available"""
        limiter = RateLimiter(
            requests_per_window=10,
            window_seconds=3600,
            use_org_key=True
        )

        # Create request without org context
        request = MagicMock(spec=Request)
        request.state = Mock()
        request.state.context = None  # No context
        request.state.auth_user = Mock(email="test@example.com", is_authenticated=True)
        request.client = Mock(host="127.0.0.1")
        request.headers = {}

        # Should still work (fallback to user key)
        allowed, info = await limiter.is_allowed(request, "test")
        assert allowed


class TestTierBasedLimits:
    """Test that different subscription tiers get different rate limits"""

    def test_free_tier_gets_lowest_limit(self):
        """Free tier should have 10 requests/hour"""
        limiter = get_athena_export_limiter('free')

        assert limiter.requests_per_window == 10
        assert limiter.window_seconds == 3600
        assert limiter.use_org_key is True

    def test_standard_tier_gets_medium_limit(self):
        """Standard tier should have 50 requests/hour"""
        limiter = get_athena_export_limiter('standard')

        assert limiter.requests_per_window == 50
        assert limiter.window_seconds == 3600
        assert limiter.use_org_key is True

    def test_enterprise_tier_gets_highest_limit(self):
        """Enterprise tier should have 200 requests/hour"""
        limiter = get_athena_export_limiter('enterprise')

        assert limiter.requests_per_window == 200
        assert limiter.window_seconds == 3600
        assert limiter.use_org_key is True

    def test_unknown_tier_defaults_to_standard(self):
        """Unknown tier should default to standard limits"""
        limiter = get_athena_export_limiter('unknown_tier')

        assert limiter.requests_per_window == 50  # Standard tier default
        assert limiter.window_seconds == 3600

    def test_tier_limits_are_configurable(self):
        """Tier limits should come from settings"""
        from backend.config.settings import get_settings
        settings = get_settings()

        limiter_free = get_athena_export_limiter('free')
        limiter_standard = get_athena_export_limiter('standard')
        limiter_enterprise = get_athena_export_limiter('enterprise')

        assert limiter_free.requests_per_window == settings.athena_export_limit_free
        assert limiter_standard.requests_per_window == settings.athena_export_limit_standard
        assert limiter_enterprise.requests_per_window == settings.athena_export_limit_enterprise


class TestAthenaExportRateLimitDependency:
    """Test the check_athena_export_rate_limit FastAPI dependency"""

    @pytest.mark.asyncio
    async def test_uses_org_subscription_tier(self, mock_request_with_org):
        """Should use organization's subscription tier to determine limit"""
        request = mock_request_with_org(subscription_tier='enterprise')

        # Call the dependency
        rate_info = await check_athena_export_rate_limit(request)

        # Should return rate info
        assert 'limit' in rate_info
        assert rate_info['limit'] == 200  # Enterprise tier

    @pytest.mark.asyncio
    async def test_free_tier_org_gets_lower_limit(self, mock_request_with_org):
        """Free tier org should get 10 requests/hour"""
        request = mock_request_with_org(subscription_tier='free')

        rate_info = await check_athena_export_rate_limit(request)

        assert rate_info['limit'] == 10  # Free tier

    @pytest.mark.asyncio
    async def test_fallback_to_standard_without_context(self):
        """Should fallback to standard tier if no context available"""
        # Create request without context
        request = MagicMock(spec=Request)
        request.state = Mock()
        request.state.context = None
        request.state.auth_user = Mock(email="test@example.com", is_authenticated=True)
        request.client = Mock(host="127.0.0.1")
        request.headers = {}
        request.url = Mock(path="/api/athena/export/csv")

        rate_info = await check_athena_export_rate_limit(request)

        assert rate_info['limit'] == 50  # Standard tier (fallback)

    @pytest.mark.asyncio
    async def test_rate_limit_enforced_across_org(self, mock_request_with_org):
        """Rate limit should be enforced across entire organization"""
        org_id = uuid4()

        # User 1 from org
        request1 = mock_request_with_org(subscription_tier='free', org_id=org_id)
        request1.state.context.user_email = "user1@example.com"

        # User 2 from same org
        request2 = mock_request_with_org(subscription_tier='free', org_id=org_id)
        request2.state.context.user_email = "user2@example.com"

        # User 1 makes 8 requests (free tier = 10)
        for _ in range(8):
            rate_info = await check_athena_export_rate_limit(request1)
            assert rate_info['remaining'] >= 0

        # User 2 should only be able to make 2 more
        rate_info = await check_athena_export_rate_limit(request2)
        assert rate_info['remaining'] == 1  # 9th request

        rate_info = await check_athena_export_rate_limit(request2)
        assert rate_info['remaining'] == 0  # 10th request

        # 11th request from either user should raise 429
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await check_athena_export_rate_limit(request2)

        assert exc_info.value.status_code == 429


class TestBackwardCompatibility:
    """Test that existing functionality is not broken"""

    @pytest.mark.asyncio
    async def test_user_level_limiting_still_works(self):
        """User-level limiting (use_org_key=False) should still work"""
        limiter = RateLimiter(
            requests_per_window=5,
            window_seconds=3600,
            use_org_key=False  # User-level
        )

        # Create request
        request = MagicMock(spec=Request)
        request.state = Mock()
        request.state.auth_user = Mock(email="test@example.com", is_authenticated=True)
        request.client = Mock(host="127.0.0.1")
        request.headers = {}

        # Should work as before
        for i in range(5):
            allowed, info = await limiter.is_allowed(request, "test")
            assert allowed
            assert info['remaining'] == 4 - i

        # 6th request should be blocked
        allowed, info = await limiter.is_allowed(request, "test")
        assert not allowed

    @pytest.mark.asyncio
    async def test_default_limiter_still_user_level(self):
        """Default RateLimiter should still use user-level limiting"""
        limiter = RateLimiter()  # No parameters

        assert limiter.use_org_key is False  # Default behavior
