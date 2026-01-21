"""
Centralized Error Handling Utilities

Provides user-friendly error messages and consistent error response format.
"""

from typing import Optional, Dict, Any
from enum import Enum
import structlog
from fastapi import HTTPException, status

logger = structlog.get_logger(__name__)


class ErrorCode(str, Enum):
    """Standard error codes for consistent API responses"""
    # General errors
    INTERNAL_ERROR = "INTERNAL_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"

    # Authentication/Authorization
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"

    # Resource-specific errors
    OPPORTUNITY_NOT_FOUND = "OPPORTUNITY_NOT_FOUND"
    OPPORTUNITY_ALREADY_EXISTS = "OPPORTUNITY_ALREADY_EXISTS"
    INVALID_STATUS_TRANSITION = "INVALID_STATUS_TRANSITION"

    # AWS integration errors
    AWS_SERVICE_ERROR = "AWS_SERVICE_ERROR"
    AWS_PERMISSION_ERROR = "AWS_PERMISSION_ERROR"
    AWS_RATE_LIMITED = "AWS_RATE_LIMITED"

    # Database errors
    DATABASE_ERROR = "DATABASE_ERROR"
    DATABASE_CONNECTION_ERROR = "DATABASE_CONNECTION_ERROR"

    # Export errors
    EXPORT_FORMAT_NOT_SUPPORTED = "EXPORT_FORMAT_NOT_SUPPORTED"


# User-friendly error messages (do not expose internal details)
USER_FRIENDLY_MESSAGES = {
    ErrorCode.INTERNAL_ERROR: "An unexpected error occurred. Please try again later.",
    ErrorCode.VALIDATION_ERROR: "The request contains invalid data. Please check your input.",
    ErrorCode.NOT_FOUND: "The requested resource was not found.",
    ErrorCode.CONFLICT: "The operation conflicts with the current state of the resource.",
    ErrorCode.RATE_LIMITED: "Too many requests. Please wait a moment before trying again.",

    ErrorCode.UNAUTHORIZED: "Authentication is required to access this resource.",
    ErrorCode.FORBIDDEN: "You don't have permission to perform this action.",

    ErrorCode.OPPORTUNITY_NOT_FOUND: "The optimization opportunity was not found.",
    ErrorCode.OPPORTUNITY_ALREADY_EXISTS: "An opportunity with this identifier already exists.",
    ErrorCode.INVALID_STATUS_TRANSITION: "This status change is not allowed.",

    ErrorCode.AWS_SERVICE_ERROR: "Unable to connect to AWS services. Please try again later.",
    ErrorCode.AWS_PERMISSION_ERROR: "Insufficient AWS permissions. Please contact your administrator.",
    ErrorCode.AWS_RATE_LIMITED: "AWS rate limit reached. Please wait a moment before trying again.",

    ErrorCode.DATABASE_ERROR: "A database error occurred. Please try again later.",
    ErrorCode.DATABASE_CONNECTION_ERROR: "Unable to connect to the database. Please try again later.",

    ErrorCode.EXPORT_FORMAT_NOT_SUPPORTED: "The requested export format is not supported.",
}


