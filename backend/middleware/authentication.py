"""
JWT Authentication Middleware

Validates JWT tokens on incoming requests and attaches authenticated
user information to the request state.

Security Features:
- Validates JWT signature and expiration
- Checks token blacklist for revoked tokens
- Rejects requests with invalid/expired tokens
- JWT is the ONLY supported authentication method (no header spoofing)
- Logs authentication failures for security monitoring

SECURITY NOTE: Legacy X-User-Email header authentication has been REMOVED
to prevent authentication bypass via header spoofing attacks.
"""

from typing import Optional, Set
from dataclasses import dataclass

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
import structlog

from backend.utils.auth import (
    JWTAuthenticator,
    TokenPayload,
    TokenExpiredError,
    TokenInvalidError,
    TokenMissingError,
    extract_token_from_header,
    get_authenticator,
)
from backend.services.cache_service import get_cache_service

logger = structlog.get_logger(__name__)


@dataclass
class AuthenticatedUser:
    """
    Authenticated user information extracted from JWT token.
    Attached to request.state.auth_user
    """
    user_id: str
    email: str
    is_admin: bool
    organization_id: Optional[str]
    token_type: str

    @property
    def is_authenticated(self) -> bool:
        return True


@dataclass
class AnonymousUser:
    """Represents an unauthenticated user"""
    user_id: str = "anonymous"
    email: str = ""
    is_admin: bool = False
    organization_id: Optional[str] = None
    token_type: str = "none"

    @property
    def is_authenticated(self) -> bool:
        return False


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """
    Middleware that validates JWT tokens and attaches user info to requests.

    Security:
    - Public paths are accessible without authentication
    - All protected paths require valid JWT token in Authorization header
    - NO fallback to header-based authentication (prevents spoofing attacks)
    """

    # Paths that don't require authentication
    PUBLIC_PATHS: Set[str] = {
        '/health',
        '/health/liveness',
        '/health/readiness',
        '/metrics',
        '/docs',
        '/redoc',
        '/openapi.json',
        '/',
        '/api/auth/login',
        '/api/auth/register',
        '/api/auth/refresh',
    }

    # Path prefixes that don't require authentication
    PUBLIC_PATH_PREFIXES: tuple = (
        '/docs',
        '/static',
    )

    def __init__(self, app, authenticator: Optional[JWTAuthenticator] = None):
        """
        Initialize authentication middleware.

        Args:
            app: The ASGI application
            authenticator: Optional JWTAuthenticator instance (uses global if not provided)
        """
        super().__init__(app)
        self._authenticator = authenticator

    @property
    def authenticator(self) -> JWTAuthenticator:
        """Get the authenticator instance"""
        if self._authenticator:
            return self._authenticator
        return get_authenticator()

    def _is_public_path(self, path: str) -> bool:
        """Check if path is publicly accessible"""
        if path in self.PUBLIC_PATHS:
            return True

        for prefix in self.PUBLIC_PATH_PREFIXES:
            if path.startswith(prefix):
                return True

        return False

    async def dispatch(self, request: Request, call_next) -> Response:
        """Process authentication for each request"""
        path = request.url.path

        # Skip authentication for public paths
        if self._is_public_path(path):
            request.state.auth_user = AnonymousUser()
            return await call_next(request)

        try:
            # Authenticate via JWT token in Authorization header
            auth_user = await self._authenticate_jwt(request)

            if auth_user:
                request.state.auth_user = auth_user
                return await call_next(request)

            # No valid JWT token found - reject the request
            # SECURITY: No fallback to header-based auth (prevents spoofing attacks)
            logger.debug("authentication_required", path=path)
            return self._unauthorized_response("Authentication required")

        except TokenExpiredError:
            logger.debug("token_expired", path=path)
            return self._unauthorized_response(
                "Token has expired",
                error_code="TOKEN_EXPIRED"
            )

        except TokenInvalidError as e:
            error_str = str(e)
            # Determine if this is a revoked token
            error_code = "TOKEN_REVOKED" if "revoked" in error_str.lower() else "TOKEN_INVALID"
            logger.warning(
                "invalid_token",
                path=path,
                error=error_str,
                error_code=error_code,
                client_ip=request.client.host if request.client else "unknown"
            )
            return self._unauthorized_response(
                error_str if error_code == "TOKEN_REVOKED" else "Invalid authentication token",
                error_code=error_code
            )

        except Exception as e:
            logger.error(
                "authentication_error",
                path=path,
                error=str(e),
                exc_info=True
            )
            return self._error_response("Authentication error")

    async def _authenticate_jwt(self, request: Request) -> Optional[AuthenticatedUser]:
        """
        Attempt JWT authentication from Authorization header.

        Args:
            request: The incoming request

        Returns:
            AuthenticatedUser if valid token, None if no token present

        Raises:
            TokenExpiredError: If token is expired
            TokenInvalidError: If token is invalid or revoked
        """
        auth_header = request.headers.get("Authorization")
        token = extract_token_from_header(auth_header)

        if not token:
            return None

        # Validate the token
        payload: TokenPayload = self.authenticator.validate_access_token(token)

        # Check if token has been revoked (blacklisted)
        try:
            cache = await get_cache_service()
            if await cache.is_access_token_blacklisted(token):
                logger.warning(
                    "revoked_token_used",
                    user_id=payload.user_id,
                    email=payload.email,
                )
                raise TokenInvalidError("Token has been revoked")
        except TokenInvalidError:
            raise
        except Exception as e:
            # Log but don't fail if cache is unavailable
            logger.debug("blacklist_check_skipped", error=str(e))

        return AuthenticatedUser(
            user_id=payload.user_id,
            email=payload.email,
            is_admin=payload.is_admin,
            organization_id=payload.organization_id,
            token_type=payload.token_type.value,
        )

    def _unauthorized_response(
        self,
        message: str,
        error_code: str = "UNAUTHORIZED"
    ) -> JSONResponse:
        """Create a 401 Unauthorized response"""
        return JSONResponse(
            status_code=401,
            content={
                "error": error_code,
                "message": message,
                "detail": "Please provide a valid authentication token in the Authorization header"
            },
            headers={
                "WWW-Authenticate": "Bearer"
            }
        )

    def _error_response(self, message: str) -> JSONResponse:
        """Create a 500 error response"""
        return JSONResponse(
            status_code=500,
            content={
                "error": "AUTHENTICATION_ERROR",
                "message": message
            }
        )


def require_auth(request: Request) -> AuthenticatedUser:
    """
    Dependency function to require authentication in route handlers.

    Usage:
        @app.get("/protected")
        async def protected_route(user: AuthenticatedUser = Depends(require_auth)):
            return {"user": user.email}

    Raises:
        HTTPException: If user is not authenticated
    """
    from fastapi import HTTPException

    auth_user = getattr(request.state, 'auth_user', None)

    if not auth_user or not auth_user.is_authenticated:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"}
        )

    return auth_user


def require_admin(request: Request) -> AuthenticatedUser:
    """
    Dependency function to require admin authentication.

    Usage:
        @app.get("/admin-only")
        async def admin_route(user: AuthenticatedUser = Depends(require_admin)):
            return {"admin": user.email}

    Raises:
        HTTPException: If user is not authenticated or not an admin
    """
    from fastapi import HTTPException

    user = require_auth(request)

    if not user.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Admin access required"
        )

    return user
