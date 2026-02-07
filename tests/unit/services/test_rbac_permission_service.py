"""
Tests for RBAC Permission Service

Verifies configuration-based role and permission management system.
"""

import pytest
from uuid import uuid4
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from backend.services.rbac_permission_service import (
    RBACPermissionService,
    get_rbac_service,
    check_permission
)
from backend.services.request_context import RequestContext


# Fixtures

@pytest.fixture
def sample_user_id():
    """Sample user UUID"""
    return uuid4()


@pytest.fixture
def sample_org_id():
    """Sample organization UUID"""
    return uuid4()


@pytest.fixture
def context_owner(sample_user_id, sample_org_id):
    """Context for organization owner"""
    return RequestContext(
        user_id=sample_user_id,
        user_email="owner@company.com",
        organization_id=sample_org_id,
        is_admin=False,
        org_role="owner"
    )


@pytest.fixture
def context_admin(sample_user_id, sample_org_id):
    """Context for organization admin"""
    return RequestContext(
        user_id=sample_user_id,
        user_email="admin@company.com",
        organization_id=sample_org_id,
        is_admin=False,
        org_role="admin"
    )


@pytest.fixture
def context_member(sample_user_id, sample_org_id):
    """Context for organization member"""
    return RequestContext(
        user_id=sample_user_id,
        user_email="member@company.com",
        organization_id=sample_org_id,
        is_admin=False,
        org_role="member"
    )


@pytest.fixture
def context_viewer(sample_user_id, sample_org_id):
    """Context for viewer"""
    return RequestContext(
        user_id=sample_user_id,
        user_email="viewer@company.com",
        organization_id=sample_org_id,
        is_admin=False,
        org_role="viewer"
    )


@pytest.fixture
def context_system_admin(sample_user_id, sample_org_id):
    """Context for system admin"""
    return RequestContext(
        user_id=sample_user_id,
        user_email="sysadmin@company.com",
        organization_id=sample_org_id,
        is_admin=True,
        org_role="member"
    )


@pytest.fixture
def rbac_service():
    """RBAC service instance"""
    # Get the real service which loads from config
    return get_rbac_service()


# Test Classes

class TestRBACServiceInitialization:
    """Test RBAC service initialization and configuration loading"""

    def test_service_loads_configuration(self, rbac_service):
        """Service should load configuration from YAML file"""
        assert rbac_service.roles is not None
        assert rbac_service.permissions is not None
        assert len(rbac_service.roles) > 0

    def test_service_has_expected_roles(self, rbac_service):
        """Service should load standard roles from config"""
        assert "owner" in rbac_service.roles
        assert "admin" in rbac_service.roles
        assert "member" in rbac_service.roles
        assert "viewer" in rbac_service.roles

    def test_service_singleton_pattern(self):
        """get_rbac_service should return same instance"""
        service1 = get_rbac_service()
        service2 = get_rbac_service()
        assert service1 is service2


class TestSavedViewsPermissions:
    """Test saved views permissions"""

    def test_owner_can_read_all_saved_views(self, rbac_service, context_owner):
        """Owners should have saved_views:read:all permission"""
        assert rbac_service.has_permission(context_owner, "saved_views:read:all")

    def test_admin_can_read_all_saved_views(self, rbac_service, context_admin):
        """Admins should have saved_views:read:all permission"""
        assert rbac_service.has_permission(context_admin, "saved_views:read:all")

    def test_member_can_only_read_shared_views(self, rbac_service, context_member):
        """Members should have saved_views:read:shared but not read:all"""
        assert rbac_service.has_permission(context_member, "saved_views:read:shared")
        assert not rbac_service.has_permission(context_member, "saved_views:read:all")

    def test_owner_can_write_all_saved_views(self, rbac_service, context_owner):
        """Owners should have saved_views:write:all permission"""
        assert rbac_service.has_permission(context_owner, "saved_views:write:all")

    def test_member_can_write_own_views(self, rbac_service, context_member):
        """Members should have saved_views:write:own permission"""
        resource_owner = str(context_member.user_id)
        assert rbac_service.has_permission(
            context_member,
            "saved_views:write:own",
            resource_owner
        )

    def test_member_cannot_write_others_views(self, rbac_service, context_member):
        """Members should not be able to write views owned by others"""
        other_owner = str(uuid4())
        assert not rbac_service.has_permission(
            context_member,
            "saved_views:write:own",
            other_owner
        )

    def test_viewer_cannot_write_any_views(self, rbac_service, context_viewer):
        """Viewers should not have write permissions"""
        assert not rbac_service.has_permission(context_viewer, "saved_views:write:own")
        assert not rbac_service.has_permission(context_viewer, "saved_views:write:all")


