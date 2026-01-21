"""
Tests for Error Handling Utilities
"""

import pytest
from fastapi import HTTPException

from backend.utils.errors import (
    ErrorCode,
    USER_FRIENDLY_MESSAGES,
    create_error_response,
    raise_not_found,
    raise_validation_error,
    raise_internal_error,
    raise_aws_error,
    handle_opportunity_error,
)


class TestErrorCode:
    """Test ErrorCode enum"""

    def test_error_codes_have_friendly_messages(self):
        """Test that all error codes have user-friendly messages"""
        for code in ErrorCode:
            assert code in USER_FRIENDLY_MESSAGES, f"Missing friendly message for {code}"

    def test_friendly_messages_are_user_safe(self):
        """Test that friendly messages don't contain internal details"""
        unsafe_terms = [
            "traceback",
            "stack",
            "exception",
            "sql",
            "query",
            "password",
            "secret",
            "key",
        ]

        for code, message in USER_FRIENDLY_MESSAGES.items():
            message_lower = message.lower()
            for term in unsafe_terms:
                assert term not in message_lower, \
                    f"Error message for {code} contains unsafe term '{term}'"


class TestCreateErrorResponse:
    """Test create_error_response function"""

    def test_creates_standard_format(self):
        """Test that error response has standard format"""
        response = create_error_response(ErrorCode.NOT_FOUND)

        assert "error" in response
        assert "code" in response["error"]
        assert "message" in response["error"]

    def test_uses_default_message(self):
        """Test that default user-friendly message is used"""
        response = create_error_response(ErrorCode.INTERNAL_ERROR)

        assert response["error"]["message"] == USER_FRIENDLY_MESSAGES[ErrorCode.INTERNAL_ERROR]

    def test_custom_message_overrides_default(self):
        """Test that custom message overrides default"""
        custom_message = "Custom error message"
        response = create_error_response(ErrorCode.NOT_FOUND, message=custom_message)

        assert response["error"]["message"] == custom_message

    def test_includes_details_when_provided(self):
        """Test that details are included when provided"""
        details = {"field": "email", "reason": "invalid format"}
        response = create_error_response(
            ErrorCode.VALIDATION_ERROR,
            details=details
        )

        assert "details" in response["error"]
        assert response["error"]["details"]["field"] == "email"


class TestRaiseNotFound:
    """Test raise_not_found function"""

    def test_raises_404(self):
        """Test that 404 status is raised"""
        with pytest.raises(HTTPException) as exc_info:
            raise_not_found("resource")

        assert exc_info.value.status_code == 404

    def test_includes_resource_type(self):
        """Test that resource type is in message"""
        with pytest.raises(HTTPException) as exc_info:
            raise_not_found("optimization opportunity")

        assert "optimization opportunity" in str(exc_info.value.detail)

    def test_includes_resource_id(self):
        """Test that resource ID is in message when provided"""
        with pytest.raises(HTTPException) as exc_info:
            raise_not_found("opportunity", "abc-123")

        assert "abc-123" in str(exc_info.value.detail)


class TestRaiseValidationError:
    """Test raise_validation_error function"""

    def test_raises_400(self):
        """Test that 400 status is raised"""
        with pytest.raises(HTTPException) as exc_info:
            raise_validation_error("Invalid input")

        assert exc_info.value.status_code == 400

    def test_includes_custom_message(self):
        """Test that custom message is included"""
        with pytest.raises(HTTPException) as exc_info:
            raise_validation_error("Email format is invalid")

        assert "Email format is invalid" in str(exc_info.value.detail)


class TestRaiseAwsError:
    """Test raise_aws_error function"""

    def test_raises_502_for_service_error(self):
        """Test that 502 status is raised for AWS errors"""
        with pytest.raises(HTTPException) as exc_info:
            raise_aws_error("Cost Explorer", "fetch recommendations")

        assert exc_info.value.status_code == 502

    def test_detects_permission_error(self):
        """Test that permission errors are detected"""
        permission_error = Exception("AccessDeniedException: User is not authorized")

        with pytest.raises(HTTPException) as exc_info:
            raise_aws_error("Cost Explorer", "fetch", permission_error)

        assert "permission" in str(exc_info.value.detail).lower()

    def test_detects_throttling_error(self):
        """Test that throttling errors are detected"""
        throttle_error = Exception("ThrottlingException: Rate exceeded")

        with pytest.raises(HTTPException) as exc_info:
            raise_aws_error("Trusted Advisor", "fetch", throttle_error)

        assert "rate limit" in str(exc_info.value.detail).lower()


class TestHandleOpportunityError:
    """Test handle_opportunity_error function"""

    def test_raises_404_for_not_found(self):
        """Test that not found errors are converted to 404"""
        not_found_error = Exception("Opportunity does not exist")

        with pytest.raises(HTTPException) as exc_info:
            handle_opportunity_error("retrieving", "abc-123", not_found_error)

        assert exc_info.value.status_code == 404

    def test_raises_500_for_generic_error(self):
        """Test that generic errors become 500"""
        generic_error = Exception("Some unexpected error")

        with pytest.raises(HTTPException) as exc_info:
            handle_opportunity_error("updating", "abc-123", generic_error)

        assert exc_info.value.status_code == 500
        # Should NOT expose the actual error message
        assert "unexpected error" not in str(exc_info.value.detail).lower()
