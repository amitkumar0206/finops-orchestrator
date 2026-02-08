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
        use_org_key: bool = False,
    ):
        """
        Initialize rate limiter.

        Args:
            requests_per_window: Max requests allowed per window (default from settings)
            window_seconds: Window size in seconds (default from settings)
            use_org_key: If True, use organization-level keys instead of user-level (default False)
        """
        self.requests_per_window = requests_per_window or settings.rate_limit_requests
        self.window_seconds = window_seconds or settings.rate_limit_window
        self.use_org_key = use_org_key

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

        # Get user email from authenticated user (set by AuthenticationMiddleware)
        # SECURITY: Never trust X-User-Email header - use authenticated user only
        auth_user = getattr(request.state, 'auth_user', None)
        user_email = auth_user.email if (auth_user and auth_user.is_authenticated) else "anonymous"

        return f"rate_limit:{endpoint}:{client_ip}:{user_email}"

    def _get_organization_key(self, request: Request, endpoint: str = "") -> str:
        """
        Generate a unique key for the organization.

        Uses organization ID for organization-level rate limiting.
        Falls back to user-level key if organization context not available.
        """
        # Get request context (set by AccountScopingMiddleware)
        context = getattr(request.state, 'context', None)

        if context and context.organization_id:
            org_id = str(context.organization_id)
            return f"rate_limit:org:{endpoint}:{org_id}"

        # Fallback to user-level key for safety
        return self._get_client_key(request, endpoint)

    async def is_allowed(self, request: Request, endpoint: str = "") -> tuple[bool, dict]:
        """
        Check if request is allowed under rate limit.

        Args:
            request: FastAPI request object
            endpoint: Optional endpoint identifier for per-endpoint limits

        Returns:
            Tuple of (is_allowed, rate_limit_info)
        """
        # Choose key generation strategy based on configuration
        if self.use_org_key:
            key = self._get_organization_key(request, endpoint)
        else:
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
_athena_export_limiters: Dict[str, RateLimiter] = {}  # Cached tier-specific limiters


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


def get_athena_export_limiter(subscription_tier: str = 'standard') -> RateLimiter:
    """
    Get rate limiter for Athena export operations based on subscription tier.

    Args:
        subscription_tier: One of 'free', 'standard', 'enterprise'

    Returns:
        RateLimiter configured for the subscription tier with organization-level limiting
    """
    global _athena_export_limiters

    # Return cached limiter if exists
    if subscription_tier in _athena_export_limiters:
        return _athena_export_limiters[subscription_tier]

    # Create new limiter for this tier
    settings_obj = get_settings()

    # Map subscription tier to limit
    limits = {
        'free': settings_obj.athena_export_limit_free,
        'standard': settings_obj.athena_export_limit_standard,
        'enterprise': settings_obj.athena_export_limit_enterprise,
    }

    # Get limit for this tier (default to standard if unknown tier)
    limit = limits.get(subscription_tier, settings_obj.athena_export_limit_standard)

    # Create organization-level limiter
    limiter = RateLimiter(
        requests_per_window=limit,
        window_seconds=settings_obj.athena_export_window,
        use_org_key=True,  # Use organization-level limiting
    )

    # Cache it
    _athena_export_limiters[subscription_tier] = limiter

    return limiter


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


async def get_per_user_limit(
    user_id: Optional[str],
    org_id: Optional[str],
    subscription_tier: str,
    user_role: str,
    endpoint: str
) -> int:
    """
    Get per-user rate limit for a specific user, organization, role, and endpoint.

    Priority order (highest to lowest):
    1. User-specific override from database (user_rate_limits)
    2. Organization role-specific override from database (organization_rate_limits)
    3. Tier-specific default from settings
    4. Conservative fallback (10/hour)

    Args:
        user_id: User UUID (None if no user context)
        org_id: Organization UUID (None if no org context)
        subscription_tier: 'free', 'standard', or 'enterprise'
        user_role: 'owner', 'admin', or 'member'
        endpoint: Endpoint name (e.g., 'athena_export')

    Returns:
        Per-user rate limit (requests per hour)
    """
    from backend.services.database import DatabaseService

    if org_id:
        try:
            db = DatabaseService()
            if not db.engine:
                await db.initialize()

            async with db.engine.begin() as conn:
                # PRIORITY 1: Check for user-specific override
                if user_id:
                    result = await conn.execute(
                        """
                        SELECT requests_per_hour
                        FROM user_rate_limits
                        WHERE user_id = :user_id
                          AND organization_id = :org_id
                          AND endpoint = :endpoint
                        """,
                        {"user_id": user_id, "org_id": org_id, "endpoint": endpoint}
                    )
                    row = result.first()
                    if row:
                        logger.debug(
                            "Using user-specific rate limit override",
                            user_id=user_id,
                            org_id=org_id,
                            endpoint=endpoint,
                            limit=row[0]
                        )
                        return row[0]

                # PRIORITY 2: Check for organization role-specific override
                result = await conn.execute(
                    """
                    SELECT requests_per_hour
                    FROM organization_rate_limits
                    WHERE organization_id = :org_id
                      AND endpoint = :endpoint
                      AND user_role = :role
                    """,
                    {"org_id": org_id, "endpoint": endpoint, "role": user_role}
                )
                row = result.first()
                if row:
                    logger.debug(
                        "Using organization role-specific rate limit",
                        org_id=org_id,
                        endpoint=endpoint,
                        role=user_role,
                        limit=row[0]
                    )
                    return row[0]
        except Exception as e:
            logger.warning(
                "Failed to fetch custom rate limit, using defaults",
                error=str(e),
                user_id=user_id,
                org_id=org_id,
                endpoint=endpoint
            )

    # Fallback to tier-specific defaults from settings
    settings = get_settings()

    # Build setting name: {endpoint}_per_user_limit_{tier}_{role}
    # Example: athena_export_per_user_limit_enterprise_admin
    setting_name = f"{endpoint}_per_user_limit_{subscription_tier}_{user_role}"

    # Get from settings or use conservative fallback
    limit = getattr(settings, setting_name, 10)

    logger.debug(
        "Using default per-user rate limit",
        endpoint=endpoint,
        tier=subscription_tier,
        role=user_role,
        limit=limit
    )

    return limit


