"""
Phase 3 Enterprise Features API Endpoints
Scheduled Reports, Multi-Account, RBAC, Dashboards, and Ticketing
"""

from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
import structlog

from backend.utils.aws_constants import DEFAULT_AWS_REGION
from backend.services.scheduled_report_service import scheduled_report_service
from backend.services.multi_account_service import multi_account_service
from backend.services.rbac_service import rbac_service, require_permission, get_current_user
from backend.services.audit_log_service import audit_log_service

router = APIRouter()
logger = structlog.get_logger(__name__)


# ============================================================================
# Pydantic Models
# ============================================================================

class ScheduledReportCreate(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    report_type: str  # 'cost_breakdown', 'trend_analysis', etc.
    query_params: Dict[str, Any]
    frequency: str  # 'DAILY', 'WEEKLY', 'MONTHLY', 'QUARTERLY', 'CUSTOM_CRON'
    cron_expression: Optional[str] = None
    timezone: str = "UTC"
    format: str  # 'PDF', 'CSV', 'EXCEL', 'JSON', 'HTML'
    delivery_methods: List[str]  # ['EMAIL', 'WEBHOOK', 'S3', 'SLACK']
    recipients: Dict[str, List[str]]  # {emails: [], webhooks: [], ...}
    report_template: Optional[str] = None


class AWSAccountCreate(BaseModel):
    account_id: str = Field(..., pattern=r'^\d{12}$')
    account_name: str = Field(..., max_length=255)
    role_arn: str
    account_email: Optional[str] = None
    environment: Optional[str] = None
    business_unit: Optional[str] = None
    cost_center: Optional[str] = None
    external_id: Optional[str] = None
    cur_database: Optional[str] = None
    cur_table: Optional[str] = None
    region: str = DEFAULT_AWS_REGION


class AccountPermissionGrant(BaseModel):
    account_id: str
    user_email: str
    access_level: str  # 'read', 'write', 'admin'
    expires_at: Optional[datetime] = None


class RoleCreate(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    permissions: List[str]


class RoleAssignment(BaseModel):
    user_email: str
    role_name: str
    expires_at: Optional[datetime] = None


class DashboardCreate(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    layout: Dict[str, Any]
    widgets: List[Dict[str, Any]]
    is_public: bool = False
    tags: Optional[Dict[str, Any]] = None
    refresh_interval_seconds: int = 300


# ============================================================================
# Scheduled Reports Endpoints
# ============================================================================

@router.post("/reports/scheduled", tags=["Phase 3"])
@require_permission("create_reports")
async def create_scheduled_report(
    report: ScheduledReportCreate,
    request: Request,
    current_user: Dict = Depends(get_current_user)
):
    """Create a new scheduled report"""
    
    try:
        result = await scheduled_report_service.create_scheduled_report(
            name=report.name,
            report_type=report.report_type,
            query_params=report.query_params,
            frequency=report.frequency,
            format=report.format,
            delivery_methods=report.delivery_methods,
            recipients=report.recipients,
            created_by=current_user['email'],
            cron_expression=report.cron_expression,
            timezone=report.timezone,
            description=report.description,
            report_template=report.report_template
        )
        
        await audit_log_service.log_report_creation(
            user_id=current_user['id'],
            user_email=current_user['email'],
            report_id=result['id'],
            report_type=report.report_type,
            request=request
        )
        
        return {"status": "success", "report": result}

    except Exception as e:
        logger.error("create_scheduled_report_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=400, detail="Invalid request. Please check your input.")


@router.get("/reports/scheduled", tags=["Phase 3"])
@require_permission("view_reports")
async def list_scheduled_reports(
    current_user: Dict = Depends(get_current_user)
):
    """List all scheduled reports for current user"""
    # Implementation would query database
    return {"reports": []}


@router.get("/reports/scheduled/{report_id}/executions", tags=["Phase 3"])
@require_permission("view_reports")
async def get_report_executions(
    report_id: UUID,
    limit: int = 50,
    current_user: Dict = Depends(get_current_user)
):
    """Get execution history for a scheduled report"""
    # Implementation would query database
    return {"executions": []}


# ============================================================================
# Multi-Account Management Endpoints
# ============================================================================

@router.post("/accounts", tags=["Phase 3"])
@require_permission("manage_accounts")
async def register_aws_account(
    account: AWSAccountCreate,
    request: Request,
    current_user: Dict = Depends(get_current_user)
):
    """Register a new AWS account for cost tracking"""
    
    try:
        result = await multi_account_service.register_account(
            account_id=account.account_id,
            account_name=account.account_name,
            role_arn=account.role_arn,
            created_by=current_user['email'],
            account_email=account.account_email,
            environment=account.environment,
            business_unit=account.business_unit,
            cost_center=account.cost_center,
            external_id=account.external_id,
            cur_database=account.cur_database,
            cur_table=account.cur_table,
            region=account.region
        )
        
        await audit_log_service.log_action(
            user_id=current_user['id'],
            user_email=current_user['email'],
            action='account_registered',
            resource_type='aws_account',
            resource_id=result['id'],
            description=f"Registered account {account.account_id}",
            request=request
        )
        
        return {"status": "success", "account": result}

    except Exception as e:
        logger.error("register_aws_account_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=400, detail="Invalid request. Please check your input.")


@router.get("/accounts", tags=["Phase 3"])
async def list_aws_accounts(
    current_user: Dict = Depends(get_current_user)
):
    """List AWS accounts accessible to current user"""
    
    accounts = await multi_account_service.list_user_accounts(
        user_email=current_user['email'],
        include_all=current_user['is_admin']
    )
    
    return {"accounts": accounts}


@router.post("/accounts/{account_id}/permissions", tags=["Phase 3"])
@require_permission("manage_accounts")
async def grant_account_permission(
    account_id: str,
    permission: AccountPermissionGrant,
    request: Request,
    current_user: Dict = Depends(get_current_user)
):
    """Grant user access to an account"""
    
    try:
        await multi_account_service.grant_account_access(
            account_id=permission.account_id,
            user_email=permission.user_email,
            access_level=permission.access_level,
            granted_by=current_user['email'],
            expires_at=permission.expires_at
        )
        
        await audit_log_service.log_action(
            user_id=current_user['id'],
            user_email=current_user['email'],
            action='account_permission_granted',
            resource_type='account_permission',
            description=f"Granted {permission.access_level} access to {permission.user_email}",
            details={'account_id': account_id, 'user_email': permission.user_email},
            request=request
        )

        return {"status": "success"}

    except Exception as e:
        logger.error("grant_account_permission_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=400, detail="Invalid request. Please check your input.")


@router.get("/accounts/aggregate-costs", tags=["Phase 3"])
@require_permission("view_all_accounts")
async def aggregate_multi_account_costs(
    start_date: str,
    end_date: str,
    account_ids: Optional[List[str]] = None,
    group_by: str = 'account',
    current_user: Dict = Depends(get_current_user)
):
    """Aggregate costs across multiple accounts"""
    
    result = await multi_account_service.aggregate_costs_across_accounts(
        account_ids=account_ids,
        start_date=start_date,
        end_date=end_date,
        group_by=group_by
    )
    
    return {"aggregation": result}


# ============================================================================
# RBAC Endpoints
# ============================================================================

@router.post("/rbac/roles", tags=["Phase 3"])
@require_permission("manage_roles")
async def create_role(
    role: RoleCreate,
    request: Request,
    current_user: Dict = Depends(get_current_user)
):
    """Create a new role"""
    
    try:
        result = await rbac_service.create_role(
            name=role.name,
            permissions=role.permissions,
            description=role.description
        )
        
        await audit_log_service.log_action(
            user_id=current_user['id'],
            user_email=current_user['email'],
            action='role_created',
            resource_type='role',
            resource_id=result['id'],
            description=f"Created role {role.name}",
            request=request
        )
        
        return {"status": "success", "role": result}

    except Exception as e:
        logger.error("create_role_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=400, detail="Invalid request. Please check your input.")


@router.post("/rbac/assign", tags=["Phase 3"])
@require_permission("manage_users")
async def assign_role(
    assignment: RoleAssignment,
    request: Request,
    current_user: Dict = Depends(get_current_user)
):
    """Assign a role to a user"""
    
    try:
        # Get target user
        target_user = await rbac_service.get_user_by_email(assignment.user_email)
        
        if not target_user:
            target_user = await rbac_service.get_or_create_user(assignment.user_email)
        
        await rbac_service.assign_role_to_user(
            user_id=target_user['id'],
            role_name=assignment.role_name,
            granted_by=current_user['email'],
            expires_at=assignment.expires_at
        )
        
        await audit_log_service.log_role_assignment(
            admin_id=current_user['id'],
            admin_email=current_user['email'],
            target_user_email=assignment.user_email,
            role_name=assignment.role_name,
            request=request
        )

        return {"status": "success"}

    except Exception as e:
        logger.error("assign_role_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=400, detail="Invalid request. Please check your input.")


@router.get("/rbac/my-permissions", tags=["Phase 3"])
async def get_my_permissions(current_user: Dict = Depends(get_current_user)):
    """Get current user's permissions"""
    
    permissions = await rbac_service.get_user_permissions(current_user['id'])
    
    return {
        "user": current_user['email'],
        "is_admin": current_user['is_admin'],
        "permissions": permissions
    }


# ============================================================================
# Audit Log Endpoints
# ============================================================================

@router.get("/audit/my-activity", tags=["Phase 3"])
async def get_my_audit_trail(
    limit: int = 100,
    offset: int = 0,
    current_user: Dict = Depends(get_current_user)
):
    """Get audit trail for current user"""
    
    trail = await audit_log_service.get_user_audit_trail(
        user_email=current_user['email'],
        limit=limit,
        offset=offset
    )
    
    return {"audit_trail": trail}


@router.get("/audit/recent", tags=["Phase 3"])
@require_permission("view_audit_logs")
async def get_recent_audit_logs(
    hours: int = 24,
    action: Optional[str] = None,
    limit: int = 1000,
    current_user: Dict = Depends(get_current_user)
):
    """Get recent audit logs (admin only)"""
    
    logs = await audit_log_service.get_recent_actions(
        hours=hours,
        action_filter=action,
        limit=limit
    )
    
    return {"logs": logs}


@router.get("/audit/failed-actions", tags=["Phase 3"])
@require_permission("view_audit_logs")
async def get_failed_actions(
    hours: int = 24,
    limit: int = 100,
    current_user: Dict = Depends(get_current_user)
):
    """Get failed actions for security monitoring"""
    
    failed = await audit_log_service.get_failed_actions(
        hours=hours,
        limit=limit
    )
    
    return {"failed_actions": failed}


# ============================================================================
# Custom Dashboards Endpoints
# ============================================================================

@router.post("/dashboards", tags=["Phase 3"])
@require_permission("create_dashboards")
async def create_dashboard(
    dashboard: DashboardCreate,
    request: Request,
    current_user: Dict = Depends(get_current_user)
):
    """Create a custom dashboard"""
    
    # Implementation would save to database
    return {"status": "success", "dashboard_id": "placeholder"}


@router.get("/dashboards", tags=["Phase 3"])
async def list_dashboards(current_user: Dict = Depends(get_current_user)):
    """List dashboards accessible to current user"""
    
    # Implementation would query database
    return {"dashboards": []}
