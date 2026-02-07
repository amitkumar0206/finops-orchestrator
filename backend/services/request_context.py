"""
Request Context Service
Provides a dataclass and utilities for managing request-scoped context
including user, organization, saved view, and account scoping information.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from uuid import UUID
from datetime import datetime
import re
import structlog

from backend.utils.sql_constants import SQL_VALUE_SEPARATOR, quote_sql_string

logger = structlog.get_logger(__name__)

# Import RBAC service at module level to avoid circular import issues
# We'll use late binding in the method
_rbac_service = None


@dataclass
class SavedViewInfo:
    """Information about the active saved view"""
    id: UUID
    name: str
    account_ids: List[UUID]
    default_time_range: Optional[Dict[str, Any]] = None
    filters: Optional[Dict[str, Any]] = None
    is_personal: bool = False
    expires_at: Optional[datetime] = None


@dataclass
class OrganizationInfo:
    """Information about the current organization"""
    id: UUID
    name: str
    slug: str
    subscription_tier: str = 'standard'
    settings: Dict[str, Any] = field(default_factory=dict)
    saved_view_default_expiration_days: Optional[int] = None


@dataclass
class RequestContext:
    """
    Request-scoped context containing user, organization, and scope information.
    This is attached to request.state by the account scoping middleware.
    """
    # User identification
    user_id: UUID
    user_email: str
    is_admin: bool = False

    # Organization context
    organization_id: Optional[UUID] = None
    organization_name: Optional[str] = None
    organization_info: Optional[OrganizationInfo] = None

    # Account scoping - these are the AWS 12-digit account IDs the user can access
    allowed_account_ids: List[str] = field(default_factory=list)

    # Active saved view (if any)
    active_saved_view: Optional[SavedViewInfo] = None

    # Effective filters from saved view
    effective_time_range: Optional[Dict[str, Any]] = None
    effective_filters: Optional[Dict[str, Any]] = None

    # User's role within the organization
    org_role: str = 'member'  # 'owner', 'admin', 'member'

    # Request metadata
    request_id: Optional[UUID] = None
    session_id: Optional[str] = None

    def has_account_access(self, account_id: str) -> bool:
        """Check if user has access to a specific AWS account ID"""
        if self.is_admin:
            return True
        return account_id in self.allowed_account_ids

    def filter_accounts(self, account_ids: List[str]) -> List[str]:
        """Filter a list of account IDs to only those the user can access"""
        if self.is_admin:
            return account_ids
        return [acc for acc in account_ids if acc in self.allowed_account_ids]

    def get_account_filter_sql(self) -> str:
        """
        Generate SQL WHERE clause fragment for account filtering.
        Returns empty string if admin or no account restrictions.
        """
        # Use late binding to avoid circular imports
        global _rbac_service
        if _rbac_service is None:
            from backend.services.rbac_permission_service import get_rbac_service
            _rbac_service = get_rbac_service()

        # Users with query:execute:all permission (admins/owners) can query all accounts
        if _rbac_service.has_permission(self, "query:execute:all") or not self.allowed_account_ids:
            return ""

        # Validate and escape account IDs to prevent SQL injection
        # AWS account IDs are 12-digit numbers
        validated_ids = []
        for acc in self.allowed_account_ids:
            # Only allow alphanumeric characters (AWS account IDs are 12 digits)
            if re.match(r'^[0-9]{12}$', str(acc)):
                validated_ids.append(quote_sql_string(acc))
            else:
                logger.warning("invalid_account_id_skipped", account_id=str(acc)[:20])

        if not validated_ids:
            return "1=0"  # No valid accounts = deny all

        return f"line_item_usage_account_id IN ({SQL_VALUE_SEPARATOR.join(validated_ids)})"

    def to_scope_dict(self) -> Dict[str, Any]:
        """Convert to a dictionary suitable for API responses"""
        return {
            'organization_id': str(self.organization_id) if self.organization_id else None,
            'organization_name': self.organization_name,
            'allowed_account_ids': self.allowed_account_ids,
            'account_count': len(self.allowed_account_ids),
            'active_view': {
                'id': str(self.active_saved_view.id) if self.active_saved_view else None,
                'name': self.active_saved_view.name if self.active_saved_view else None,
                'expires_at': self.active_saved_view.expires_at.isoformat() if self.active_saved_view and self.active_saved_view.expires_at else None,
            } if self.active_saved_view else None,
            'effective_time_range': self.effective_time_range,
            'effective_filters': self.effective_filters,
            'is_admin': self.is_admin,
            'org_role': self.org_role,
        }

    def to_audit_context(self) -> Dict[str, Any]:
        """Convert to a dictionary suitable for audit logging"""
        return {
            'user_id': str(self.user_id),
            'user_email': self.user_email,
            'organization_id': str(self.organization_id) if self.organization_id else None,
            'saved_view_id': str(self.active_saved_view.id) if self.active_saved_view else None,
            'allowed_account_count': len(self.allowed_account_ids),
            'is_admin': self.is_admin,
            'org_role': self.org_role,
        }


def create_empty_context(user_email: str = 'anonymous') -> RequestContext:
    """Create an empty request context for unauthenticated requests"""
    from uuid import uuid4
    return RequestContext(
        user_id=uuid4(),
        user_email=user_email,
        is_admin=False,
        allowed_account_ids=[],
    )


def get_context_from_request(request) -> Optional[RequestContext]:
    """
    Extract RequestContext from a FastAPI request.
    Returns None if no context is attached.
    """
    if hasattr(request, 'state') and hasattr(request.state, 'context'):
        return request.state.context
    return None


def require_context(request) -> RequestContext:
    """
    Get RequestContext from request, raising an error if not present.
    Use this when authentication/scoping is required.
    """
    ctx = get_context_from_request(request)
    if ctx is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Authentication required")
    return ctx


def require_org_admin(request) -> RequestContext:
    """
    Get RequestContext and verify user is an organization admin.
    """
    ctx = require_context(request)
    if ctx.org_role not in ('owner', 'admin') and not ctx.is_admin:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Organization admin access required")
    return ctx