class TestOrganizationPermissions:
    """Test organization management permissions"""

    def test_owner_can_manage_members(self, rbac_service, context_owner):
        """Owners should be able to manage organization members"""
        assert rbac_service.has_permission(context_owner, "organization:manage_members")

    def test_admin_can_manage_members(self, rbac_service, context_admin):
        """Admins should be able to manage organization members"""
        assert rbac_service.has_permission(context_admin, "organization:manage_members")

    def test_member_cannot_manage_members(self, rbac_service, context_member):
        """Members should not be able to manage organization members"""
        assert not rbac_service.has_permission(context_member, "organization:manage_members")

    def test_owner_can_change_roles(self, rbac_service, context_owner):
        """Owners should be able to change member roles"""
        assert rbac_service.has_permission(context_owner, "organization:change_roles")

    def test_admin_cannot_change_roles(self, rbac_service, context_admin):
        """Admins should not be able to change roles (only owner can)"""
        assert not rbac_service.has_permission(context_admin, "organization:change_roles")

    def test_owner_can_delete_organization(self, rbac_service, context_owner):
        """Owners should be able to delete organization"""
        assert rbac_service.has_permission(context_owner, "organization:delete")

    def test_admin_cannot_delete_organization(self, rbac_service, context_admin):
        """Admins should not be able to delete organization"""
        assert not rbac_service.has_permission(context_admin, "organization:delete")


class TestQueryPermissions:
    """Test query execution permissions"""

    def test_owner_can_execute_queries_on_all_accounts(self, rbac_service, context_owner):
        """Owners should have query:execute:all permission"""
        assert rbac_service.has_permission(context_owner, "query:execute:all")

    def test_admin_can_execute_queries_on_all_accounts(self, rbac_service, context_admin):
        """Admins should have query:execute:all permission"""
        assert rbac_service.has_permission(context_admin, "query:execute:all")

    def test_member_can_only_execute_on_assigned_accounts(self, rbac_service, context_member):
        """Members should have query:execute:assigned but not execute:all"""
        assert rbac_service.has_permission(context_member, "query:execute:assigned")
        assert not rbac_service.has_permission(context_member, "query:execute:all")


class TestSystemAdminPrivileges:
    """Test system admin special privileges"""

    def test_system_admin_has_all_permissions(self, rbac_service, context_system_admin):
        """System admins should have all permissions via wildcard"""
        # Test various permissions
        assert rbac_service.has_permission(context_system_admin, "saved_views:read:all")
        assert rbac_service.has_permission(context_system_admin, "saved_views:write:all")
        assert rbac_service.has_permission(context_system_admin, "organization:manage_members")
        assert rbac_service.has_permission(context_system_admin, "organization:change_roles")
        assert rbac_service.has_permission(context_system_admin, "organization:delete")
        assert rbac_service.has_permission(context_system_admin, "query:execute:all")
        assert rbac_service.has_permission(context_system_admin, "account:write:all")

    def test_system_admin_bypasses_ownership_checks(self, rbac_service, context_system_admin):
        """System admins should bypass ownership checks"""
        other_owner = str(uuid4())
        assert rbac_service.has_permission(
            context_system_admin,
            "saved_views:write:own",
            other_owner
        )


class TestRoleHierarchy:
    """Test role hierarchy and can_assign_roles logic"""

    def test_owner_can_assign_all_roles(self, rbac_service, context_owner):
        """Owners should be able to assign any role"""
        assert rbac_service.can_manage_role(context_owner, "owner")
        assert rbac_service.can_manage_role(context_owner, "admin")
        assert rbac_service.can_manage_role(context_owner, "member")
        assert rbac_service.can_manage_role(context_owner, "viewer")

    def test_admin_can_assign_member_and_viewer_only(self, rbac_service, context_admin):
        """Admins should only be able to assign member and viewer roles"""
        assert not rbac_service.can_manage_role(context_admin, "owner")
        assert not rbac_service.can_manage_role(context_admin, "admin")
        assert rbac_service.can_manage_role(context_admin, "member")
        assert rbac_service.can_manage_role(context_admin, "viewer")

    def test_member_cannot_assign_any_roles(self, rbac_service, context_member):
        """Members should not be able to assign any roles"""
        assert not rbac_service.can_manage_role(context_member, "owner")
        assert not rbac_service.can_manage_role(context_member, "admin")
        assert not rbac_service.can_manage_role(context_member, "member")
        assert not rbac_service.can_manage_role(context_member, "viewer")


