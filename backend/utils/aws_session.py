"""
AWS Session Factory

Provides secure AWS session creation using IAM roles and the default credential chain.
This module ensures AWS credentials are NOT stored in application memory.

Security Best Practices:
- Uses boto3's default credential chain (IAM roles > environment > config files)
- Never stores explicit credentials in application memory
- Logs deprecation warnings if explicit credentials are configured
- Supports all AWS deployment patterns (EC2, ECS, Lambda, local development)

Credential Resolution Order (boto3 default chain):
1. IAM role credentials (EC2 instance profile, ECS task role, Lambda execution role)
2. Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
3. Shared credentials file (~/.aws/credentials)
4. AWS config file (~/.aws/config)
5. Assume role provider
6. Container credential provider (ECS)
7. Instance metadata service (EC2)
"""

import warnings
from typing import Optional, Any
from functools import lru_cache

import boto3
from botocore.config import Config
import structlog

from backend.utils.aws_constants import (
    AwsService,
    AwsRegion,
    DEFAULT_AWS_REGION,
)

logger = structlog.get_logger(__name__)


def _check_explicit_credentials_configured() -> bool:
    """
    Check if explicit AWS credentials are configured in settings.

    Returns True if credentials are explicitly set (which is discouraged).
    Logs a deprecation warning if found.
    """
    try:
        from backend.config.settings import get_settings
        settings = get_settings()

        has_explicit_creds = bool(
            settings.aws_access_key_id and settings.aws_secret_access_key
        )

        if has_explicit_creds:
            logger.warning(
                "explicit_aws_credentials_configured",
                message=(
                    "SECURITY WARNING: Explicit AWS credentials are configured. "
                    "This is deprecated and insecure. Use IAM roles instead. "
                    "Credentials will be ignored in favor of the default credential chain."
                )
            )
            warnings.warn(
                "Explicit AWS credentials (AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY) are deprecated. "
                "Use IAM roles for EC2/ECS/Lambda or the default credential chain for local development. "
                "These settings will be removed in a future version.",
                DeprecationWarning,
                stacklevel=3
            )

        return has_explicit_creds
    except Exception:
        return False


def create_aws_session(
    region_name: Optional[str] = None,
    profile_name: Optional[str] = None,
) -> boto3.Session:
    """
    Create an AWS session using the default credential chain.

    SECURITY: This function intentionally does NOT accept explicit credentials.
    It relies on boto3's default credential chain which supports:
    - IAM roles (recommended for AWS deployments)
    - Environment variables (for local development)
    - Shared credentials file (for local development)

    Args:
        region_name: AWS region (defaults to settings.aws_region)
        profile_name: Optional AWS profile name for local development

    Returns:
        boto3.Session configured with the default credential chain

    Example:
        session = create_aws_session()
        s3_client = session.client('s3')
        athena_client = session.client('athena')
    """
    # Check for deprecated explicit credentials (logs warning if found)
    _check_explicit_credentials_configured()

    # Get default region from settings if not provided
    if region_name is None:
        try:
            from backend.config.settings import get_settings
            settings = get_settings()
            region_name = settings.aws_region
        except Exception:
            region_name = DEFAULT_AWS_REGION

    # Create session using default credential chain (NO explicit credentials)
    session_kwargs = {"region_name": region_name}
    if profile_name:
        session_kwargs["profile_name"] = profile_name

    session = boto3.Session(**session_kwargs)

    logger.debug(
        "aws_session_created",
        region=region_name,
        profile=profile_name,
        credential_method="default_chain"
    )

    return session


def create_aws_client(
    service_name: str,
    region_name: Optional[str] = None,
    config: Optional[Config] = None,
) -> Any:
    """
    Create an AWS service client using the default credential chain.

    Args:
        service_name: AWS service name (e.g., 's3', 'athena', 'ce')
        region_name: AWS region (defaults to settings.aws_region)
        config: Optional botocore Config for retry/timeout settings

    Returns:
        boto3 service client

    Example:
        athena = create_aws_client('athena')
        s3 = create_aws_client('s3')
        ce = create_aws_client('ce', region_name=COST_EXPLORER_REGION)
    """
    session = create_aws_session(region_name=region_name)

    client_kwargs = {}
    if config:
        client_kwargs["config"] = config

    return session.client(service_name, **client_kwargs)


def create_aws_resource(
    service_name: str,
    region_name: Optional[str] = None,
    config: Optional[Config] = None,
) -> Any:
    """
    Create an AWS service resource using the default credential chain.

    Args:
        service_name: AWS service name (e.g., 's3', 'dynamodb')
        region_name: AWS region (defaults to settings.aws_region)
        config: Optional botocore Config for retry/timeout settings

    Returns:
        boto3 service resource

    Example:
        s3 = create_aws_resource('s3')
        bucket = s3.Bucket('my-bucket')
    """
    session = create_aws_session(region_name=region_name)

    resource_kwargs = {}
    if config:
        resource_kwargs["config"] = config

    return session.resource(service_name, **resource_kwargs)


def get_default_retry_config(
    max_attempts: int = 3,
    mode: str = "adaptive",
    max_pool_connections: int = 50,
) -> Config:
    """
    Get a standard botocore Config with retry settings.

    Args:
        max_attempts: Maximum retry attempts
        mode: Retry mode ('legacy', 'standard', 'adaptive')
        max_pool_connections: Connection pool size

    Returns:
        botocore.config.Config instance
    """
    try:
        from backend.config.settings import get_settings
        settings = get_settings()
        region = settings.aws_region
    except Exception:
        region = DEFAULT_AWS_REGION

    return Config(
        region_name=region,
        retries={
            "max_attempts": max_attempts,
            "mode": mode,
        },
        max_pool_connections=max_pool_connections,
    )


def verify_aws_credentials() -> dict:
    """
    Verify that AWS credentials are available and valid.

    Returns:
        dict with credential verification results

    Example:
        result = verify_aws_credentials()
        if result['valid']:
            print(f"Using credentials for: {result['identity']}")
    """
    try:
        session = create_aws_session()
        sts = session.client(AwsService.STS)
        identity = sts.get_caller_identity()

        return {
            "valid": True,
            "identity": {
                "account": identity.get("Account"),
                "arn": identity.get("Arn"),
                "user_id": identity.get("UserId"),
            },
            "method": "default_credential_chain",
            "error": None,
        }
    except Exception as e:
        logger.error("aws_credential_verification_failed", error=str(e))
        return {
            "valid": False,
            "identity": None,
            "method": "default_credential_chain",
            "error": str(e),
        }
