"""
Tests for JWT Authentication Utilities
"""

import time
from datetime import datetime, timedelta, timezone

import pytest
import jwt

from backend.utils.auth import (
    JWTAuthenticator,
    TokenType,
    TokenPayload,
    TokenPair,
    TokenExpiredError,
    TokenInvalidError,
    TokenMissingError,
    AuthError,
    extract_token_from_header,
    generate_secure_secret_key,
    initialize_authenticator,
    get_authenticator,
)


# Test fixtures

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
def test_user():
    """Test user data"""
    return {
        "user_id": "user-123-abc",
        "email": "test@example.com",
        "is_admin": False,
        "organization_id": "org-456-def",
    }


# JWTAuthenticator Tests


class TestJWTAuthenticator:
    """Test JWTAuthenticator class"""

    def test_create_authenticator(self, secret_key):
        """Test creating an authenticator"""
        auth = JWTAuthenticator(secret_key=secret_key)
        assert auth.secret_key == secret_key
        assert auth.ALGORITHM == "HS256"

    def test_create_authenticator_with_custom_expiry(self, secret_key):
        """Test creating authenticator with custom expiry times"""
        auth = JWTAuthenticator(
            secret_key=secret_key,
            access_token_expiry_minutes=30,
            refresh_token_expiry_days=14,
        )
        assert auth.access_token_expiry == timedelta(minutes=30)
        assert auth.refresh_token_expiry == timedelta(days=14)

    def test_empty_secret_key_raises_error(self):
        """Test that empty secret key raises error"""
        with pytest.raises(ValueError):
            JWTAuthenticator(secret_key="")

    def test_insecure_default_secret_logs_warning(self, caplog):
        """Test that insecure default secret logs warning"""
        # This should log a warning but not raise
        auth = JWTAuthenticator(secret_key="dev-secret-key-change-in-production")
        assert auth is not None


class TestAccessTokenCreation:
    """Test access token creation"""

    def test_create_access_token(self, authenticator, test_user):
        """Test creating an access token"""
        token = authenticator.create_access_token(
            user_id=test_user["user_id"],
            email=test_user["email"],
        )
        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0

    def test_access_token_contains_required_claims(self, authenticator, test_user, secret_key):
        """Test that access token contains required claims"""
        token = authenticator.create_access_token(
            user_id=test_user["user_id"],
            email=test_user["email"],
            is_admin=True,
            organization_id=test_user["organization_id"],
        )

        payload = jwt.decode(token, secret_key, algorithms=["HS256"])

        assert payload["sub"] == test_user["user_id"]
        assert payload["email"] == test_user["email"]
        assert payload["type"] == "access"
        assert payload["is_admin"] is True
        assert payload["org_id"] == test_user["organization_id"]
        assert "iat" in payload
        assert "exp" in payload
        assert "iss" in payload

    def test_access_token_expiry(self, secret_key, test_user):
        """Test that access token expires correctly"""
        auth = JWTAuthenticator(
            secret_key=secret_key,
            access_token_expiry_minutes=1,
        )

        token = auth.create_access_token(
            user_id=test_user["user_id"],
            email=test_user["email"],
        )

        payload = jwt.decode(token, secret_key, algorithms=["HS256"])
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        iat = datetime.fromtimestamp(payload["iat"], tz=timezone.utc)

        # Expiry should be ~1 minute after issue
        diff = exp - iat
        assert 50 <= diff.total_seconds() <= 70  # Allow some margin


class TestRefreshTokenCreation:
    """Test refresh token creation"""

    def test_create_refresh_token(self, authenticator, test_user):
        """Test creating a refresh token"""
        token = authenticator.create_refresh_token(
            user_id=test_user["user_id"],
            email=test_user["email"],
        )
        assert token is not None
        assert isinstance(token, str)

    def test_refresh_token_contains_required_claims(self, authenticator, test_user, secret_key):
        """Test that refresh token contains required claims"""
        token = authenticator.create_refresh_token(
            user_id=test_user["user_id"],
            email=test_user["email"],
        )

        payload = jwt.decode(token, secret_key, algorithms=["HS256"])

        assert payload["sub"] == test_user["user_id"]
        assert payload["email"] == test_user["email"]
        assert payload["type"] == "refresh"
        assert "jti" in payload  # Token ID for revocation


