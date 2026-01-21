"""
Scope API endpoints
Provides the current effective scope for the authenticated user.
"""

from typing import Optional, List

from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel
import structlog

from backend.services.request_context import get_context_from_request, RequestContext

router = APIRouter()
logger = structlog.get_logger(__name__)


class ActiveViewInfo(BaseModel):
    """Information about the active saved view"""
    id: Optional[str]
    name: Optional[str]
    expires_at: Optional[str]


class EffectiveScopeResponse(BaseModel):
    """Response model for effective scope"""
    organization_id: Optional[str]
    organization_name: Optional[str]
    allowed_account_ids: List[str]
    account_count: int
    active_view: Optional[ActiveViewInfo]
    effective_time_range: Optional[dict]
    effective_filters: Optional[dict]
    is_admin: bool
    org_role: str
    user_email: str


def get_optional_context(request: Request) -> Optional[RequestContext]:
    """Get request context if available (doesn't require auth)"""
    return get_context_from_request(request)


@router.get("/scope/current", response_model=EffectiveScopeResponse)
async def get_current_scope(
    request: Request,
    context: Optional[RequestContext] = Depends(get_optional_context)
):
    """
    Get the effective scope for the current user.

    Returns:
    - Organization context (if any)
    - Allowed AWS account IDs
    - Active saved view (if any)
    - Effective time range and filters from saved view
    - User's admin status and org role
    """
    if not context:
        return EffectiveScopeResponse(
            organization_id=None,
            organization_name=None,
            allowed_account_ids=[],
            account_count=0,
            active_view=None,
            effective_time_range=None,
            effective_filters=None,
            is_admin=False,
            org_role='none',
            user_email='anonymous'
        )

    scope_dict = context.to_scope_dict()

    active_view = None
    if scope_dict.get('active_view'):
        active_view = ActiveViewInfo(
            id=scope_dict['active_view'].get('id'),
            name=scope_dict['active_view'].get('name'),
            expires_at=scope_dict['active_view'].get('expires_at')
        )

    return EffectiveScopeResponse(
        organization_id=scope_dict.get('organization_id'),
        organization_name=scope_dict.get('organization_name'),
        allowed_account_ids=scope_dict.get('allowed_account_ids', []),
        account_count=scope_dict.get('account_count', 0),
        active_view=active_view,
        effective_time_range=scope_dict.get('effective_time_range'),
        effective_filters=scope_dict.get('effective_filters'),
        is_admin=scope_dict.get('is_admin', False),
        org_role=scope_dict.get('org_role', 'none'),
        user_email=context.user_email
    )


@router.get("/scope/accounts")
async def list_allowed_accounts(
    request: Request,
    context: Optional[RequestContext] = Depends(get_optional_context)
):
    """
    Get the list of AWS accounts the user can access.
    """
    if not context:
        return {
            "accounts": [],
            "count": 0,
            "is_admin": False
        }

    return {
        "accounts": context.allowed_account_ids,
        "count": len(context.allowed_account_ids),
        "is_admin": context.is_admin,
        "organization_id": str(context.organization_id) if context.organization_id else None
    }
