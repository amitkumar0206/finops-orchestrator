"""
Tests for Rate Limiting Middleware
"""

import pytest
from unittest.mock import Mock, AsyncMock
from fastapi import HTTPException

from backend.middleware.rate_limiting import (
    RateLimiter,
    check_rate_limit,
    check_ingest_rate_limit,
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
    """Create a mock request with X-Forwarded-For header and authenticated user"""
    request = Mock()
    request.client = Mock()
    request.client.host = "10.0.0.1"
    request.headers = {
        "X-Forwarded-For": "203.0.113.1, 10.0.0.1",
    }
    # Set up authenticated user in request state
    request.state = Mock()
    request.state.auth_user = mock_auth_user
    return request


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
    async def test_uses_forwarded_ip(self, mock_request_with_forwarded):
        """Test that X-Forwarded-For header is used for client identification"""
        limiter = RateLimiter(requests_per_window=5, window_seconds=60)

        key = limiter._get_client_key(mock_request_with_forwarded, "test")

        # Should use the first IP from X-Forwarded-For
        assert "203.0.113.1" in key
        assert "10.0.0.1" not in key

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
