"""
Organization Service
Manages organizations for multi-tenant support.
Handles CRUD operations, membership management, and organization switching.
"""

from typing import Dict, Any, List, Optional
from uuid import UUID
import re
import structlog

from backend.services.database import DatabaseService
from backend.services.request_context import RequestContext
from backend.services.rbac_permission_service import get_rbac_service

logger = structlog.get_logger(__name__)


def generate_slug(name: str) -> str:
    """Generate URL-friendly slug from organization name"""
    slug = name.lower().strip()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s_-]+', '-', slug)
    slug = slug.strip('-')
    return slug[:100]


class OrganizationService:
    """Service for managing organizations"""

    def __init__(self):
        self.db = DatabaseService()

    async def _ensure_initialized(self):
        """Ensure database is initialized"""
        if not self.db.engine:
            await self.db.initialize()

    async def create_organization(
        self,
        name: str,
        owner_user_id: UUID,
        slug: Optional[str] = None,
        subscription_tier: str = 'standard',
        settings: Optional[Dict[str, Any]] = None,
        max_users: int = 50,
        max_accounts: int = 100,
        saved_view_default_expiration_days: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Create a new organization.

        Args:
            name: Organization name
            owner_user_id: UUID of the user who will own the org
            slug: URL-friendly identifier (auto-generated if not provided)
            subscription_tier: 'free', 'standard', 'enterprise'
            settings: Organization settings JSON
            max_users: Maximum allowed users
            max_accounts: Maximum allowed AWS accounts
            saved_view_default_expiration_days: Default view expiration

        Returns:
            Created organization details
        """
        await self._ensure_initialized()

        if not slug:
            slug = generate_slug(name)

        async with self.db.engine.begin() as conn:
            # Check if slug already exists
            existing = await conn.execute(
                "SELECT id FROM organizations WHERE slug = :slug",
                {'slug': slug}
            )
            if existing.mappings().first():
                # Add random suffix to make unique
                import secrets
                slug = f"{slug}-{secrets.token_hex(3)}"

            # Create organization
            result = await conn.execute(
                """
                INSERT INTO organizations (
                    name, slug, subscription_tier, settings,
                    max_users, max_accounts, saved_view_default_expiration_days
                ) VALUES (
                    :name, :slug, :tier, :settings,
                    :max_users, :max_accounts, :exp_days
                )
                RETURNING id, created_at
                """,
                {
                    'name': name,
                    'slug': slug,
                    'tier': subscription_tier,
                    'settings': settings or {},
                    'max_users': max_users,
                    'max_accounts': max_accounts,
                    'exp_days': saved_view_default_expiration_days,
                }
            )
            org_row = result.mappings().first()
            org_id = org_row['id']

            # Add owner as member with 'owner' role
            await conn.execute(
                """
                INSERT INTO organization_members (organization_id, user_id, role)
                VALUES (:org_id, :user_id, 'owner')
                """,
                {'org_id': org_id, 'user_id': owner_user_id}
            )

            # Set as user's default organization if they don't have one
            await conn.execute(
                """
                UPDATE users
                SET default_organization_id = :org_id
                WHERE id = :user_id AND default_organization_id IS NULL
                """,
                {'org_id': org_id, 'user_id': owner_user_id}
            )

            logger.info(
                "organization_created",
                org_id=str(org_id),
                name=name,
                slug=slug,
                owner_id=str(owner_user_id),
            )

            return {
                'id': str(org_id),
                'name': name,
                'slug': slug,
                'subscription_tier': subscription_tier,
                'settings': settings or {},
                'max_users': max_users,
                'max_accounts': max_accounts,
                'saved_view_default_expiration_days': saved_view_default_expiration_days,
                'created_at': org_row['created_at'].isoformat(),
            }

    async def get_user_organizations(
        self,
        user_id: UUID,
    ) -> List[Dict[str, Any]]:
        """Get all organizations a user belongs to"""
        await self._ensure_initialized()

        async with self.db.engine.begin() as conn:
            result = await conn.execute(
                """
                SELECT
                    o.id, o.name, o.slug, o.subscription_tier, o.settings,
                    o.max_users, o.max_accounts, o.saved_view_default_expiration_days,
                    o.created_at,
                    om.role as user_role,
                    om.joined_at,
                    u.default_organization_id
                FROM organizations o
                JOIN organization_members om ON om.organization_id = o.id
                JOIN users u ON u.id = om.user_id
                WHERE om.user_id = :user_id AND o.is_active = true
                ORDER BY o.name ASC
                """,
                {'user_id': user_id}
            )
            rows = result.mappings().all()

            return [
                {
                    'id': str(row['id']),
                    'name': row['name'],
                    'slug': row['slug'],
                    'subscription_tier': row['subscription_tier'],
                    'settings': row['settings'],
                    'max_users': row['max_users'],
                    'max_accounts': row['max_accounts'],
                    'saved_view_default_expiration_days': row['saved_view_default_expiration_days'],
                    'created_at': row['created_at'].isoformat() if row['created_at'] else None,
                    'user_role': row['user_role'],
                    'joined_at': row['joined_at'].isoformat() if row['joined_at'] else None,
                    'is_default': row['id'] == row['default_organization_id'],
                }
                for row in rows
            ]

    async def get_organization(
        self,
        org_id: UUID,
    ) -> Optional[Dict[str, Any]]:
        """Get organization by ID"""
        await self._ensure_initialized()

        async with self.db.engine.begin() as conn:
            result = await conn.execute(
                """
                SELECT
                    o.id, o.name, o.slug, o.subscription_tier, o.settings,
                    o.max_users, o.max_accounts, o.saved_view_default_expiration_days,
                    o.is_active, o.created_at, o.updated_at,
                    COUNT(DISTINCT om.user_id) as member_count,
                    COUNT(DISTINCT aa.id) as account_count
                FROM organizations o
                LEFT JOIN organization_members om ON om.organization_id = o.id
                LEFT JOIN aws_accounts aa ON aa.tenant_org_id = o.id AND aa.status = 'ACTIVE'
                WHERE o.id = :org_id
                GROUP BY o.id
                """,
                {'org_id': org_id}
            )
            row = result.mappings().first()

            if not row:
                return None

            return {
                'id': str(row['id']),
                'name': row['name'],
                'slug': row['slug'],
                'subscription_tier': row['subscription_tier'],
                'settings': row['settings'],
                'max_users': row['max_users'],
                'max_accounts': row['max_accounts'],
                'saved_view_default_expiration_days': row['saved_view_default_expiration_days'],
                'is_active': row['is_active'],
                'created_at': row['created_at'].isoformat() if row['created_at'] else None,
                'updated_at': row['updated_at'].isoformat() if row['updated_at'] else None,
                'member_count': row['member_count'],
                'account_count': row['account_count'],
            }

    async def get_current_organization(
        self,
        context: RequestContext,
    ) -> Optional[Dict[str, Any]]:
        """Get the user's current organization from context"""
        if not context.organization_id:
            return None
        return await self.get_organization(context.organization_id)

    async def switch_organization(
        self,
        user_id: UUID,
        org_id: UUID,
    ) -> bool:
        """
        Switch user's default organization.
        Verifies user is a member of the target organization.
        """
        await self._ensure_initialized()

        async with self.db.engine.begin() as conn:
            # Verify membership
            member_check = await conn.execute(
                """
                SELECT 1 FROM organization_members
                WHERE user_id = :user_id AND organization_id = :org_id
                """,
                {'user_id': user_id, 'org_id': org_id}
            )
            if not member_check.mappings().first():
                raise ValueError("User is not a member of this organization")

            # Update default org
            await conn.execute(
                """
                UPDATE users
                SET default_organization_id = :org_id, updated_at = NOW()
                WHERE id = :user_id
                """,
                {'org_id': org_id, 'user_id': user_id}
            )

            logger.info(
                "organization_switched",
                user_id=str(user_id),
                org_id=str(org_id),
            )

            return True

    async def add_member(
        self,
        context: RequestContext,
        user_email: str,
        role: str = 'member',
    ) -> Dict[str, Any]:
        """
        Add a user to the organization.
        Requires admin/owner role in the org.
        """
        await self._ensure_initialized()

        if not context.organization_id:
            raise ValueError("Organization context required")

        rbac = get_rbac_service()
        rbac.require_permission(
            context,
            "organization:manage_members",
            error_message="Admin access required to add members"
        )

        if role not in ('owner', 'admin', 'member', 'viewer'):
            raise ValueError("Invalid role")

        async with self.db.engine.begin() as conn:
            # Find user by email
            user_result = await conn.execute(
                "SELECT id, email FROM users WHERE email = :email",
                {'email': user_email}
            )
            user_row = user_result.mappings().first()

            if not user_row:
                raise ValueError(f"User with email {user_email} not found")

            target_user_id = user_row['id']

            # Check if already a member
            existing = await conn.execute(
                """
                SELECT id FROM organization_members
                WHERE organization_id = :org_id AND user_id = :user_id
                """,
                {'org_id': context.organization_id, 'user_id': target_user_id}
            )
            if existing.mappings().first():
                raise ValueError("User is already a member of this organization")

            # Check member limit
            org = await self.get_organization(context.organization_id)
            if org and org['member_count'] >= org['max_users']:
                raise ValueError("Organization has reached maximum member limit")

            # Add member
            await conn.execute(
                """
                INSERT INTO organization_members (organization_id, user_id, role, invited_by)
                VALUES (:org_id, :user_id, :role, :invited_by)
                """,
                {
                    'org_id': context.organization_id,
                    'user_id': target_user_id,
                    'role': role,
                    'invited_by': context.user_id,
                }
            )

            logger.info(
                "organization_member_added",
                org_id=str(context.organization_id),
                user_email=user_email,
                role=role,
                added_by=context.user_email,
            )

            return {
                'user_id': str(target_user_id),
                'email': user_email,
                'role': role,
                'organization_id': str(context.organization_id),
            }

    async def remove_member(
        self,
        context: RequestContext,
        user_id: UUID,
    ) -> bool:
        """Remove a user from the organization"""
        await self._ensure_initialized()

        if not context.organization_id:
            raise ValueError("Organization context required")

        rbac = get_rbac_service()
        rbac.require_permission(
            context,
            "organization:manage_members",
            error_message="Admin access required to remove members"
        )

        async with self.db.engine.begin() as conn:
            # Cannot remove the last owner
            owner_count = await conn.execute(
                """
                SELECT COUNT(*) as cnt FROM organization_members
                WHERE organization_id = :org_id AND role = 'owner'
                """,
                {'org_id': context.organization_id}
            )
            owner_row = owner_count.mappings().first()

            target_role = await conn.execute(
                """
                SELECT role FROM organization_members
                WHERE organization_id = :org_id AND user_id = :user_id
                """,
                {'org_id': context.organization_id, 'user_id': user_id}
            )
            target_row = target_role.mappings().first()

            if target_row and target_row['role'] == 'owner' and owner_row['cnt'] <= 1:
                raise ValueError("Cannot remove the last owner of an organization")

            # Remove member
            await conn.execute(
                """
                DELETE FROM organization_members
                WHERE organization_id = :org_id AND user_id = :user_id
                """,
                {'org_id': context.organization_id, 'user_id': user_id}
            )

            # Clear default org if this was user's default
            await conn.execute(
                """
                UPDATE users
                SET default_organization_id = NULL
                WHERE id = :user_id AND default_organization_id = :org_id
                """,
                {'user_id': user_id, 'org_id': context.organization_id}
            )

            logger.info(
                "organization_member_removed",
                org_id=str(context.organization_id),
                user_id=str(user_id),
                removed_by=context.user_email,
            )

            return True

    async def update_member_role(
        self,
        context: RequestContext,
        user_id: UUID,
        new_role: str,
    ) -> bool:
        """Update a member's role within the organization"""
        await self._ensure_initialized()

        if not context.organization_id:
            raise ValueError("Organization context required")

        rbac = get_rbac_service()
        rbac.require_permission(
            context,
            "organization:change_roles",
            error_message="Owner access required to change roles"
        )

        if new_role not in ('owner', 'admin', 'member', 'viewer'):
            raise ValueError("Invalid role")

        async with self.db.engine.begin() as conn:
            # If demoting the last owner, prevent it
            if new_role != 'owner':
                current_role = await conn.execute(
                    """
                    SELECT role FROM organization_members
                    WHERE organization_id = :org_id AND user_id = :user_id
                    """,
                    {'org_id': context.organization_id, 'user_id': user_id}
                )
                current_row = current_role.mappings().first()

                if current_row and current_row['role'] == 'owner':
                    owner_count = await conn.execute(
                        """
                        SELECT COUNT(*) as cnt FROM organization_members
                        WHERE organization_id = :org_id AND role = 'owner'
                        """,
                        {'org_id': context.organization_id}
                    )
                    if owner_count.mappings().first()['cnt'] <= 1:
                        raise ValueError("Cannot demote the last owner")

            await conn.execute(
                """
                UPDATE organization_members
                SET role = :role
                WHERE organization_id = :org_id AND user_id = :user_id
                """,
                {'org_id': context.organization_id, 'user_id': user_id, 'role': new_role}
            )

            logger.info(
                "organization_member_role_updated",
                org_id=str(context.organization_id),
                user_id=str(user_id),
                new_role=new_role,
                updated_by=context.user_email,
            )

            return True

    async def list_members(
        self,
        context: RequestContext,
    ) -> List[Dict[str, Any]]:
        """List all members of the organization"""
        await self._ensure_initialized()

        if not context.organization_id:
            return []

        async with self.db.engine.begin() as conn:
            result = await conn.execute(
                """
                SELECT
                    u.id, u.email, u.full_name, u.is_active,
                    om.role, om.joined_at,
                    inv.email as invited_by_email
                FROM organization_members om
                JOIN users u ON u.id = om.user_id
                LEFT JOIN users inv ON inv.id = om.invited_by
                WHERE om.organization_id = :org_id
                ORDER BY om.role DESC, u.email ASC
                """,
                {'org_id': context.organization_id}
            )
            rows = result.mappings().all()

            return [
                {
                    'user_id': str(row['id']),
                    'email': row['email'],
                    'full_name': row['full_name'],
                    'is_active': row['is_active'],
                    'role': row['role'],
                    'joined_at': row['joined_at'].isoformat() if row['joined_at'] else None,
                    'invited_by': row['invited_by_email'],
                }
                for row in rows
            ]


# Global service instance
organization_service = OrganizationService()
