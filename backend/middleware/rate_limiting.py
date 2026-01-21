"""
Rate Limiting Middleware and Utilities

Provides rate limiting for API endpoints using in-memory storage
with optional Redis/Valkey backend for distributed deployments.
"""

import time
from typing import Optional, Dict, Callable
from collections import defaultdict
from functools import wraps
import asyncio

import structlog
from fastapi import Request, HTTPException, status

from backend.config.settings import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()


class RateLimiter:
    """
    Simple rate limiter using sliding window algorithm.

    Uses in-memory storage by default, suitable for single-instance deployments.
    For multi-instance deployments, configure Valkey/Redis backend.
    """

    def __init__(
        self,
        requests_per_window: int = None,
        window_seconds: int = None,
    ):
        """
        Initialize rate limiter.

        Args:
            requests_per_window: Max requests allowed per window (default from settings)
            window_seconds: Window size in seconds (default from settings)
        """
        self.requests_per_window = requests_per_window or settings.rate_limit_requests
        self.window_seconds = window_seconds or settings.rate_limit_window

        # In-memory storage: {key: [(timestamp, count), ...]}
        self._storage: Dict[str, list] = defaultdict(list)
        self._lock = asyncio.Lock()

    def _get_client_key(self, request: Request, endpoint: str = "") -> str:
        """
        Generate a unique key for the client.

        Uses X-Forwarded-For header if behind a proxy, otherwise client host.
        """
        # Check for forwarded IP (behind load balancer/proxy)
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            # Take the first IP in the chain (original client)
            client_ip = forwarded.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown"

        # Include user email if available for more granular limiting
        user_email = request.headers.get("X-User-Email", "anonymous")

        return f"rate_limit:{endpoint}:{client_ip}:{user_email}"

    async def is_allowed(self, request: Request, endpoint: str = "") -> tuple[bool, dict]:
        """
        Check if request is allowed under rate limit.

        Args:
            request: FastAPI request object
            endpoint: Optional endpoint identifier for per-endpoint limits

        Returns:
            Tuple of (is_allowed, rate_limit_info)
        """
        key = self._get_client_key(request, endpoint)
        current_time = time.time()
        window_start = current_time - self.window_seconds

        async with self._lock:
            # Clean old entries outside the window
            self._storage[key] = [
                (ts, count) for ts, count in self._storage[key]
                if ts > window_start
            ]

            # Count requests in current window
            total_requests = sum(count for _, count in self._storage[key])

            # Check if under limit
            remaining = max(0, self.requests_per_window - total_requests)
            reset_time = int(window_start + self.window_seconds)

            rate_info = {
                "limit": self.requests_per_window,
                "remaining": remaining,
                "reset": reset_time,
                "window_seconds": self.window_seconds,
            }

            if total_requests >= self.requests_per_window:
                logger.warning(
                    "Rate limit exceeded",
                    key=key,
                    requests=total_requests,
                    limit=self.requests_per_window,
                )
                return False, rate_info

            # Record this request
            self._storage[key].append((current_time, 1))
            rate_info["remaining"] = remaining - 1

            return True, rate_info

    async def cleanup(self):
        """Remove expired entries to prevent memory growth."""
        current_time = time.time()
        window_start = current_time - self.window_seconds

        async with self._lock:
            keys_to_delete = []
            for key in self._storage:
                self._storage[key] = [
                    (ts, count) for ts, count in self._storage[key]
                    if ts > window_start
                ]
                if not self._storage[key]:
                    keys_to_delete.append(key)

            for key in keys_to_delete:
                del self._storage[key]


# Global rate limiter instances for different use cases
_default_limiter: Optional[RateLimiter] = None
_ingest_limiter: Optional[RateLimiter] = None


def get_default_limiter() -> RateLimiter:
    """Get or create default rate limiter."""
    global _default_limiter
    if _default_limiter is None:
        _default_limiter = RateLimiter()
    return _default_limiter


def get_ingest_limiter() -> RateLimiter:
    """
    Get or create rate limiter for ingest endpoints.

    More restrictive limits for resource-intensive operations.
    """
    global _ingest_limiter
    if _ingest_limiter is None:
        # Ingest operations are expensive - limit to 5 per hour
        _ingest_limiter = RateLimiter(
            requests_per_window=5,
            window_seconds=3600,  # 1 hour
        )
    return _ingest_limiter


async def check_rate_limit(
    request: Request,
    limiter: RateLimiter = None,
    endpoint: str = "",
) -> dict:
    """
    FastAPI dependency for rate limiting.

    Usage:
        @router.post("/endpoint")
        async def my_endpoint(
            rate_info: dict = Depends(lambda r: check_rate_limit(r, endpoint="my_endpoint"))
        ):
            ...

    Args:
        request: FastAPI request
        limiter: Rate limiter instance (default: global limiter)
        endpoint: Endpoint identifier

    Returns:
        Rate limit info dict

    Raises:
        HTTPException 429 if rate limit exceeded
    """
    if limiter is None:
        limiter = get_default_limiter()

    allowed, rate_info = await limiter.is_allowed(request, endpoint)

    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "Rate limit exceeded",
                "message": f"Too many requests. Please wait {rate_info['window_seconds']} seconds before retrying.",
                "retry_after": rate_info["reset"] - int(time.time()),
                "limit": rate_info["limit"],
            },
            headers={
                "Retry-After": str(rate_info["reset"] - int(time.time())),
                "X-RateLimit-Limit": str(rate_info["limit"]),
                "X-RateLimit-Remaining": str(rate_info["remaining"]),
                "X-RateLimit-Reset": str(rate_info["reset"]),
            },
        )

    return rate_info


async def check_ingest_rate_limit(request: Request) -> dict:
    """
    FastAPI dependency specifically for ingest endpoints.

    More restrictive rate limiting for expensive operations.

    Usage:
        @router.post("/ingest")
        async def ingest(rate_info: dict = Depends(check_ingest_rate_limit)):
            ...
    """
    return await check_rate_limit(
        request,
        limiter=get_ingest_limiter(),
        endpoint="opportunities_ingest",
    )
