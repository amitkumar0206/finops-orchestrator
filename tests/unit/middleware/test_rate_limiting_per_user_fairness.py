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


# ============================================================================
# HIGH-32 — Per-User Rate Limiter Ineffective (Fresh Instance Per Request)
# ============================================================================
#
# Before the fix, check_athena_export_rate_limit() constructed a NEW RateLimiter
# on every request. RateLimiter._storage is instance-scoped (self._storage =
# defaultdict(list)), so every request saw an empty dict and the per-user limit
# NEVER fired. Layer 1 was a silent no-op.
#
# The existing test classes above missed this because:
#   - TestPerUserRateLimitingPreventsHogging creates limiters ONCE in test
#     setup and reuses them across iterations → tests the CLASS, not the
#     DEPENDENCY function that was reconstructing fresh instances.
#   - TestMultiLayerRateLimitingIntegration mocks check_rate_limit entirely
#     → tests control-flow ordering and error messages, never exercises
#     actual _storage accumulation.
#
# These tests close that gap: they call check_athena_export_rate_limit()
# REPEATEDLY with a real (unmocked) check_rate_limit and assert the
# per-user limit actually engages across calls.

from uuid import uuid4
from unittest.mock import Mock
import backend.middleware.rate_limiting as rl_module
from backend.middleware.rate_limiting import _get_athena_export_per_user_limiter


@pytest.fixture
def reset_per_user_limiter_cache():
    """
    Module-level limiter caches persist across tests. Without this reset,
    a user who hit their limit in test A is still blocked in test B.
    Snapshot-and-restore so we don't leak state into OTHER test files either.
    """
    snapshot_per_user = dict(rl_module._athena_export_per_user_limiters)
    snapshot_org = dict(rl_module._athena_export_limiters)
    rl_module._athena_export_per_user_limiters.clear()
    rl_module._athena_export_limiters.clear()
    yield
    rl_module._athena_export_per_user_limiters.clear()
    rl_module._athena_export_per_user_limiters.update(snapshot_per_user)
    rl_module._athena_export_limiters.clear()
    rl_module._athena_export_limiters.update(snapshot_org)


def _make_request(email: str, org_uuid, tier: str = "standard", role: str = "member"):
    """
    Build a request mock wired for the FULL path through
    check_athena_export_rate_limit → check_rate_limit → limiter.is_allowed
    → _get_client_key. Every attribute the real code touches must be concrete,
    not an auto-generated child MagicMock (those stringify to unstable ids and
    pollute the rate-limit key).
    """
    request = MagicMock(spec=Request)

    # --- request.state.context: read at rate_limiting.py ~478-490 ---
    org_info = MagicMock()
    org_info.subscription_tier = tier
    context = MagicMock()
    context.organization_info = org_info
    context.organization_id = org_uuid
    context.user_id = uuid4()
    context.org_role = role

    # --- request.state: Mock (not MagicMock) so missing attrs raise,
    # catching any drift in what the dependency reads ---
    request.state = Mock()
    request.state.context = context
    request.state.user_email = email  # read for the log-warning at ~498 only

    # --- request.state.auth_user: read by _get_client_key at ~69-70.
    # THIS is what actually goes into the rate-limit storage key. Must be a
    # real string — a MagicMock here would give every request a unique key
    # (via repr(mock)), which would mask the very bug we're testing. ---
    request.state.auth_user = Mock(email=email, is_authenticated=True)

    # --- _get_client_key also reads headers + client.host ---
    request.headers = {}
    request.client = Mock(host="203.0.113.7")
    request.url = Mock(path="/api/athena/export/csv")

    return request


class TestHigh32PerUserLimiterCaching:
    """Direct tests of the cached-getter. Fast white-box checks."""

    def test_same_limit_returns_same_instance(self, reset_per_user_limiter_cache):
        """
        Core fix assertion: two calls with the same limit MUST return
        the same object. `is` identity, not equality — the whole point is
        that _storage is shared across calls.
        """
        a = _get_athena_export_per_user_limiter(50)
        b = _get_athena_export_per_user_limiter(50)
        assert a is b

    def test_different_limits_return_different_instances(self, reset_per_user_limiter_cache):
        """Different requests_per_window → can't share an instance."""
        a = _get_athena_export_per_user_limiter(50)
        b = _get_athena_export_per_user_limiter(100)
        assert a is not b
        assert a.requests_per_window == 50
        assert b.requests_per_window == 100

    def test_limiter_configured_for_user_level_keying(self, reset_per_user_limiter_cache):
        """
        use_org_key=False is load-bearing: it routes is_allowed() through
        _get_client_key (email-keyed) not _get_organization_key. If someone
        "cleans up" by flipping this, two users in the same org share a quota.
        """
        limiter = _get_athena_export_per_user_limiter(15)
        assert limiter.use_org_key is False
        assert limiter.window_seconds == 3600

    def test_cache_bounded_by_distinct_limits_not_users(self, reset_per_user_limiter_cache):
        """
        Memory-bound check: 100 calls across 3 distinct limits → 3 cached
        instances. This is why we key by limit, not by (user_id, endpoint).
        """
        for _ in range(100):
            _get_athena_export_per_user_limiter(3)
            _get_athena_export_per_user_limiter(15)
            _get_athena_export_per_user_limiter(50)
        assert len(rl_module._athena_export_per_user_limiters) == 3


