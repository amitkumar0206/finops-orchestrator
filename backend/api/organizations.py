"""
Organizations API endpoints
Manages organizations for multi-tenant support.
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field
import structlog

from backend.services.organization_service import organization_service
from backend.services.request_context import require_context, require_org_admin, RequestContext

router = APIRouter()
logger = structlog.get_logger(__name__)


# Request/Response Models
class OrganizationResponse(BaseModel):
    """Response model for organization"""
    id: str
    name: str
    slug: str
    subscription_tier: str
    max_users: int
    max_accounts: int
    saved_view_default_expiration_days: Optional[int]
    created_at: Optional[str]
    user_role: Optional[str] = None
    joined_at: Optional[str] = None
    is_default: Optional[bool] = None
    member_count: Optional[int] = None
    account_count: Optional[int] = None


class OrganizationMemberResponse(BaseModel):
    """Response model for organization member"""
    user_id: str
    email: str
    full_name: Optional[str]
    is_active: bool
    role: str
    joined_at: Optional[str]
    invited_by: Optional[str]


class AddMemberRequest(BaseModel):
    """Request to add a member to the organization"""
    email: str = Field(..., min_length=1)
    role: str = Field(default='member', pattern='^(owner|admin|member)$')


class UpdateMemberRoleRequest(BaseModel):
    """Request to update member's role"""
    role: str = Field(..., pattern='^(owner|admin|member)$')


async def get_request_context(request: Request) -> RequestContext:
    """Dependency to get request context"""
    return require_context(request)


async def get_admin_context(request: Request) -> RequestContext:
    """Dependency to get admin-level context"""
    return require_org_admin(request)


@router.get("/organizations", response_model=List[OrganizationResponse])
async def list_user_organizations(
    request: Request,
    context: RequestContext = Depends(get_request_context)
):
    """List all organizations the user belongs to"""
    try:
        orgs = await organization_service.get_user_organizations(user_id=context.user_id)
        return [OrganizationResponse(**org) for org in orgs]

    except Exception as e:
        logger.error("failed_to_list_organizations", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list organizations")


@router.get("/organizations/current", response_model=OrganizationResponse)
async def get_current_organization(
    request: Request,
    context: RequestContext = Depends(get_request_context)
):
    """Get the user's current organization"""
    try:
        org = await organization_service.get_current_organization(context=context)
        if not org:
            raise HTTPException(status_code=404, detail="No current organization")

        # Add user's role in this org
        orgs = await organization_service.get_user_organizations(user_id=context.user_id)
        current_org = next((o for o in orgs if o['id'] == str(context.organization_id)), None)
        if current_org:
            org['user_role'] = current_org.get('user_role')

        return OrganizationResponse(**org)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("failed_to_get_current_organization", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get current organization")


@router.put("/organizations/current/{org_id}")
async def switch_organization(
    org_id: UUID,
    request: Request,
    context: RequestContext = Depends(get_request_context)
):
    """Switch to a different organization"""
    try:
        await organization_service.switch_organization(
            user_id=context.user_id,
            org_id=org_id
        )

        # Get the new org details
        org = await organization_service.get_organization(org_id)

        logger.info(
            "organization_switched",
            user_id=str(context.user_id),
            org_id=str(org_id),
        )

        return {
            "success": True,
            "organization": OrganizationResponse(**org) if org else None,
            "message": f"Switched to organization: {org['name'] if org else 'Unknown'}"
        }

    except ValueError as e:
        logger.error("switch_organization_validation_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=400, detail="Invalid request. Please check your input.")
    except Exception as e:
        logger.error("failed_to_switch_organization", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to switch organization")


@router.get("/organizations/{org_id}", response_model=OrganizationResponse)
async def get_organization(
    org_id: UUID,
    request: Request,
    context: RequestContext = Depends(get_request_context)
):
    """Get organization details"""
    try:
        org = await organization_service.get_organization(org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")

        return OrganizationResponse(**org)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("failed_to_get_organization", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get organization")


@router.get("/organizations/current/members", response_model=List[OrganizationMemberResponse])
async def list_organization_members(
    request: Request,
    context: RequestContext = Depends(get_request_context)
):
    """List all members of the current organization"""
    try:
        members = await organization_service.list_members(context=context)
        return [OrganizationMemberResponse(**m) for m in members]

    except Exception as e:
        logger.error("failed_to_list_members", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list organization members")


@router.post("/organizations/current/members", response_model=OrganizationMemberResponse)
async def add_organization_member(
    payload: AddMemberRequest,
    request: Request,
    context: RequestContext = Depends(get_admin_context)
):
    """Add a member to the organization (admin only)"""
    try:
        result = await organization_service.add_member(
            context=context,
            user_email=payload.email,
            role=payload.role
        )

        logger.info(
            "member_added",
            org_id=str(context.organization_id),
            email=payload.email,
            role=payload.role,
        )

        return OrganizationMemberResponse(
            user_id=result['user_id'],
            email=result['email'],
            full_name=None,
            is_active=True,
            role=result['role'],
            joined_at=None,
            invited_by=context.user_email
        )

    except ValueError as e:
        logger.error("add_member_validation_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=400, detail="Invalid request. Please check your input.")
    except Exception as e:
        logger.error("failed_to_add_member", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to add member")


@router.put("/organizations/current/members/{user_id}/role")
async def update_member_role(
    user_id: UUID,
    payload: UpdateMemberRoleRequest,
    request: Request,
    context: RequestContext = Depends(get_admin_context)
):
    """Update a member's role (owner only)"""
    try:
        await organization_service.update_member_role(
            context=context,
            user_id=user_id,
            new_role=payload.role
        )

        logger.info(
            "member_role_updated",
            org_id=str(context.organization_id),
            target_user_id=str(user_id),
            new_role=payload.role,
        )

        return {"success": True, "user_id": str(user_id), "new_role": payload.role}

    except ValueError as e:
        logger.error("update_member_role_validation_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=400, detail="Invalid request. Please check your input.")
    except Exception as e:
        logger.error("failed_to_update_member_role", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update member role")


@router.delete("/organizations/current/members/{user_id}")
async def remove_organization_member(
    user_id: UUID,
    request: Request,
    context: RequestContext = Depends(get_admin_context)
):
    """Remove a member from the organization (admin only)"""
    try:
        await organization_service.remove_member(context=context, user_id=user_id)

        logger.info(
            "member_removed",
            org_id=str(context.organization_id),
            removed_user_id=str(user_id),
        )

        return {"success": True, "removed_user_id": str(user_id)}

    except ValueError as e:
        logger.error("remove_member_validation_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=400, detail="Invalid request. Please check your input.")
    except Exception as e:
        logger.error("failed_to_remove_member", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to remove member")
