"""
JWT Authentication Utilities

Provides secure token-based authentication to prevent header spoofing attacks.
Uses PyJWT for token generation and validation.
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum

import jwt
import structlog

logger = structlog.get_logger(__name__)


class AuthError(Exception):
    """Base authentication error"""
    pass


class TokenExpiredError(AuthError):
    """Token has expired"""
    pass


class TokenInvalidError(AuthError):
    """Token is invalid or malformed"""
    pass


class TokenMissingError(AuthError):
    """Token is missing from request"""
    pass


class TokenType(str, Enum):
    """Token types for different purposes"""
    ACCESS = "access"
    REFRESH = "refresh"


@dataclass
class TokenPayload:
    """Decoded token payload"""
    user_id: str
    email: str
    token_type: TokenType
    issued_at: datetime
    expires_at: datetime
    is_admin: bool = False
    organization_id: Optional[str] = None

    def is_expired(self) -> bool:
        """Check if token has expired"""
        return datetime.now(timezone.utc) > self.expires_at


@dataclass
class TokenPair:
    """Access and refresh token pair"""
    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime
    token_type: str = "Bearer"


class JWTAuthenticator:
    """
    JWT token authenticator for secure API authentication.

    Features:
    - Access tokens with short expiration (default 15 minutes)
    - Refresh tokens with longer expiration (default 7 days)
    - Token validation with signature verification
    - Automatic token type detection
    """

    # JWT algorithm - HS256 is secure for symmetric keys
    ALGORITHM = "HS256"

    # Token expiration defaults
    DEFAULT_ACCESS_TOKEN_EXPIRY_MINUTES = 15
    DEFAULT_REFRESH_TOKEN_EXPIRY_DAYS = 7

    # Minimum secret key length for security
    MIN_SECRET_KEY_LENGTH = 32

    def __init__(
        self,
        secret_key: str,
        access_token_expiry_minutes: int = DEFAULT_ACCESS_TOKEN_EXPIRY_MINUTES,
        refresh_token_expiry_days: int = DEFAULT_REFRESH_TOKEN_EXPIRY_DAYS,
        issuer: str = "finops-platform",
    ):
        """
        Initialize the JWT authenticator.

        Args:
            secret_key: Secret key for signing tokens (must be secure in production)
            access_token_expiry_minutes: Access token expiration time
            refresh_token_expiry_days: Refresh token expiration time
            issuer: Token issuer identifier
        """
        self._validate_secret_key(secret_key)
        self.secret_key = secret_key
        self.access_token_expiry = timedelta(minutes=access_token_expiry_minutes)
        self.refresh_token_expiry = timedelta(days=refresh_token_expiry_days)
        self.issuer = issuer

    def _validate_secret_key(self, secret_key: str) -> None:
        """Validate that secret key meets security requirements"""
        if not secret_key:
            raise ValueError("Secret key cannot be empty")

        # Check for insecure default values
        insecure_defaults = [
            "dev-secret-key-change-in-production",
            "secret",
            "changeme",
            "password",
            "123456",
        ]
        if secret_key.lower() in [s.lower() for s in insecure_defaults]:
            logger.warning(
                "SECURITY WARNING: Using insecure default secret key. "
                "This must be changed in production!"
            )

    def create_access_token(
        self,
        user_id: str,
        email: str,
        is_admin: bool = False,
        organization_id: Optional[str] = None,
        additional_claims: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Create a short-lived access token.

        Args:
            user_id: User's unique identifier
            email: User's email address
            is_admin: Whether user has admin privileges
            organization_id: User's organization ID
            additional_claims: Any additional claims to include

        Returns:
            Encoded JWT access token
        """
        now = datetime.now(timezone.utc)
        expires = now + self.access_token_expiry

        payload = {
            "sub": user_id,
            "email": email,
            "type": TokenType.ACCESS.value,
            "iat": now,
            "exp": expires,
            "iss": self.issuer,
            "is_admin": is_admin,
        }

        if organization_id:
            payload["org_id"] = organization_id

        if additional_claims:
            payload.update(additional_claims)

        token = jwt.encode(payload, self.secret_key, algorithm=self.ALGORITHM)

        logger.debug(
            "access_token_created",
            user_id=user_id,
            expires_at=expires.isoformat(),
        )

        return token

    def create_refresh_token(
        self,
        user_id: str,
        email: str,
    ) -> str:
        """
        Create a long-lived refresh token.

        Args:
            user_id: User's unique identifier
            email: User's email address

        Returns:
            Encoded JWT refresh token
        """
        now = datetime.now(timezone.utc)
        expires = now + self.refresh_token_expiry

        # Add a unique token ID for potential revocation
        token_id = secrets.token_urlsafe(16)

        payload = {
            "sub": user_id,
            "email": email,
            "type": TokenType.REFRESH.value,
            "iat": now,
            "exp": expires,
            "iss": self.issuer,
            "jti": token_id,  # JWT ID for revocation tracking
        }

        token = jwt.encode(payload, self.secret_key, algorithm=self.ALGORITHM)

        logger.debug(
            "refresh_token_created",
            user_id=user_id,
            token_id=token_id,
            expires_at=expires.isoformat(),
        )

        return token

    def create_token_pair(
        self,
        user_id: str,
        email: str,
        is_admin: bool = False,
        organization_id: Optional[str] = None,
    ) -> TokenPair:
        """
        Create both access and refresh tokens.

        Args:
            user_id: User's unique identifier
            email: User's email address
            is_admin: Whether user has admin privileges
            organization_id: User's organization ID

        Returns:
            TokenPair with both tokens and expiration times
        """
        access_token = self.create_access_token(
            user_id=user_id,
            email=email,
            is_admin=is_admin,
            organization_id=organization_id,
        )

        refresh_token = self.create_refresh_token(
            user_id=user_id,
            email=email,
        )

        now = datetime.now(timezone.utc)

        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_at=now + self.access_token_expiry,
            refresh_expires_at=now + self.refresh_token_expiry,
        )

    def validate_token(self, token: str) -> TokenPayload:
        """
        Validate and decode a JWT token.

        Args:
            token: The JWT token to validate

        Returns:
            Decoded TokenPayload

        Raises:
            TokenExpiredError: If token has expired
            TokenInvalidError: If token is invalid or malformed
        """
        if not token:
            raise TokenMissingError("Token is required")

        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.ALGORITHM],
                issuer=self.issuer,
            )

            # Extract and validate required fields
            user_id = payload.get("sub")
            email = payload.get("email")
            token_type_str = payload.get("type", TokenType.ACCESS.value)

            if not user_id or not email:
                raise TokenInvalidError("Token missing required claims")

            try:
                token_type = TokenType(token_type_str)
            except ValueError:
                raise TokenInvalidError(f"Invalid token type: {token_type_str}")

            # Parse timestamps
            iat = payload.get("iat")
            exp = payload.get("exp")

            if isinstance(iat, (int, float)):
                issued_at = datetime.fromtimestamp(iat, tz=timezone.utc)
            else:
                issued_at = datetime.now(timezone.utc)

            if isinstance(exp, (int, float)):
                expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
            else:
                expires_at = datetime.now(timezone.utc)

            return TokenPayload(
                user_id=user_id,
                email=email,
                token_type=token_type,
                issued_at=issued_at,
                expires_at=expires_at,
                is_admin=payload.get("is_admin", False),
                organization_id=payload.get("org_id"),
            )

        except jwt.ExpiredSignatureError:
            logger.debug("token_expired")
            raise TokenExpiredError("Token has expired")
        except jwt.InvalidIssuerError:
            logger.warning("token_invalid_issuer")
            raise TokenInvalidError("Invalid token issuer")
        except jwt.InvalidTokenError as e:
            logger.warning("token_invalid", error=str(e))
            raise TokenInvalidError(f"Invalid token: {str(e)}")

    def validate_access_token(self, token: str) -> TokenPayload:
        """
        Validate specifically an access token.

        Args:
            token: The JWT token to validate

        Returns:
            Decoded TokenPayload

        Raises:
            TokenInvalidError: If not an access token
        """
        payload = self.validate_token(token)

        if payload.token_type != TokenType.ACCESS:
            raise TokenInvalidError("Expected access token, got refresh token")

        return payload

    def validate_refresh_token(self, token: str) -> TokenPayload:
        """
        Validate specifically a refresh token.

        Args:
            token: The JWT token to validate

        Returns:
            Decoded TokenPayload

        Raises:
            TokenInvalidError: If not a refresh token
        """
        payload = self.validate_token(token)

        if payload.token_type != TokenType.REFRESH:
            raise TokenInvalidError("Expected refresh token, got access token")

        return payload

    def refresh_access_token(
        self,
        refresh_token: str,
        is_admin: bool = False,
        organization_id: Optional[str] = None,
    ) -> str:
        """
        Use a refresh token to create a new access token.

        Args:
            refresh_token: Valid refresh token
            is_admin: Current admin status (may have changed)
            organization_id: Current organization ID

        Returns:
            New access token
        """
        payload = self.validate_refresh_token(refresh_token)

        return self.create_access_token(
            user_id=payload.user_id,
            email=payload.email,
            is_admin=is_admin,
            organization_id=organization_id,
        )


