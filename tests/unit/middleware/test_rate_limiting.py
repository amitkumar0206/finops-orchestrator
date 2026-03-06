"""
Tests for Rate Limiting Middleware
"""

import pytest
from unittest.mock import Mock
from fastapi import HTTPException

from backend.middleware.rate_limiting import (
    RateLimiter,
    check_rate_limit,
    get_default_limiter,
    get_ingest_limiter,
)


@pytest.fixture
def mock_auth_user():
    """Create a mock authenticated user"""
    auth_user = Mock()
    auth_user.email = "test@example.com"
    auth_user.is_authenticated = True
    return auth_user


@pytest.fixture
def mock_request(mock_auth_user):
    """Create a mock FastAPI request with authenticated user"""
    request = Mock()
    request.client = Mock()
    request.client.host = "127.0.0.1"
    request.headers = {}
    # Set up authenticated user in request state (as AuthenticationMiddleware does)
    request.state = Mock()
    request.state.auth_user = mock_auth_user
    return request


@pytest.fixture
def mock_request_with_forwarded(mock_auth_user):
    """
    Mock request with a REALISTIC X-Forwarded-For chain behind an ALB.

    Three distinct IPs so assertions unambiguously prove which one was used:
      - 1.1.1.1       → leftmost XFF entry (attacker-controlled spoof)
      - 203.0.113.1   → rightmost XFF entry (ALB-appended = real client)
      - 10.0.0.99     → TCP peer (the ALB's own IP)
    """
    request = Mock()
    request.client = Mock()
    request.client.host = "10.0.0.99"  # ALB's IP, NOT the client
    request.headers = {
        "X-Forwarded-For": "1.1.1.1, 203.0.113.1",
    }
    # Set up authenticated user in request state
    request.state = Mock()
    request.state.auth_user = mock_auth_user
    return request


@pytest.fixture(autouse=True)
def _pin_trusted_proxy_count():
    """
    SECURITY (HIGH-12): pin trusted_proxy_count=1 for every test in this
    module. rate_limiting._get_client_key() calls get_client_ip() with no
    override, which reads from the lru_cached get_settings(). In CI the
    cache may already be populated by an earlier test with a different env,
    so patch at the point of use (client_ip.get_settings) to guarantee
    deterministic depth=1 behavior here.
    """
    from unittest.mock import patch
    fake = Mock(trusted_proxy_count=1)
    with patch("backend.utils.client_ip.get_settings", return_value=fake):
        yield


