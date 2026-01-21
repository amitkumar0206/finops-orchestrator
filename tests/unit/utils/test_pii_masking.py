"""
Tests for PII Masking Utilities
"""

import pytest

from backend.utils.pii_masking import (
    mask_email,
    hash_identifier,
    mask_account_id,
    sanitize_exception,
    mask_query_for_logging,
    create_audit_context,
)


class TestMaskEmail:
    """Test email masking function"""

    def test_masks_standard_email(self):
        """Test masking a standard email address"""
        result = mask_email("john.doe@example.com")

        assert "jo***" in result
        assert "@" in result
        assert "ex***" in result
        assert ".com" in result
        assert "john.doe" not in result

    def test_masks_short_local_part(self):
        """Test masking email with short local part"""
        result = mask_email("a@b.com")

        assert "@" in result
        assert "a***" in result or "a" in result

    def test_handles_none(self):
        """Test handling None input"""
        result = mask_email(None)

        assert result == "unknown"

    def test_handles_empty_string(self):
        """Test handling empty string"""
        result = mask_email("")

        assert result == "unknown"

    def test_handles_invalid_email(self):
        """Test handling string without @ symbol"""
        result = mask_email("notanemail")

        assert "no***" in result
        assert "@" not in result

    def test_preserves_tld(self):
        """Test that TLD is preserved"""
        result = mask_email("user@company.org")

        assert ".org" in result

    def test_handles_complex_domain(self):
        """Test handling email with complex domain"""
        result = mask_email("test@mail.company.co.uk")

        assert "@" in result
        assert ".uk" in result


class TestHashIdentifier:
    """Test identifier hashing function"""

    def test_creates_hashed_identifier(self):
        """Test creating a hashed identifier"""
        result = hash_identifier("user@example.com", "user")

        assert result.startswith("user_")
        assert len(result) == 13  # "user_" + 8 hex chars
        assert "example.com" not in result

    def test_consistent_hashing(self):
        """Test that same input produces same hash"""
        result1 = hash_identifier("test@test.com", "user")
        result2 = hash_identifier("test@test.com", "user")

        assert result1 == result2

    def test_different_inputs_different_hashes(self):
        """Test that different inputs produce different hashes"""
        result1 = hash_identifier("user1@test.com", "user")
        result2 = hash_identifier("user2@test.com", "user")

        assert result1 != result2

    def test_handles_none(self):
        """Test handling None input"""
        result = hash_identifier(None, "user")

        assert result == "user_unknown"

    def test_custom_prefix(self):
        """Test using custom prefix"""
        result = hash_identifier("test", "session")

        assert result.startswith("session_")


class TestMaskAccountId:
    """Test AWS account ID masking function"""

    def test_masks_standard_account_id(self):
        """Test masking a standard AWS account ID"""
        result = mask_account_id("123456789012")

        assert result == "1234****9012"

    def test_handles_none(self):
        """Test handling None input"""
        result = mask_account_id(None)

        assert result == "unknown"

    def test_handles_short_account_id(self):
        """Test handling shorter account IDs"""
        result = mask_account_id("1234")

        assert "****" in result

    def test_handles_account_id_with_dashes(self):
        """Test handling account ID with formatting"""
        result = mask_account_id("1234-5678-9012")

        assert result == "1234****9012"


