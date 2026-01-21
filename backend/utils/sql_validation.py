"""
SQL Input Validation Utilities

Provides validation and sanitization for SQL query inputs to prevent
SQL injection attacks, particularly for AWS Athena queries where
parameterized queries are not fully supported.

IMPORTANT: Athena does not support traditional prepared statements with
parameter binding. All user input MUST be validated/sanitized before
being included in queries.
"""

import re
from typing import Optional, List, Set
from enum import Enum
import structlog

logger = structlog.get_logger(__name__)


class ValidationError(ValueError):
    """Raised when input validation fails"""
    pass


# Patterns for validation
SAFE_IDENTIFIER_PATTERN = re.compile(r'^[a-zA-Z][a-zA-Z0-9_-]*$')
SAFE_TAG_KEY_PATTERN = re.compile(r'^[a-zA-Z][a-zA-Z0-9_:/-]*$')
SAFE_TAG_VALUE_PATTERN = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_\-\s./]*$')
AWS_ACCOUNT_ID_PATTERN = re.compile(r'^\d{12}$')
AWS_REGION_PATTERN = re.compile(r'^[a-z]{2}-[a-z]+-\d$')
DATE_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$')
SAFE_RESOURCE_ID_PATTERN = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_\-:/\.]*$')

# SQL injection patterns to detect
SQL_INJECTION_PATTERNS = [
    re.compile(r"['\"].*?['\"]", re.IGNORECASE),  # Quoted strings
    re.compile(r"--"),  # SQL comments
    re.compile(r"/\*.*?\*/", re.DOTALL),  # Block comments
    re.compile(r";\s*(?:SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE)", re.IGNORECASE),
    re.compile(r"\bOR\b\s+['\"]?\d+['\"]?\s*=\s*['\"]?\d+['\"]?", re.IGNORECASE),  # OR 1=1
    re.compile(r"\bAND\b\s+['\"]?\d+['\"]?\s*=\s*['\"]?\d+['\"]?", re.IGNORECASE),  # AND 1=1
    re.compile(r"\bUNION\b.*?\bSELECT\b", re.IGNORECASE),  # UNION SELECT
    re.compile(r";\s*$"),  # Trailing semicolon
]

# Known AWS service codes (allowlist)
KNOWN_AWS_SERVICES: Set[str] = {
    "AmazonEC2", "AmazonS3", "AmazonRDS", "AWSLambda", "AmazonDynamoDB",
    "AmazonCloudWatch", "AmazonVPC", "AmazonRoute53", "AmazonSNS", "AmazonSQS",
    "AmazonElastiCache", "AmazonEFS", "AmazonEKS", "AmazonECS", "AmazonECR",
    "AWSCloudTrail", "AWSConfig", "AWSSecretsManager", "AWSSystemsManager",
    "AmazonKinesis", "AmazonRedshift", "AmazonAthena", "AWSGlue",
    "AmazonSageMaker", "AmazonComprehend", "AmazonRekognition", "AmazonTextract",
    "AmazonTranscribe", "AmazonTranslate", "AmazonPolly", "AmazonLex",
    "AWSCodeBuild", "AWSCodePipeline", "AWSCodeDeploy", "AWSCodeCommit",
    "AmazonCloudFront", "AmazonAPIGateway", "AWSAppSync", "AmazonCognito",
    "AWSAmplify", "AWSBatch", "AWSStep Functions", "AmazonMQ",
    "AmazonMSK", "AmazonDocumentDB", "AmazonNeptune", "AmazonQLDB",
    "AmazonTimestream", "AmazonKeyspaces", "AmazonMemoryDB",
    "AWSBackup", "AWSDataSync", "AWSTransfer", "AWSSnowball",
    "AmazonWorkSpaces", "AmazonAppStream", "AmazonConnect",
    "AWSDirectConnect", "AWSPrivateLink", "AWSTransitGateway",
    "AWSGlobalAccelerator", "AWSNetworkFirewall", "AWSShield",
    "AWSWAF", "AWSFirewallManager", "AmazonGuardDuty", "AmazonInspector",
    "AWSSecurityHub", "AWSArtifact", "AmazonMacie", "AWSDetective",
    "AWSIoT", "AWSIoTAnalytics", "AWSIoTEvents", "AWSIoTSiteWise",
    "AWSRoboMaker", "AWSGroundStation", "AWSOutposts", "AWSWavelength",
    "AWSLocalZones", "AmazonLightsail", "AWSElasticBeanstalk",
    "AmazonOpenSearch", "AmazonKendra", "AmazonPersonalize",
    "AmazonForecast", "AmazonFraudDetector", "AmazonDevOpsGuru",
    "AWSProton", "AWSAppRunner", "AmazonMWAA", "AWSDataExchange",
    "AWSMarketplace", "AWSSavingsPlans", "AWSCostExplorer",
    "AWSBudgets", "AWSCostAndUsageReport", "AmazonQuickSight",
    "AWSDataPipeline", "AmazonEMR", "AWSLakeFormation",
    # Common variations
    "Amazon Elastic Compute Cloud", "Amazon Simple Storage Service",
    "Amazon Relational Database Service", "AWS Lambda",
}

