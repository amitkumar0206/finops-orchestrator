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
        from backend.services.cache_service import CacheService

        app = Mock()
        middleware = AuthenticationMiddleware(app, authenticator=authenticator)

        request = Mock()
        request.url = Mock()
        request.url.path = "/api/v1/protected"
        request.headers = {"Authorization": f"Bearer {valid_access_token}"}
        request.state = Mock()

        call_next = AsyncMock(return_value=Mock())

        # Mock cache service: token is not blacklisted
        mock_cache = Mock(spec=CacheService)
        mock_cache.is_access_token_blacklisted = AsyncMock(return_value=False)

        with patch('backend.middleware.authentication.get_cache_service', return_value=mock_cache):
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
    async def test_blacklist_check_failure_rejects_token(self, authenticator, valid_access_token):
        """
        HIGH-8 REGRESSION: cache-infrastructure failure must fail CLOSED.

        If get_cache_service() raises (or any exception escapes the blacklist
        check), the request is REJECTED. A revoked token is known-compromised —
        we cannot distinguish "cache down" from "cache down AND this token was
        revoked yesterday". Rejecting valid tokens during an outage is the
        lesser harm.

        Pre-fix: the except Exception at authentication.py:220 swallowed the
        error, logged at debug, and let the request through — defeating
        the cache service's own fail-closed design (F-25) one layer up.
        """
        app = Mock()
        middleware = AuthenticationMiddleware(app, authenticator=authenticator)

        request = Mock()
        request.url = Mock()
        request.url.path = "/api/v1/protected"
        request.headers = {"Authorization": f"Bearer {valid_access_token}"}
        request.state = Mock()
        request.client = Mock()
        request.client.host = "127.0.0.1"

        call_next = AsyncMock(return_value=Mock())

        # Mock get_cache_service itself to raise — simulates the gap that
        # is_access_token_blacklisted's internal fail-closed can't cover.
        async def raise_error():
            raise ConnectionError("Cache unavailable")

        with patch('backend.middleware.authentication.get_cache_service', side_effect=raise_error):
            response = await middleware.dispatch(request, call_next)

        # FAIL CLOSED: 401, handler NOT reached, auth_user NOT set.
        assert response.status_code == 401
        call_next.assert_not_called()

        # Error code is TOKEN_INVALID (not TOKEN_REVOKED — we don't know
        # if it's revoked, only that we can't verify). The user-facing message
        # is the generic "Invalid authentication token" — doesn't leak that
        # the cache is down.
        import json
        body = json.loads(response.body.decode())
        assert body["error"] == "TOKEN_INVALID"
        assert "cache" not in body["message"].lower()
        assert "unavailable" not in body["message"].lower()

    @pytest.mark.asyncio
    async def test_blacklist_check_failure_logs_at_error_level(self, authenticator, valid_access_token):
        """
        HIGH-8: the deny event must be visible to ops. The old code logged at
        DEBUG ("blacklist_check_skipped") — silent in production. The fix logs
        at ERROR ("blacklist_check_unavailable_denied") so cache outages
        surfacing as auth denials trigger alerts.
        """
        app = Mock()
        middleware = AuthenticationMiddleware(app, authenticator=authenticator)

        request = Mock()
        request.url = Mock()
        request.url.path = "/api/v1/protected"
        request.headers = {"Authorization": f"Bearer {valid_access_token}"}
        request.state = Mock()
        request.client = Mock()
        request.client.host = "127.0.0.1"

        call_next = AsyncMock(return_value=Mock())

        async def raise_error():
            raise RuntimeError("Valkey connection pool exhausted")

        with patch('backend.middleware.authentication.get_cache_service', side_effect=raise_error), \
             patch('backend.middleware.authentication.logger') as mock_logger:
            await middleware.dispatch(request, call_next)

        # ERROR logged with the new event name — not debug, not the old name.
        mock_logger.error.assert_any_call(
            "blacklist_check_unavailable_denied",
            user_id="user-123",
            error="Valkey connection pool exhausted",
        )
        # The old fail-open debug event must NOT be emitted.
        for call in mock_logger.debug.call_args_list:
            assert call.args[0] != "blacklist_check_skipped", (
                "Old fail-open debug event emitted — HIGH-8 regressed"
            )

    @pytest.mark.asyncio
    async def test_blacklist_check_exception_in_is_blacklisted_rejects(self, authenticator, valid_access_token):
        """
        HIGH-8 secondary path: get_cache_service() succeeds but the blacklist
        check method itself raises. Same result — fail closed.

        (In practice cache_service.is_access_token_blacklisted catches its own
        exceptions and returns True — F-25 — so this path is defense-in-depth.
        But the middleware's except Exception must handle it correctly if
        something ever escapes.)
        """
        app = Mock()
        middleware = AuthenticationMiddleware(app, authenticator=authenticator)

        request = Mock()
        request.url = Mock()
        request.url.path = "/api/v1/protected"
        request.headers = {"Authorization": f"Bearer {valid_access_token}"}
        request.state = Mock()
        request.client = Mock()
        request.client.host = "127.0.0.1"

        call_next = AsyncMock(return_value=Mock())

        mock_cache = Mock()
        mock_cache.is_access_token_blacklisted = AsyncMock(
            side_effect=OSError("Socket timeout")
        )

        with patch('backend.middleware.authentication.get_cache_service', return_value=mock_cache):
            response = await middleware.dispatch(request, call_next)

        assert response.status_code == 401
        call_next.assert_not_called()