async def check_athena_export_rate_limit(request: Request) -> dict:
    """
    FastAPI dependency for Athena export endpoints with multi-layer rate limiting.

    Implements TWO layers of rate limiting for fairness:
    1. Per-user limit (based on role) - prevents resource hogging
    2. Organization limit (based on tier) - prevents org from exceeding quota

    Rate limits by tier and role:
    - Enterprise (org=200/hour): owner/admin=100/hour, member=50/hour
    - Standard (org=50/hour): owner/admin=30/hour, member=15/hour
    - Free (org=10/hour): owner/admin=5/hour, member=3/hour

    Both limits must pass for request to succeed.

    Usage:
        @router.post("/export/csv")
        async def export_csv(
            rate_info: dict = Depends(check_athena_export_rate_limit)
        ):
            ...
    """
    from fastapi import HTTPException

    # Get request context (set by AccountScopingMiddleware)
    context = getattr(request.state, 'context', None)

    # Extract user email from request (set by authentication middleware)
    user_email = getattr(request.state, 'user_email', None)

    # Determine subscription tier, org role, and user ID
    if context and context.organization_info:
        subscription_tier = context.organization_info.subscription_tier
        org_id = str(context.organization_id) if context.organization_id else None
        user_id = str(context.user_id) if context.user_id else None
        user_role = context.org_role  # 'owner', 'admin', or 'member'
    else:
        # Fallback if no context available
        subscription_tier = 'standard'
        org_id = None
        user_id = None
        user_role = 'member'
        logger.warning(
            "No organization context available for rate limiting, using defaults",
            path=request.url.path,
            user_email=user_email
        )

    # LAYER 1: Check per-user limit (prevents resource hogging)
    # Checks user-specific override first, then role-based, then defaults
    per_user_limit = await get_per_user_limit(user_id, org_id, subscription_tier, user_role, "athena_export")

    # Create per-user limiter (uses user email as key, not org)
    user_limiter = RateLimiter(
        requests_per_window=per_user_limit,
        window_seconds=3600,
        use_org_key=False  # Use user email as key
    )

    try:
        await check_rate_limit(
            request,
            limiter=user_limiter,
            endpoint=f"athena_export_user"
        )
    except HTTPException as e:
        # Per-user limit exceeded
        logger.warning(
            "Per-user rate limit exceeded",
            user_email=user_email,
            user_role=user_role,
            limit=per_user_limit,
            tier=subscription_tier
        )
        raise HTTPException(
            status_code=429,
            detail=f"User rate limit exceeded. You have reached your personal limit of {per_user_limit} requests per hour as a '{user_role}' user. Please wait before making more requests.",
            headers=e.headers if hasattr(e, 'headers') else {
                "Retry-After": "3600",
                "X-RateLimit-Limit": str(per_user_limit),
                "X-RateLimit-Scope": "user"
            }
        )

    # LAYER 2: Check organization limit (prevents org from exceeding tier quota)
    org_limiter = get_athena_export_limiter(subscription_tier)

    try:
        return await check_rate_limit(
            request,
            limiter=org_limiter,
            endpoint="athena_export"
        )
    except HTTPException as e:
        # Organization limit exceeded
        org_limit = getattr(get_settings(), f"athena_export_limit_{subscription_tier}", 50)
        logger.warning(
            "Organization rate limit exceeded",
            org_id=org_id,
            tier=subscription_tier,
            limit=org_limit
        )
        raise HTTPException(
            status_code=429,
            detail=f"Organization rate limit exceeded. Your organization has reached its limit of {org_limit} requests per hour for the '{subscription_tier}' tier. Please wait or upgrade your plan.",
            headers=e.headers if hasattr(e, 'headers') else {
                "Retry-After": "3600",
                "X-RateLimit-Limit": str(org_limit),
                "X-RateLimit-Scope": "organization"
            }
        )