# Known AWS regions
KNOWN_AWS_REGIONS: Set[str] = {
    "us-east-1", "us-east-2", "us-west-1", "us-west-2",
    "eu-west-1", "eu-west-2", "eu-west-3", "eu-central-1", "eu-north-1",
    "eu-south-1", "eu-south-2", "eu-central-2",
    "ap-south-1", "ap-south-2", "ap-northeast-1", "ap-northeast-2", "ap-northeast-3",
    "ap-southeast-1", "ap-southeast-2", "ap-southeast-3", "ap-southeast-4",
    "ap-east-1", "sa-east-1", "ca-central-1", "ca-west-1",
    "me-south-1", "me-central-1", "af-south-1", "il-central-1",
    "us-gov-west-1", "us-gov-east-1",
    "cn-north-1", "cn-northwest-1",
    "global",  # For global services
}

# Known instance type patterns
INSTANCE_TYPE_PATTERN = re.compile(
    r'^[a-z][a-z0-9]*\d*[a-z]*\.(nano|micro|small|medium|large|xlarge|\d*xlarge|metal)$'
)

# Known operating systems
KNOWN_OPERATING_SYSTEMS: Set[str] = {
    "Linux", "Windows", "RHEL", "SUSE", "Ubuntu",
    "Amazon Linux", "Amazon Linux 2", "Amazon Linux 2023",
    "Windows Server", "Red Hat Enterprise Linux",
    "CentOS", "Debian", "macOS",
}

# Known database engines
KNOWN_DATABASE_ENGINES: Set[str] = {
    "mysql", "postgres", "postgresql", "mariadb", "oracle",
    "sqlserver", "sql-server", "aurora", "aurora-mysql", "aurora-postgresql",
    "neptune", "documentdb", "dynamodb", "redis", "memcached",
    "elasticsearch", "opensearch",
}


def contains_sql_injection(value: str) -> bool:
    """
    Check if a string contains potential SQL injection patterns.

    Args:
        value: String to check

    Returns:
        True if potential injection detected
    """
    if not value:
        return False

    for pattern in SQL_INJECTION_PATTERNS:
        if pattern.search(value):
            return True

    # Check for unbalanced quotes
    single_quotes = value.count("'")
    double_quotes = value.count('"')
    if single_quotes % 2 != 0 or double_quotes % 2 != 0:
        return True

    return False


def escape_sql_string(value: str) -> str:
    """
    Escape a string value for safe SQL inclusion.

    This escapes single quotes by doubling them (SQL standard).

    Args:
        value: String to escape

    Returns:
        Escaped string (without surrounding quotes)
    """
    if value is None:
        return ""
    return str(value).replace("'", "''")


def escape_like_pattern(value: str) -> str:
    """
    Escape LIKE wildcard characters in a string.

    Args:
        value: String to escape

    Returns:
        String with LIKE wildcards escaped
    """
    if value is None:
        return ""
    # Escape SQL string first, then LIKE wildcards
    escaped = escape_sql_string(value)
    escaped = escaped.replace("%", "\\%")
    escaped = escaped.replace("_", "\\_")
    return escaped


def validate_identifier(value: str, field_name: str = "identifier") -> str:
    """
    Validate a SQL identifier (column name, table name, etc.).

    Args:
        value: Value to validate
        field_name: Name for error messages

    Returns:
        Validated value

    Raises:
        ValidationError: If validation fails
    """
    if not value:
        raise ValidationError(f"{field_name} cannot be empty")

    value = str(value).strip()

    if len(value) > 128:
        raise ValidationError(f"{field_name} exceeds maximum length (128 characters)")

    if not SAFE_IDENTIFIER_PATTERN.match(value):
        raise ValidationError(
            f"Invalid {field_name}: must start with letter, contain only alphanumeric, underscore, or hyphen"
        )

    if contains_sql_injection(value):
        logger.warning(
            "SQL injection attempt detected in identifier",
            field=field_name,
            value_preview=value[:50]
        )
        raise ValidationError(f"Invalid {field_name}: contains prohibited characters")

    return value