def extract_token_from_header(authorization_header: Optional[str]) -> Optional[str]:
    """
    Extract JWT token from Authorization header.

    Expected format: "Bearer <token>"

    Args:
        authorization_header: The Authorization header value

    Returns:
        The extracted token or None
    """
    if not authorization_header:
        return None

    parts = authorization_header.split()

    if len(parts) != 2:
        return None

    scheme, token = parts

    if scheme.lower() != "bearer":
        return None

    return token


def generate_secure_secret_key(length: int = 64) -> str:
    """
    Generate a cryptographically secure secret key.

    Use this to generate a production secret key.

    Args:
        length: Length of the key in bytes (will be URL-safe encoded)

    Returns:
        Secure random string
    """
    return secrets.token_urlsafe(length)


# Singleton authenticator instance (initialized by app startup)
_authenticator: Optional[JWTAuthenticator] = None


def get_authenticator() -> JWTAuthenticator:
    """
    Get the global authenticator instance.

    Returns:
        JWTAuthenticator instance

    Raises:
        RuntimeError: If authenticator not initialized
    """
    global _authenticator
    if _authenticator is None:
        raise RuntimeError(
            "Authenticator not initialized. Call initialize_authenticator() first."
        )
    return _authenticator


def initialize_authenticator(
    secret_key: str,
    access_token_expiry_minutes: int = 15,
    refresh_token_expiry_days: int = 7,
) -> JWTAuthenticator:
    """
    Initialize the global authenticator instance.

    Args:
        secret_key: Secret key for signing tokens
        access_token_expiry_minutes: Access token expiration
        refresh_token_expiry_days: Refresh token expiration

    Returns:
        Initialized JWTAuthenticator
    """
    global _authenticator
    _authenticator = JWTAuthenticator(
        secret_key=secret_key,
        access_token_expiry_minutes=access_token_expiry_minutes,
        refresh_token_expiry_days=refresh_token_expiry_days,
    )
    logger.info("jwt_authenticator_initialized")
    return _authenticator
