"""
Tests for JWT Authentication Middleware

These tests verify that the authentication middleware properly validates
JWT tokens and rejects all other forms of authentication (including
the previously vulnerable X-User-Email header).
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timedelta, timezone

from backend.middleware.authentication import (
    AuthenticationMiddleware,
    AuthenticatedUser,
    AnonymousUser,
    require_auth,
    require_admin,
)
from backend.utils.auth import (
    JWTAuthenticator,
    TokenExpiredError,
    TokenInvalidError,
)


@pytest.fixture
def secret_key():
    """Secure test secret key"""
    return "test-secret-key-that-is-long-enough-for-testing-purposes-12345"


@pytest.fixture
def authenticator(secret_key):
    """Create a test authenticator"""
    return JWTAuthenticator(
        secret_key=secret_key,
        access_token_expiry_minutes=15,
        refresh_token_expiry_days=7,
    )


@pytest.fixture
def valid_access_token(authenticator):
    """Create a valid access token"""
    return authenticator.create_access_token(
        user_id="user-123",
        email="test@example.com",
        is_admin=False,
    )


@pytest.fixture
def admin_access_token(authenticator):
    """Create an admin access token"""
    return authenticator.create_access_token(
        user_id="admin-123",
        email="admin@example.com",
        is_admin=True,
    )


class TestLegacyHeaderAuthRemoved:
    """Test that legacy X-User-Email header authentication is removed"""

    def test_no_legacy_header_auth_method(self):
        """Test that _authenticate_legacy_header method no longer exists"""
        # The method should have been removed
        assert not hasattr(AuthenticationMiddleware, '_authenticate_legacy_header')

    def test_no_settings_attribute(self):
        """Test that _settings attribute no longer exists on middleware"""
        # Create middleware instance (without actually initializing it properly)
        app = Mock()
        middleware = AuthenticationMiddleware(app)

        # The middleware should not have _settings attribute
        assert not hasattr(middleware, '_settings')

    @pytest.mark.asyncio
    async def test_x_user_email_header_ignored(self, authenticator):
        """Test that X-User-Email header is completely ignored"""
        app = Mock()
        middleware = AuthenticationMiddleware(app, authenticator=authenticator)

        # Create request with X-User-Email header but no JWT token
        request = Mock()
        request.url = Mock()
        request.url.path = "/api/v1/protected"
        request.headers = {"X-User-Email": "attacker@evil.com"}
        request.state = Mock()

        call_next = AsyncMock()

        # This should return 401, not authenticate via header
        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 401
        # call_next should NOT have been called (request was rejected)
        call_next.assert_not_called()


class TestJWTAuthentication:
    """Test JWT token authentication"""

    @pytest.mark.asyncio
    async def test_valid_token_authenticates(self, authenticator, valid_access_token):
        """Test that valid JWT token successfully authenticates"""
        app = Mock()
        middleware = AuthenticationMiddleware(app, authenticator=authenticator)

        request = Mock()
        request.url = Mock()
        request.url.path = "/api/v1/protected"
        request.headers = {"Authorization": f"Bearer {valid_access_token}"}
        request.state = Mock()

        call_next = AsyncMock(return_value=Mock())

        response = await middleware.dispatch(request, call_next)

        # Should have called the next handler
        call_next.assert_called_once()

        # Check that auth_user was set correctly
        assert hasattr(request.state, 'auth_user')
        auth_user = request.state.auth_user
        assert isinstance(auth_user, AuthenticatedUser)
        assert auth_user.email == "test@example.com"
        assert auth_user.is_authenticated is True

    @pytest.mark.asyncio
    async def test_expired_token_rejected(self, secret_key):
        """Test that expired token returns 401"""
        # Create authenticator with 0 minute expiry
        auth = JWTAuthenticator(
            secret_key=secret_key,
            access_token_expiry_minutes=0,
        )

        # Create an already-expired token manually
        import jwt
        from datetime import datetime, timedelta, timezone

        payload = {
            "sub": "user-123",
            "email": "test@example.com",
            "type": "access",
            "iat": datetime.now(timezone.utc) - timedelta(hours=1),
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
            "iss": "finops-platform",
        }
        expired_token = jwt.encode(payload, secret_key, algorithm="HS256")

        app = Mock()
        middleware = AuthenticationMiddleware(app, authenticator=auth)

        request = Mock()
        request.url = Mock()
        request.url.path = "/api/v1/protected"
        request.headers = {"Authorization": f"Bearer {expired_token}"}
        request.state = Mock()
        request.client = Mock()
        request.client.host = "127.0.0.1"

        call_next = AsyncMock()

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 401
        call_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_token_rejected(self, authenticator):
        """Test that invalid token returns 401"""
        app = Mock()
        middleware = AuthenticationMiddleware(app, authenticator=authenticator)

        request = Mock()
        request.url = Mock()
        request.url.path = "/api/v1/protected"
        request.headers = {"Authorization": "Bearer invalid.token.here"}
        request.state = Mock()
        request.client = Mock()
        request.client.host = "127.0.0.1"

        call_next = AsyncMock()

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 401
        call_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_token_returns_401(self, authenticator):
        """Test that missing token returns 401 on protected paths"""
        app = Mock()
        middleware = AuthenticationMiddleware(app, authenticator=authenticator)

        request = Mock()
        request.url = Mock()
        request.url.path = "/api/v1/protected"
        request.headers = {}
        request.state = Mock()

        call_next = AsyncMock()

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 401
        call_next.assert_not_called()


class TestPublicPaths:
    """Test that public paths don't require authentication"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", [
        "/health",
        "/health/liveness",
        "/health/readiness",
        "/metrics",
        "/",
        "/api/auth/login",
        "/api/auth/register",
        "/api/auth/refresh",
    ])
    async def test_public_paths_accessible(self, authenticator, path):
        """Test that public paths are accessible without authentication"""
        app = Mock()
        middleware = AuthenticationMiddleware(app, authenticator=authenticator)

        request = Mock()
        request.url = Mock()
        request.url.path = path
        request.headers = {}
        request.state = Mock()

        call_next = AsyncMock(return_value=Mock())

        response = await middleware.dispatch(request, call_next)

        # Should have called the next handler
        call_next.assert_called_once()

        # Auth user should be anonymous
        auth_user = request.state.auth_user
        assert isinstance(auth_user, AnonymousUser)
        assert auth_user.is_authenticated is False