def validate_service_code(value: str, strict: bool = False) -> str:
    """
    Validate an AWS service code.

    Args:
        value: Service code to validate
        strict: If True, only allow known services; if False, allow pattern-matching

    Returns:
        Validated service code

    Raises:
        ValidationError: If validation fails
    """
    if not value:
        raise ValidationError("Service code cannot be empty")

    value = str(value).strip()

    # Check against known services (case-insensitive)
    value_lower = value.lower()
    for known in KNOWN_AWS_SERVICES:
        if known.lower() == value_lower:
            return known  # Return canonical form

    if strict:
        raise ValidationError(f"Unknown service code: {value}")

    # For non-strict mode, validate pattern
    if not SAFE_IDENTIFIER_PATTERN.match(value):
        raise ValidationError(f"Invalid service code format: {value}")

    if contains_sql_injection(value):
        logger.warning("SQL injection attempt in service code", value=value[:50])
        raise ValidationError(f"Invalid service code: {value}")

    # Log unknown service for monitoring
    logger.info("Unknown service code used", service=value)
    return value


def validate_region(value: str) -> str:
    """
    Validate an AWS region code.

    Args:
        value: Region code to validate

    Returns:
        Validated region code

    Raises:
        ValidationError: If validation fails
    """
    if not value:
        raise ValidationError("Region cannot be empty")

    value = str(value).strip().lower()

    if value in KNOWN_AWS_REGIONS:
        return value

    # Check pattern for potentially new regions
    if AWS_REGION_PATTERN.match(value):
        logger.info("Unknown AWS region used", region=value)
        return value

    raise ValidationError(f"Invalid region: {value}")


def validate_account_id(value: str) -> str:
    """
    Validate an AWS account ID.

    Args:
        value: Account ID to validate

    Returns:
        Validated account ID

    Raises:
        ValidationError: If validation fails
    """
    if not value:
        raise ValidationError("Account ID cannot be empty")

    value = str(value).strip()

    if not AWS_ACCOUNT_ID_PATTERN.match(value):
        raise ValidationError(f"Invalid account ID: must be 12 digits")

    return value


def validate_tag_key(value: str) -> str:
    """
    Validate a tag key for use in column names.

    AWS tag keys can contain letters, numbers, and some special characters.
    For SQL safety, we're more restrictive.

    Args:
        value: Tag key to validate

    Returns:
        Validated and normalized tag key (lowercase, alphanumeric + underscore)

    Raises:
        ValidationError: If validation fails
    """
    if not value:
        raise ValidationError("Tag key cannot be empty")

    value = str(value).strip()

    if len(value) > 128:
        raise ValidationError("Tag key exceeds maximum length (128 characters)")

    # Normalize: lowercase, replace special chars with underscore
    normalized = value.lower()
    normalized = re.sub(r'[^a-z0-9]', '_', normalized)
    normalized = re.sub(r'_+', '_', normalized)  # Collapse multiple underscores
    normalized = normalized.strip('_')

    if not normalized:
        raise ValidationError(f"Tag key contains no valid characters: {value}")

    if not normalized[0].isalpha():
        normalized = 'tag_' + normalized

    return normalized


def validate_tag_value(value: str) -> str:
    """
    Validate and escape a tag value for SQL inclusion.

    Args:
        value: Tag value to validate

    Returns:
        Validated and escaped tag value

    Raises:
        ValidationError: If validation fails
    """
    if value is None:
        return ""

    value = str(value).strip()

    if len(value) > 256:
        raise ValidationError("Tag value exceeds maximum length (256 characters)")

    if contains_sql_injection(value):
        logger.warning("SQL injection attempt in tag value", value_preview=value[:50])
        raise ValidationError("Invalid tag value: contains prohibited characters")

    # Return escaped value
    return escape_sql_string(value)


def validate_instance_type(value: str) -> str:
    """
    Validate an EC2 instance type.

    Args:
        value: Instance type to validate (e.g., "m5.large")

    Returns:
        Validated instance type

    Raises:
        ValidationError: If validation fails
    """
    if not value:
        raise ValidationError("Instance type cannot be empty")

    value = str(value).strip().lower()

    if not INSTANCE_TYPE_PATTERN.match(value):
        # Check for common prefixes at least
        if not re.match(r'^[a-z][a-z0-9]*\d*[a-z]*\.', value):
            raise ValidationError(f"Invalid instance type format: {value}")

    if contains_sql_injection(value):
        raise ValidationError(f"Invalid instance type: {value}")

    return value


def validate_operating_system(value: str) -> str:
    """
    Validate an operating system name.

    Args:
        value: OS name to validate

    Returns:
        Validated OS name

    Raises:
        ValidationError: If validation fails
    """
    if not value:
        raise ValidationError("Operating system cannot be empty")

    value = str(value).strip()

    # Check against known OS (case-insensitive)
    value_lower = value.lower()
    for known in KNOWN_OPERATING_SYSTEMS:
        if known.lower() == value_lower:
            return known

    # Allow partial matches for flexibility
    for known in KNOWN_OPERATING_SYSTEMS:
        if value_lower in known.lower() or known.lower() in value_lower:
            return known

    # If not in known list, validate pattern
    if not SAFE_IDENTIFIER_PATTERN.match(value.replace(" ", "")):
        raise ValidationError(f"Invalid operating system: {value}")

    if contains_sql_injection(value):
        raise ValidationError(f"Invalid operating system: {value}")

    return escape_sql_string(value)