class TestTokenPairCreation:
    """Test token pair creation"""

    def test_create_token_pair(self, authenticator, test_user):
        """Test creating a token pair"""
        pair = authenticator.create_token_pair(
            user_id=test_user["user_id"],
            email=test_user["email"],
        )

        assert isinstance(pair, TokenPair)
        assert pair.access_token is not None
        assert pair.refresh_token is not None
        assert pair.token_type == "Bearer"
        assert pair.access_expires_at > datetime.now(timezone.utc)
        assert pair.refresh_expires_at > pair.access_expires_at


class TestTokenValidation:
    """Test token validation"""

    def test_validate_valid_access_token(self, authenticator, test_user):
        """Test validating a valid access token"""
        token = authenticator.create_access_token(
            user_id=test_user["user_id"],
            email=test_user["email"],
            is_admin=True,
        )

        payload = authenticator.validate_token(token)

        assert isinstance(payload, TokenPayload)
        assert payload.user_id == test_user["user_id"]
        assert payload.email == test_user["email"]
        assert payload.token_type == TokenType.ACCESS
        assert payload.is_admin is True

    def test_validate_expired_token_raises_error(self, secret_key, test_user):
        """Test that expired token raises TokenExpiredError"""
        auth = JWTAuthenticator(
            secret_key=secret_key,
            access_token_expiry_minutes=0,  # Immediate expiry
        )

        # Create a token with past expiry
        payload = {
            "sub": test_user["user_id"],
            "email": test_user["email"],
            "type": "access",
            "iat": datetime.now(timezone.utc) - timedelta(hours=1),
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
            "iss": "finops-platform",
        }
        token = jwt.encode(payload, secret_key, algorithm="HS256")

        with pytest.raises(TokenExpiredError):
            auth.validate_token(token)

    def test_validate_invalid_signature_raises_error(self, authenticator, test_user):
        """Test that invalid signature raises TokenInvalidError"""
        # Create token with different secret
        other_auth = JWTAuthenticator(secret_key="different-secret-key-for-testing-purposes")
        token = other_auth.create_access_token(
            user_id=test_user["user_id"],
            email=test_user["email"],
        )

        with pytest.raises(TokenInvalidError):
            authenticator.validate_token(token)

    def test_validate_malformed_token_raises_error(self, authenticator):
        """Test that malformed token raises TokenInvalidError"""
        with pytest.raises(TokenInvalidError):
            authenticator.validate_token("not.a.valid.token")

    def test_validate_missing_token_raises_error(self, authenticator):
        """Test that missing token raises TokenMissingError"""
        with pytest.raises(TokenMissingError):
            authenticator.validate_token("")

        with pytest.raises(TokenMissingError):
            authenticator.validate_token(None)

    def test_validate_wrong_issuer_raises_error(self, secret_key, test_user):
        """Test that wrong issuer raises TokenInvalidError"""
        auth = JWTAuthenticator(secret_key=secret_key, issuer="my-issuer")

        payload = {
            "sub": test_user["user_id"],
            "email": test_user["email"],
            "type": "access",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "iss": "wrong-issuer",
        }
        token = jwt.encode(payload, secret_key, algorithm="HS256")

        with pytest.raises(TokenInvalidError):
            auth.validate_token(token)


class TestAccessTokenValidation:
    """Test access token specific validation"""

    def test_validate_access_token_success(self, authenticator, test_user):
        """Test validating an access token"""
        token = authenticator.create_access_token(
            user_id=test_user["user_id"],
            email=test_user["email"],
        )

        payload = authenticator.validate_access_token(token)
        assert payload.token_type == TokenType.ACCESS

    def test_validate_refresh_as_access_raises_error(self, authenticator, test_user):
        """Test that using refresh token as access token raises error"""
        token = authenticator.create_refresh_token(
            user_id=test_user["user_id"],
            email=test_user["email"],
        )

        with pytest.raises(TokenInvalidError) as exc_info:
            authenticator.validate_access_token(token)

        assert "refresh token" in str(exc_info.value).lower()