class TestRequireAuthDependency:
    """Test the require_auth FastAPI dependency"""

    def test_require_auth_with_authenticated_user(self):
        """Test require_auth returns authenticated user"""
        request = Mock()
        request.state = Mock()
        request.state.auth_user = AuthenticatedUser(
            user_id="user-123",
            email="test@example.com",
            is_admin=False,
            organization_id=None,
            token_type="access",
        )

        user = require_auth(request)

        assert user.email == "test@example.com"
        assert user.is_authenticated is True

    def test_require_auth_with_anonymous_user_raises(self):
        """Test require_auth raises 401 for anonymous user"""
        from fastapi import HTTPException

        request = Mock()
        request.state = Mock()
        request.state.auth_user = AnonymousUser()

        with pytest.raises(HTTPException) as exc_info:
            require_auth(request)

        assert exc_info.value.status_code == 401

    def test_require_auth_with_no_auth_user_raises(self):
        """Test require_auth raises 401 when auth_user is missing"""
        from fastapi import HTTPException

        request = Mock()
        request.state = Mock(spec=[])  # No auth_user attribute

        with pytest.raises(HTTPException) as exc_info:
            require_auth(request)

        assert exc_info.value.status_code == 401


class TestRequireAdminDependency:
    """Test the require_admin FastAPI dependency"""

    def test_require_admin_with_admin_user(self):
        """Test require_admin returns admin user"""
        request = Mock()
        request.state = Mock()
        request.state.auth_user = AuthenticatedUser(
            user_id="admin-123",
            email="admin@example.com",
            is_admin=True,
            organization_id=None,
            token_type="access",
        )

        user = require_admin(request)

        assert user.email == "admin@example.com"
        assert user.is_admin is True

    def test_require_admin_with_non_admin_raises(self):
        """Test require_admin raises 403 for non-admin user"""
        from fastapi import HTTPException

        request = Mock()
        request.state = Mock()
        request.state.auth_user = AuthenticatedUser(
            user_id="user-123",
            email="test@example.com",
            is_admin=False,
            organization_id=None,
            token_type="access",
        )

        with pytest.raises(HTTPException) as exc_info:
            require_admin(request)

        assert exc_info.value.status_code == 403