def validate_database_engine(value: str) -> str:
    """
    Validate a database engine name.

    Args:
        value: Database engine to validate

    Returns:
        Validated engine name

    Raises:
        ValidationError: If validation fails
    """
    if not value:
        raise ValidationError("Database engine cannot be empty")

    value = str(value).strip().lower()

    if value in KNOWN_DATABASE_ENGINES:
        return value

    # Check for partial match
    for known in KNOWN_DATABASE_ENGINES:
        if value in known or known in value:
            return known

    # Validate pattern for unknown engines
    if not re.match(r'^[a-z][a-z0-9_-]*$', value):
        raise ValidationError(f"Invalid database engine: {value}")

    if contains_sql_injection(value):
        raise ValidationError(f"Invalid database engine: {value}")

    logger.info("Unknown database engine used", engine=value)
    return escape_sql_string(value)


def validate_date(value: str) -> str:
    """
    Validate a date string in YYYY-MM-DD format.

    Args:
        value: Date string to validate

    Returns:
        Validated date string

    Raises:
        ValidationError: If validation fails
    """
    if not value:
        raise ValidationError("Date cannot be empty")

    value = str(value).strip()

    if not DATE_PATTERN.match(value):
        raise ValidationError(f"Invalid date format: {value}. Expected YYYY-MM-DD")

    # Basic range validation
    parts = value.split('-')
    year, month, day = int(parts[0]), int(parts[1]), int(parts[2])

    if year < 2000 or year > 2100:
        raise ValidationError(f"Invalid year: {year}")
    if month < 1 or month > 12:
        raise ValidationError(f"Invalid month: {month}")
    if day < 1 or day > 31:
        raise ValidationError(f"Invalid day: {day}")

    return value


def validate_resource_id(value: str) -> str:
    """
    Validate an AWS resource ID.

    Resource IDs can be instance IDs, ARNs, or other identifiers.

    Args:
        value: Resource ID to validate

    Returns:
        Validated and escaped resource ID

    Raises:
        ValidationError: If validation fails
    """
    if not value:
        raise ValidationError("Resource ID cannot be empty")

    value = str(value).strip()

    if len(value) > 512:
        raise ValidationError("Resource ID exceeds maximum length (512 characters)")

    # Check for SQL injection patterns
    if contains_sql_injection(value):
        logger.warning("SQL injection attempt in resource ID", value_preview=value[:50])
        raise ValidationError("Invalid resource ID: contains prohibited characters")

    # Validate pattern - resource IDs can contain colons (ARNs), slashes, etc.
    if not SAFE_RESOURCE_ID_PATTERN.match(value):
        raise ValidationError(f"Invalid resource ID format: {value[:50]}")

    return escape_sql_string(value)


def validate_filter_values(
    values: List[str],
    validator: callable,
    field_name: str = "values",
    max_count: int = 100
) -> List[str]:
    """
    Validate a list of filter values.

    Args:
        values: List of values to validate
        validator: Validation function to apply to each value
        field_name: Name for error messages
        max_count: Maximum number of values allowed

    Returns:
        List of validated values

    Raises:
        ValidationError: If validation fails
    """
    if not values:
        return []

    if len(values) > max_count:
        raise ValidationError(f"Too many {field_name}: maximum {max_count} allowed")

    validated = []
    for i, value in enumerate(values):
        try:
            validated.append(validator(value))
        except ValidationError as e:
            raise ValidationError(f"{field_name}[{i}]: {str(e)}")

    return validated


def build_safe_in_clause(values: List[str], validator: callable) -> str:
    """
    Build a safe IN clause from validated values.

    Args:
        values: List of values
        validator: Validation function to apply

    Returns:
        SQL IN clause content (without IN keyword), e.g., "'val1', 'val2'"
    """
    if not values:
        return "'__EMPTY__'"  # Return impossible match

    validated = validate_filter_values(values, validator)
    return ", ".join(f"'{v}'" for v in validated)


def build_safe_like_clause(value: str, column: str, position: str = "contains") -> str:
    """
    Build a safe LIKE clause.

    Args:
        value: Value to search for
        column: Column name (must be pre-validated)
        position: "contains", "starts", or "ends"

    Returns:
        Safe LIKE clause, e.g., "column LIKE '%value%'"
    """
    escaped = escape_like_pattern(value)

    if position == "starts":
        pattern = f"{escaped}%"
    elif position == "ends":
        pattern = f"%{escaped}"
    else:  # contains
        pattern = f"%{escaped}%"

    return f"{column} LIKE '{pattern}'"