class TestRequirePermission:
    """Test require_permission method (raises on failure)"""

    def test_require_permission_succeeds_when_granted(self, rbac_service, context_owner):
        """require_permission should not raise when permission is granted"""
        # Should not raise
        rbac_service.require_permission(context_owner, "saved_views:read:all")

    def test_require_permission_raises_when_denied(self, rbac_service, context_member):
        """require_permission should raise ValueError when permission denied"""
        with pytest.raises(ValueError) as exc_info:
            rbac_service.require_permission(context_member, "organization:delete")

        assert "Permission denied" in str(exc_info.value)

    def test_require_permission_with_custom_error_message(self, rbac_service, context_member):
        """require_permission should use custom error message"""
        custom_message = "You must be an owner to perform this action"

        with pytest.raises(ValueError) as exc_info:
            rbac_service.require_permission(
                context_member,
                "organization:delete",
                error_message=custom_message
            )

        assert custom_message in str(exc_info.value)


class TestPrivilegedRoleHelper:
    """Test is_privileged_role helper method"""

    def test_owner_is_privileged(self, rbac_service, context_owner):
        """Owners should be considered privileged"""
        assert rbac_service.is_privileged_role(context_owner)

    def test_admin_is_privileged(self, rbac_service, context_admin):
        """Admins should be considered privileged"""
        assert rbac_service.is_privileged_role(context_admin)

    def test_member_is_not_privileged(self, rbac_service, context_member):
        """Members should not be considered privileged"""
        assert not rbac_service.is_privileged_role(context_member)

    def test_viewer_is_not_privileged(self, rbac_service, context_viewer):
        """Viewers should not be considered privileged"""
        assert not rbac_service.is_privileged_role(context_viewer)

    def test_system_admin_is_privileged(self, rbac_service, context_system_admin):
        """System admins should be considered privileged"""
        assert rbac_service.is_privileged_role(context_system_admin)


class TestWildcardPermissions:
    """Test wildcard permission matching"""

    def test_exact_match(self, rbac_service):
        """Exact permission match should work"""
        assert rbac_service._match_permission(
            "saved_views:read:all",
            "saved_views:read:all"
        )

    def test_wildcard_all_match(self, rbac_service):
        """*:*:* should match any permission"""
        assert rbac_service._match_permission(
            "saved_views:read:all",
            "*:*:*"
        )
        assert rbac_service._match_permission(
            "organization:delete",
            "*:*:*"
        )

    def test_wildcard_action_match(self, rbac_service):
        """saved_views:*:all should match any action on saved_views with scope all"""
        assert rbac_service._match_permission(
            "saved_views:read:all",
            "saved_views:*:all"
        )
        assert rbac_service._match_permission(
            "saved_views:write:all",
            "saved_views:*:all"
        )

    def test_wildcard_scope_match(self, rbac_service):
        """saved_views:read:* should match read action with any scope"""
        assert rbac_service._match_permission(
            "saved_views:read:all",
            "saved_views:read:*"
        )
        assert rbac_service._match_permission(
            "saved_views:read:shared",
            "saved_views:read:*"
        )


class TestConvenienceFunctions:
    """Test convenience functions"""

    def test_check_permission_function(self, context_owner):
        """check_permission convenience function should work"""
        result = check_permission(context_owner, "saved_views:read:all")
        assert result is True

    def test_check_permission_denied(self, context_member):
        """check_permission should return False when denied"""
        result = check_permission(context_member, "organization:delete")
        assert result is False


class TestGetUserPermissions:
    """Test getting all user permissions"""

    def test_get_owner_permissions(self, rbac_service, context_owner):
        """Should return list of owner permissions"""
        permissions = rbac_service.get_user_permissions(context_owner)
        assert len(permissions) > 0
        assert "saved_views:read:all" in permissions
        assert "organization:manage_members" in permissions

    def test_get_system_admin_permissions(self, rbac_service, context_system_admin):
        """System admin should return wildcard permission"""
        permissions = rbac_service.get_user_permissions(context_system_admin)
        assert permissions == ["*:*:*"]


class TestRoleInfo:
    """Test getting role information"""

    def test_get_role_info_returns_config(self, rbac_service):
        """Should return role configuration"""
        info = rbac_service.get_role_info("owner")
        assert info is not None
        assert info['display_name'] == "Organization Owner"
        assert info['priority'] == 100

    def test_get_role_info_invalid_role(self, rbac_service):
        """Should return None for invalid role"""
        info = rbac_service.get_role_info("invalid_role")
        assert info is None