class TestTokenBlacklist:
    """Test token blacklist checking in authentication middleware"""

    @pytest.mark.asyncio
    async def test_blacklisted_token_rejected(self, authenticator, valid_access_token):
        """Test that blacklisted tokens are rejected"""
        from backend.services.cache_service import CacheService

        app = Mock()
        middleware = AuthenticationMiddleware(app, authenticator=authenticator)

        request = Mock()
        request.url = Mock()
        request.url.path = "/api/v1/protected"
        request.headers = {"Authorization": f"Bearer {valid_access_token}"}
        request.state = Mock()
        request.client = Mock()
        request.client.host = "127.0.0.1"

        call_next = AsyncMock()

        # Mock the cache service to return True for blacklist check
        mock_cache = Mock(spec=CacheService)
        mock_cache.is_access_token_blacklisted = AsyncMock(return_value=True)

        with patch('backend.middleware.authentication.get_cache_service', return_value=mock_cache):
            response = await middleware.dispatch(request, call_next)

        # Token should be rejected with 401
        assert response.status_code == 401
        call_next.assert_not_called()

        # Verify response contains revoked error code
        import json
        response_body = json.loads(response.body.decode())
        assert response_body.get("error") == "TOKEN_REVOKED"

    @pytest.mark.asyncio
    async def test_non_blacklisted_token_allowed(self, authenticator, valid_access_token):
        """Test that non-blacklisted tokens are allowed"""
        from backend.services.cache_service import CacheService

        app = Mock()
        middleware = AuthenticationMiddleware(app, authenticator=authenticator)

        request = Mock()
        request.url = Mock()
        request.url.path = "/api/v1/protected"
        request.headers = {"Authorization": f"Bearer {valid_access_token}"}
        request.state = Mock()

        call_next = AsyncMock(return_value=Mock())

        # Mock the cache service to return False for blacklist check
        mock_cache = Mock(spec=CacheService)
        mock_cache.is_access_token_blacklisted = AsyncMock(return_value=False)

        with patch('backend.middleware.authentication.get_cache_service', return_value=mock_cache):
            response = await middleware.dispatch(request, call_next)

        # Should have called the next handler
        call_next.assert_called_once()

        # Auth user should be set
        auth_user = request.state.auth_user
        assert isinstance(auth_user, AuthenticatedUser)
        assert auth_user.email == "test@example.com"

    @pytest.mark.asyncio
    async def test_blacklist_check_failure_allows_token(self, authenticator, valid_access_token):
        """Test that cache failures don't block valid tokens (fail open)"""
        app = Mock()
        middleware = AuthenticationMiddleware(app, authenticator=authenticator)

        request = Mock()
        request.url = Mock()
        request.url.path = "/api/v1/protected"
        request.headers = {"Authorization": f"Bearer {valid_access_token}"}
        request.state = Mock()

        call_next = AsyncMock(return_value=Mock())

        # Mock cache service to raise an exception
        async def raise_error():
            raise Exception("Cache unavailable")

        with patch('backend.middleware.authentication.get_cache_service', side_effect=raise_error):
            response = await middleware.dispatch(request, call_next)

        # Should still allow the request (fail open)
        call_next.assert_called_once()

        auth_user = request.state.auth_user
        assert isinstance(auth_user, AuthenticatedUser)
