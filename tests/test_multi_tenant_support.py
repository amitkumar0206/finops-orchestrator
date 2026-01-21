"""
Tests for Multi-Tenant Support Implementation

Tests cover:
1. RequestContext dataclass and methods
2. Account scoping in Text-to-SQL service
3. Account scoping in Athena Query service
4. Audit logging with scope context
"""

import pytest
from uuid import uuid4, UUID
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch

# Import the modules we're testing
from backend.services.request_context import (
    RequestContext,
    SavedViewInfo,
    OrganizationInfo,
    create_empty_context,
    get_context_from_request,
    require_context,
)
from backend.services.text_to_sql_service import TextToSQLService
from backend.services.athena_query_service import AthenaQueryService


# ==================== RequestContext Tests ====================

class TestRequestContext:
    """Tests for RequestContext dataclass"""

    def test_create_basic_context(self):
        """Test creating a basic request context"""
        user_id = uuid4()
        org_id = uuid4()

        context = RequestContext(
            user_id=user_id,
            user_email="test@example.com",
            is_admin=False,
            organization_id=org_id,
            organization_name="Test Org",
            allowed_account_ids=["123456789012", "234567890123"],
            org_role="member"
        )

        assert context.user_id == user_id
        assert context.user_email == "test@example.com"
        assert context.is_admin is False
        assert context.organization_id == org_id
        assert len(context.allowed_account_ids) == 2

    def test_has_account_access_allowed(self):
        """Test checking access to an allowed account"""
        context = RequestContext(
            user_id=uuid4(),
            user_email="test@example.com",
            allowed_account_ids=["123456789012", "234567890123"],
        )

        assert context.has_account_access("123456789012") is True
        assert context.has_account_access("234567890123") is True

    def test_has_account_access_denied(self):
        """Test checking access to a denied account"""
        context = RequestContext(
            user_id=uuid4(),
            user_email="test@example.com",
            allowed_account_ids=["123456789012"],
        )

        assert context.has_account_access("999999999999") is False

    def test_has_account_access_admin_bypass(self):
        """Test that admins can access any account"""
        context = RequestContext(
            user_id=uuid4(),
            user_email="admin@example.com",
            is_admin=True,
            allowed_account_ids=["123456789012"],
        )

        # Admin should have access to any account
        assert context.has_account_access("999999999999") is True

    def test_filter_accounts(self):
        """Test filtering a list of accounts to allowed ones"""
        context = RequestContext(
            user_id=uuid4(),
            user_email="test@example.com",
            allowed_account_ids=["123456789012", "234567890123"],
        )

        input_accounts = ["123456789012", "999999999999", "234567890123"]
        filtered = context.filter_accounts(input_accounts)

        assert len(filtered) == 2
        assert "123456789012" in filtered
        assert "234567890123" in filtered
        assert "999999999999" not in filtered

    def test_filter_accounts_admin_bypass(self):
        """Test that admins get all accounts"""
        context = RequestContext(
            user_id=uuid4(),
            user_email="admin@example.com",
            is_admin=True,
            allowed_account_ids=["123456789012"],
        )

        input_accounts = ["123456789012", "999999999999"]
        filtered = context.filter_accounts(input_accounts)

        assert filtered == input_accounts

    def test_get_account_filter_sql_with_accounts(self):
        """Test generating SQL filter for accounts"""
        context = RequestContext(
            user_id=uuid4(),
            user_email="test@example.com",
            allowed_account_ids=["123456789012", "234567890123"],
        )

        sql_filter = context.get_account_filter_sql()

        assert "line_item_usage_account_id IN" in sql_filter
        assert "'123456789012'" in sql_filter
        assert "'234567890123'" in sql_filter

    def test_get_account_filter_sql_admin_empty(self):
        """Test that admins get empty filter"""
        context = RequestContext(
            user_id=uuid4(),
            user_email="admin@example.com",
            is_admin=True,
            allowed_account_ids=["123456789012"],
        )

        sql_filter = context.get_account_filter_sql()

        assert sql_filter == ""

    def test_to_scope_dict(self):
        """Test converting context to scope dictionary"""
        org_id = uuid4()
        view_id = uuid4()

        context = RequestContext(
            user_id=uuid4(),
            user_email="test@example.com",
            organization_id=org_id,
            organization_name="Test Org",
            allowed_account_ids=["123456789012"],
            active_saved_view=SavedViewInfo(
                id=view_id,
                name="Production View",
                account_ids=[uuid4()],
            ),
            org_role="admin",
            is_admin=False,
        )

        scope_dict = context.to_scope_dict()

        assert scope_dict['organization_id'] == str(org_id)
        assert scope_dict['organization_name'] == "Test Org"
        assert scope_dict['account_count'] == 1
        assert scope_dict['active_view']['name'] == "Production View"
        assert scope_dict['org_role'] == "admin"

    def test_to_audit_context(self):
        """Test converting context to audit log format"""
        user_id = uuid4()
        org_id = uuid4()

        context = RequestContext(
            user_id=user_id,
            user_email="test@example.com",
            organization_id=org_id,
            allowed_account_ids=["123456789012", "234567890123"],
            is_admin=False,
            org_role="member",
        )

        audit_ctx = context.to_audit_context()

        assert audit_ctx['user_id'] == str(user_id)
        assert audit_ctx['user_email'] == "test@example.com"
        assert audit_ctx['organization_id'] == str(org_id)
        assert audit_ctx['allowed_account_count'] == 2

    def test_create_empty_context(self):
        """Test creating empty context for anonymous users"""
        context = create_empty_context("anonymous@example.com")

        assert context.user_email == "anonymous@example.com"
        assert context.is_admin is False
        assert len(context.allowed_account_ids) == 0


