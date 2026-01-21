"""
Authentication API Endpoints

Provides endpoints for user authentication:
- Login with email/password
- Token refresh
- Logout (token invalidation)
- Current user info
"""

from typing import Optional
from datetime import datetime, timezone
import hashlib
import secrets

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, EmailStr, Field
import structlog

from backend.utils.auth import (
    get_authenticator,
    TokenExpiredError,
    TokenInvalidError,
    extract_token_from_header,
)
from backend.services.database import DatabaseService
from backend.middleware.authentication import AuthenticatedUser, require_auth
from backend.config.settings import get_settings

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/auth", tags=["authentication"])


# Request/Response Models


class LoginRequest(BaseModel):
    """Login request with email and password"""
    email: EmailStr
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    """Login response with tokens"""
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int  # seconds until access token expires
    user: "UserInfo"


class RefreshRequest(BaseModel):
    """Token refresh request"""
    refresh_token: str


class RefreshResponse(BaseModel):
    """Token refresh response"""
    access_token: str
    token_type: str = "Bearer"
    expires_in: int


class UserInfo(BaseModel):
    """User information returned in responses"""
    id: str
    email: str
    full_name: Optional[str] = None
    is_admin: bool = False
    organization_id: Optional[str] = None
    organization_name: Optional[str] = None


class CurrentUserResponse(BaseModel):
    """Current authenticated user response"""
    user: UserInfo
    authenticated_at: datetime
    token_type: str


# Update forward reference
LoginResponse.model_rebuild()


# Database helper


async def get_db() -> DatabaseService:
    """Get database service instance"""
    db = DatabaseService()
    if not db.engine:
        await db.initialize()
    return db


def hash_password(password: str, salt: str) -> str:
    """
    Hash a password with the given salt.

    Uses PBKDF2 with SHA-256 for secure password hashing.
    """
    return hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000  # iterations
    ).hex()


def verify_password(password: str, salt: str, hashed: str) -> bool:
    """Verify a password against its hash"""
    return hash_password(password, salt) == hashed


def generate_salt() -> str:
    """Generate a random salt for password hashing"""
    return secrets.token_hex(32)


# Endpoints


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """
    Authenticate user with email and password.

    Returns JWT access and refresh tokens on successful authentication.
    """
    db = await get_db()

    async with db.engine.begin() as conn:
        # Look up user by email
        result = await conn.execute(
            """
            SELECT id, email, full_name, password_hash, password_salt,
                   is_admin, is_active, default_organization_id
            FROM users
            WHERE email = :email
            """,
            {"email": request.email}
        )
        user_row = result.mappings().first()

        if not user_row:
            logger.warning("login_failed_user_not_found", email=request.email)
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )

        if not user_row['is_active']:
            logger.warning("login_failed_user_inactive", email=request.email)
            raise HTTPException(
                status_code=401,
                detail="Account is disabled"
            )

        # Verify password
        if not user_row['password_hash'] or not user_row['password_salt']:
            logger.warning("login_failed_no_password", email=request.email)
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )

        if not verify_password(
            request.password,
            user_row['password_salt'],
            user_row['password_hash']
        ):
            logger.warning("login_failed_wrong_password", email=request.email)
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )

        user_id = str(user_row['id'])
        is_admin = user_row['is_admin'] or False
        org_id = user_row['default_organization_id']

        # Get organization info if user has one
        org_name = None
        if org_id:
            org_result = await conn.execute(
                """
                SELECT name FROM organizations WHERE id = :org_id AND is_active = true
                """,
                {"org_id": org_id}
            )
            org_row = org_result.mappings().first()
            if org_row:
                org_name = org_row['name']

        # Create tokens
        authenticator = get_authenticator()
        settings = get_settings()

        token_pair = authenticator.create_token_pair(
            user_id=user_id,
            email=request.email,
            is_admin=is_admin,
            organization_id=str(org_id) if org_id else None,
        )

        # Update last login timestamp
        await conn.execute(
            """
            UPDATE users SET last_login_at = :now WHERE id = :user_id
            """,
            {"now": datetime.now(timezone.utc), "user_id": user_row['id']}
        )

        logger.info(
            "login_successful",
            user_id=user_id,
            email=request.email,
            is_admin=is_admin,
        )

        return LoginResponse(
            access_token=token_pair.access_token,
            refresh_token=token_pair.refresh_token,
            token_type="Bearer",
            expires_in=settings.jwt_access_token_expiry_minutes * 60,
            user=UserInfo(
                id=user_id,
                email=request.email,
                full_name=user_row['full_name'],
                is_admin=is_admin,
                organization_id=str(org_id) if org_id else None,
                organization_name=org_name,
            )
        )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_token(request: RefreshRequest):
    """
    Refresh an access token using a valid refresh token.

    The refresh token must be valid and not expired.
    """
    authenticator = get_authenticator()
    settings = get_settings()

    try:
        # Validate the refresh token
        payload = authenticator.validate_refresh_token(request.refresh_token)

        # Get current user info from database for latest admin/org status
        db = await get_db()

        async with db.engine.begin() as conn:
            result = await conn.execute(
                """
                SELECT id, is_admin, is_active, default_organization_id
                FROM users
                WHERE email = :email
                """,
                {"email": payload.email}
            )
            user_row = result.mappings().first()

            if not user_row or not user_row['is_active']:
                raise HTTPException(
                    status_code=401,
                    detail="User account is no longer active"
                )

            # Create new access token with current permissions
            new_access_token = authenticator.create_access_token(
                user_id=payload.user_id,
                email=payload.email,
                is_admin=user_row['is_admin'] or False,
                organization_id=str(user_row['default_organization_id']) if user_row['default_organization_id'] else None,
            )

            logger.debug(
                "token_refreshed",
                user_id=payload.user_id,
                email=payload.email,
            )

            return RefreshResponse(
                access_token=new_access_token,
                token_type="Bearer",
                expires_in=settings.jwt_access_token_expiry_minutes * 60,
            )

    except TokenExpiredError:
        logger.debug("refresh_token_expired")
        raise HTTPException(
            status_code=401,
            detail="Refresh token has expired. Please login again."
        )
    except TokenInvalidError as e:
        logger.warning("refresh_token_invalid", error=str(e))
        raise HTTPException(
            status_code=401,
            detail="Invalid refresh token"
        )