def create_error_response(
    code: ErrorCode,
    message: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Create a standardized error response.

    Args:
        code: Error code enum
        message: Optional custom message (defaults to user-friendly message)
        details: Optional additional details (be careful not to expose sensitive info)

    Returns:
        Standardized error response dict
    """
    return {
        "error": {
            "code": code.value,
            "message": message or USER_FRIENDLY_MESSAGES.get(code, USER_FRIENDLY_MESSAGES[ErrorCode.INTERNAL_ERROR]),
            **({"details": details} if details else {}),
        }
    }


def raise_not_found(
    resource_type: str = "resource",
    resource_id: Optional[str] = None,
) -> None:
    """
    Raise a 404 Not Found error with user-friendly message.

    Args:
        resource_type: Type of resource (e.g., "opportunity", "account")
        resource_id: Optional resource identifier
    """
    message = f"The {resource_type} was not found."
    if resource_id:
        message = f"The {resource_type} with ID '{resource_id}' was not found."

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=create_error_response(ErrorCode.NOT_FOUND, message),
    )


def raise_validation_error(
    message: str,
    field: Optional[str] = None,
) -> None:
    """
    Raise a 400 Validation error with user-friendly message.

    Args:
        message: Description of what's invalid
        field: Optional field name that has the error
    """
    details = {"field": field} if field else None

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=create_error_response(ErrorCode.VALIDATION_ERROR, message, details),
    )


def raise_internal_error(
    log_message: str,
    exception: Optional[Exception] = None,
    user_message: Optional[str] = None,
) -> None:
    """
    Raise a 500 Internal Server Error with user-friendly message.

    Logs the actual error for debugging but returns sanitized message to user.

    Args:
        log_message: Detailed message for logs (not shown to user)
        exception: Optional exception to log
        user_message: Optional custom user-facing message
    """
    # Log the actual error for debugging
    if exception:
        logger.error(log_message, error=str(exception), exc_info=True)
    else:
        logger.error(log_message)

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=create_error_response(
            ErrorCode.INTERNAL_ERROR,
            user_message or USER_FRIENDLY_MESSAGES[ErrorCode.INTERNAL_ERROR],
        ),
    )


def raise_aws_error(
    service: str,
    operation: str,
    exception: Optional[Exception] = None,
) -> None:
    """
    Raise an error for AWS service failures with user-friendly message.

    Args:
        service: AWS service name (e.g., "Cost Explorer", "Trusted Advisor")
        operation: Operation that failed (e.g., "fetch recommendations")
        exception: Optional exception to log
    """
    log_message = f"AWS {service} error during {operation}"
    if exception:
        logger.error(log_message, error=str(exception), exc_info=True)

    # Check for specific AWS error types
    error_str = str(exception).lower() if exception else ""

    if "accessdenied" in error_str or "unauthorized" in error_str:
        code = ErrorCode.AWS_PERMISSION_ERROR
        user_message = f"Insufficient permissions to access {service}. Please contact your administrator."
    elif "throttl" in error_str or "rate" in error_str:
        code = ErrorCode.AWS_RATE_LIMITED
        user_message = f"{service} rate limit reached. Please wait a moment and try again."
    else:
        code = ErrorCode.AWS_SERVICE_ERROR
        user_message = f"Unable to retrieve data from {service}. Please try again later."

    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=create_error_response(code, user_message),
    )


def raise_database_error(
    operation: str,
    exception: Optional[Exception] = None,
) -> None:
    """
    Raise an error for database failures with user-friendly message.

    Args:
        operation: Operation that failed (e.g., "saving opportunity")
        exception: Optional exception to log
    """
    log_message = f"Database error during {operation}"
    if exception:
        logger.error(log_message, error=str(exception), exc_info=True)

    # Check for connection errors
    error_str = str(exception).lower() if exception else ""

    if "connection" in error_str or "connect" in error_str:
        code = ErrorCode.DATABASE_CONNECTION_ERROR
    else:
        code = ErrorCode.DATABASE_ERROR

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=create_error_response(code),
    )


def handle_opportunity_error(
    operation: str,
    opportunity_id: Optional[str] = None,
    exception: Optional[Exception] = None,
) -> None:
    """
    Handle opportunity-related errors with appropriate user-friendly messages.

    Args:
        operation: Operation that failed (e.g., "retrieving", "updating", "deleting")
        opportunity_id: Optional opportunity ID
        exception: Optional exception
    """
    log_message = f"Error {operation} opportunity"
    if opportunity_id:
        log_message += f" {opportunity_id}"

    if exception:
        logger.error(log_message, error=str(exception), exc_info=True)

        error_str = str(exception).lower()

        # Check for specific error types
        if "not found" in error_str or "does not exist" in error_str:
            raise_not_found("optimization opportunity", opportunity_id)
        elif "duplicate" in error_str or "unique" in error_str:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=create_error_response(
                    ErrorCode.OPPORTUNITY_ALREADY_EXISTS,
                    "An opportunity with this identifier already exists.",
                ),
            )
        elif "connection" in error_str:
            raise_database_error(operation, exception)

    # Default to internal error
    raise_internal_error(
        log_message,
        exception,
        f"Unable to {operation} the opportunity. Please try again later.",
    )