class TestSavedViewInfo:
    """Tests for SavedViewInfo dataclass"""

    def test_create_saved_view_info(self):
        """Test creating SavedViewInfo"""
        view_id = uuid4()
        account_ids = [uuid4(), uuid4()]
        expires = datetime.utcnow() + timedelta(days=30)

        view_info = SavedViewInfo(
            id=view_id,
            name="Test View",
            account_ids=account_ids,
            default_time_range={"days": 30},
            filters={"service": "EC2"},
            is_personal=True,
            expires_at=expires,
        )

        assert view_info.id == view_id
        assert view_info.name == "Test View"
        assert len(view_info.account_ids) == 2
        assert view_info.is_personal is True


class TestOrganizationInfo:
    """Tests for OrganizationInfo dataclass"""

    def test_create_organization_info(self):
        """Test creating OrganizationInfo"""
        org_id = uuid4()

        org_info = OrganizationInfo(
            id=org_id,
            name="Test Org",
            slug="test-org",
            subscription_tier="enterprise",
            settings={"feature_x": True},
            saved_view_default_expiration_days=90,
        )

        assert org_info.id == org_id
        assert org_info.name == "Test Org"
        assert org_info.subscription_tier == "enterprise"
        assert org_info.saved_view_default_expiration_days == 90


# ==================== Text-to-SQL Scoping Tests ====================

