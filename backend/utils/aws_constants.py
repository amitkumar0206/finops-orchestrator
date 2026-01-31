"""
AWS Constants

Centralizes AWS-related string literals used across the codebase.
This improves maintainability, consistency, and allows easy configuration
for different SaaS clients with varying AWS setups.

Usage:
    from backend.utils.aws_constants import (
        AwsService,
        AwsRegion,
        COST_EXPLORER_REGION,
    )
"""

from typing import Set


# =============================================================================
# AWS SERVICE NAMES
# =============================================================================

class AwsService:
    """
    AWS service name constants for boto3 client/resource creation.

    These are the service names used with boto3.client() and boto3.resource().
    Centralizing them ensures consistency and makes it easy to update
    if AWS changes service identifiers.

    Usage:
        from backend.utils.aws_constants import AwsService
        client = create_aws_client(AwsService.S3)
        athena = create_aws_client(AwsService.ATHENA)
    """
    # Storage
    S3 = "s3"

    # Analytics & Query
    ATHENA = "athena"

    # Cost Management
    COST_EXPLORER = "ce"
    COST_AND_USAGE_REPORTS = "cur"

    # Compute
    EC2 = "ec2"
    LAMBDA = "lambda"
    ECS = "ecs"
    EKS = "eks"

    # Database
    RDS = "rds"
    DYNAMODB = "dynamodb"
    REDSHIFT = "redshift"

    # AI/ML
    BEDROCK = "bedrock"
    BEDROCK_RUNTIME = "bedrock-runtime"
    SAGEMAKER = "sagemaker"

    # Security & Identity
    IAM = "iam"
    STS = "sts"
    SECRETS_MANAGER = "secretsmanager"
    KMS = "kms"

    # Monitoring & Logging
    CLOUDWATCH = "cloudwatch"
    CLOUDWATCH_LOGS = "logs"

    # Optimization
    COMPUTE_OPTIMIZER = "compute-optimizer"
    TRUSTED_ADVISOR = "support"  # Trusted Advisor is part of support API

    # Networking
    VPC = "ec2"  # VPC operations are part of EC2 API
    ROUTE53 = "route53"
    CLOUDFRONT = "cloudfront"
    ELB = "elbv2"

    # Application Services
    SNS = "sns"
    SQS = "sqs"
    EVENTBRIDGE = "events"
    STEP_FUNCTIONS = "stepfunctions"


# =============================================================================
# AWS REGIONS
# =============================================================================

class AwsRegion:
    """
    AWS region constants.

    Contains commonly used regions and special regions for global services.

    Usage:
        from backend.utils.aws_constants import AwsRegion
        client = create_aws_client(AwsService.COST_EXPLORER, region_name=AwsRegion.US_EAST_1)
    """
    # US Regions
    US_EAST_1 = "us-east-1"  # N. Virginia (primary for many global services)
    US_EAST_2 = "us-east-2"  # Ohio
    US_WEST_1 = "us-west-1"  # N. California
    US_WEST_2 = "us-west-2"  # Oregon

    # Europe Regions
    EU_WEST_1 = "eu-west-1"  # Ireland
    EU_WEST_2 = "eu-west-2"  # London
    EU_WEST_3 = "eu-west-3"  # Paris
    EU_CENTRAL_1 = "eu-central-1"  # Frankfurt
    EU_NORTH_1 = "eu-north-1"  # Stockholm
    EU_SOUTH_1 = "eu-south-1"  # Milan

    # Asia Pacific Regions
    AP_SOUTH_1 = "ap-south-1"  # Mumbai
    AP_NORTHEAST_1 = "ap-northeast-1"  # Tokyo
    AP_NORTHEAST_2 = "ap-northeast-2"  # Seoul
    AP_NORTHEAST_3 = "ap-northeast-3"  # Osaka
    AP_SOUTHEAST_1 = "ap-southeast-1"  # Singapore
    AP_SOUTHEAST_2 = "ap-southeast-2"  # Sydney

    # Other Regions
    SA_EAST_1 = "sa-east-1"  # São Paulo
    CA_CENTRAL_1 = "ca-central-1"  # Canada
    ME_SOUTH_1 = "me-south-1"  # Bahrain
    AF_SOUTH_1 = "af-south-1"  # Cape Town

    # GovCloud Regions
    US_GOV_WEST_1 = "us-gov-west-1"
    US_GOV_EAST_1 = "us-gov-east-1"

    # China Regions
    CN_NORTH_1 = "cn-north-1"  # Beijing
    CN_NORTHWEST_1 = "cn-northwest-1"  # Ningxia

    # Global (for global services like IAM, Route53)
    GLOBAL = "global"


# =============================================================================
# SERVICE-SPECIFIC REGION REQUIREMENTS
# =============================================================================

# Cost Explorer API is ONLY available in us-east-1
# This is an AWS limitation, not a configuration choice
COST_EXPLORER_REGION = AwsRegion.US_EAST_1

# Cost and Usage Reports API is ONLY available in us-east-1
CUR_API_REGION = AwsRegion.US_EAST_1

# IAM is a global service but API calls go through us-east-1
IAM_REGION = AwsRegion.US_EAST_1

# Route53 is global
ROUTE53_REGION = AwsRegion.US_EAST_1

# CloudFront is global
CLOUDFRONT_REGION = AwsRegion.US_EAST_1

# Trusted Advisor (Support API) is ONLY available in us-east-1
TRUSTED_ADVISOR_REGION = AwsRegion.US_EAST_1


# =============================================================================
# KNOWN AWS REGIONS SET (for validation)
# =============================================================================

# Re-export from sql_validation for convenience
# This allows validation of user-provided regions
KNOWN_AWS_REGIONS: Set[str] = {
    AwsRegion.US_EAST_1, AwsRegion.US_EAST_2, AwsRegion.US_WEST_1, AwsRegion.US_WEST_2,
    AwsRegion.EU_WEST_1, AwsRegion.EU_WEST_2, AwsRegion.EU_WEST_3,
    AwsRegion.EU_CENTRAL_1, AwsRegion.EU_NORTH_1, AwsRegion.EU_SOUTH_1,
    AwsRegion.AP_SOUTH_1, AwsRegion.AP_NORTHEAST_1, AwsRegion.AP_NORTHEAST_2,
    AwsRegion.AP_NORTHEAST_3, AwsRegion.AP_SOUTHEAST_1, AwsRegion.AP_SOUTHEAST_2,
    AwsRegion.SA_EAST_1, AwsRegion.CA_CENTRAL_1,
    AwsRegion.ME_SOUTH_1, AwsRegion.AF_SOUTH_1,
    AwsRegion.US_GOV_WEST_1, AwsRegion.US_GOV_EAST_1,
    AwsRegion.CN_NORTH_1, AwsRegion.CN_NORTHWEST_1,
    AwsRegion.GLOBAL,
    # Additional regions from sql_validation.py
    "eu-south-2", "eu-central-2",
    "ap-south-2", "ap-southeast-3", "ap-southeast-4", "ap-east-1",
    "ca-west-1", "me-central-1", "il-central-1",
}


# =============================================================================
# DEFAULT FALLBACK REGION
# =============================================================================

# Default region used when settings are not available
# This should match the default in settings.py
DEFAULT_AWS_REGION = AwsRegion.US_EAST_1
