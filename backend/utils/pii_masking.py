"""
PII Masking Utilities for Logging

Provides functions to mask personally identifiable information (PII)
before logging to prevent sensitive data exposure.
"""

import hashlib
import re
from typing import Optional


def mask_email(email: Optional[str]) -> str:
    """
    Mask an email address for logging.

    Preserves first 2 characters of local part and domain for debugging,
    while masking the rest.

    Examples:
        john.doe@example.com -> jo***@ex***.com
        a@b.com -> a***@b***.com

    Args:
        email: Email address to mask

    Returns:
        Masked email string, or "unknown" if email is None/empty
    """
    if not email:
        return "unknown"

    try:
        if "@" not in email:
            # Not a valid email, just mask most of it
            return email[:2] + "***" if len(email) > 2 else "***"

        local, domain = email.rsplit("@", 1)

        # Mask local part (keep first 2 chars)
        masked_local = local[:2] + "***" if len(local) > 2 else local[0] + "***"

        # Mask domain (keep first 2 chars and TLD)
        if "." in domain:
            domain_parts = domain.rsplit(".", 1)
            domain_name = domain_parts[0]
            tld = domain_parts[1]
            masked_domain = domain_name[:2] + "***." + tld if len(domain_name) > 2 else domain_name + "***." + tld
        else:
            masked_domain = domain[:2] + "***" if len(domain) > 2 else domain + "***"

        return f"{masked_local}@{masked_domain}"
    except Exception:
        return "***@***.***"


def hash_identifier(identifier: Optional[str], prefix: str = "id") -> str:
    """
    Create a short hash of an identifier for correlation in logs.

    Useful when you need to correlate log entries without exposing
    the actual identifier.

    Args:
        identifier: The identifier to hash
        prefix: Prefix for the hash (e.g., "user", "session")

    Returns:
        A short hashed identifier like "user_a1b2c3"
    """
    if not identifier:
        return f"{prefix}_unknown"

    # Create SHA256 hash and take first 8 characters
    hash_value = hashlib.sha256(identifier.encode()).hexdigest()[:8]
    return f"{prefix}_{hash_value}"


def mask_account_id(account_id: Optional[str]) -> str:
    """
    Mask an AWS account ID for logging.

    Shows first 4 and last 4 digits.

    Example:
        123456789012 -> 1234****9012

    Args:
        account_id: AWS account ID to mask

    Returns:
        Masked account ID
    """
    if not account_id:
        return "unknown"

    # Remove any non-digit characters
    clean_id = re.sub(r"\D", "", account_id)

    if len(clean_id) <= 8:
        return clean_id[:2] + "****" + clean_id[-2:] if len(clean_id) >= 4 else "****"

    return clean_id[:4] + "****" + clean_id[-4:]


def sanitize_exception(exception: Optional[Exception], max_length: int = 200) -> str:
    """
    Sanitize an exception message for logging.

    Removes potentially sensitive information like:
    - File paths
    - Connection strings
    - Credentials
    - SQL queries

    Args:
        exception: The exception to sanitize
        max_length: Maximum length of the returned message

    Returns:
        Sanitized exception message
    """
    if not exception:
        return "Unknown error"

    message = str(exception)

    # Patterns to redact
    patterns = [
        # Connection strings
        (r"(postgresql|mysql|mongodb|redis)://[^\s]+", "[REDACTED_CONNECTION_STRING]"),
        # AWS credentials
        (r"AKIA[A-Z0-9]{16}", "[REDACTED_AWS_KEY]"),
        (r"(?i)(aws_secret_access_key|secret_key|password|passwd|pwd)\s*[=:]\s*\S+", "[REDACTED_CREDENTIAL]"),
        # API keys
        (r"(?i)(api[_-]?key|token|bearer)\s*[=:]\s*\S+", "[REDACTED_API_KEY]"),
        # File paths (keep basename only)
        (r"(/[a-zA-Z0-9_.-]+)+/([a-zA-Z0-9_.-]+\.(py|js|ts|json|yaml|yml))", r"[PATH]/\2"),
        # Email addresses in error messages
        (r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "[REDACTED_EMAIL]"),
        # IP addresses
        (r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "[REDACTED_IP]"),
        # SQL-like patterns (table names, etc.)
        (r"(?i)(INSERT INTO|UPDATE|DELETE FROM|SELECT .* FROM)\s+([a-zA-Z_]+)", r"\1 [TABLE]"),
    ]

    for pattern, replacement in patterns:
        message = re.sub(pattern, replacement, message)

    # Truncate if too long
    if len(message) > max_length:
        message = message[:max_length] + "..."

    return message


def mask_query_for_logging(query: str, max_length: int = 100) -> str:
    """
    Mask a user query for logging.

    Truncates long queries and redacts potential PII patterns.

    Args:
        query: The user query to mask
        max_length: Maximum length of logged query

    Returns:
        Masked/truncated query safe for logging
    """
    if not query:
        return "[empty]"

    # Redact email patterns
    masked = re.sub(
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        "[EMAIL]",
        query
    )

    # Redact phone numbers
    masked = re.sub(
        r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
        "[PHONE]",
        masked
    )

    # Redact credit card patterns
    masked = re.sub(
        r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b",
        "[CARD]",
        masked
    )

    # Truncate
    if len(masked) > max_length:
        masked = masked[:max_length] + "..."

    return masked


def create_audit_context(
    user_email: Optional[str] = None,
    account_id: Optional[str] = None,
    resource_id: Optional[str] = None,
) -> dict:
    """
    Create a sanitized audit context for logging.

    Args:
        user_email: User's email address
        account_id: AWS account ID
        resource_id: Resource identifier

    Returns:
        Dictionary with masked values safe for logging
    """
    context = {}

    if user_email:
        context["user"] = hash_identifier(user_email, "user")
        context["user_masked"] = mask_email(user_email)

    if account_id:
        context["account"] = mask_account_id(account_id)

    if resource_id:
        # Resource IDs (like UUIDs) are generally safe to log
        context["resource_id"] = resource_id

    return context