class TestTextToSQLScoping:
    """Tests for account scoping in Text-to-SQL service"""

    def test_enforce_account_filter_no_existing_filter(self):
        """Test injecting account filter when none exists"""
        service = TextToSQLService()

        sql = """
        SELECT service, SUM(cost) as total_cost
        FROM cost_usage_db.cur_data
        WHERE line_item_usage_start_date >= DATE '2025-01-01'
        GROUP BY service
        """

        allowed_accounts = ["123456789012", "234567890123"]

        modified_sql, was_modified = service._enforce_account_filter(sql, allowed_accounts)

        assert was_modified is True
        assert "line_item_usage_account_id IN" in modified_sql
        assert "'123456789012'" in modified_sql
        assert "'234567890123'" in modified_sql

    def test_enforce_account_filter_existing_filter(self):
        """Test that existing filter is not modified"""
        service = TextToSQLService()

        sql = """
        SELECT service, SUM(cost) as total_cost
        FROM cost_usage_db.cur_data
        WHERE line_item_usage_account_id IN ('123456789012')
          AND line_item_usage_start_date >= DATE '2025-01-01'
        GROUP BY service
        """

        allowed_accounts = ["123456789012"]

        modified_sql, was_modified = service._enforce_account_filter(sql, allowed_accounts)

        assert was_modified is False
        assert modified_sql == sql

    def test_validate_sql_scope_valid(self):
        """Test validating SQL with valid account access"""
        service = TextToSQLService()

        sql = """
        SELECT service, SUM(cost)
        FROM cost_usage_db.cur_data
        WHERE line_item_usage_account_id IN ('123456789012')
        """

        allowed_accounts = ["123456789012", "234567890123"]

        is_valid, error = service.validate_sql_scope(sql, allowed_accounts)

        assert is_valid is True
        assert error is None

    def test_validate_sql_scope_unauthorized(self):
        """Test validating SQL with unauthorized account"""
        service = TextToSQLService()

        sql = """
        SELECT service, SUM(cost)
        FROM cost_usage_db.cur_data
        WHERE line_item_usage_account_id = '999999999999'
        """

        allowed_accounts = ["123456789012"]

        is_valid, error = service.validate_sql_scope(sql, allowed_accounts)

        assert is_valid is False
        assert "999999999999" in error

    def test_validate_sql_scope_missing_filter(self):
        """Test validating SQL without account filter"""
        service = TextToSQLService()

        sql = """
        SELECT service, SUM(cost)
        FROM cost_usage_db.cur_data
        WHERE line_item_usage_start_date >= DATE '2025-01-01'
        """

        allowed_accounts = ["123456789012"]

        is_valid, error = service.validate_sql_scope(sql, allowed_accounts)

        assert is_valid is False
        assert "must include account filter" in error


# ==================== Athena Query Scoping Tests ====================

class TestAthenaQueryScoping:
    """Tests for account scoping in Athena Query service"""

    def test_enforce_account_filter_where_exists(self):
        """Test injecting filter into existing WHERE clause"""
        service = AthenaQueryService()

        sql = """
        SELECT service, SUM(cost)
        FROM cur_data
        WHERE line_item_usage_start_date >= DATE '2025-01-01'
        GROUP BY service
        """

        allowed_accounts = ["123456789012"]

        modified_sql, was_modified = service._enforce_account_filter(sql, allowed_accounts)

        assert was_modified is True
        assert "line_item_usage_account_id IN ('123456789012')" in modified_sql

    def test_enforce_account_filter_no_where(self):
        """Test adding WHERE clause when none exists"""
        service = AthenaQueryService()

        sql = """
        SELECT service, SUM(cost)
        FROM cur_data
        GROUP BY service
        """

        allowed_accounts = ["123456789012"]

        modified_sql, was_modified = service._enforce_account_filter(sql, allowed_accounts)

        assert was_modified is True
        assert "WHERE line_item_usage_account_id IN" in modified_sql

    def test_validate_account_scope_valid_multiple_accounts(self):
        """Test validation with multiple valid accounts"""
        service = AthenaQueryService()

        sql = """
        SELECT service
        FROM cur_data
        WHERE line_item_usage_account_id IN ('123456789012', '234567890123')
        """

        allowed_accounts = ["123456789012", "234567890123", "345678901234"]

        is_valid, error = service._validate_account_scope(sql, allowed_accounts)

        assert is_valid is True
        assert error is None

    def test_validate_account_scope_partial_unauthorized(self):
        """Test validation with some unauthorized accounts"""
        service = AthenaQueryService()

        sql = """
        SELECT service
        FROM cur_data
        WHERE line_item_usage_account_id IN ('123456789012', '999999999999')
        """

        allowed_accounts = ["123456789012"]

        is_valid, error = service._validate_account_scope(sql, allowed_accounts)

        assert is_valid is False
        assert "999999999999" in error

    def test_inject_account_filter_public_method(self):
        """Test public inject_account_filter method"""
        service = AthenaQueryService()

        sql = "SELECT * FROM cur_data WHERE date >= '2025-01-01'"
        allowed_accounts = ["111111111111", "222222222222"]

        result = service.inject_account_filter(sql, allowed_accounts)

        assert "line_item_usage_account_id IN" in result
        assert "'111111111111'" in result
        assert "'222222222222'" in result


