"""
Cache Service using Valkey/Redis

Provides caching functionality including token blacklisting for JWT revocation.
Uses Valkey (Redis-compatible) as the backing store.
"""

import hashlib
from typing import Optional, Any
from datetime import datetime, timezone

import structlog

# Lazy import valkey to allow tests to run without it installed
try:
    import valkey.asyncio as valkey_client
    VALKEY_AVAILABLE = True
except ImportError:
    valkey_client = None  # type: ignore
    VALKEY_AVAILABLE = False

from backend.config.settings import get_settings

logger = structlog.get_logger(__name__)


class CacheService:
    """
    Async cache service using Valkey/Redis.

    Features:
    - Token blacklisting for JWT revocation
    - General-purpose caching with TTL support
    - Connection pooling for performance
    """

    # Key prefixes for organization
    TOKEN_BLACKLIST_PREFIX = "token:blacklist:"
    REFRESH_TOKEN_BLACKLIST_PREFIX = "refresh:blacklist:"

    _instance: Optional["CacheService"] = None
    _client: Optional[Any] = None  # valkey.Valkey when available

    def __init__(self):
        """Initialize cache service (connection created on first use)"""
        self._settings = get_settings()
        self._available = VALKEY_AVAILABLE

    @classmethod
    async def get_instance(cls) -> "CacheService":
        """Get or create singleton instance"""
        if cls._instance is None:
            cls._instance = CacheService()
            await cls._instance.connect()
        return cls._instance

    async def connect(self) -> None:
        """Establish connection to Valkey/Redis"""
        if self._client is not None:
            return

        if not self._available:
            logger.warning(
                "valkey_module_not_available",
                message="Token blacklisting disabled - valkey package not installed"
            )
            return

        try:
            self._client = valkey_client.Valkey(
                host=self._settings.valkey_host,
                port=self._settings.valkey_port,
                db=self._settings.valkey_db,
                password=self._settings.valkey_password,
                decode_responses=True,
                socket_timeout=5.0,
                socket_connect_timeout=5.0,
            )
            # Test connection
            await self._client.ping()
            logger.info(
                "cache_service_connected",
                host=self._settings.valkey_host,
                port=self._settings.valkey_port,
            )
        except Exception as e:
            logger.error("cache_service_connection_failed", error=str(e))
            self._client = None
            raise

    async def disconnect(self) -> None:
        """Close connection to Valkey/Redis"""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("cache_service_disconnected")

    async def is_connected(self) -> bool:
        """Check if connected to cache server"""
        if not self._available or self._client is None:
            return False
        try:
            await self._client.ping()
            return True
        except Exception:
            return False

    def _hash_token(self, token: str) -> str:
        """
        Create a secure hash of a token for storage.

        Uses SHA-256 to avoid storing raw tokens in cache.
        """
        return hashlib.sha256(token.encode()).hexdigest()

    async def blacklist_access_token(
        self,
        token: str,
        expires_at: datetime,
    ) -> bool:
        """
        Add an access token to the blacklist.

        Args:
            token: The JWT access token to blacklist
            expires_at: When the token expires (TTL will be set accordingly)

        Returns:
            True if successfully blacklisted, False otherwise
        """
        if self._client is None:
            logger.warning("cache_not_connected_blacklist_failed")
            return False

        try:
            # Calculate TTL based on token expiration
            now = datetime.now(timezone.utc)
            ttl_seconds = int((expires_at - now).total_seconds())

            # Don't blacklist already-expired tokens
            if ttl_seconds <= 0:
                return True

            # Store hash of token with TTL
            key = f"{self.TOKEN_BLACKLIST_PREFIX}{self._hash_token(token)}"
            await self._client.setex(key, ttl_seconds, "1")

            logger.debug(
                "access_token_blacklisted",
                ttl_seconds=ttl_seconds,
            )
            return True

        except Exception as e:
            logger.error("blacklist_access_token_failed", error=str(e))
            return False

    async def blacklist_refresh_token(
        self,
        jti: str,
        expires_at: datetime,
    ) -> bool:
        """
        Add a refresh token to the blacklist by its JWT ID (jti).

        Args:
            jti: The JWT ID (jti claim) of the refresh token
            expires_at: When the token expires (TTL will be set accordingly)

        Returns:
            True if successfully blacklisted, False otherwise
        """
        if self._client is None:
            logger.warning("cache_not_connected_blacklist_failed")
            return False

        try:
            # Calculate TTL based on token expiration
            now = datetime.now(timezone.utc)
            ttl_seconds = int((expires_at - now).total_seconds())

            # Don't blacklist already-expired tokens
            if ttl_seconds <= 0:
                return True

            # Store jti with TTL
            key = f"{self.REFRESH_TOKEN_BLACKLIST_PREFIX}{jti}"
            await self._client.setex(key, ttl_seconds, "1")

            logger.debug(
                "refresh_token_blacklisted",
                jti=jti,
                ttl_seconds=ttl_seconds,
            )
            return True

        except Exception as e:
            logger.error("blacklist_refresh_token_failed", error=str(e))
            return False

    async def is_access_token_blacklisted(self, token: str) -> bool:
        """
        Check if an access token is blacklisted.

        Args:
            token: The JWT access token to check

        Returns:
            True if blacklisted, False otherwise
        """
        if self._client is None:
            # SECURITY: Fail closed — deny access when cache is unavailable.
            # A cache outage must not allow revoked tokens to pass through.
            logger.error("cache_not_connected_blacklist_check_denied")
            return True

        try:
            key = f"{self.TOKEN_BLACKLIST_PREFIX}{self._hash_token(token)}"
            result = await self._client.exists(key)
            return bool(result)
        except Exception as e:
            # SECURITY: Fail closed on any Valkey error during blacklist check.
            logger.error("blacklist_check_failed_denied", error=str(e))
            return True

    async def is_refresh_token_blacklisted(self, jti: str) -> bool:
        """
        Check if a refresh token is blacklisted by its JWT ID.

        Args:
            jti: The JWT ID (jti claim) of the refresh token

        Returns:
            True if blacklisted, False otherwise
        """
        if self._client is None:
            # SECURITY: Fail closed — deny access when cache is unavailable.
            # A cache outage must not allow revoked tokens to pass through.
            logger.error("cache_not_connected_blacklist_check_denied")
            return True

        try:
            key = f"{self.REFRESH_TOKEN_BLACKLIST_PREFIX}{jti}"
            result = await self._client.exists(key)
            return bool(result)
        except Exception as e:
            # SECURITY: Fail closed on any Valkey error during blacklist check.
            logger.error("blacklist_check_failed_denied", error=str(e))
            return True

    async def set(
        self,
        key: str,
        value: str,
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        """
        Set a cache value.

        Args:
            key: Cache key
            value: Value to store
            ttl_seconds: Optional TTL in seconds

        Returns:
            True if successful, False otherwise
        """
        if self._client is None:
            return False

        try:
            if ttl_seconds:
                await self._client.setex(key, ttl_seconds, value)
            else:
                await self._client.set(key, value)
            return True
        except Exception as e:
            logger.error("cache_set_failed", key=key, error=str(e))
            return False

    async def get(self, key: str) -> Optional[str]:
        """
        Get a cache value.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found
        """
        if self._client is None:
            return None

        try:
            return await self._client.get(key)
        except Exception as e:
            logger.error("cache_get_failed", key=key, error=str(e))
            return None

    async def delete(self, key: str) -> bool:
        """
        Delete a cache value.

        Args:
            key: Cache key

        Returns:
            True if successful, False otherwise
        """
        if self._client is None:
            return False

        try:
            await self._client.delete(key)
            return True
        except Exception as e:
            logger.error("cache_delete_failed", key=key, error=str(e))
            return False


# Module-level singleton access
_cache_service: Optional[CacheService] = None


async def get_cache_service() -> CacheService:
    """
    Get the cache service singleton instance.

    Creates connection on first call.
    """
    global _cache_service
    if _cache_service is None:
        _cache_service = CacheService()
        try:
            await _cache_service.connect()
        except Exception as e:
            logger.warning(
                "cache_service_unavailable",
                error=str(e),
                message="Token blacklisting will be disabled"
            )
    return _cache_service


async def initialize_cache_service() -> Optional[CacheService]:
    """
    Initialize the cache service at application startup.

    Returns:
        CacheService instance or None if connection failed
    """
    global _cache_service
    _cache_service = CacheService()
    try:
        await _cache_service.connect()
        return _cache_service
    except Exception as e:
        logger.warning(
            "cache_service_init_failed",
            error=str(e),
            message="Application will run without token blacklisting"
        )
        return None


async def shutdown_cache_service() -> None:
    """Shutdown cache service (call at application shutdown)"""
    global _cache_service
    if _cache_service:
        await _cache_service.disconnect()
        _cache_service = None
