"""
Standardized column name constants for unified query outputs.
All SQL templates and data processors should use these column names for consistency.
"""

# ============================================================================
# STANDARDIZED OUTPUT COLUMNS
# ============================================================================
# These are the canonical column names returned by all query templates
# and consumed by formatter, chart builder, and frontend.

# Primary dimension column - the "what" being grouped/analyzed
DIMENSION_VALUE = "dimension_value"

# Service identifier - which AWS service
SERVICE = "service"

# Geographic region
REGION = "region"

# Cost amount in USD
COST_USD = "cost_usd"

# Account identifier
ACCOUNT = "account"

# Time period (for temporal queries)
TIME_PERIOD = "time_period"

# Resource type (for ARN fallback queries)
RESOURCE_TYPE = "resource_type"

# Usage metrics
USAGE_AMOUNT = "usage_amount"
DAYS_WITH_USAGE = "days_with_usage"

# ============================================================================
# STANDARDIZED COLUMN SETS
# ============================================================================

# Minimum required columns for chart rendering
CHART_REQUIRED_COLUMNS = {DIMENSION_VALUE, COST_USD}

# ARN fallback result columns
ARN_FALLBACK_COLUMNS = {DIMENSION_VALUE, SERVICE, REGION, COST_USD, DAYS_WITH_USAGE, RESOURCE_TYPE}

# Standard breakdown columns
BREAKDOWN_COLUMNS = {DIMENSION_VALUE, SERVICE, REGION, COST_USD}

# Temporal trend columns
TREND_COLUMNS = {TIME_PERIOD, SERVICE, COST_USD}

# ============================================================================
# CHARGE TYPE SYNONYMS
# ============================================================================
# Mapping of user-friendly terms to canonical AWS CUR charge type values

CHARGE_TYPE_SYNONYMS = {
    "tax": "Tax",
    "taxes": "Tax",
    "credit": "Credit",
    "credits": "Credit",
    "promo credit": "Credit",
    "refund": "Refund",
    "refunds": "Refund",
    "fee": "Fee",
    "fees": "Fee",
    "support": "Support",
    "edp": "EdpDiscount",
    "discount": "DiscountedUsage",
}