class TestRateLimiter:
    """Test RateLimiter class"""

    @pytest.mark.asyncio
    async def test_allows_requests_under_limit(self, mock_request):
        """Test that requests under the limit are allowed"""
        limiter = RateLimiter(requests_per_window=5, window_seconds=60)

        # First request should be allowed
        allowed, info = await limiter.is_allowed(mock_request, "test")

        assert allowed is True
        assert info["limit"] == 5
        assert info["remaining"] == 4

    @pytest.mark.asyncio
    async def test_blocks_requests_over_limit(self, mock_request):
        """Test that requests over the limit are blocked"""
        limiter = RateLimiter(requests_per_window=3, window_seconds=60)

        # Make 3 requests (at the limit)
        for _ in range(3):
            allowed, _ = await limiter.is_allowed(mock_request, "test")
            assert allowed is True

        # 4th request should be blocked
        allowed, info = await limiter.is_allowed(mock_request, "test")

        assert allowed is False
        assert info["remaining"] == 0

    @pytest.mark.asyncio
    async def test_uses_trusted_xff_entry_not_spoofed_leftmost(
        self, mock_request_with_forwarded
    ):
        """
        HIGH-12 REGRESSION — INVERTED FROM THE PRE-FIX TEST.

        This test previously asserted the LEFTMOST XFF entry was used —
        which is exactly the vulnerable behavior. It was a test pinning a
        bug, the same pattern as F-41 where a test asserted fail-open was
        correct for the token blacklist.

        With trusted_proxy_count=1, the ALB-appended rightmost entry is the
        real client. The attacker-prependable leftmost entry must be IGNORED.

        Fixture chain: "1.1.1.1, 203.0.113.1" with client.host="10.0.0.99".
        All three IPs are distinct, so these assertions unambiguously prove
        trusted-depth parsing (not leftmost, not TCP-peer fallback).
        """
        limiter = RateLimiter(requests_per_window=5, window_seconds=60)

        key = limiter._get_client_key(mock_request_with_forwarded, "test")

        # Real client (ALB-appended, rightmost) IS in the key
        assert "203.0.113.1" in key
        # Spoofed leftmost is NOT — attacker cannot choose their bucket
        assert "1.1.1.1" not in key
        # ALB's own IP is NOT — XFF was present and parsed, not ignored
        assert "10.0.0.99" not in key

    @pytest.mark.asyncio
    async def test_spoofed_xff_does_not_evade_rate_limit(self, mock_auth_user):
        """
        HIGH-12 END-TO-END REGRESSION — the actual attack.

        Pre-fix: one attacker IP behind the ALB, varying the spoofed
        X-Forwarded-For prefix on each request → each request got a fresh
        rate-limit bucket → unlimited requests. Post-fix: the ALB-appended
        rightmost entry is constant (it's the real client) → all requests
        share one bucket → 4th request blocked.
        """
        limiter = RateLimiter(requests_per_window=3, window_seconds=60)

        def spoofed_request(fake_leftmost: str):
            # Same real client (203.0.113.1) every time. Same ALB peer.
            # Only the attacker-controlled leftmost prefix varies.
            r = Mock()
            r.client = Mock(host="10.0.0.99")
            r.headers = {"X-Forwarded-For": f"{fake_leftmost}, 203.0.113.1"}
            r.state = Mock(auth_user=mock_auth_user)
            return r

        # 3 requests with 3 different spoofed prefixes — all from the SAME
        # real client, so all land in the same bucket post-fix.
        for i in range(3):
            allowed, _ = await limiter.is_allowed(
                spoofed_request(f"99.99.99.{i}"), "spray"
            )
            assert allowed is True

        # 4th with yet another spoof — pre-fix: allowed (fresh bucket);
        # post-fix: BLOCKED (same real-client bucket, now at limit).
        allowed, info = await limiter.is_allowed(
            spoofed_request("99.99.99.255"), "spray"
        )
        assert allowed is False, (
            "HIGH-12 REGRESSION: varying the spoofed X-Forwarded-For prefix "
            "must NOT evade the rate limit. If this fails, the leftmost-XFF "
            "bug is back — an attacker can bypass all IP-based controls."
        )
        assert info["remaining"] == 0

    @pytest.mark.asyncio
    async def test_different_endpoints_have_separate_limits(self, mock_request):
        """Test that different endpoints have separate rate limits"""
        limiter = RateLimiter(requests_per_window=2, window_seconds=60)

        # Exhaust limit for endpoint1
        for _ in range(2):
            await limiter.is_allowed(mock_request, "endpoint1")

        # endpoint2 should still be allowed
        allowed, _ = await limiter.is_allowed(mock_request, "endpoint2")
        assert allowed is True

        # endpoint1 should be blocked
        allowed, _ = await limiter.is_allowed(mock_request, "endpoint1")
        assert allowed is False


class TestCheckRateLimit:
    """Test rate limit dependency functions"""

    @pytest.mark.asyncio
    async def test_check_rate_limit_allows_valid_request(self, mock_request):
        """Test that valid requests pass rate limiting"""
        # Create a fresh limiter
        limiter = RateLimiter(requests_per_window=10, window_seconds=60)

        info = await check_rate_limit(mock_request, limiter, "test")

        assert "limit" in info
        assert "remaining" in info

    @pytest.mark.asyncio
    async def test_check_rate_limit_raises_429_when_exceeded(self, mock_request):
        """Test that HTTPException 429 is raised when limit exceeded"""
        limiter = RateLimiter(requests_per_window=1, window_seconds=60)

        # First request OK
        await check_rate_limit(mock_request, limiter, "test")

        # Second request should raise
        with pytest.raises(HTTPException) as exc_info:
            await check_rate_limit(mock_request, limiter, "test")

        assert exc_info.value.status_code == 429
        assert "Rate limit exceeded" in str(exc_info.value.detail)


class TestIngestRateLimiter:
    """Test ingest-specific rate limiting"""

    def test_ingest_limiter_has_stricter_limits(self):
        """Test that ingest limiter is more restrictive than default"""
        default = get_default_limiter()
        ingest = get_ingest_limiter()

        # Ingest should have lower request limit
        assert ingest.requests_per_window < default.requests_per_window

        # Ingest should have longer window (1 hour)
        assert ingest.window_seconds == 3600