class TestHigh32PerUserLimitEngagesAcrossRequests:
    """
    THE regression tests. These call check_athena_export_rate_limit() directly
    and repeatedly — the actual FastAPI dependency — with a real unmocked
    check_rate_limit. Before the fix, every call here would pass because each
    got a fresh empty _storage.
    """

    @pytest.mark.asyncio
    async def test_per_user_limit_fires_on_nth_plus_one_request(
        self, reset_per_user_limiter_cache
    ):
        """
        HIGH-32 PRIMARY REGRESSION.

        Force per_user_limit=3. Give the org limiter a huge limit so it can't
        interfere. Call the dependency 4 times with the SAME user. Request 4
        MUST raise 429 with the per-user message.

        Pre-fix: request 4 passed (fresh limiter, empty _storage, user had
        "0 prior requests").
        """
        org = uuid4()
        alice = _make_request("alice@example.com", org, tier="free", role="member")

        with patch(
            "backend.middleware.rate_limiting.get_per_user_limit",
            new=AsyncMock(return_value=3),
        ), patch(
            "backend.middleware.rate_limiting.get_athena_export_limiter",
            return_value=RateLimiter(requests_per_window=10_000, window_seconds=3600, use_org_key=True),
        ):
            # Requests 1-3: under limit → must pass
            for i in range(3):
                result = await check_athena_export_rate_limit(alice)
                assert isinstance(result, dict), f"Request {i + 1} should pass, got {result!r}"

            # Request 4: over limit → MUST raise 429
            # If this passes, the limiter is still being reconstructed per-request.
            with pytest.raises(HTTPException) as exc_info:
                await check_athena_export_rate_limit(alice)

        assert exc_info.value.status_code == 429
        assert "User rate limit" in exc_info.value.detail
        assert "3" in exc_info.value.detail  # the limit value appears in the message

    @pytest.mark.asyncio
    async def test_storage_accumulates_across_dependency_calls(
        self, reset_per_user_limiter_cache
    ):
        """
        White-box: after N passing calls, the cached limiter's _storage
        must have N entries for this user's key. Direct proof of state
        persistence — the exact property the bug broke.
        """
        org = uuid4()
        bob = _make_request("bob@example.com", org)

        with patch(
            "backend.middleware.rate_limiting.get_per_user_limit",
            new=AsyncMock(return_value=5),
        ), patch(
            "backend.middleware.rate_limiting.get_athena_export_limiter",
            return_value=RateLimiter(requests_per_window=10_000, window_seconds=3600, use_org_key=True),
        ):
            for _ in range(4):
                await check_athena_export_rate_limit(bob)

        cached = rl_module._athena_export_per_user_limiters[5]
        # Exactly one key for bob; that key has 4 recorded hits
        keys = [k for k in cached._storage if "bob@example.com" in k]
        assert len(keys) == 1, f"Expected one storage key for bob, got: {list(cached._storage)}"
        assert len(cached._storage[keys[0]]) == 4

    @pytest.mark.asyncio
    async def test_users_with_same_limit_share_limiter_but_not_quota(
        self, reset_per_user_limiter_cache
    ):
        """
        Cache-key-choice validation. Alice and Carol both get limit=2 → they
        share the SAME limiter instance (memory bound). But _get_client_key
        separates them inside _storage → independent quotas.

        If we'd keyed the cache by user_id, this would trivially pass via
        separate instances; we're proving the tighter design is still correct.
        """
        org = uuid4()
        alice = _make_request("alice@example.com", org)
        carol = _make_request("carol@example.com", org)

        with patch(
            "backend.middleware.rate_limiting.get_per_user_limit",
            new=AsyncMock(return_value=2),
        ), patch(
            "backend.middleware.rate_limiting.get_athena_export_limiter",
            return_value=RateLimiter(requests_per_window=10_000, window_seconds=3600, use_org_key=True),
        ):
            # Exhaust Alice's quota
            await check_athena_export_rate_limit(alice)
            await check_athena_export_rate_limit(alice)
            with pytest.raises(HTTPException):
                await check_athena_export_rate_limit(alice)

            # Carol is untouched — same limiter instance, different _storage key
            await check_athena_export_rate_limit(carol)
            await check_athena_export_rate_limit(carol)
            with pytest.raises(HTTPException):
                await check_athena_export_rate_limit(carol)

        # Confirm single shared instance served both
        assert len(rl_module._athena_export_per_user_limiters) == 1
        shared = rl_module._athena_export_per_user_limiters[2]
        alice_keys = [k for k in shared._storage if "alice@example.com" in k]
        carol_keys = [k for k in shared._storage if "carol@example.com" in k]
        assert len(alice_keys) == 1 and len(carol_keys) == 1
        assert alice_keys[0] != carol_keys[0]

    @pytest.mark.asyncio
    async def test_org_limit_layer_still_engages_after_fix(
        self, reset_per_user_limiter_cache
    ):
        """
        Regression guard: the fix touched layer 1; layer 2 (org) must still work.
        Give per-user a high limit, org a low limit → org is the binding constraint.
        """
        org = uuid4()
        dave = _make_request("dave@example.com", org)

        org_limiter = RateLimiter(requests_per_window=2, window_seconds=3600, use_org_key=True)

        with patch(
            "backend.middleware.rate_limiting.get_per_user_limit",
            new=AsyncMock(return_value=1000),  # per-user won't bind
        ), patch(
            "backend.middleware.rate_limiting.get_athena_export_limiter",
            return_value=org_limiter,
        ):
            await check_athena_export_rate_limit(dave)
            await check_athena_export_rate_limit(dave)
            with pytest.raises(HTTPException) as exc_info:
                await check_athena_export_rate_limit(dave)

        assert exc_info.value.status_code == 429
        assert "Organization rate limit" in exc_info.value.detail


