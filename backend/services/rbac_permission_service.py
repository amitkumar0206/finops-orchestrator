"""
RBAC Permission Service - Configuration-based Role and Permission Management

This service loads role and permission definitions from a YAML configuration file
and provides methods to check user permissions dynamically without hardcoded role checks.

Key Features:
- Configuration-based role definitions
- Permission inheritance
- Wildcard permission support
- Resource-action-scope permission model
- Role hierarchy enforcement
"""

import os
import yaml
from typing import List, Dict, Optional, Set
from pathlib import Path
import structlog
from functools import lru_cache

from backend.services.request_context import RequestContext

logger = structlog.get_logger(__name__)


class RBACPermissionService:
    """Service for checking user permissions based on RBAC configuration"""

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize RBAC service with configuration

        Args:
            config_path: Path to RBAC YAML configuration file
        """
        self.config_path = config_path or self._get_default_config_path()
        self.config = self._load_config()
        self.roles = self.config.get('roles', {})
        self.permissions = self.config.get('permissions', {})
        self.role_hierarchy = self.config.get('role_hierarchy', {})
        self.default_role = self.config.get('default_role', 'member')

        logger.info(
            "rbac_service_initialized",
            roles_count=len(self.roles),
            permissions_count=len(self.permissions),
            config_path=self.config_path
        )

    def _get_default_config_path(self) -> str:
        """Get default path to RBAC configuration file"""
        # Try multiple possible locations
        possible_paths = [
            # Relative to project root
            Path(__file__).parent.parent.parent / "config" / "rbac_config.yaml",
            # Relative to backend directory
            Path(__file__).parent.parent / "config" / "rbac_config.yaml",
            # Environment variable
            Path(os.getenv("RBAC_CONFIG_PATH", "config/rbac_config.yaml")),
        ]

        for path in possible_paths:
            if path.exists():
                return str(path)

        # Default fallback
        return str(possible_paths[0])

    def _load_config(self) -> Dict:
        """Load RBAC configuration from YAML file"""
        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
                logger.info("rbac_config_loaded", path=self.config_path)
                return config
        except FileNotFoundError:
            logger.error("rbac_config_not_found", path=self.config_path)
            # Return minimal default configuration
            return {
                'roles': {
                    'member': {
                        'display_name': 'Member',
                        'priority': 50,
                        'permissions': []
                    }
                },
                'permissions': {},
                'default_role': 'member'
            }
        except Exception as e:
            logger.error("rbac_config_load_failed", error=str(e), exc_info=True)
            raise

    def reload_config(self):
        """Reload configuration from file (useful for runtime updates)"""
        self.config = self._load_config()
        self.roles = self.config.get('roles', {})
        self.permissions = self.config.get('permissions', {})
        self.role_hierarchy = self.config.get('role_hierarchy', {})
        logger.info("rbac_config_reloaded")

    @lru_cache(maxsize=1024)
    def _get_role_permissions(self, role_name: str) -> Set[str]:
        """
        Get all permissions for a role (including inherited)

        Args:
            role_name: Name of the role

        Returns:
            Set of permission strings
        """
        if role_name not in self.roles:
            logger.warning("role_not_found", role=role_name)
            return set()

        role_config = self.roles[role_name]
        permissions = set(role_config.get('permissions', []))

        # Add inherited permissions
        for inherited_role in role_config.get('inherits_from', []):
            permissions.update(self._get_role_permissions(inherited_role))

        return permissions

    def _match_permission(self, required: str, granted: str) -> bool:
        """
        Check if a granted permission matches a required permission

        Supports wildcards:
        - "*:*:*" matches everything
        - "saved_views:*:all" matches any action on saved_views with scope all
        - "saved_views:read:*" matches read action on saved_views with any scope

        Args:
            required: Required permission (e.g., "saved_views:read:all")
            granted: Granted permission (may contain wildcards)

        Returns:
            True if granted permission covers required permission
        """
        # Exact match
        if granted == required:
            return True

        # Wildcard match
        if granted == "*:*:*":
            return True

        # Split into parts
        granted_parts = granted.split(':')
        required_parts = required.split(':')

        # Must have same number of parts
        if len(granted_parts) != len(required_parts):
            return False

        # Check each part
        for granted_part, required_part in zip(granted_parts, required_parts):
            if granted_part != "*" and granted_part != required_part:
                return False

        return True

    def has_permission(
        self,
        context: RequestContext,
        permission: str,
        resource_owner_id: Optional[str] = None
    ) -> bool:
        """
        Check if user has a specific permission

        Args:
            context: Request context with user info
            permission: Permission string (e.g., "saved_views:read:all")
            resource_owner_id: ID of resource owner (for "own" scope checks)

        Returns:
            True if user has permission
        """
        # System admins have all permissions
        if context.is_admin:
            return True

        # Get user's role
        user_role = context.org_role or self.default_role

        # Get all permissions for this role
        role_permissions = self._get_role_permissions(user_role)

        # Check if any granted permission matches required
        for granted_permission in role_permissions:
            if self._match_permission(permission, granted_permission):
                # For "own" scope, verify ownership
                if ":own" in permission:
                    return resource_owner_id == str(context.user_id)
                return True

        return False

    def has_any_permission(
        self,
        context: RequestContext,
        permissions: List[str],
        resource_owner_id: Optional[str] = None
    ) -> bool:
        """
        Check if user has ANY of the specified permissions

        Args:
            context: Request context
            permissions: List of permission strings
            resource_owner_id: ID of resource owner

        Returns:
            True if user has at least one permission
        """
        return any(
            self.has_permission(context, perm, resource_owner_id)
            for perm in permissions
        )

    def has_all_permissions(
        self,
        context: RequestContext,
        permissions: List[str],
        resource_owner_id: Optional[str] = None
    ) -> bool:
        """
        Check if user has ALL of the specified permissions

        Args:
            context: Request context
            permissions: List of permission strings
            resource_owner_id: ID of resource owner

        Returns:
            True if user has all permissions
        """
        return all(
            self.has_permission(context, perm, resource_owner_id)
            for perm in permissions
        )

    def can_manage_role(self, context: RequestContext, target_role: str) -> bool:
        """
        Check if user can assign/remove a specific role

        Args:
            context: Request context
            target_role: Role to be assigned/removed

        Returns:
            True if user can manage this role
        """
        # System admins can manage all roles
        if context.is_admin:
            return True

        user_role = context.org_role or self.default_role

        # Check role hierarchy
        can_assign = self.role_hierarchy.get('can_assign_roles', {})
        allowed_roles = can_assign.get(user_role, [])

        return target_role in allowed_roles

    def get_role_info(self, role_name: str) -> Optional[Dict]:
        """
        Get role configuration information

        Args:
            role_name: Name of the role

        Returns:
            Role configuration dictionary or None
        """
        return self.roles.get(role_name)

    def get_user_permissions(self, context: RequestContext) -> List[str]:
        """
        Get all permissions for the current user

        Args:
            context: Request context

        Returns:
            List of permission strings
        """
        if context.is_admin:
            return ["*:*:*"]

        user_role = context.org_role or self.default_role
        return list(self._get_role_permissions(user_role))

    def is_privileged_role(self, context: RequestContext) -> bool:
        """
        Check if user has a privileged role (admin, owner, system_admin)

        This is a convenience method to replace common hardcoded checks
        like: context.is_admin or context.org_role in ('owner', 'admin')

        Args:
            context: Request context

        Returns:
            True if user has privileged role
        """
        if context.is_admin:
            return True

        user_role = context.org_role or self.default_role
        role_config = self.roles.get(user_role, {})

        # Roles with priority >= 90 are considered privileged
        # (owner=100, admin=90, member=50, viewer=10)
        priority = role_config.get('priority', 0)
        return priority >= 90

    def require_permission(
        self,
        context: RequestContext,
        permission: str,
        resource_owner_id: Optional[str] = None,
        error_message: Optional[str] = None
    ):
        """
        Require a permission or raise ValueError

        Args:
            context: Request context
            permission: Required permission
            resource_owner_id: ID of resource owner
            error_message: Custom error message

        Raises:
            ValueError: If permission is not granted
        """
        if not self.has_permission(context, permission, resource_owner_id):
            msg = error_message or f"Permission denied: {permission}"
            logger.warning(
                "permission_denied",
                user_id=str(context.user_id),
                user_email=context.user_email,
                user_role=context.org_role,
                required_permission=permission
            )
            raise ValueError(msg)


# Global singleton instance
_rbac_service_instance: Optional[RBACPermissionService] = None


def get_rbac_service() -> RBACPermissionService:
    """
    Get or create the global RBAC service instance

    Returns:
        RBACPermissionService instance
    """
    global _rbac_service_instance
    if _rbac_service_instance is None:
        _rbac_service_instance = RBACPermissionService()
    return _rbac_service_instance


# Convenience function for common use
def check_permission(
    context: RequestContext,
    permission: str,
    resource_owner_id: Optional[str] = None
) -> bool:
    """
    Convenience function to check permission

    Args:
        context: Request context
        permission: Permission to check
        resource_owner_id: ID of resource owner

    Returns:
        True if user has permission
    """
    return get_rbac_service().has_permission(context, permission, resource_owner_id)