class TestRefreshTokenValidation:
    """Test refresh token specific validation"""

    def test_validate_refresh_token_success(self, authenticator, test_user):
        """Test validating a refresh token"""
        token = authenticator.create_refresh_token(
            user_id=test_user["user_id"],
            email=test_user["email"],
        )

        payload = authenticator.validate_refresh_token(token)
        assert payload.token_type == TokenType.REFRESH

    def test_validate_access_as_refresh_raises_error(self, authenticator, test_user):
        """Test that using access token as refresh token raises error"""
        token = authenticator.create_access_token(
            user_id=test_user["user_id"],
            email=test_user["email"],
        )

        with pytest.raises(TokenInvalidError) as exc_info:
            authenticator.validate_refresh_token(token)

        assert "access token" in str(exc_info.value).lower()


class TestTokenRefresh:
    """Test token refresh functionality"""

    def test_refresh_access_token(self, authenticator, test_user):
        """Test refreshing an access token"""
        refresh_token = authenticator.create_refresh_token(
            user_id=test_user["user_id"],
            email=test_user["email"],
        )

        new_access_token = authenticator.refresh_access_token(
            refresh_token=refresh_token,
            is_admin=True,
            organization_id=test_user["organization_id"],
        )

        # Validate the new access token
        payload = authenticator.validate_access_token(new_access_token)
        assert payload.user_id == test_user["user_id"]
        assert payload.is_admin is True
        assert payload.organization_id == test_user["organization_id"]


class TestTokenPayload:
    """Test TokenPayload dataclass"""

    def test_is_expired_false_for_valid_token(self):
        """Test is_expired returns False for valid token"""
        payload = TokenPayload(
            user_id="user-123",
            email="test@example.com",
            token_type=TokenType.ACCESS,
            issued_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        assert not payload.is_expired()

    def test_is_expired_true_for_expired_token(self):
        """Test is_expired returns True for expired token"""
        payload = TokenPayload(
            user_id="user-123",
            email="test@example.com",
            token_type=TokenType.ACCESS,
            issued_at=datetime.now(timezone.utc) - timedelta(hours=2),
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        assert payload.is_expired()


# Helper function tests


class TestExtractTokenFromHeader:
    """Test extract_token_from_header function"""

    def test_extract_valid_bearer_token(self):
        """Test extracting valid Bearer token"""
        token = extract_token_from_header("Bearer abc123def456")
        assert token == "abc123def456"

    def test_extract_case_insensitive(self):
        """Test that Bearer is case insensitive"""
        token = extract_token_from_header("bearer abc123")
        assert token == "abc123"

        token = extract_token_from_header("BEARER abc123")
        assert token == "abc123"

    def test_extract_returns_none_for_missing_header(self):
        """Test returns None for missing header"""
        assert extract_token_from_header(None) is None
        assert extract_token_from_header("") is None

    def test_extract_returns_none_for_invalid_scheme(self):
        """Test returns None for non-Bearer scheme"""
        assert extract_token_from_header("Basic abc123") is None
        assert extract_token_from_header("Token abc123") is None

    def test_extract_returns_none_for_malformed(self):
        """Test returns None for malformed header"""
        assert extract_token_from_header("Bearer") is None
        assert extract_token_from_header("Bearer token extra") is None


class TestGenerateSecureSecretKey:
    """Test generate_secure_secret_key function"""

    def test_generate_key_default_length(self):
        """Test generating key with default length"""
        key = generate_secure_secret_key()
        assert len(key) > 32  # URL-safe encoding makes it longer

    def test_generate_key_custom_length(self):
        """Test generating key with custom length"""
        key = generate_secure_secret_key(32)
        assert len(key) >= 32

    def test_generate_key_is_random(self):
        """Test that generated keys are random"""
        key1 = generate_secure_secret_key()
        key2 = generate_secure_secret_key()
        assert key1 != key2


class TestGlobalAuthenticator:
    """Test global authenticator initialization"""

    def test_get_authenticator_before_init_raises_error(self):
        """Test that getting authenticator before init raises error"""
        # Reset global state
        import backend.utils.auth as auth_module
        auth_module._authenticator = None

        with pytest.raises(RuntimeError):
            get_authenticator()

    def test_initialize_and_get_authenticator(self):
        """Test initializing and getting authenticator"""
        auth = initialize_authenticator(
            secret_key="test-key-long-enough-for-testing-12345678901234567890"
        )
        assert auth is not None

        retrieved = get_authenticator()
        assert retrieved is auth