@router.get("/me", response_model=CurrentUserResponse)
async def get_current_user(request: Request, user: AuthenticatedUser = Depends(require_auth)):
    """
    Get information about the currently authenticated user.

    Requires a valid access token.
    """
    db = await get_db()

    async with db.engine.begin() as conn:
        result = await conn.execute(
            """
            SELECT u.id, u.email, u.full_name, u.is_admin,
                   u.default_organization_id, o.name as org_name
            FROM users u
            LEFT JOIN organizations o ON o.id = u.default_organization_id
            WHERE u.email = :email AND u.is_active = true
            """,
            {"email": user.email}
        )
        user_row = result.mappings().first()

        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")

        return CurrentUserResponse(
            user=UserInfo(
                id=str(user_row['id']),
                email=user_row['email'],
                full_name=user_row['full_name'],
                is_admin=user_row['is_admin'] or False,
                organization_id=str(user_row['default_organization_id']) if user_row['default_organization_id'] else None,
                organization_name=user_row['org_name'],
            ),
            authenticated_at=datetime.now(timezone.utc),
            token_type=user.token_type,
        )


@router.post("/logout")
async def logout(request: Request, user: AuthenticatedUser = Depends(require_auth)):
    """
    Logout the current user.

    Note: JWT tokens are stateless, so this endpoint primarily serves as
    a signal to the client to discard tokens. For true token revocation,
    implement a token blacklist with Redis/Valkey.
    """
    logger.info(
        "user_logout",
        user_id=user.user_id,
        email=user.email,
    )

    # TODO: Add token to blacklist for true revocation
    # This would require storing the token's jti in Redis with TTL

    return {"message": "Logged out successfully"}


@router.post("/validate")
async def validate_token(request: Request):
    """
    Validate an access token.

    Returns token information if valid, or error if invalid.
    Useful for external services to verify tokens.
    """
    auth_header = request.headers.get("Authorization")
    token = extract_token_from_header(auth_header)

    if not token:
        raise HTTPException(
            status_code=401,
            detail="No token provided"
        )

    authenticator = get_authenticator()

    try:
        payload = authenticator.validate_access_token(token)

        return {
            "valid": True,
            "user_id": payload.user_id,
            "email": payload.email,
            "is_admin": payload.is_admin,
            "organization_id": payload.organization_id,
            "expires_at": payload.expires_at.isoformat(),
        }

    except TokenExpiredError:
        raise HTTPException(
            status_code=401,
            detail="Token has expired"
        )
    except TokenInvalidError as e:
        raise HTTPException(
            status_code=401,
            detail=f"Invalid token: {str(e)}"
        )