class TestSanitizeException:
    """Test exception sanitization function"""

    def test_sanitizes_connection_string(self):
        """Test sanitizing connection strings"""
        exception = Exception("Failed to connect to postgresql://user:pass@localhost/db")
        result = sanitize_exception(exception)

        assert "postgresql://" not in result
        assert "[REDACTED_CONNECTION_STRING]" in result

    def test_sanitizes_aws_key(self):
        """Test sanitizing AWS access keys"""
        exception = Exception("Invalid credentials: AKIAIOSFODNN7EXAMPLE")
        result = sanitize_exception(exception)

        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "[REDACTED_AWS_KEY]" in result

    def test_sanitizes_email_in_error(self):
        """Test sanitizing email addresses in errors"""
        exception = Exception("User john@example.com not found")
        result = sanitize_exception(exception)

        assert "john@example.com" not in result
        assert "[REDACTED_EMAIL]" in result

    def test_sanitizes_ip_address(self):
        """Test sanitizing IP addresses"""
        exception = Exception("Connection refused from 192.168.1.100")
        result = sanitize_exception(exception)

        assert "192.168.1.100" not in result
        assert "[REDACTED_IP]" in result

    def test_truncates_long_messages(self):
        """Test truncating long exception messages"""
        long_message = "x" * 500
        exception = Exception(long_message)
        result = sanitize_exception(exception, max_length=200)

        assert len(result) <= 203  # 200 + "..."
        assert result.endswith("...")

    def test_handles_none(self):
        """Test handling None input"""
        result = sanitize_exception(None)

        assert result == "Unknown error"

    def test_sanitizes_password_patterns(self):
        """Test sanitizing password patterns"""
        exception = Exception("password=secret123")
        result = sanitize_exception(exception)

        assert "secret123" not in result
        assert "[REDACTED_CREDENTIAL]" in result


class TestMaskQueryForLogging:
    """Test query masking function"""

    def test_masks_email_in_query(self):
        """Test masking email addresses in queries"""
        query = "Find costs for user john@example.com"
        result = mask_query_for_logging(query)

        assert "john@example.com" not in result
        assert "[EMAIL]" in result

    def test_masks_phone_number(self):
        """Test masking phone numbers"""
        query = "Contact at 555-123-4567"
        result = mask_query_for_logging(query)

        assert "555-123-4567" not in result
        assert "[PHONE]" in result

    def test_masks_credit_card(self):
        """Test masking credit card numbers"""
        query = "Charge to 4111-1111-1111-1111"
        result = mask_query_for_logging(query)

        assert "4111-1111-1111-1111" not in result
        assert "[CARD]" in result

    def test_truncates_long_queries(self):
        """Test truncating long queries"""
        query = "optimize " + "x" * 200
        result = mask_query_for_logging(query, max_length=100)

        assert len(result) <= 103  # 100 + "..."
        assert result.endswith("...")

    def test_handles_empty_query(self):
        """Test handling empty query"""
        result = mask_query_for_logging("")

        assert result == "[empty]"

    def test_handles_none_query(self):
        """Test handling None query"""
        result = mask_query_for_logging(None)

        assert result == "[empty]"

    def test_preserves_safe_content(self):
        """Test that safe content is preserved"""
        query = "Show me EC2 cost optimization recommendations"
        result = mask_query_for_logging(query)

        assert "EC2" in result
        assert "optimization" in result


class TestCreateAuditContext:
    """Test audit context creation function"""

    def test_creates_context_with_all_fields(self):
        """Test creating context with all fields"""
        context = create_audit_context(
            user_email="user@example.com",
            account_id="123456789012",
            resource_id="abc-123"
        )

        assert "user" in context
        assert "user_masked" in context
        assert "account" in context
        assert "resource_id" in context

    def test_user_hash_is_consistent(self):
        """Test that user hash is consistent"""
        context1 = create_audit_context(user_email="user@example.com")
        context2 = create_audit_context(user_email="user@example.com")

        assert context1["user"] == context2["user"]

    def test_handles_partial_fields(self):
        """Test handling partial fields"""
        context = create_audit_context(user_email="user@example.com")

        assert "user" in context
        assert "account" not in context

    def test_handles_empty_call(self):
        """Test handling call with no arguments"""
        context = create_audit_context()

        assert context == {}

    def test_masks_account_id_in_context(self):
        """Test that account ID is masked in context"""
        context = create_audit_context(account_id="123456789012")

        assert context["account"] == "1234****9012"

    def test_preserves_resource_id(self):
        """Test that resource IDs are preserved"""
        context = create_audit_context(resource_id="uuid-abc-123")

        assert context["resource_id"] == "uuid-abc-123"
