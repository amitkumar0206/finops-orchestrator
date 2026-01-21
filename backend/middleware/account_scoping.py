"""
Account Scoping Middleware

Loads organization and saved view context from the database based on
the authenticated user, and attaches RequestContext to each request
for account-level scoping.

NOTE: This middleware runs AFTER the AuthenticationMiddleware, which
validates the JWT token and attaches the authenticated user info to
request.state.auth_user. This middleware uses that authenticated user
to load the full context from the database.
"""

from typing import Optional
from uuid import UUID, uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
import structlog

from backend.services.request_context import (
    RequestContext,
    SavedViewInfo,
    OrganizationInfo,
    create_empty_context,
)
from backend.services.database import DatabaseService
from backend.middleware.authentication import AuthenticatedUser, AnonymousUser

logger = structlog.get_logger(__name__)


class AccountScopingMiddleware(BaseHTTPMiddleware):
    """
    Middleware that loads account scoping context from the database.

    This middleware runs AFTER AuthenticationMiddleware and uses the
    authenticated user (from request.state.auth_user) to load the full
    context from the database.

    Flow:
    1. Get authenticated user from request.state.auth_user (set by AuthenticationMiddleware)
    2. Load user from database
    3. Load user's organization and active saved view
    4. Compute effective account scope
    5. Attach RequestContext to request.state.context
    """

    # Paths that should skip scoping (health checks, metrics, docs)
    SKIP_PATHS = {
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

    def __init__(self, app, db_service: Optional[DatabaseService] = None):
        super().__init__(app)
        self.db_service = db_service

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip scoping for health/metrics/auth endpoints
        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)

        # Generate request ID
        request_id = uuid4()

        try:
            # Get authenticated user from AuthenticationMiddleware
            auth_user = getattr(request.state, 'auth_user', None)

            # If no auth_user or anonymous, attach empty context
            if not auth_user or isinstance(auth_user, AnonymousUser) or not auth_user.is_authenticated:
                request.state.context = create_empty_context()
                request.state.request_id = request_id
                return await call_next(request)

            # Get user email from authenticated user (validated by JWT)
            user_email = auth_user.email

            if not user_email:
                # This shouldn't happen with valid JWT, but handle defensively
                request.state.context = create_empty_context()
                request.state.request_id = request_id
                return await call_next(request)

            # Load full context from database
            context = await self._load_user_context(user_email, request_id)
            request.state.context = context
            request.state.request_id = request_id

            logger.debug(
                "request_context_loaded",
                user_email=user_email,
                auth_type=auth_user.token_type,
                organization_id=str(context.organization_id) if context.organization_id else None,
                account_count=len(context.allowed_account_ids),
                has_active_view=context.active_saved_view is not None,
                request_id=str(request_id),
            )

        except Exception as e:
            logger.error(
                "failed_to_load_request_context",
                error=str(e),
                request_id=str(request_id),
                exc_info=True,
            )
            # On error, attach empty context to avoid breaking the request
            request.state.context = create_empty_context(user_email or 'anonymous')
            request.state.request_id = request_id

        return await call_next(request)

    async def _load_user_context(self, user_email: str, request_id: UUID) -> RequestContext:
        """Load user context from database"""

        db = self.db_service or DatabaseService()
        if not db.engine:
            await db.initialize()

        async with db.engine.begin() as conn:
            # Load user
            user_result = await conn.execute(
                """
                SELECT id, email, full_name, is_admin, default_organization_id
                FROM users
                WHERE email = :email AND is_active = true
                """,
                {'email': user_email}
            )
            user_row = user_result.mappings().first()

            if not user_row:
                # User not found - return empty context
                logger.warning("user_not_found", email=user_email)
                return create_empty_context(user_email)

            user_id = user_row['id']
            is_admin = user_row['is_admin']
            default_org_id = user_row['default_organization_id']

            # Load organization membership and determine current org
            org_result = await conn.execute(
                """
                SELECT
                    o.id, o.name, o.slug, o.subscription_tier, o.settings,
                    o.saved_view_default_expiration_days,
                    om.role as org_role
                FROM organizations o
                JOIN organization_members om ON om.organization_id = o.id
                WHERE om.user_id = :user_id
                  AND o.is_active = true
                ORDER BY
                    CASE WHEN o.id = :default_org_id THEN 0 ELSE 1 END,
                    om.joined_at ASC
                LIMIT 1
                """,
                {'user_id': user_id, 'default_org_id': default_org_id}
            )
            org_row = org_result.mappings().first()

            organization_info = None
            organization_id = None
            organization_name = None
            org_role = 'member'

            if org_row:
                organization_id = org_row['id']
                organization_name = org_row['name']
                org_role = org_row['org_role'] or 'member'
                organization_info = OrganizationInfo(
                    id=org_row['id'],
                    name=org_row['name'],
                    slug=org_row['slug'],
                    subscription_tier=org_row['subscription_tier'] or 'standard',
                    settings=org_row['settings'] or {},
                    saved_view_default_expiration_days=org_row['saved_view_default_expiration_days'],
                )

            # Load active saved view for user
            active_view = None
            effective_time_range = None
            effective_filters = None

            if organization_id:
                view_result = await conn.execute(
                    """
                    SELECT sv.id, sv.name, sv.account_ids, sv.default_time_range,
                           sv.filters, sv.is_personal, sv.expires_at
                    FROM saved_views sv
                    JOIN user_active_views uav ON uav.saved_view_id = sv.id
                    WHERE uav.user_id = :user_id
                      AND sv.organization_id = :org_id
                      AND sv.is_active = true
                      AND (sv.expires_at IS NULL OR sv.expires_at > NOW())
                    """,
                    {'user_id': user_id, 'org_id': organization_id}
                )
                view_row = view_result.mappings().first()

                if view_row:
                    active_view = SavedViewInfo(
                        id=view_row['id'],
                        name=view_row['name'],
                        account_ids=view_row['account_ids'] or [],
                        default_time_range=view_row['default_time_range'],
                        filters=view_row['filters'] or {},
                        is_personal=view_row['is_personal'] or False,
                        expires_at=view_row['expires_at'],
                    )
                    effective_time_range = view_row['default_time_range']
                    effective_filters = view_row['filters']

            # Load allowed account IDs
            allowed_account_ids = await self._load_allowed_accounts(
                conn, user_id, organization_id, active_view, is_admin
            )

            return RequestContext(
                user_id=user_id,
                user_email=user_email,
                is_admin=is_admin,
                organization_id=organization_id,
                organization_name=organization_name,
                organization_info=organization_info,
                allowed_account_ids=allowed_account_ids,
                active_saved_view=active_view,
                effective_time_range=effective_time_range,
                effective_filters=effective_filters,
                org_role=org_role,
                request_id=request_id,
            )

    async def _load_allowed_accounts(
        self,
        conn,
        user_id: UUID,
        organization_id: Optional[UUID],
        active_view: Optional[SavedViewInfo],
        is_admin: bool,
    ) -> list[str]:
        """
        Load the list of AWS account IDs the user is allowed to access.

        Priority:
        1. If active view has account_ids, use those (intersected with permissions)
        2. Otherwise, use all accounts from organization that user has permission for
        3. Admins can access all accounts in their organization
        """

        if not organization_id:
            return []

        if active_view and active_view.account_ids:
            # Get AWS account IDs for the view's account_ids (UUIDs)
            view_account_uuids = active_view.account_ids
            if not view_account_uuids:
                return []

            # Load account IDs for view's selected accounts
            result = await conn.execute(
                """
                SELECT aa.account_id
                FROM aws_accounts aa
                WHERE aa.id = ANY(:account_uuids)
                  AND aa.tenant_org_id = :org_id
                  AND aa.status = 'ACTIVE'
                """,
                {'account_uuids': view_account_uuids, 'org_id': organization_id}
            )
            rows = result.mappings().all()

            # If not admin, intersect with user's permissions
            if not is_admin:
                perm_result = await conn.execute(
                    """
                    SELECT aa.account_id
                    FROM aws_accounts aa
                    JOIN account_permissions ap ON ap.account_id = aa.id
                    WHERE ap.user_email = (SELECT email FROM users WHERE id = :user_id)
                      AND aa.tenant_org_id = :org_id
                      AND aa.status = 'ACTIVE'
                      AND (ap.expires_at IS NULL OR ap.expires_at > NOW())
                    """,
                    {'user_id': user_id, 'org_id': organization_id}
                )
                user_permitted = {r['account_id'] for r in perm_result.mappings().all()}
                return [r['account_id'] for r in rows if r['account_id'] in user_permitted]

            return [r['account_id'] for r in rows]

        # No active view - load all accounts user can access
        if is_admin:
            # Admin can access all org accounts
            result = await conn.execute(
                """
                SELECT account_id
                FROM aws_accounts
                WHERE tenant_org_id = :org_id AND status = 'ACTIVE'
                """,
                {'org_id': organization_id}
            )
        else:
            # Regular user - only permitted accounts
            result = await conn.execute(
                """
                SELECT aa.account_id
                FROM aws_accounts aa
                JOIN account_permissions ap ON ap.account_id = aa.id
                WHERE ap.user_email = (SELECT email FROM users WHERE id = :user_id)
                  AND aa.tenant_org_id = :org_id
                  AND aa.status = 'ACTIVE'
                  AND (ap.expires_at IS NULL OR ap.expires_at > NOW())
                """,
                {'user_id': user_id, 'org_id': organization_id}
            )

        rows = result.mappings().all()
        return [r['account_id'] for r in rows]
