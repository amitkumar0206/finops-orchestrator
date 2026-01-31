"""
Tests for Cache Service

Tests token blacklisting functionality for JWT revocation.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import hashlib

from backend.services.cache_service import (
    CacheService,
    get_cache_service,
    initialize_cache_service,
    shutdown_cache_service,
    VALKEY_AVAILABLE,
)


class TestCacheServiceInit:
    """Tests for CacheService initialization"""

    def test_cache_service_creates_instance(self):
        """Test that CacheService can be instantiated"""
        service = CacheService()
        assert service is not None
        assert service._client is None  # Not connected yet

    def test_cache_service_has_correct_prefixes(self):
        """Test that cache service has correct key prefixes"""
        assert CacheService.TOKEN_BLACKLIST_PREFIX == "token:blacklist:"
        assert CacheService.REFRESH_TOKEN_BLACKLIST_PREFIX == "refresh:blacklist:"


class TestTokenHashing:
    """Tests for token hashing functionality"""

    def test_hash_token_produces_consistent_hash(self):
        """Test that hashing same token produces same result"""
        service = CacheService()
        token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test"
        hash1 = service._hash_token(token)
        hash2 = service._hash_token(token)
        assert hash1 == hash2

    def test_hash_token_produces_sha256(self):
        """Test that hash is SHA-256"""
        service = CacheService()
        token = "test_token"
        result = service._hash_token(token)
        expected = hashlib.sha256(token.encode()).hexdigest()
        assert result == expected
        assert len(result) == 64  # SHA-256 produces 64 hex characters

    def test_hash_token_different_tokens_different_hashes(self):
        """Test that different tokens produce different hashes"""
        service = CacheService()
        hash1 = service._hash_token("token1")
        hash2 = service._hash_token("token2")
        assert hash1 != hash2


class TestCacheServiceWithoutValkey:
    """Tests for CacheService when valkey is not available"""

    @pytest.mark.asyncio
    async def test_blacklist_access_token_returns_false_when_not_connected(self):
        """Test that blacklisting returns False when not connected"""
        service = CacheService()
        service._client = None
        result = await service.blacklist_access_token(
            token="test_token",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1)
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_blacklist_refresh_token_returns_false_when_not_connected(self):
        """Test that refresh token blacklisting returns False when not connected"""
        service = CacheService()
        service._client = None
        result = await service.blacklist_refresh_token(
            jti="test_jti",
            expires_at=datetime.now(timezone.utc) + timedelta(days=1)
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_is_access_token_blacklisted_denies_when_not_connected(self):
        """SECURITY: blacklist check must fail closed (deny) when cache is unavailable"""
        service = CacheService()
        service._client = None
        result = await service.is_access_token_blacklisted("test_token")
        assert result is True

    @pytest.mark.asyncio
    async def test_is_refresh_token_blacklisted_denies_when_not_connected(self):
        """SECURITY: refresh blacklist check must fail closed (deny) when cache is unavailable"""
        service = CacheService()
        service._client = None
        result = await service.is_refresh_token_blacklisted("test_jti")
        assert result is True

    @pytest.mark.asyncio
    async def test_is_connected_returns_false_when_no_client(self):
        """Test that is_connected returns False when no client"""
        service = CacheService()
        service._client = None
        result = await service.is_connected()
        assert result is False


class TestCacheServiceWithMockedValkey:
    """Tests for CacheService with mocked Valkey client"""

    @pytest.mark.asyncio
    async def test_blacklist_access_token_success(self):
        """Test successful access token blacklisting"""
        service = CacheService()
        service._client = AsyncMock()
        service._client.setex = AsyncMock(return_value=True)

        expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
        result = await service.blacklist_access_token(
            token="test_token",
            expires_at=expires_at
        )

        assert result is True
        service._client.setex.assert_called_once()
        call_args = service._client.setex.call_args
        # Verify key has correct prefix and hash
        assert call_args[0][0].startswith(CacheService.TOKEN_BLACKLIST_PREFIX)

    @pytest.mark.asyncio
    async def test_blacklist_access_token_expired_returns_true(self):
        """Test that already-expired tokens return True without storing"""
        service = CacheService()
        service._client = AsyncMock()

        # Token already expired
        expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        result = await service.blacklist_access_token(
            token="test_token",
            expires_at=expires_at
        )

        assert result is True
        # Should not call setex for expired token
        service._client.setex.assert_not_called()

    @pytest.mark.asyncio
    async def test_blacklist_refresh_token_success(self):
        """Test successful refresh token blacklisting"""
        service = CacheService()
        service._client = AsyncMock()
        service._client.setex = AsyncMock(return_value=True)

        expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        result = await service.blacklist_refresh_token(
            jti="unique_token_id",
            expires_at=expires_at
        )

        assert result is True
        service._client.setex.assert_called_once()
        call_args = service._client.setex.call_args
        # Verify key has correct prefix
        expected_key = f"{CacheService.REFRESH_TOKEN_BLACKLIST_PREFIX}unique_token_id"
        assert call_args[0][0] == expected_key

    @pytest.mark.asyncio
    async def test_is_access_token_blacklisted_true(self):
        """Test checking blacklisted access token"""
        service = CacheService()
        service._client = AsyncMock()
        service._client.exists = AsyncMock(return_value=1)

        result = await service.is_access_token_blacklisted("blacklisted_token")

        assert result is True
        service._client.exists.assert_called_once()

    @pytest.mark.asyncio
    async def test_is_access_token_blacklisted_false(self):
        """Test checking non-blacklisted access token"""
        service = CacheService()
        service._client = AsyncMock()
        service._client.exists = AsyncMock(return_value=0)

        result = await service.is_access_token_blacklisted("valid_token")

        assert result is False

    @pytest.mark.asyncio
    async def test_is_refresh_token_blacklisted_true(self):
        """Test checking blacklisted refresh token by jti"""
        service = CacheService()
        service._client = AsyncMock()
        service._client.exists = AsyncMock(return_value=1)

        result = await service.is_refresh_token_blacklisted("blacklisted_jti")

        assert result is True
        expected_key = f"{CacheService.REFRESH_TOKEN_BLACKLIST_PREFIX}blacklisted_jti"
        service._client.exists.assert_called_once_with(expected_key)

    @pytest.mark.asyncio
    async def test_is_refresh_token_blacklisted_false(self):
        """Test checking non-blacklisted refresh token"""
        service = CacheService()
        service._client = AsyncMock()
        service._client.exists = AsyncMock(return_value=0)

        result = await service.is_refresh_token_blacklisted("valid_jti")

        assert result is False

    @pytest.mark.asyncio
    async def test_blacklist_handles_exception(self):
        """Test that blacklist handles exceptions gracefully"""
        service = CacheService()
        service._client = AsyncMock()
        service._client.setex = AsyncMock(side_effect=Exception("Connection error"))

        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        result = await service.blacklist_access_token(
            token="test_token",
            expires_at=expires_at
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_is_access_token_blacklisted_denies_on_valkey_error(self):
        """SECURITY: blacklist check must fail closed when Valkey raises during exists()"""
        service = CacheService()
        service._client = AsyncMock()
        service._client.exists = AsyncMock(side_effect=Exception("Connection reset"))

        result = await service.is_access_token_blacklisted("some_token")

        assert result is True

    @pytest.mark.asyncio
    async def test_is_refresh_token_blacklisted_denies_on_valkey_error(self):
        """SECURITY: refresh blacklist check must fail closed when Valkey raises during exists()"""
        service = CacheService()
        service._client = AsyncMock()
        service._client.exists = AsyncMock(side_effect=Exception("Connection reset"))

        result = await service.is_refresh_token_blacklisted("some_jti")

        assert result is True

    @pytest.mark.asyncio
    async def test_is_connected_returns_true_when_connected(self):
        """Test that is_connected returns True when ping succeeds"""
        service = CacheService()
        service._available = True
        service._client = AsyncMock()
        service._client.ping = AsyncMock(return_value=True)

        result = await service.is_connected()

        assert result is True
        service._client.ping.assert_called_once()


class TestCacheServiceGeneralOperations:
    """Tests for general cache operations"""

    @pytest.mark.asyncio
    async def test_set_with_ttl(self):
        """Test setting a cache value with TTL"""
        service = CacheService()
        service._client = AsyncMock()
        service._client.setex = AsyncMock(return_value=True)

        result = await service.set("test_key", "test_value", ttl_seconds=3600)

        assert result is True
        service._client.setex.assert_called_once_with("test_key", 3600, "test_value")

    @pytest.mark.asyncio
    async def test_set_without_ttl(self):
        """Test setting a cache value without TTL"""
        service = CacheService()
        service._client = AsyncMock()
        service._client.set = AsyncMock(return_value=True)

        result = await service.set("test_key", "test_value")

        assert result is True
        service._client.set.assert_called_once_with("test_key", "test_value")

    @pytest.mark.asyncio
    async def test_get_returns_value(self):
        """Test getting a cached value"""
        service = CacheService()
        service._client = AsyncMock()
        service._client.get = AsyncMock(return_value="cached_value")

        result = await service.get("test_key")

        assert result == "cached_value"
        service._client.get.assert_called_once_with("test_key")

    @pytest.mark.asyncio
    async def test_get_returns_none_when_not_found(self):
        """Test getting a non-existent key returns None"""
        service = CacheService()
        service._client = AsyncMock()
        service._client.get = AsyncMock(return_value=None)

        result = await service.get("nonexistent_key")

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_success(self):
        """Test deleting a cached value"""
        service = CacheService()
        service._client = AsyncMock()
        service._client.delete = AsyncMock(return_value=1)

        result = await service.delete("test_key")

        assert result is True
        service._client.delete.assert_called_once_with("test_key")


class TestModuleLevelFunctions:
    """Tests for module-level helper functions"""

    @pytest.mark.asyncio
    async def test_get_cache_service_returns_instance(self):
        """Test that get_cache_service returns a CacheService instance"""
        # Reset module state
        import backend.services.cache_service as cache_module
        cache_module._cache_service = None

        with patch.object(CacheService, 'connect', new_callable=AsyncMock):
            service = await get_cache_service()
            assert isinstance(service, CacheService)

    @pytest.mark.asyncio
    async def test_shutdown_cache_service(self):
        """Test that shutdown properly disconnects"""
        import backend.services.cache_service as cache_module

        mock_service = CacheService()
        mock_service._client = AsyncMock()
        mock_service._client.close = AsyncMock()
        cache_module._cache_service = mock_service

        await shutdown_cache_service()

        assert cache_module._cache_service is None


class TestTTLCalculation:
    """Tests for TTL calculation in blacklisting"""

    @pytest.mark.asyncio
    async def test_ttl_calculated_correctly_for_access_token(self):
        """Test that TTL is calculated from expiration time"""
        service = CacheService()
        service._client = AsyncMock()
        service._client.setex = AsyncMock(return_value=True)

        # Token expires in 15 minutes
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
        await service.blacklist_access_token(token="test", expires_at=expires_at)

        call_args = service._client.setex.call_args
        ttl = call_args[0][1]  # Second positional argument is TTL
        # TTL should be approximately 15 minutes (900 seconds), give or take a second
        assert 890 <= ttl <= 910

    @pytest.mark.asyncio
    async def test_ttl_calculated_correctly_for_refresh_token(self):
        """Test that TTL is calculated from expiration time for refresh tokens"""
        service = CacheService()
        service._client = AsyncMock()
        service._client.setex = AsyncMock(return_value=True)

        # Token expires in 7 days
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        await service.blacklist_refresh_token(jti="test_jti", expires_at=expires_at)

        call_args = service._client.setex.call_args
        ttl = call_args[0][1]
        # TTL should be approximately 7 days in seconds
        expected_ttl = 7 * 24 * 60 * 60
        assert expected_ttl - 10 <= ttl <= expected_ttl + 10