class TestHigh32SourceTripwire:
    """
    Source-level regression lock. Behavioural tests above prove the fix works
    TODAY; this proves it won't silently regress if someone "simplifies" by
    inlining the constructor again.
    """

    def test_no_direct_ratelimiter_construction_in_dependency(self):
        """
        Walk the AST of check_athena_export_rate_limit(). Any RateLimiter(...)
        call node in its body is the bug — the ONLY safe way to get a limiter
        inside a per-request function is through a module-cached getter.

        AST-based (not string match) so comments explaining the vulnerability
        don't false-positive.
        """
        import ast
        import inspect
        import textwrap

        src = textwrap.dedent(inspect.getsource(check_athena_export_rate_limit))
        tree = ast.parse(src)

        violations = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "RateLimiter"
            ):
                violations.append(f"line {node.lineno}: {ast.unparse(node)}")

        assert not violations, (
            f"HIGH-32: check_athena_export_rate_limit() constructs RateLimiter "
            f"directly — this reintroduces the fresh-instance-per-request bug. "
            f"_storage is instance-scoped; a fresh instance has an empty dict "
            f"and the limit never fires. Use _get_athena_export_per_user_limiter() "
            f"instead. Found: {violations}"
        )

    def test_dependency_routes_through_cached_getter(self):
        """
        Positive counterpart to the AST tripwire above: the cached getter
        IS called. Together these pin the fix in place — can't remove the
        getter call without failing one, can't add direct construction
        without failing the other.
        """
        import ast
        import inspect
        import textwrap

        src = textwrap.dedent(inspect.getsource(check_athena_export_rate_limit))
        tree = ast.parse(src)

        getter_calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_get_athena_export_per_user_limiter"
        ]
        assert len(getter_calls) == 1, (
            f"Expected exactly one call to _get_athena_export_per_user_limiter "
            f"in check_athena_export_rate_limit(), found {len(getter_calls)}"
        )

    def test_all_other_ratelimiter_constructions_are_in_cached_getters(self):
        """
        HIGH-32 sibling sweep, pinned as a test.

        Every RateLimiter(...) call in the module must be inside a function
        whose name starts with get_ or _get_ — the module's caching convention.
        Construction inside any other function (especially check_* dependencies,
        which run per-request) is the vulnerable pattern.

        If this fails after adding a new limiter: don't inline RateLimiter()
        in your dependency — add a get_*_limiter() that caches it module-level,
        same as get_default_limiter / get_ingest_limiter / get_athena_export_limiter.
        """
        import ast
        import inspect

        src = inspect.getsource(rl_module)
        tree = ast.parse(src)

        violations = []
        for func_node in ast.walk(tree):
            if not isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # The caching convention: get_* and _get_* functions are the
            # designated construction sites.
            if func_node.name.startswith("get_") or func_node.name.startswith("_get_"):
                continue
            for inner in ast.walk(func_node):
                if (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Name)
                    and inner.func.id == "RateLimiter"
                ):
                    violations.append(
                        f"{func_node.name}:{inner.lineno}: {ast.unparse(inner)}"
                    )

        assert not violations, (
            f"HIGH-32 sibling: RateLimiter constructed outside a cached getter. "
            f"Per-request construction means _storage resets every call. "
            f"Found: {violations}"
        )