class TestHigh8SourceTripwire:
    """
    Source-level guard: the old fail-open line must not reappear.
    """

    def test_no_blacklist_check_skipped_debug_log(self):
        """
        The old code had:
            logger.debug("blacklist_check_skipped", error=str(e))

        That string is the signature of the fail-open bug. It must not exist
        in authentication.py. If someone re-adds it (e.g. merge conflict,
        copy-paste from old branch), this test fails.
        """
        import backend.middleware.authentication as auth_mw
        import inspect
        source = inspect.getsource(auth_mw)
        assert "blacklist_check_skipped" not in source, (
            "Found 'blacklist_check_skipped' in authentication.py — this is "
            "the signature of the HIGH-8 fail-open bug. The blacklist check "
            "must fail closed: raise TokenInvalidError when the cache is "
            "unavailable."
        )

    def test_except_exception_block_raises_token_invalid(self):
        """
        AST tripwire: the except-Exception handler in _authenticate_jwt must
        contain a Raise node. Prevents someone from replacing the raise with
        a pass/log/return and re-opening HIGH-8 without triggering the
        string-match test above.
        """
        import ast
        import backend.middleware.authentication as auth_mw
        import inspect

        tree = ast.parse(inspect.getsource(auth_mw))

        # Find _authenticate_jwt
        func = None
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_authenticate_jwt":
                func = node
                break
        assert func is not None, "_authenticate_jwt not found"

        # Find the Try node containing the blacklist check
        try_nodes = [n for n in ast.walk(func) if isinstance(n, ast.Try)]
        assert len(try_nodes) >= 1, "No try block in _authenticate_jwt"

        # For each except-Exception handler (the bare Exception catch, not
        # TokenInvalidError), verify it contains a Raise
        found_exception_handler = False
        for try_node in try_nodes:
            for handler in try_node.handlers:
                # handler.type is the exception class; None = bare except
                if handler.type is None:
                    continue
                if isinstance(handler.type, ast.Name) and handler.type.id == "Exception":
                    found_exception_handler = True
                    raises = [n for n in ast.walk(handler) if isinstance(n, ast.Raise)]
                    assert len(raises) >= 1, (
                        "except Exception handler in _authenticate_jwt does not "
                        "contain a raise statement. HIGH-8: the blacklist check "
                        "must fail closed — raise TokenInvalidError when the "
                        "cache is unavailable, do not swallow the exception."
                    )

        assert found_exception_handler, (
            "No 'except Exception' handler found in _authenticate_jwt's try "
            "block — structure changed; update this tripwire."
        )
