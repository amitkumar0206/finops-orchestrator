"""
Saved Views Service
Manages saved views for multi-tenant account scoping.
Handles CRUD operations, view switching, and expiration cleanup.
"""

from typing import Dict, Any, List, Optional
from uuid import UUID
from datetime import datetime, timedelta
import structlog

from backend.services.database import DatabaseService
from backend.services.request_context import RequestContext, SavedViewInfo

logger = structlog.get_logger(__name__)


class SavedViewsService:
    """Service for managing saved views"""

    def __init__(self):
        self.db = DatabaseService()

    async def _ensure_initialized(self):
        """Ensure database is initialized"""
        if not self.db.engine:
            await self.db.initialize()

    async def create_saved_view(
        self,
        context: RequestContext,
        name: str,
        account_ids: List[UUID],
        description: Optional[str] = None,
        default_time_range: Optional[Dict[str, Any]] = None,
        filters: Optional[Dict[str, Any]] = None,
        is_default: bool = False,
        is_personal: bool = False,
        shared_with_users: Optional[List[UUID]] = None,
        shared_with_roles: Optional[List[UUID]] = None,
        expires_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Create a new saved view.

        Args:
            context: Request context with user and org info
            name: Name of the view
            account_ids: List of aws_accounts.id UUIDs to include
            description: Optional description
            default_time_range: Optional default time range JSON
            filters: Optional additional filters JSON
            is_default: Whether this is the org default view
            is_personal: Whether this is a personal view
            shared_with_users: List of user UUIDs to share with
            shared_with_roles: List of role UUIDs to share with
            expires_at: Optional expiration timestamp

        Returns:
            Created view details
        """
        await self._ensure_initialized()

        if not context.organization_id:
            raise ValueError("Organization context required to create saved view")

        # Calculate expiration if org has default expiration
        if expires_at is None and context.organization_info:
            exp_days = context.organization_info.saved_view_default_expiration_days
            if exp_days:
                expires_at = datetime.utcnow() + timedelta(days=exp_days)

        async with self.db.engine.begin() as conn:
            # If setting as default, unset any existing default
            if is_default:
                await conn.execute(
                    """
                    UPDATE saved_views
                    SET is_default = false, updated_at = NOW()
                    WHERE organization_id = :org_id AND is_default = true
                    """,
                    {'org_id': context.organization_id}
                )

            # Create the view
            result = await conn.execute(
                """
                INSERT INTO saved_views (
                    organization_id, name, description, created_by,
                    account_ids, default_time_range, filters,
                    is_default, is_personal, shared_with_users, shared_with_roles,
                    expires_at
                ) VALUES (
                    :org_id, :name, :description, :user_id,
                    :account_ids, :time_range, :filters,
                    :is_default, :is_personal, :shared_users, :shared_roles,
                    :expires_at
                )
                RETURNING id, created_at
                """,
                {
                    'org_id': context.organization_id,
                    'name': name,
                    'description': description,
                    'user_id': context.user_id,
                    'account_ids': account_ids,
                    'time_range': default_time_range,
                    'filters': filters or {},
                    'is_default': is_default,
                    'is_personal': is_personal,
                    'shared_users': shared_with_users,
                    'shared_roles': shared_with_roles,
                    'expires_at': expires_at,
                }
            )
            row = result.mappings().first()

            logger.info(
                "saved_view_created",
                view_id=str(row['id']),
                name=name,
                org_id=str(context.organization_id),
                created_by=context.user_email,
                account_count=len(account_ids),
            )

            return {
                'id': row['id'],
                'name': name,
                'description': description,
                'account_ids': account_ids,
                'default_time_range': default_time_range,
                'filters': filters or {},
                'is_default': is_default,
                'is_personal': is_personal,
                'expires_at': expires_at.isoformat() if expires_at else None,
                'created_at': row['created_at'].isoformat(),
                'created_by': str(context.user_id),
            }

    async def update_saved_view(
        self,
        context: RequestContext,
        view_id: UUID,
        name: Optional[str] = None,
        description: Optional[str] = None,
        account_ids: Optional[List[UUID]] = None,
        default_time_range: Optional[Dict[str, Any]] = None,
        filters: Optional[Dict[str, Any]] = None,
        is_default: Optional[bool] = None,
        shared_with_users: Optional[List[UUID]] = None,
        shared_with_roles: Optional[List[UUID]] = None,
        expires_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Update an existing saved view"""
        await self._ensure_initialized()

        if not context.organization_id:
            raise ValueError("Organization context required")

        async with self.db.engine.begin() as conn:
            # Verify ownership/access
            view = await self._get_view_with_access_check(conn, context, view_id)
            if not view:
                raise ValueError("View not found or access denied")

            # Build update fields
            updates = []
            params = {'view_id': view_id, 'org_id': context.organization_id}

            if name is not None:
                updates.append("name = :name")
                params['name'] = name
            if description is not None:
                updates.append("description = :description")
                params['description'] = description
            if account_ids is not None:
                updates.append("account_ids = :account_ids")
                params['account_ids'] = account_ids
            if default_time_range is not None:
                updates.append("default_time_range = :time_range")
                params['time_range'] = default_time_range
            if filters is not None:
                updates.append("filters = :filters")
                params['filters'] = filters
            if shared_with_users is not None:
                updates.append("shared_with_users = :shared_users")
                params['shared_users'] = shared_with_users
            if shared_with_roles is not None:
                updates.append("shared_with_roles = :shared_roles")
                params['shared_roles'] = shared_with_roles
            if expires_at is not None:
                updates.append("expires_at = :expires_at")
                params['expires_at'] = expires_at

            if is_default is True:
                # Unset existing default first
                await conn.execute(
                    """
                    UPDATE saved_views
                    SET is_default = false, updated_at = NOW()
                    WHERE organization_id = :org_id AND is_default = true AND id != :view_id
                    """,
                    {'org_id': context.organization_id, 'view_id': view_id}
                )
                updates.append("is_default = true")
            elif is_default is False:
                updates.append("is_default = false")

            updates.append("updated_at = NOW()")

            await conn.execute(
                f"""
                UPDATE saved_views
                SET {', '.join(updates)}
                WHERE id = :view_id AND organization_id = :org_id
                """,
                params
            )

            logger.info(
                "saved_view_updated",
                view_id=str(view_id),
                org_id=str(context.organization_id),
                updated_by=context.user_email,
            )

            return await self.get_saved_view(context, view_id)

    async def delete_saved_view(
        self,
        context: RequestContext,
        view_id: UUID,
    ) -> bool:
        """Delete (soft-delete) a saved view"""
        await self._ensure_initialized()

        if not context.organization_id:
            raise ValueError("Organization context required")

        async with self.db.engine.begin() as conn:
            # Verify ownership/access
            view = await self._get_view_with_access_check(conn, context, view_id)
            if not view:
                raise ValueError("View not found or access denied")

            # Soft delete
            await conn.execute(
                """
                UPDATE saved_views
                SET is_active = false, updated_at = NOW()
                WHERE id = :view_id AND organization_id = :org_id
                """,
                {'view_id': view_id, 'org_id': context.organization_id}
            )

            # Remove from any user's active view
            await conn.execute(
                """
                UPDATE user_active_views
                SET saved_view_id = NULL, updated_at = NOW()
                WHERE saved_view_id = :view_id
                """,
                {'view_id': view_id}
            )

            logger.info(
                "saved_view_deleted",
                view_id=str(view_id),
                org_id=str(context.organization_id),
                deleted_by=context.user_email,
            )

            return True

    async def list_saved_views(
        self,
        context: RequestContext,
        include_personal: bool = True,
        include_shared: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        List saved views accessible by the user.
        Includes: org defaults, personal views, and shared views.
        """
        await self._ensure_initialized()

        if not context.organization_id:
            return []

        async with self.db.engine.begin() as conn:
            result = await conn.execute(
                """
                SELECT
                    sv.id, sv.name, sv.description, sv.created_by,
                    sv.account_ids, sv.default_time_range, sv.filters,
                    sv.is_default, sv.is_personal,
                    sv.shared_with_users, sv.shared_with_roles,
                    sv.expires_at, sv.created_at, sv.updated_at,
                    u.email as created_by_email
                FROM saved_views sv
                LEFT JOIN users u ON u.id = sv.created_by
                WHERE sv.organization_id = :org_id
                  AND sv.is_active = true
                  AND (sv.expires_at IS NULL OR sv.expires_at > NOW())
                  AND (
                      -- Org default views visible to all
                      sv.is_default = true
                      -- Personal views created by user
                      OR (sv.is_personal = true AND sv.created_by = :user_id AND :include_personal)
                      -- Views shared with user
                      OR (:user_id = ANY(sv.shared_with_users) AND :include_shared)
                      -- Views shared with user's roles (would need role check)
                      OR (sv.is_personal = false AND sv.is_default = false AND :include_shared)
                  )
                ORDER BY sv.is_default DESC, sv.name ASC
                """,
                {
                    'org_id': context.organization_id,
                    'user_id': context.user_id,
                    'include_personal': include_personal,
                    'include_shared': include_shared,
                }
            )
            rows = result.mappings().all()

            return [
                {
                    'id': str(row['id']),
                    'name': row['name'],
                    'description': row['description'],
                    'account_ids': [str(aid) for aid in (row['account_ids'] or [])],
                    'account_count': len(row['account_ids'] or []),
                    'default_time_range': row['default_time_range'],
                    'filters': row['filters'],
                    'is_default': row['is_default'],
                    'is_personal': row['is_personal'],
                    'expires_at': row['expires_at'].isoformat() if row['expires_at'] else None,
                    'created_at': row['created_at'].isoformat() if row['created_at'] else None,
                    'created_by': str(row['created_by']) if row['created_by'] else None,
                    'created_by_email': row['created_by_email'],
                }
                for row in rows
            ]

    async def get_saved_view(
        self,
        context: RequestContext,
        view_id: UUID,
    ) -> Optional[Dict[str, Any]]:
        """Get a specific saved view by ID"""
        await self._ensure_initialized()

        if not context.organization_id:
            return None

        async with self.db.engine.begin() as conn:
            result = await conn.execute(
                """
                SELECT
                    sv.id, sv.name, sv.description, sv.created_by,
                    sv.account_ids, sv.default_time_range, sv.filters,
                    sv.is_default, sv.is_personal,
                    sv.shared_with_users, sv.shared_with_roles,
                    sv.expires_at, sv.created_at, sv.updated_at,
                    u.email as created_by_email
                FROM saved_views sv
                LEFT JOIN users u ON u.id = sv.created_by
                WHERE sv.id = :view_id
                  AND sv.organization_id = :org_id
                  AND sv.is_active = true
                """,
                {'view_id': view_id, 'org_id': context.organization_id}
            )
            row = result.mappings().first()

            if not row:
                return None

            return {
                'id': str(row['id']),
                'name': row['name'],
                'description': row['description'],
                'account_ids': [str(aid) for aid in (row['account_ids'] or [])],
                'account_count': len(row['account_ids'] or []),
                'default_time_range': row['default_time_range'],
                'filters': row['filters'],
                'is_default': row['is_default'],
                'is_personal': row['is_personal'],
                'shared_with_users': [str(uid) for uid in (row['shared_with_users'] or [])],
                'shared_with_roles': [str(rid) for rid in (row['shared_with_roles'] or [])],
                'expires_at': row['expires_at'].isoformat() if row['expires_at'] else None,
                'created_at': row['created_at'].isoformat() if row['created_at'] else None,
                'updated_at': row['updated_at'].isoformat() if row['updated_at'] else None,
                'created_by': str(row['created_by']) if row['created_by'] else None,
                'created_by_email': row['created_by_email'],
            }

    async def get_active_view(
        self,
        context: RequestContext,
    ) -> Optional[Dict[str, Any]]:
        """Get the user's currently active view"""
        await self._ensure_initialized()

        if not context.organization_id:
            return None

        async with self.db.engine.begin() as conn:
            result = await conn.execute(
                """
                SELECT sv.id
                FROM saved_views sv
                JOIN user_active_views uav ON uav.saved_view_id = sv.id
                WHERE uav.user_id = :user_id
                  AND sv.organization_id = :org_id
                  AND sv.is_active = true
                  AND (sv.expires_at IS NULL OR sv.expires_at > NOW())
                """,
                {'user_id': context.user_id, 'org_id': context.organization_id}
            )
            row = result.mappings().first()

            if row:
                return await self.get_saved_view(context, row['id'])

            # Return org default if no active view
            result = await conn.execute(
                """
                SELECT id
                FROM saved_views
                WHERE organization_id = :org_id
                  AND is_default = true
                  AND is_active = true
                  AND (expires_at IS NULL OR expires_at > NOW())
                """,
                {'org_id': context.organization_id}
            )
            default_row = result.mappings().first()

            if default_row:
                return await self.get_saved_view(context, default_row['id'])

            return None

    async def set_active_view(
        self,
        context: RequestContext,
        view_id: Optional[UUID],
    ) -> bool:
        """Set the user's active view"""
        await self._ensure_initialized()

        if not context.organization_id:
            raise ValueError("Organization context required")

        async with self.db.engine.begin() as conn:
            if view_id:
                # Verify view exists and is accessible
                view = await self._get_view_with_access_check(conn, context, view_id)
                if not view:
                    raise ValueError("View not found or access denied")

            # Upsert active view
            await conn.execute(
                """
                INSERT INTO user_active_views (user_id, saved_view_id, updated_at)
                VALUES (:user_id, :view_id, NOW())
                ON CONFLICT (user_id)
                DO UPDATE SET saved_view_id = :view_id, updated_at = NOW()
                """,
                {'user_id': context.user_id, 'view_id': view_id}
            )

            logger.info(
                "active_view_changed",
                user_id=str(context.user_id),
                view_id=str(view_id) if view_id else None,
                org_id=str(context.organization_id),
            )

            return True

    async def cleanup_expired_views(self) -> int:
        """
        Background job to mark expired views as inactive.
        Returns count of views cleaned up.
        """
        await self._ensure_initialized()

        async with self.db.engine.begin() as conn:
            # Mark expired views as inactive
            result = await conn.execute(
                """
                UPDATE saved_views
                SET is_active = false, updated_at = NOW()
                WHERE expires_at IS NOT NULL
                  AND expires_at <= NOW()
                  AND is_active = true
                RETURNING id
                """
            )
            expired_rows = result.fetchall()
            expired_count = len(expired_rows)

            if expired_count > 0:
                expired_ids = [row[0] for row in expired_rows]

                # Clear from user active views
                await conn.execute(
                    """
                    UPDATE user_active_views
                    SET saved_view_id = NULL, updated_at = NOW()
                    WHERE saved_view_id = ANY(:view_ids)
                    """,
                    {'view_ids': expired_ids}
                )

                logger.info(
                    "expired_views_cleaned",
                    count=expired_count,
                    view_ids=[str(vid) for vid in expired_ids],
                )

            return expired_count

    async def _get_view_with_access_check(
        self,
        conn,
        context: RequestContext,
        view_id: UUID,
    ) -> Optional[Dict[str, Any]]:
        """Check if user has access to modify a view"""
        result = await conn.execute(
            """
            SELECT id, created_by, is_personal, is_default
            FROM saved_views
            WHERE id = :view_id
              AND organization_id = :org_id
              AND is_active = true
            """,
            {'view_id': view_id, 'org_id': context.organization_id}
        )
        row = result.mappings().first()

        if not row:
            return None

        # Admins can edit any view
        if context.is_admin or context.org_role in ('owner', 'admin'):
            return dict(row)

        # Users can only edit their own personal views
        if row['is_personal'] and row['created_by'] == context.user_id:
            return dict(row)

        return None


# Global service instance
saved_views_service = SavedViewsService()
