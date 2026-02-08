"""
Admin API for managing rate limits.

Platform Super-Admins can manage rate limits for any organization.
Organization Admins can manage rate limits for their own organization only.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field
import structlog

from backend.middleware.authentication import AuthenticatedUser, require_auth
from backend.services.database import DatabaseService
from backend.services.request_context import RequestContext

logger = structlog.get_logger(__name__)

# Platform admin router (requires is_admin=true)
admin_router = APIRouter(prefix="/api/admin/rate-limits", tags=["admin", "rate-limits"])

# Organization admin router (requires org admin role)
org_admin_router = APIRouter(prefix="/api/organizations", tags=["organization-admin", "rate-limits"])


# Request/Response Models

class RateLimitRoleConfig(BaseModel):
    """Rate limit configuration for a specific role"""
    role: str = Field(..., description="User role: owner, admin, or member")
    requests_per_hour: int = Field(..., gt=0, description="Requests per hour for this role")


class RateLimitUserConfig(BaseModel):
    """Rate limit configuration for a specific user"""
    user_id: str = Field(..., description="User UUID")
    user_email: str = Field(..., description="User email (for display)")
    requests_per_hour: int = Field(..., gt=0, description="Custom requests per hour for this user")
    notes: Optional[str] = Field(None, description="Optional note explaining why custom limit")


class OrganizationRateLimitsResponse(BaseModel):
    """Complete rate limit configuration for an organization"""
    organization_id: str
    organization_name: str
    subscription_tier: str
    endpoint: str

    # System defaults (from settings)
    system_defaults: Dict[str, int] = Field(..., description="Default limits by role from system settings")

    # Organization role overrides
    role_overrides: List[RateLimitRoleConfig] = Field(default_factory=list, description="Custom limits by role")

    # User-specific overrides
    user_overrides: List[RateLimitUserConfig] = Field(default_factory=list, description="Custom limits for specific users")


class SetRoleLimitsRequest(BaseModel):
    """Request to set role-based rate limits for an organization"""
    endpoint: str = Field(default="athena_export", description="Endpoint name")
    role_limits: List[RateLimitRoleConfig] = Field(..., min_length=1, description="Role-based limits to set")


class SetUserLimitRequest(BaseModel):
    """Request to set rate limit for a specific user"""
    endpoint: str = Field(default="athena_export", description="Endpoint name")
    user_id: str = Field(..., description="User UUID")
    requests_per_hour: int = Field(..., gt=0, le=10000, description="Custom requests per hour")
    notes: Optional[str] = Field(None, max_length=500, description="Optional note")


# Helper functions

async def get_db() -> DatabaseService:
    """Get database service instance"""
    db = DatabaseService()
    if not db.engine:
        await db.initialize()
    return db


def require_platform_admin(user: AuthenticatedUser = Depends(require_auth)) -> AuthenticatedUser:
    """Require platform super-admin access"""
    if not user.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Platform admin access required"
        )
    return user


async def require_org_admin(
    request: Request,
    org_id: str,
    user: AuthenticatedUser = Depends(require_auth)
) -> AuthenticatedUser:
    """Require organization admin access for the specified organization"""
    context: Optional[RequestContext] = getattr(request.state, 'context', None)

    # Platform admins can manage any organization
    if user.is_admin:
        return user

    # Organization admins can only manage their own organization
    if not context:
        raise HTTPException(status_code=403, detail="No organization context")

    if str(context.organization_id) != org_id:
        raise HTTPException(status_code=403, detail="Can only manage your own organization")

    if context.org_role not in ('owner', 'admin'):
        raise HTTPException(status_code=403, detail="Organization owner or admin access required")

    return user


async def get_system_defaults(subscription_tier: str, endpoint: str) -> Dict[str, int]:
    """Get system default rate limits from settings"""
    from backend.config.settings import get_settings
    settings = get_settings()

    defaults = {}
    for role in ['owner', 'admin', 'member']:
        setting_name = f"{endpoint}_per_user_limit_{subscription_tier}_{role}"
        limit = getattr(settings, setting_name, 10)
        defaults[role] = limit

    return defaults


# Platform Admin Endpoints

@admin_router.get("/organizations/{org_id}/{endpoint}", response_model=OrganizationRateLimitsResponse)
async def get_organization_rate_limits(
    org_id: str,
    endpoint: str = "athena_export",
    admin: AuthenticatedUser = Depends(require_platform_admin)
):
    """
    Get complete rate limit configuration for an organization.

    **Platform Admin Only**

    Returns:
    - System defaults (from settings)
    - Organization role overrides (if any)
    - User-specific overrides (if any)
    """
    db = await get_db()

    async with db.engine.begin() as conn:
        # Get organization info
        org_result = await conn.execute(
            """
            SELECT id, name, subscription_tier
            FROM organizations
            WHERE id = :org_id AND is_active = true
            """,
            {"org_id": org_id}
        )
        org = org_result.mappings().first()

        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")

        # Get system defaults
        system_defaults = await get_system_defaults(org['subscription_tier'], endpoint)

        # Get organization role overrides
        role_result = await conn.execute(
            """
            SELECT user_role, requests_per_hour
            FROM organization_rate_limits
            WHERE organization_id = :org_id AND endpoint = :endpoint
            ORDER BY user_role
            """,
            {"org_id": org_id, "endpoint": endpoint}
        )
        role_overrides = [
            RateLimitRoleConfig(role=row['user_role'], requests_per_hour=row['requests_per_hour'])
            for row in role_result.mappings()
        ]

        # Get user-specific overrides
        user_result = await conn.execute(
            """
            SELECT url.user_id, u.email, url.requests_per_hour, url.notes
            FROM user_rate_limits url
            JOIN users u ON u.id = url.user_id
            WHERE url.organization_id = :org_id AND url.endpoint = :endpoint
            ORDER BY u.email
            """,
            {"org_id": org_id, "endpoint": endpoint}
        )
        user_overrides = [
            RateLimitUserConfig(
                user_id=str(row['user_id']),
                user_email=row['email'],
                requests_per_hour=row['requests_per_hour'],
                notes=row['notes']
            )
            for row in user_result.mappings()
        ]

        return OrganizationRateLimitsResponse(
            organization_id=str(org['id']),
            organization_name=org['name'],
            subscription_tier=org['subscription_tier'],
            endpoint=endpoint,
            system_defaults=system_defaults,
            role_overrides=role_overrides,
            user_overrides=user_overrides
        )


@admin_router.put("/organizations/{org_id}/roles")
async def set_organization_role_limits(
    org_id: str,
    request: SetRoleLimitsRequest,
    admin: AuthenticatedUser = Depends(require_platform_admin)
):
    """
    Set role-based rate limits for an organization.

    **Platform Admin Only**

    This overrides system defaults for specific roles.
    To reset to defaults, use DELETE endpoint.
    """
    db = await get_db()

    async with db.engine.begin() as conn:
        # Verify organization exists
        org_result = await conn.execute(
            "SELECT id FROM organizations WHERE id = :org_id AND is_active = true",
            {"org_id": org_id}
        )
        if not org_result.first():
            raise HTTPException(status_code=404, detail="Organization not found")

        # Upsert role limits
        for role_config in request.role_limits:
            await conn.execute(
                """
                INSERT INTO organization_rate_limits
                  (organization_id, endpoint, user_role, requests_per_hour, created_by)
                VALUES
                  (:org_id, :endpoint, :role, :limit, :created_by)
                ON CONFLICT (organization_id, endpoint, user_role)
                DO UPDATE SET
                  requests_per_hour = EXCLUDED.requests_per_hour,
                  updated_at = CURRENT_TIMESTAMP,
                  created_by = EXCLUDED.created_by
                """,
                {
                    "org_id": org_id,
                    "endpoint": request.endpoint,
                    "role": role_config.role,
                    "limit": role_config.requests_per_hour,
                    "created_by": admin.user_id
                }
            )

        logger.info(
            "organization_rate_limits_updated",
            org_id=org_id,
            endpoint=request.endpoint,
            roles_updated=[r.role for r in request.role_limits],
            admin_user_id=admin.user_id
        )

        return {
            "success": True,
            "message": f"Updated rate limits for {len(request.role_limits)} roles",
            "organization_id": org_id,
            "endpoint": request.endpoint
        }


@admin_router.delete("/organizations/{org_id}/roles/{role}")
async def delete_organization_role_limit(
    org_id: str,
    role: str,
    endpoint: str = "athena_export",
    admin: AuthenticatedUser = Depends(require_platform_admin)
):
    """
    Delete role-based rate limit override for an organization.

    **Platform Admin Only**

    This resets the role to use system defaults.
    """
    db = await get_db()

    async with db.engine.begin() as conn:
        result = await conn.execute(
            """
            DELETE FROM organization_rate_limits
            WHERE organization_id = :org_id
              AND endpoint = :endpoint
              AND user_role = :role
            """,
            {"org_id": org_id, "endpoint": endpoint, "role": role}
        )

        if result.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail=f"No custom limit found for role '{role}'"
            )

        logger.info(
            "organization_rate_limit_deleted",
            org_id=org_id,
            endpoint=endpoint,
            role=role,
            admin_user_id=admin.user_id
        )

        return {
            "success": True,
            "message": f"Reset rate limit for role '{role}' to system default",
            "organization_id": org_id,
            "role": role
        }


@admin_router.put("/organizations/{org_id}/users/{user_id}")
async def set_user_rate_limit(
    org_id: str,
    user_id: str,
    request: SetUserLimitRequest,
    admin: AuthenticatedUser = Depends(require_platform_admin)
):
    """
    Set custom rate limit for a specific user.

    **Platform Admin Only**

    This overrides both role-based and system defaults for this user.
    """
    db = await get_db()

    async with db.engine.begin() as conn:
        # Verify user exists and belongs to organization
        user_result = await conn.execute(
            """
            SELECT u.id, u.email, om.organization_id
            FROM users u
            JOIN organization_members om ON om.user_id = u.id
            WHERE u.id = :user_id
              AND om.organization_id = :org_id
              AND u.is_active = true
            """,
            {"user_id": user_id, "org_id": org_id}
        )
        user = user_result.mappings().first()

        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found or not member of this organization"
            )

        # Upsert user-specific limit
        await conn.execute(
            """
            INSERT INTO user_rate_limits
              (user_id, organization_id, endpoint, requests_per_hour, notes, created_by)
            VALUES
              (:user_id, :org_id, :endpoint, :limit, :notes, :created_by)
            ON CONFLICT (user_id, organization_id, endpoint)
            DO UPDATE SET
              requests_per_hour = EXCLUDED.requests_per_hour,
              notes = EXCLUDED.notes,
              updated_at = CURRENT_TIMESTAMP,
              created_by = EXCLUDED.created_by
            """,
            {
                "user_id": user_id,
                "org_id": org_id,
                "endpoint": request.endpoint,
                "limit": request.requests_per_hour,
                "notes": request.notes,
                "created_by": admin.user_id
            }
        )

        logger.info(
            "user_rate_limit_set",
            user_id=user_id,
            user_email=user['email'],
            org_id=org_id,
            endpoint=request.endpoint,
            limit=request.requests_per_hour,
            admin_user_id=admin.user_id
        )

        return {
            "success": True,
            "message": f"Set custom rate limit for user {user['email']}",
            "user_id": user_id,
            "user_email": user['email'],
            "requests_per_hour": request.requests_per_hour
        }


@admin_router.delete("/organizations/{org_id}/users/{user_id}")
async def delete_user_rate_limit(
    org_id: str,
    user_id: str,
    endpoint: str = "athena_export",
    admin: AuthenticatedUser = Depends(require_platform_admin)
):
    """
    Delete custom rate limit for a specific user.

    **Platform Admin Only**

    This resets the user to use role-based or system defaults.
    """
    db = await get_db()

    async with db.engine.begin() as conn:
        result = await conn.execute(
            """
            DELETE FROM user_rate_limits
            WHERE user_id = :user_id
              AND organization_id = :org_id
              AND endpoint = :endpoint
            """,
            {"user_id": user_id, "org_id": org_id, "endpoint": endpoint}
        )

        if result.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="No custom limit found for this user"
            )

        logger.info(
            "user_rate_limit_deleted",
            user_id=user_id,
            org_id=org_id,
            endpoint=endpoint,
            admin_user_id=admin.user_id
        )

        return {
            "success": True,
            "message": "Reset user rate limit to role-based default",
            "user_id": user_id
        }


# Organization Admin Endpoints

@org_admin_router.get("/{org_id}/rate-limits/{endpoint}", response_model=OrganizationRateLimitsResponse)
async def get_own_organization_rate_limits(
    request: Request,
    org_id: str,
    endpoint: str = "athena_export",
    user: AuthenticatedUser = Depends(require_auth)
):
    """
    Get rate limit configuration for your own organization.

    **Organization Owner/Admin Only**

    Returns complete configuration including system defaults, role overrides, and user overrides.
    """
    await require_org_admin(request, org_id, user)

    # Reuse platform admin endpoint logic
    return await get_organization_rate_limits(org_id, endpoint, user)


@org_admin_router.put("/{org_id}/rate-limits/roles")
async def set_own_organization_role_limits(
    request: Request,
    org_id: str,
    limit_request: SetRoleLimitsRequest,
    user: AuthenticatedUser = Depends(require_auth)
):
    """
    Set role-based rate limits for your own organization.

    **Organization Owner/Admin Only**

    Allows organization admins to customize rate limits for different roles within their organization.
    """
    await require_org_admin(request, org_id, user)

    # Reuse platform admin endpoint logic
    return await set_organization_role_limits(org_id, limit_request, user)


@org_admin_router.put("/{org_id}/rate-limits/users/{user_id}")
async def set_own_organization_user_limit(
    request: Request,
    org_id: str,
    user_id: str,
    limit_request: SetUserLimitRequest,
    user: AuthenticatedUser = Depends(require_auth)
):
    """
    Set custom rate limit for a specific user in your organization.

    **Organization Owner/Admin Only**

    Allows organization admins to set custom limits for specific users.
    Example: Give a power user higher limits than their role default.
    """
    await require_org_admin(request, org_id, user)

    # Reuse platform admin endpoint logic
    return await set_user_rate_limit(org_id, user_id, limit_request, user)


@org_admin_router.delete("/{org_id}/rate-limits/roles/{role}")
async def delete_own_organization_role_limit(
    request: Request,
    org_id: str,
    role: str,
    endpoint: str = "athena_export",
    user: AuthenticatedUser = Depends(require_auth)
):
    """
    Reset role-based rate limit to system default for your organization.

    **Organization Owner/Admin Only**
    """
    await require_org_admin(request, org_id, user)

    # Reuse platform admin endpoint logic
    return await delete_organization_role_limit(org_id, role, endpoint, user)


@org_admin_router.delete("/{org_id}/rate-limits/users/{user_id}")
async def delete_own_organization_user_limit(
    request: Request,
    org_id: str,
    user_id: str,
    endpoint: str = "athena_export",
    user: AuthenticatedUser = Depends(require_auth)
):
    """
    Reset user-specific rate limit to role default for your organization.

    **Organization Owner/Admin Only**
    """
    await require_org_admin(request, org_id, user)

    # Reuse platform admin endpoint logic
    return await delete_user_rate_limit(org_id, user_id, endpoint, user)