# ==================== Integration Tests ====================

class TestScopingIntegration:
    """Integration tests for scoping flow"""

    def test_context_to_sql_filter_flow(self):
        """Test full flow from RequestContext to SQL filter"""
        # Create context
        context = RequestContext(
            user_id=uuid4(),
            user_email="test@example.com",
            organization_id=uuid4(),
            organization_name="Test Org",
            allowed_account_ids=["123456789012", "234567890123"],
            org_role="member",
        )

        # Get SQL filter from context
        sql_filter = context.get_account_filter_sql()

        # Verify filter
        assert "line_item_usage_account_id IN" in sql_filter
        assert "'123456789012'" in sql_filter
        assert "'234567890123'" in sql_filter

        # Verify scope dict for API response
        scope_dict = context.to_scope_dict()
        assert scope_dict['account_count'] == 2
        assert '123456789012' in scope_dict['allowed_account_ids']

    def test_scope_enforcement_chain(self):
        """Test that scope enforcement works across services"""
        # Create a non-admin context with limited accounts
        context = RequestContext(
            user_id=uuid4(),
            user_email="limited@example.com",
            allowed_account_ids=["123456789012"],
            is_admin=False,
        )

        # SQL that tries to access unauthorized account
        bad_sql = """
        SELECT * FROM cur_data
        WHERE line_item_usage_account_id = '999999999999'
        """

        # TextToSQL validation should fail
        text_to_sql = TextToSQLService()
        is_valid, error = text_to_sql.validate_sql_scope(bad_sql, context.allowed_account_ids)
        assert is_valid is False

        # Athena validation should also fail
        athena = AthenaQueryService()
        is_valid, error = athena._validate_account_scope(bad_sql, context.allowed_account_ids)
        assert is_valid is False


# ==================== Edge Case Tests ====================

class TestEdgeCases:
    """Tests for edge cases and boundary conditions"""

    def test_empty_allowed_accounts(self):
        """Test behavior with empty allowed accounts list"""
        context = RequestContext(
            user_id=uuid4(),
            user_email="test@example.com",
            allowed_account_ids=[],
        )

        # Should not have access to any account
        assert context.has_account_access("123456789012") is False

        # Filter should return empty list
        assert context.filter_accounts(["123456789012"]) == []

    def test_special_characters_in_account_ids(self):
        """Test that account IDs are properly escaped"""
        context = RequestContext(
            user_id=uuid4(),
            user_email="test@example.com",
            allowed_account_ids=["123456789012"],
        )

        sql_filter = context.get_account_filter_sql()

        # Ensure proper quoting
        assert "'" in sql_filter
        assert "123456789012" in sql_filter

    def test_context_with_saved_view(self):
        """Test context with active saved view"""
        view_id = uuid4()
        account_id = uuid4()

        context = RequestContext(
            user_id=uuid4(),
            user_email="test@example.com",
            organization_id=uuid4(),
            allowed_account_ids=["123456789012"],
            active_saved_view=SavedViewInfo(
                id=view_id,
                name="My View",
                account_ids=[account_id],
                default_time_range={"days": 30},
                filters={"region": "us-east-1"},
            ),
            effective_time_range={"days": 30},
            effective_filters={"region": "us-east-1"},
        )

        scope_dict = context.to_scope_dict()

        assert scope_dict['active_view'] is not None
        assert scope_dict['active_view']['name'] == "My View"
        assert scope_dict['effective_time_range'] == {"days": 30}
        assert scope_dict['effective_filters'] == {"region": "us-east-1"}

    def test_large_number_of_accounts(self):
        """Test with many allowed accounts"""
        # Generate 100 fake account IDs
        accounts = [f"{i:012d}" for i in range(100)]

        context = RequestContext(
            user_id=uuid4(),
            user_email="test@example.com",
            allowed_account_ids=accounts,
        )

        sql_filter = context.get_account_filter_sql()

        # All accounts should be in the filter
        for account in accounts[:5]:  # Check first 5
            assert f"'{account}'" in sql_filter

        # Filter should work correctly
        assert len(context.filter_accounts(accounts[:50])) == 50


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
