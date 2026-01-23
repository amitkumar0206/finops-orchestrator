"""
Audit Logging Service
Tracks all user actions for security and compliance
"""

from typing import Dict, Any, Optional, List, TYPE_CHECKING
import structlog
from datetime import datetime
from uuid import UUID, uuid4
from fastapi import Request

from backend.services.database import DatabaseService

if TYPE_CHECKING:
    from backend.services.request_context import RequestContext

logger = structlog.get_logger(__name__)


class AuditLogService:
    """Service for audit logging"""
    
    def __init__(self):
        self.db = DatabaseService()
    
    async def log_action(
        self,
        user_id: Optional[UUID],
        user_email: str,
        action: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[UUID] = None,
        description: Optional[str] = None,
        status: str = 'success',
        error_message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        request: Optional[Request] = None,
        request_id: Optional[UUID] = None,
        session_id: Optional[str] = None
    ):
        """Log an action to the audit log"""
        
        # Extract request context
        ip_address = None
        user_agent = None
        
        if request:
            ip_address = request.client.host
            user_agent = request.headers.get('user-agent')
            if not request_id:
                request_id = uuid4()
        
        query = """
            INSERT INTO audit_logs (
                user_id, user_email, action, resource_type, resource_id,
                description, ip_address, user_agent, request_id, session_id,
                status, error_message, details
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13
            )
        """
        
        await self.db.execute(
            query,
            user_id, user_email, action, resource_type, resource_id,
            description, ip_address, user_agent, request_id, session_id,
            status, error_message, details
        )
        
        logger.info(
            "audit_log_created",
            user_email=user_email,
            action=action,
            resource_type=resource_type,
            status=status
        )
    
    async def log_query_execution(
        self,
        user_id: UUID,
        user_email: str,
        query: str,
        intent: str,
        execution_time_ms: int,
        result_count: int,
        request: Optional[Request] = None
    ):
        """Log a query execution"""
        
        await self.log_action(
            user_id=user_id,
            user_email=user_email,
            action='query_executed',
            description=f"Executed {intent} query",
            status='success',
            details={
                'query': query,
                'intent': intent,
                'execution_time_ms': execution_time_ms,
                'result_count': result_count
            },
            request=request
        )
    
    async def log_report_creation(
        self,
        user_id: UUID,
        user_email: str,
        report_id: UUID,
        report_type: str,
        request: Optional[Request] = None
    ):
        """Log report creation"""
        
        await self.log_action(
            user_id=user_id,
            user_email=user_email,
            action='report_created',
            resource_type='scheduled_report',
            resource_id=report_id,
            description=f"Created {report_type} report",
            status='success',
            request=request
        )
    
    async def log_access_denied(
        self,
        user_email: str,
        action: str,
        resource_type: Optional[str] = None,
        reason: Optional[str] = None,
        request: Optional[Request] = None
    ):
        """Log access denied event"""
        
        await self.log_action(
            user_id=None,
            user_email=user_email,
            action=action,
            resource_type=resource_type,
            description=f"Access denied: {reason}",
            status='denied',
            error_message=reason,
            request=request
        )
    
    async def log_account_access(
        self,
        user_id: UUID,
        user_email: str,
        account_id: str,
        access_type: str,
        request: Optional[Request] = None
    ):
        """Log multi-account access"""
        
        await self.log_action(
            user_id=user_id,
            user_email=user_email,
            action='account_accessed',
            resource_type='aws_account',
            description=f"Accessed account {account_id} for {access_type}",
            status='success',
            details={'account_id': account_id, 'access_type': access_type},
            request=request
        )
    
    async def log_role_assignment(
        self,
        admin_id: UUID,
        admin_email: str,
        target_user_email: str,
        role_name: str,
        request: Optional[Request] = None
    ):
        """Log role assignment"""
        
        await self.log_action(
            user_id=admin_id,
            user_email=admin_email,
            action='role_assigned',
            resource_type='user_role',
            description=f"Assigned {role_name} role to {target_user_email}",
            status='success',
            details={'target_user': target_user_email, 'role': role_name},
            request=request
        )
    
    async def get_user_audit_trail(
        self,
        user_email: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get audit trail for a specific user"""
        
        query = """
            SELECT action, resource_type, description, status,
                   ip_address, created_at, details
            FROM audit_logs
            WHERE user_email = $1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
        """
        
        return await self.db.fetch_all(query, user_email, limit, offset)
    
    async def get_resource_audit_trail(
        self,
        resource_type: str,
        resource_id: UUID,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get audit trail for a specific resource"""
        
        query = """
            SELECT user_email, action, description, status,
                   ip_address, created_at, details
            FROM audit_logs
            WHERE resource_type = $1 AND resource_id = $2
            ORDER BY created_at DESC
            LIMIT $3
        """
        
        return await self.db.fetch_all(query, resource_type, resource_id, limit)
    
    async def get_recent_actions(
        self,
        hours: int = 24,
        action_filter: Optional[str] = None,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """Get recent actions"""
        
        if action_filter:
            query = """
                SELECT user_email, action, resource_type, description,
                       status, created_at
                FROM audit_logs
                WHERE created_at >= NOW() - INTERVAL '%s hours'
                AND action = $1
                ORDER BY created_at DESC
                LIMIT $2
            """ % hours
            return await self.db.fetch_all(query, action_filter, limit)
        
        query = """
            SELECT user_email, action, resource_type, description,
                   status, created_at
            FROM audit_logs
            WHERE created_at >= NOW() - INTERVAL '%s hours'
            ORDER BY created_at DESC
            LIMIT $1
        """ % hours
        
        return await self.db.fetch_all(query, limit)
    
    async def get_failed_actions(
        self,
        hours: int = 24,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get failed actions for security monitoring"""

        query = """
            SELECT user_email, action, resource_type, description,
                   error_message, ip_address, created_at
            FROM audit_logs
            WHERE created_at >= NOW() - INTERVAL '%s hours'
            AND status IN ('failure', 'denied')
            ORDER BY created_at DESC
            LIMIT $1
        """ % hours

        return await self.db.fetch_all(query, limit)

    # ==================== Enhanced Logging Methods for Multi-Tenant Support ====================

    async def log_action_with_scope(
        self,
        context: "RequestContext",
        action: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[UUID] = None,
        description: Optional[str] = None,
        status: str = 'success',
        error_message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        request: Optional[Request] = None,
    ):
        """Log an action with full scope context from RequestContext"""

        scope_context = context.to_audit_context() if context else {}

        # Extract request context
        ip_address = None
        user_agent = None

        if request:
            ip_address = request.client.host if request.client else None
            user_agent = request.headers.get('user-agent')

        query = """
            INSERT INTO audit_logs (
                user_id, user_email, action, resource_type, resource_id,
                description, ip_address, user_agent, request_id, session_id,
                status, error_message, details,
                organization_id, saved_view_id, scope_context
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16
            )
        """

        await self.db.execute(
            query,
            context.user_id if context else None,
            context.user_email if context else 'anonymous',
            action,
            resource_type,
            resource_id,
            description,
            ip_address,
            user_agent,
            context.request_id if context else uuid4(),
            context.session_id if context else None,
            status,
            error_message,
            details,
            context.organization_id if context else None,
            context.active_saved_view.id if context and context.active_saved_view else None,
            scope_context,
        )

        logger.info(
            "audit_log_created_with_scope",
            user_email=context.user_email if context else 'anonymous',
            action=action,
            organization_id=str(context.organization_id) if context and context.organization_id else None,
            status=status
        )

    async def log_saved_view_created(
        self,
        context: "RequestContext",
        view_id: UUID,
        view_name: str,
        account_count: int,
        request: Optional[Request] = None
    ):
        """Log saved view creation"""

        await self.log_action_with_scope(
            context=context,
            action='saved_view_created',
            resource_type='saved_view',
            resource_id=view_id,
            description=f"Created saved view '{view_name}' with {account_count} accounts",
            status='success',
            details={
                'view_name': view_name,
                'account_count': account_count,
            },
            request=request
        )

    async def log_saved_view_updated(
        self,
        context: "RequestContext",
        view_id: UUID,
        view_name: str,
        changes: Dict[str, Any],
        request: Optional[Request] = None
    ):
        """Log saved view update"""

        await self.log_action_with_scope(
            context=context,
            action='saved_view_updated',
            resource_type='saved_view',
            resource_id=view_id,
            description=f"Updated saved view '{view_name}'",
            status='success',
            details={'changes': changes},
            request=request
        )

    async def log_saved_view_deleted(
        self,
        context: "RequestContext",
        view_id: UUID,
        view_name: str,
        request: Optional[Request] = None
    ):
        """Log saved view deletion"""

        await self.log_action_with_scope(
            context=context,
            action='saved_view_deleted',
            resource_type='saved_view',
            resource_id=view_id,
            description=f"Deleted saved view '{view_name}'",
            status='success',
            request=request
        )

    async def log_active_view_changed(
        self,
        context: "RequestContext",
        old_view_id: Optional[UUID],
        new_view_id: Optional[UUID],
        new_view_name: Optional[str],
        request: Optional[Request] = None
    ):
        """Log when user switches their active saved view"""

        await self.log_action_with_scope(
            context=context,
            action='active_view_changed',
            resource_type='user_active_view',
            resource_id=new_view_id,
            description=f"Switched to saved view '{new_view_name or 'None'}'",
            status='success',
            details={
                'old_view_id': str(old_view_id) if old_view_id else None,
                'new_view_id': str(new_view_id) if new_view_id else None,
                'new_view_name': new_view_name,
            },
            request=request
        )

    async def log_data_exported(
        self,
        context: "RequestContext",
        export_format: str,
        row_count: int,
        query_type: Optional[str] = None,
        request: Optional[Request] = None
    ):
        """Log data export with scope information"""

        await self.log_action_with_scope(
            context=context,
            action='data_exported',
            resource_type='export',
            description=f"Exported {row_count} rows in {export_format} format",
            status='success',
            details={
                'format': export_format,
                'row_count': row_count,
                'query_type': query_type,
                'allowed_account_count': len(context.allowed_account_ids) if context else 0,
            },
            request=request
        )

    async def log_query_executed_scoped(
        self,
        context: "RequestContext",
        query: str,
        intent: str,
        execution_time_ms: int,
        result_count: int,
        account_filter_enforced: bool = False,
        request: Optional[Request] = None
    ):
        """Log a scoped query execution"""

        await self.log_action_with_scope(
            context=context,
            action='query_executed_scoped',
            resource_type='query',
            description=f"Executed {intent} query (scoped to {len(context.allowed_account_ids)} accounts)",
            status='success',
            details={
                'query_preview': query[:500] if query else None,
                'intent': intent,
                'execution_time_ms': execution_time_ms,
                'result_count': result_count,
                'account_filter_enforced': account_filter_enforced,
                'scoped_account_count': len(context.allowed_account_ids) if context else 0,
            },
            request=request
        )

    async def log_scope_violation_attempt(
        self,
        context: "RequestContext",
        attempted_accounts: List[str],
        request: Optional[Request] = None
    ):
        """Log an attempt to access unauthorized accounts"""

        await self.log_action_with_scope(
            context=context,
            action='scope_violation_attempt',
            resource_type='security',
            description=f"Attempted to access {len(attempted_accounts)} unauthorized accounts",
            status='denied',
            error_message=f"Access denied to accounts: {', '.join(attempted_accounts[:5])}...",
            details={
                'attempted_accounts': attempted_accounts[:10],  # Limit to first 10
                'attempted_count': len(attempted_accounts),
            },
            request=request
        )

    async def get_organization_audit_trail(
        self,
        organization_id: UUID,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get audit trail for an organization"""

        query = """
            SELECT action, resource_type, resource_id, description, status,
                   user_email, ip_address, created_at, details, scope_context
            FROM audit_logs
            WHERE organization_id = $1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
        """

        return await self.db.fetch_all(query, organization_id, limit, offset)

    async def get_saved_view_audit_trail(
        self,
        saved_view_id: UUID,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get audit trail for a specific saved view"""

        query = """
            SELECT action, user_email, description, status, created_at, details
            FROM audit_logs
            WHERE saved_view_id = $1 OR resource_id = $1
            ORDER BY created_at DESC
            LIMIT $2
        """

        return await self.db.fetch_all(query, saved_view_id, limit)


# Global audit log service instance
audit_log_service = AuditLogService()


# Middleware for automatic audit logging
class AuditLoggingMiddleware:
    """Middleware to automatically log API requests"""
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        request = Request(scope, receive)

        # Get user email from authenticated user if available (set by AuthenticationMiddleware)
        # SECURITY: Never trust X-User-Email header - use authenticated user only
        auth_user = getattr(request.state, 'auth_user', None)
        user_email = auth_user.email if (auth_user and getattr(auth_user, 'is_authenticated', False)) else 'anonymous'
        request_id = uuid4()

        # Log request
        logger.info(
            "api_request",
            method=request.method,
            path=request.url.path,
            user_email=user_email,
            request_id=str(request_id),
            ip=request.client.host
        )

        # Process request
        await self.app(scope, receive, send)
