from __future__ import annotations

"""
DEPRECATED: This file is deprecated and will be removed in a future version.
Use unified_query_processor.py instead for all query processing.

This file is kept only for backward compatibility during migration.
"""

"""Universal Parameter Schema (UPS) extractor (shadow mode).

Generates a normalized JSON structure for any FinOps cost query using the LLM.
Shadow mode: does NOT alter existing behavior yet; used for evaluation + diff logging.

If LLM unavailable or invalid JSON output, falls back to heuristic extraction.
"""

import json
import os
import re
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timedelta
import structlog
from pydantic import BaseModel, Field, validator

from backend.services.llm_service import llm_service
from backend.services.repair_layer import repair_json

logger = structlog.get_logger(__name__)

SCHEMA_VERSION = "1.0"

# Canonical reference values for advanced filtering
VALID_CHARGE_TYPES = {
    "Usage",
    "Tax",
    "Credit",
    "Refund",
    "Fee",
    "RIFee",
    "SavingsPlanCoveredUsage",
    "SavingsPlanRecurringCharge",
    "SavingsPlanNegation",
    "SavingsPlanUpfrontFee",
    "DiscountedUsage",
    "EdpDiscount",
    "PrivateRateDiscount",
    "Support",
}

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

PURCHASE_OPTION_SYNONYMS = {
    "on-demand": "On-Demand",
    "ondemand": "On-Demand",
    "on demand": "On-Demand",
    "reserved": "Reserved",
    "ri": "Reserved",
    "reservation": "Reserved",
    "reservations": "Reserved",
    "standard reserved": "Reserved",
    "convertible reserved": "Reserved",
    "spot": "Spot",
    "spot instance": "Spot",
    "spot instances": "Spot",
    "savings plan": "SavingsPlan",
    "savings plans": "SavingsPlan",
    "sp": "SavingsPlan",
    "savingsplan": "SavingsPlan",
}

PLATFORM_SYNONYMS = {
    "linux": "Linux",
    "windows": "Windows",
    "red hat": "Red Hat Enterprise Linux",
    "rhel": "Red Hat Enterprise Linux",
    "suse": "SUSE Linux",
    "ubuntu": "Ubuntu",
}

DATABASE_ENGINE_SYNONYMS = {
    "mysql": "MySQL",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "aurora": "Aurora",
    "sql server": "SQL Server",
    "mssql": "SQL Server",
    "oracle": "Oracle",
    "mariadb": "MariaDB",
}

TAG_KEY_NORMALIZATION = {
    "env": "Environment",
    "environment": "Environment",
    "application": "Application",
    "app": "Application",
    "costcenter": "CostCenter",
    "cost_center": "CostCenter",
    "cost-centre": "CostCenter",
    "owner": "Owner",
    "product": "Product",
    "team": "Team",
    "project": "Project",
}


def _normalize_simple_token(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = value.strip()
    return cleaned or None


def _normalize_charge_type(value: Optional[str]) -> Optional[str]:
    token = _normalize_simple_token(value)
    if not token:
        return None
    normalized = CHARGE_TYPE_SYNONYMS.get(token.lower(), token)
    if normalized not in VALID_CHARGE_TYPES:
        # Title-case unknown values but allow them to flow through for visibility
        normalized = normalized.strip().title()
    return normalized


def _normalize_from_mapping(value: Optional[str], mapping: Dict[str, str]) -> Optional[str]:
    token = _normalize_simple_token(value)
    if not token:
        return None
    lower = token.lower()
    return mapping.get(lower, token.strip().title())


def _normalize_tag_key(key: str) -> str:
    token = (key or "").strip().lower().replace(" ", "")
    if not token:
        return "Unknown"
    return TAG_KEY_NORMALIZATION.get(token, key.strip().title())


def _unique(values: List[str]) -> List[str]:
    seen: List[str] = []
    for val in values:
        if val and val not in seen:
            seen.append(val)
    return seen


# ============================================================================
# LLM VALIDATION LAYER (Option 2 + Option 3)
# ============================================================================

class FilterValidator:
    """Validates LLM-extracted filter values against canonical values."""
    
    @staticmethod
    def validate_charge_types(
        values: Optional[List[str]]
    ) -> Tuple[Optional[List[str]], List[str]]:
        """
        Validate charge types against canonical values.
        
        Returns:
            Tuple of (valid_values, invalid_values)
        """
        if not values:
            return None, []
        
        valid = []
        invalid = []
        
        for value in values:
            # Check if it's already a valid canonical value
            if value in VALID_CHARGE_TYPES:
                valid.append(value)
            # Check if it's a known synonym
            elif value.lower() in CHARGE_TYPE_SYNONYMS:
                canonical = CHARGE_TYPE_SYNONYMS[value.lower()]
                if canonical in VALID_CHARGE_TYPES:
                    valid.append(canonical)
                else:
                    invalid.append(value)
            else:
                invalid.append(value)
        
        return valid or None, invalid
    
    @staticmethod
    def validate_purchase_options(
        values: Optional[List[str]]
    ) -> Tuple[Optional[List[str]], List[str]]:
        """
        Validate purchase options against canonical values.
        
        Returns:
            Tuple of (valid_values, invalid_values)
        """
        if not values:
            return None, []
        
        canonical_options = {"On-Demand", "Reserved", "Spot", "SavingsPlan"}
        valid = []
        invalid = []
        
        for value in values:
            # Check if it's already canonical
            if value in canonical_options:
                valid.append(value)
            # Check if it's a known synonym
            elif value.lower() in PURCHASE_OPTION_SYNONYMS:
                canonical = PURCHASE_OPTION_SYNONYMS[value.lower()]
                valid.append(canonical)
            else:
                invalid.append(value)
        
        return valid or None, invalid
    
    @staticmethod
    def validate_platforms(
        values: Optional[List[str]]
    ) -> Tuple[Optional[List[str]], List[str]]:
        """
        Validate platform/OS values against canonical values.
        
        Returns:
            Tuple of (valid_values, invalid_values)
        """
        if not values:
            return None, []
        
        canonical_platforms = {
            "Linux", "Windows", "Red Hat Enterprise Linux", 
            "SUSE Linux", "Ubuntu"
        }
        valid = []
        invalid = []
        
        for value in values:
            if value in canonical_platforms:
                valid.append(value)
            elif value.lower() in PLATFORM_SYNONYMS:
                canonical = PLATFORM_SYNONYMS[value.lower()]
                valid.append(canonical)
            else:
                invalid.append(value)
        
        return valid or None, invalid
    
    @staticmethod
    def validate_database_engines(
        values: Optional[List[str]]
    ) -> Tuple[Optional[List[str]], List[str]]:
        """
        Validate database engine values against canonical values.
        
        Returns:
            Tuple of (valid_values, invalid_values)
        """
        if not values:
            return None, []
        
        canonical_engines = {
            "MySQL", "PostgreSQL", "Aurora", "SQL Server", 
            "Oracle", "MariaDB"
        }
        valid = []
        invalid = []
        
        for value in values:
            if value in canonical_engines:
                valid.append(value)
            elif value.lower() in DATABASE_ENGINE_SYNONYMS:
                canonical = DATABASE_ENGINE_SYNONYMS[value.lower()]
                valid.append(canonical)
            else:
                invalid.append(value)
        
        return valid or None, invalid
    
    @staticmethod
    def validate_and_normalize_filters(
        entities: 'UPSEntities'
    ) -> Tuple['UPSEntities', Dict[str, Any]]:
        """
        Validate all filter fields against canonical values.
        
        Returns:
            Tuple of (updated_entities, validation_info)
            validation_info contains: {
                'needs_clarification': bool,
                'clarification_details': List[str],
                'invalid_filters': {}
            }
        """
        validation_info = {
            'needs_clarification': False,
            'clarification_details': [],
            'invalid_filters': {}
        }
        
        # Validate exclude_charge_types
        if entities.exclude_charge_types:
            valid, invalid = FilterValidator.validate_charge_types(
                entities.exclude_charge_types
            )
            entities.exclude_charge_types = valid
            
            if invalid:
                validation_info['invalid_filters']['exclude_charge_types'] = invalid
                validation_info['clarification_details'].append(
                    f"Excluded charge types: {', '.join(invalid)} (not recognized)"
                )
        
        # Validate include_charge_types
        if entities.include_charge_types:
            valid, invalid = FilterValidator.validate_charge_types(
                entities.include_charge_types
            )
            entities.include_charge_types = valid
            
            if invalid:
                validation_info['invalid_filters']['include_charge_types'] = invalid
                validation_info['clarification_details'].append(
                    f"Included charge types: {', '.join(invalid)} (not recognized)"
                )
        
        # Validate purchase_options
        if entities.purchase_options:
            valid, invalid = FilterValidator.validate_purchase_options(
                entities.purchase_options
            )
            entities.purchase_options = valid
            
            if invalid:
                validation_info['invalid_filters']['purchase_options'] = invalid
                validation_info['clarification_details'].append(
                    f"Purchase options: {', '.join(invalid)} (not recognized)"
                )
        
        # Validate platforms
        if entities.platforms:
            valid, invalid = FilterValidator.validate_platforms(
                entities.platforms
            )
            entities.platforms = valid
            
            if invalid:
                validation_info['invalid_filters']['platforms'] = invalid
                validation_info['clarification_details'].append(
                    f"Platforms: {', '.join(invalid)} (not recognized)"
                )
        
        # Validate database_engines
        if entities.database_engines:
            valid, invalid = FilterValidator.validate_database_engines(
                entities.database_engines
            )
            entities.database_engines = valid
            
            if invalid:
                validation_info['invalid_filters']['database_engines'] = invalid
                validation_info['clarification_details'].append(
                    f"Database engines: {', '.join(invalid)} (not recognized)"
                )
        
        # Trigger clarification if any invalid filters exist
        if validation_info['invalid_filters']:
            validation_info['needs_clarification'] = True
        
        return entities, validation_info
    
    @staticmethod
    def generate_clarification_question(validation_info: Dict[str, Any]) -> str:
        """Generate user-friendly clarification question for invalid filters."""
        if not validation_info['invalid_filters']:
            return "Some filter values seem unclear. Could you clarify what you're looking for?"
        
        questions = []
        
        if 'purchase_options' in validation_info['invalid_filters']:
            invalid = validation_info['invalid_filters']['purchase_options']
            questions.append(
                f"I didn't recognize the purchase option(s): {', '.join(invalid)}. "
                f"Did you mean:\n"
                f"- On-Demand\n"
                f"- Reserved Instances (RI)\n"
                f"- Savings Plans\n"
                f"- Spot Instances"
            )
        
        if 'exclude_charge_types' in validation_info['invalid_filters']:
            invalid = validation_info['invalid_filters']['exclude_charge_types']
            questions.append(
                f"I didn't recognize the charge type(s) to exclude: {', '.join(invalid)}. "
                f"Did you mean to exclude:\n"
                f"- Taxes\n"
                f"- Credits\n"
                f"- Refunds\n"
                f"- Fees\n"
                f"- Support charges"
            )
        
        if 'include_charge_types' in validation_info['invalid_filters']:
            invalid = validation_info['invalid_filters']['include_charge_types']
            questions.append(
                f"I didn't recognize the charge type(s): {', '.join(invalid)}. "
                f"Which specific charge type did you want to analyze?"
            )
        
        if 'platforms' in validation_info['invalid_filters']:
            invalid = validation_info['invalid_filters']['platforms']
            questions.append(
                f"I didn't recognize the platform(s): {', '.join(invalid)}. "
                f"Did you mean:\n"
                f"- Linux\n"
                f"- Windows\n"
                f"- Red Hat Enterprise Linux\n"
                f"- Ubuntu"
            )
        
        if 'database_engines' in validation_info['invalid_filters']:
            invalid = validation_info['invalid_filters']['database_engines']
            questions.append(
                f"I didn't recognize the database engine(s): {', '.join(invalid)}. "
                f"Did you mean:\n"
                f"- MySQL\n"
                f"- PostgreSQL\n"
                f"- Aurora\n"
                f"- SQL Server\n"
                f"- Oracle"
            )
        
        return "\n\n".join(questions)


class TimeRangeValidator:
    """Validates LLM-extracted time ranges without parsing."""
    
    @staticmethod
    def validate(tr: 'UPSTimeRange') -> tuple[bool, Optional[str]]:
        """
        Validate LLM output is reasonable.
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            start = datetime.strptime(tr.start_date, "%Y-%m-%d")
            end = datetime.strptime(tr.end_date, "%Y-%m-%d")
            today = datetime.utcnow().date()
            
            # Sanity checks
            if start.date() > end.date():
                return False, "Start date is after end date"
            
            if (end.date() - start.date()).days > 3650:  # 10 years
                return False, "Date range too large (exceeds 10 years)"
            
            # Allow future dates for forecasting, but not too far
            if end.date() > today + timedelta(days=365):
                return False, "End date too far in future (exceeds 1 year)"
            
            # Check dates aren't too far in the past (e.g., before AWS existed)
            if start.date().year < 2006:
                return False, f"Start date too far in past ({start.date().year})"
            
            return True, None
            
        except ValueError as e:
            return False, f"Invalid date format: {e}"


class UPSTimeRange(BaseModel):
    start_date: str
    end_date: str
    description: Optional[str] = None
    explicit: bool = False
    source: Optional[str] = None

    @validator("start_date", "end_date")
    def _valid_date(cls, v: str) -> str:
        # Basic YYYY-MM-DD validation
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except Exception:
            raise ValueError(f"Invalid date format: {v}")
        return v

    @property
    def days(self) -> int:
        try:
            return (datetime.strptime(self.end_date, "%Y-%m-%d") - datetime.strptime(self.start_date, "%Y-%m-%d")).days + 1
        except Exception:
            return 0


class UPSEntities(BaseModel):
    services: List[str] = Field(default_factory=list)
    regions: List[str] = Field(default_factory=list)
    accounts: List[str] = Field(default_factory=list)
    dimensions: List[str] = Field(default_factory=list)
    time_range: Optional[UPSTimeRange] = None
    exclude_charge_types: Optional[List[str]] = None
    include_charge_types: Optional[List[str]] = None
    exclude_line_item_types: Optional[List[str]] = None  # Legacy field (synonym for exclude_charge_types)
    purchase_options: Optional[List[str]] = None
    database_engines: Optional[List[str]] = None
    platforms: Optional[List[str]] = None
    tags: Optional[Dict[str, List[str]]] = None

    @staticmethod
    def _normalize_value_list(value, normalizer) -> Optional[List[str]]:
        if value in (None, ""):
            return None
        if isinstance(value, str):
            value = [value]
        normalized: List[str] = []
        for item in value:
            normalized_value = normalizer(item)
            if normalized_value:
                normalized.append(normalized_value)
        return normalized or None

    @validator("exclude_charge_types", pre=True)
    def _normalize_exclude_charge_types(cls, value):
        return cls._normalize_value_list(value, _normalize_charge_type)
    
    @validator("exclude_line_item_types", pre=True)
    def _normalize_exclude_line_item_types(cls, value):
        """Legacy field - syncs with exclude_charge_types"""
        return cls._normalize_value_list(value, _normalize_charge_type)

    @validator("include_charge_types", pre=True)
    def _normalize_include_charge_types(cls, value):
        return cls._normalize_value_list(value, _normalize_charge_type)

    @validator("purchase_options", pre=True)
    def _normalize_purchase_options(cls, value):
        return cls._normalize_value_list(value, lambda v: _normalize_from_mapping(v, PURCHASE_OPTION_SYNONYMS))

    @validator("database_engines", pre=True)
    def _normalize_database_engines(cls, value):
        return cls._normalize_value_list(value, lambda v: _normalize_from_mapping(v, DATABASE_ENGINE_SYNONYMS))

    @validator("platforms", pre=True)
    def _normalize_platforms(cls, value):
        return cls._normalize_value_list(value, lambda v: _normalize_from_mapping(v, PLATFORM_SYNONYMS))

    @validator("tags", pre=True)
    def _normalize_tags(cls, value):
        if not value:
            return None
        normalized: Dict[str, List[str]] = {}
        for raw_key, raw_values in value.items():
            if raw_values in (None, ""):
                continue
            key = _normalize_tag_key(raw_key)
            if isinstance(raw_values, str):
                values = [raw_values]
            else:
                values = list(raw_values)
            clean_values = []
            for val in values:
                normalized_val = _normalize_simple_token(val)
                if normalized_val:
                    clean_values.append(normalized_val)
            if clean_values:
                normalized[key] = clean_values
        return normalized or None


class UPSOperations(BaseModel):
    aggregation: List[str] = Field(default_factory=list)
    compare_periods: bool = False
    top_n: Optional[int] = None


class UPSOutput(BaseModel):
    schema_version: str = SCHEMA_VERSION
    intent: str
    confidence: float = 0.0
    needs_clarification: bool = False
    clarification_question: Optional[str] = None  # User-friendly clarification prompt
    entities: UPSEntities
    operations: UPSOperations = Field(default_factory=UPSOperations)
    reasoning: Optional[str] = None
    raw_query: Optional[str] = None

    @validator("confidence")
    def _clamp_conf(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


PROMPT_TEMPLATE_WITH_CONTEXT = """You are a FinOps and cloud intelligence interpreter with conversation awareness.
You are analyzing AWS data including cost reports, logs, metrics, and usage data.

AWS CONTEXT:
- All queries are about AWS cloud resources, costs, and operations
- Service names refer to AWS services (EC2, S3, RDS, Lambda, CloudWatch, etc.)
- Platforms refer to AWS operating systems (Linux, Windows, RHEL, SUSE, Ubuntu)
- Purchase options refer to AWS pricing models (On-Demand, Reserved Instances, Spot, Savings Plans)
- Database engines refer to AWS RDS/Aurora engines (MySQL, PostgreSQL, Aurora, SQL Server, Oracle, MariaDB)
- Data sources may include: Cost and Usage Reports (CUR), CloudWatch Logs, CloudWatch Metrics, CloudTrail, etc.

CRITICAL CLARIFICATION PRINCIPLE:
When you are uncertain or the query is ambiguous, ALWAYS set needs_clarification=true and provide a helpful clarification_question.
DO NOT guess, assume defaults, or infer missing information when uncertain.
Examples requiring clarification:
- Vague time references ("recently", "lately") without explicit dates
- Missing breakdown dimensions ("EC2 costs" - total or by region/account/instance?)
- Ambiguous intent (could be multiple interpretations)
- Low confidence in parameter extraction (confidence < 0.7)
Better to ask than to return wrong data!

Extract structured parameters from the user query in the context of an ongoing conversation.

IMPORTANT: TODAY'S DATE IS {current_date}. Use this as the reference for calculating date ranges.

DATE INTERPRETATION GUIDELINES (CRITICAL - READ CAREFULLY):
TODAY IS: {current_date}
All "last" or "past" time ranges look BACKWARD into the PAST from TODAY.
The end_date is ALWAYS {current_date} or earlier, NEVER a future date!

CONCRETE EXAMPLES (if today is 2025-11-26):
- "last 6 months" = start: 2025-05-01, end: 2025-10-31 (exactly 6 complete months: May, Jun, Jul, Aug, Sep, Oct)
- "last 12 months" = start: 2024-11-01, end: 2025-10-31 (exactly 12 complete months, excluding current partial month)
- "last 30 days" = start: 2025-10-27, end: 2025-11-26 (rolling 30 days)

ROLLING PERIODS (going backward from today):
- "last months" / "past months" (plural) → 12 COMPLETE calendar months BACKWARD
  * start_date = first day of the month 12 months ago
  * end_date = last day of previous month (exclude current partial month)
  * Example: If today is 2025-11-26, return 2024-11-01 to 2025-10-31 (12 complete months)
- "last 12 months" → 12 COMPLETE calendar months BACKWARD
  * start_date = first day of the month 12 months ago
  * end_date = last day of previous month
  * Example: If today is 2025-11-26, return 2024-11-01 to 2025-10-31
- "last N months" → N COMPLETE calendar months BACKWARD (excluding current partial month)
  * start_date = first day of the month N months ago
  * end_date = last day of previous month
  * Example: If today is 2025-11-26 and N=6, return 2025-05-01 to 2025-10-31 (exactly 6 complete months: May, June, July, Aug, Sep, Oct)
- "last N days/weeks/years" → N periods BACKWARD from {current_date}
  * start_date = {current_date} minus N periods
  * end_date = {current_date}
- "recent months" → 3 COMPLETE calendar months BACKWARD
  * start_date = first day of the month 3 months ago
  * end_date = last day of previous month
- "few months" → 3 COMPLETE calendar months BACKWARD
- "several months" → 6 COMPLETE calendar months BACKWARD
- "recently" / "lately" → 30 days BACKWARD (with confidence < 0.7)

CALENDAR PERIODS:
- "last month" (singular) → previous calendar month only (e.g., Oct 1 - Oct 31, 2024)
- "this month" → current month to date (start of month to {current_date})
- "last quarter" → previous full quarter (e.g., Q3 2024: Jul 1 - Sep 30)
- "this quarter" → current quarter to date (e.g., Q4 2024: Oct 1 - {current_date})
- "last year" → previous full calendar year (e.g., Jan 1 - Dec 31, 2023)
- "this year" / "ytd" / "year to date" → current year to date (Jan 1 - {current_date})

DEFAULT:
- No explicit time → inherit from context OR set needs_clarification=true
- NEVER default to "last 30 days" - always ask the user to specify the time period

AMBIGUITY HANDLING:
- If unclear or vague, set confidence < 0.7 and explain in reasoning
- Always provide start_date and end_date in YYYY-MM-DD format
- Set explicit=true only if user explicitly states a time period
- Set explicit=false for inherited or defaulted time ranges

CLARIFICATION RULES:
- Set needs_clarification=true when confidence < 0.7 OR query is ambiguous
- Provide clarification_question as a user-friendly prompt
- Examples of ambiguous queries:
  * "recently" / "lately" → Ask: "Did you mean last 7 days, last 30 days, or last 90 days?"
  * "few months" → Ask: "Did you mean last 3 months or last 6 months?"
  * No time specified + no context → REQUIRED: Ask: "What time period would you like to analyze? (e.g., last month, last quarter, this year, last 30 days)"
  * Vague service names → Ask: "Did you mean [Option A] or [Option B]?"
- If NO clarification needed, set clarification_question=null

CONVERSATION CONTEXT:
{context_info}

CURRENT QUERY: "{query}"

INTENT CLASSIFICATION RULES (READ CAREFULLY):
COST_TREND: Query asks for how costs EVOLVE over sequential time buckets (month/week/day). Words like "trend", "progression", "month by month", "monthly comparison over <range>", "show monthly costs" mean COST_TREND.
    Positive examples:
        * "monthly comparison of total cost for last 12 months" (NOT COMPARATIVE — no A vs B, wants sequence)
        * "show month by month cost for last year"
        * "cost trend over the past 6 months"
    Output: time-series list (each row a period with its cost). Do NOT mark compare_periods=true.

COMPARATIVE: ONLY when user contrasts TWO (or a small fixed set of) distinct TIME PERIODS or TAG-BASED GROUPS: explicit "vs", "versus", "difference between", "compare X and Y", "this month vs last month", "dev vs prod" (environment tags).
    Positive examples:
        * "compare this month vs last month" (TIME PERIOD comparison)
        * "dev vs prod cost difference" (TAG comparison - Environment tag values)
        * "Q3 vs Q4 EC2 spend" (TIME PERIOD comparison)
        * "production vs staging costs" (TAG comparison)
    Negative examples (should NOT be COMPARATIVE):
        * "monthly comparison over last 12 months" (COST_TREND - sequential monthly data)
        * "compare costs month by month" (COST_TREND - time-series)
        * "Compare Linux vs Windows EC2 costs" (COST_BREAKDOWN - platform dimension, extract platforms=["Linux", "Windows"])
        * "On-Demand vs Reserved Instance costs" (COST_BREAKDOWN - purchase option dimension, extract purchase_options=["On-Demand", "Reserved"])
    Output: current period vs previous or group A vs group B summary. Set compare_periods=true.
    CRITICAL: When "vs" is used with PLATFORMS or PURCHASE_OPTIONS, classify as COST_BREAKDOWN with those filters, NOT COMPARATIVE.

COST_BREAKDOWN: Distribution across a dimension (service, region, account, tag, platform, purchase_option) for a period.
    CRITICAL: Only use this intent when user EXPLICITLY asks to break down, distribute, group by, or show costs across a dimension.
    Examples: 
        * "break down cost by service"
        * "cost by region" 
        * "show cost distribution across accounts"
        * "Compare Linux vs Windows EC2 costs" (platform comparison - extract platforms=["Linux", "Windows"], dimension=["platform"])
        * "On-Demand vs Reserved Instance costs" (purchase option comparison - extract purchase_options=["On-Demand", "Reserved"], dimension=["purchase_option"])
    CRITICAL: When "vs" compares dimension VALUES (Linux vs Windows, On-Demand vs Spot), classify as COST_BREAKDOWN and extract those values as filters.
    
    If user specifies filters (service, purchase_option, platform) but NO breakdown dimension, DO NOT use COST_BREAKDOWN.
    Use TOP_N_RANKING or COST_TREND instead, depending on whether they want a ranking or time series.

TOP_N_RANKING: Ranking queries AND simple filtered totals without breakdown dimensions.
    Examples:
        * "top 5 services" - ranking query
        * "most expensive resources" - ranking query
        * "EC2 costs on On-Demand instances" - filtered total, NO breakdown (use TOP_N_RANKING with limit=1)
        * "Linux EC2 costs for Q1" - filtered total (use TOP_N_RANKING with limit=1)
        * "S3 costs excluding credits" - filtered total (use TOP_N_RANKING with limit=1)
    
    CRITICAL: If user doesn't specify "top N" but just wants a filtered cost total, set top_n to 1 and use this intent.
    This avoids defaulting to arbitrary dimension breakdowns.

Decision flow:
    1. Does query contain "vs" / "versus" with DIMENSION VALUES (Linux vs Windows, On-Demand vs Spot)? -> COST_BREAKDOWN with those filters extracted.
    2. Else if contains "vs" / "versus" / "difference between" with TIME PERIODS or TAG GROUPS (this month vs last month, dev vs prod)? -> COMPARATIVE.
    3. Else if contains "monthly" or "month by month" or "trend" or "progression" -> COST_TREND unless rules 1-2 matched.
    4. Else if asks for "break down" / "distribution" / "by service" etc. -> COST_BREAKDOWN.
    5. Else if asks for "top" / "most expensive" / "highest" -> TOP_N_RANKING.
    6. Otherwise infer remaining intents normally.

IMPORTANT: The word "comparison" alone ("monthly comparison", "comparison over last 12 months") DOES NOT imply COMPARATIVE unless there are TWO explicit target periods/groups.

DIMENSION EXTRACTION GUIDELINES:
The "dimensions" field captures what the user wants to group/break down by:
- "group by service" / "grouped by services" / "by service" / "breakdown by service" → ["service"]
- "by region" / "regional breakdown" / "group by region" → ["region"]  
- "by account" / "per account" / "group by account" → ["account"]
- "by usage type" / "breakdown by usage" → ["usage_type"]
- "by operation" / "breakdown by operation" → ["operation"]
- "by resource" / "resource breakdown" → ["resource"]
- Multiple: "by service and region" → ["service", "region"]
- If user wants service-level detail in a trend: "monthly costs by service" → ["service"]
- Empty array if no grouping/breakdown requested

FILTER EXTRACTION RULES:
- Set `exclude_charge_types` when user removes fees/taxes/credits (map words like "tax", "credits", "refunds", "support" to canonical charge types: Tax, Credit, Refund, Fee, Support, EdpDiscount, DiscountedUsage, SavingsPlanCoveredUsage, SavingsPlanRecurringCharge).
- Set `include_charge_types` when user wants ONLY a specific charge type ("only taxes", "just RI fees").
- `purchase_options`: normalize to ["On-Demand", "Reserved", "Spot", "SavingsPlan"]. Capture phrases like "on demand", "RI", "reserved", "spot", "savings plans".
  Examples: "Savings Plan costs" → ["SavingsPlan"], "On-Demand vs Reserved costs" → ["On-Demand", "Reserved"]
- `platforms`: normalize to operating systems in CUR ("Linux", "Windows", "Red Hat Enterprise Linux", "SUSE Linux", "Ubuntu").
  Examples: "Linux EC2 costs" → ["Linux"], "Compare Linux vs Windows" → ["Linux", "Windows"], "RHEL instances" → ["Red Hat Enterprise Linux"]
- `database_engines`: normalize to CUR engine names ("MySQL", "PostgreSQL", "Aurora", "SQL Server", "Oracle", "MariaDB").
- `tags`: object with TagKey → list of values. Preserve multiple values per tag. Accept inputs like `Environment=prod`, `env:prod`, `tag:CostCenter=media`. Normalize keys to TitleCase (Environment, Application, CostCenter, Owner, Product, etc.).
- Omit these fields when user never mentioned them. Never invent filters.

Extract parameters and return ONLY valid JSON matching this schema:
{{
  "intent": string (one of: COST_BREAKDOWN, TOP_N_RANKING, COST_TREND, COMPARATIVE, OPTIMIZATION, UTILIZATION, ANOMALY_ANALYSIS, GOVERNANCE, DATA_METADATA, OTHER),
  "confidence": number 0-1,
  "needs_clarification": boolean,
  "clarification_question": string | null,
  "entities": {{
    "services": [string],
    "regions": [string],
    "accounts": [string],
    "dimensions": [string],
        "exclude_charge_types": [string],
        "include_charge_types": [string],
        "purchase_options": [string],
        "database_engines": [string],
        "platforms": [string],
        "tags": {{ "TagKey": [string] }},
    "time_range": {{
      "start_date": "YYYY-MM-DD",
      "end_date": "YYYY-MM-DD",
      "description": string,
      "explicit": boolean,
      "source": string
    }} | null
  }},
  "operations": {{
    "aggregation": [string],
    "compare_periods": boolean,
    "top_n": number | null
  }},
  "reasoning": string,
  "raw_query": string
}}

CRITICAL RULES FOR FOLLOW-UP QUERIES:
1. If current query references previous data ("break that down", "for VPC", "show details", "more on that"), this is a FOLLOW-UP
2. If current query ONLY specifies a new time range (e.g., "for 200 days", "last month", "this year") with NO other context, inherit the INTENT from previous query
3. For follow-ups WITHOUT explicit time range, INHERIT the time_range from conversation context (set explicit=false, source="inherited_followup")
4. For follow-ups that mention a specific service/region/account, ADD it to the inherited context
5. If query says "drill down into X" or "breakdown X", treat X as the NEW service filter
6. If query says "more details on Y" or "give me Y recommendations", maintain the current intent and add Y as context
7. Phrases like "that", "it", "them", "those" refer to data from previous queries - use conversation context

CONTEXT INHERITANCE EXAMPLES:
- Previous: "Show costs last 30 days" → Current: "break down VPC" → Inherit last 30 days, add VPC service
- Previous: "Show costs last 30 days" → Current: "for 200 days" → Inherit same intent (COST_BREAKDOWN), change time to 200 days
- Previous: "EC2 costs this month" → Current: "how to optimize" → Inherit EC2 + this month, change intent to OPTIMIZATION  
- Previous: "Top 5 services" → Current: "show regional breakdown" → Inherit time range, add "region" dimension
- Previous: "CloudWatch costs" → Current: "drill into us-east-1" → Inherit CloudWatch + time, add us-east-1 region
- Previous: "Compare current vs previous month" → Current: "for last quarter" → Inherit COMPARATIVE intent, change time to last quarter

Guidelines:
- If query asks for "top N" include top_n number
- If query asks for "highest", "most expensive", "largest", "biggest" without a number, set top_n to 1
- If timeframe not stated BUT conversation context has one, INHERIT it (set source="inherited_followup")
- Do NOT invent services or regions not mentioned in query OR context
- Use rolling interpretation for "last 30 days" = today minus 29 days to today
- Detect follow-up intent changes: asking about same data differently vs switching topics

CLARIFICATION REQUIREMENTS:
- If timeframe implied but not stated AND no context exists, set needs_clarification=true and ask for time period
- If uncertain about any parameter (confidence < 0.7), set needs_clarification=true
- If query could have multiple interpretations, set needs_clarification=true
- NEVER assume defaults when information is missing - always ask!

Return ONLY JSON. No markdown fences, no commentary."""  # noqa: E501

PROMPT_TEMPLATE_NO_CONTEXT = """You are a FinOps and cloud intelligence interpreter.
You are analyzing AWS data including cost reports, logs, metrics, and usage data.

AWS CONTEXT:
- All queries are about AWS cloud resources, costs, and operations
- Service names refer to AWS services (EC2, S3, RDS, Lambda, CloudWatch, etc.)
- Platforms refer to AWS operating systems (Linux, Windows, RHEL, SUSE, Ubuntu)
- Purchase options refer to AWS pricing models (On-Demand, Reserved Instances, Spot, Savings Plans)
- Database engines refer to AWS RDS/Aurora engines (MySQL, PostgreSQL, Aurora, SQL Server, Oracle, MariaDB)
- Data sources may include: Cost and Usage Reports (CUR), CloudWatch Logs, CloudWatch Metrics, CloudTrail, etc.

CRITICAL CLARIFICATION PRINCIPLE:
When you are uncertain or the query is ambiguous, ALWAYS set needs_clarification=true and provide a helpful clarification_question.
DO NOT guess, assume defaults, or infer missing information when uncertain.
Examples requiring clarification:
- Vague time references ("recently", "lately") without explicit dates
- Missing breakdown dimensions ("EC2 costs" - total or by region/account/instance?)
- Ambiguous intent (could be multiple interpretations)
- Low confidence in parameter extraction (confidence < 0.7)
Better to ask than to return wrong data!

Extract structured parameters from the user query and return ONLY valid JSON matching this schema:

IMPORTANT: TODAY'S DATE IS {current_date}. Use this as the reference for calculating date ranges.

DATE INTERPRETATION GUIDELINES (CRITICAL - READ CAREFULLY):
TODAY IS: {current_date}
All "last" or "past" time ranges look BACKWARD into the PAST from TODAY.
The end_date is ALWAYS {current_date} or earlier, NEVER a future date!

CONCRETE EXAMPLES (if today is 2025-11-26):
- "last 6 months" = start: 2025-05-01, end: 2025-10-31 (exactly 6 complete months: May, Jun, Jul, Aug, Sep, Oct)
- "last 12 months" = start: 2024-11-01, end: 2025-10-31 (exactly 12 complete months, excluding current partial month)
- "last 30 days" = start: 2025-10-27, end: 2025-11-26 (rolling 30 days)

ROLLING PERIODS (going backward from today):
- "last months" / "past months" (plural) → 12 COMPLETE calendar months BACKWARD
  * start_date = first day of the month 12 months ago
  * end_date = last day of previous month (exclude current partial month)
  * Example: If today is 2025-11-26, return 2024-11-01 to 2025-10-31 (12 complete months)
- "last 12 months" → 12 COMPLETE calendar months BACKWARD
  * start_date = first day of the month 12 months ago
  * end_date = last day of previous month
  * Example: If today is 2025-11-26, return 2024-11-01 to 2025-10-31
- "last N months" → N COMPLETE calendar months BACKWARD (excluding current partial month)
  * start_date = first day of the month N months ago
  * end_date = last day of previous month
  * Example: If today is 2025-11-26 and N=6, return 2025-05-01 to 2025-10-31 (exactly 6 complete months: May, June, July, Aug, Sep, Oct)
- "last N days/weeks/years" → N periods BACKWARD from {current_date}
  * start_date = {current_date} minus N periods
  * end_date = {current_date}
- "recent months" → 3 COMPLETE calendar months BACKWARD
  * start_date = first day of the month 3 months ago
  * end_date = last day of previous month
- "few months" → 3 COMPLETE calendar months BACKWARD
- "several months" → 6 COMPLETE calendar months BACKWARD
- "recently" / "lately" → 30 days BACKWARD (with confidence < 0.7)

CALENDAR PERIODS:
- "last month" (singular) → previous calendar month only (e.g., Oct 1 - Oct 31, 2024)
- "this month" → current month to date (start of month to {current_date})
- "last quarter" → previous full quarter (e.g., Q3 2024: Jul 1 - Sep 30)
- "this quarter" → current quarter to date (e.g., Q4 2024: Oct 1 - {current_date})
- "last year" → previous full calendar year (e.g., Jan 1 - Dec 31, 2023)
- "this year" / "ytd" / "year to date" → current year to date (Jan 1 - {current_date})

DEFAULT:
- No explicit time → default to last 30 days BACKWARD

AMBIGUITY HANDLING:
- If unclear or vague, set confidence < 0.7 and explain in reasoning
- Always provide start_date and end_date in YYYY-MM-DD format
- Set explicit=true only if user explicitly states a time period
- Set explicit=false for defaulted time ranges

CLARIFICATION RULES:
- Set needs_clarification=true when confidence < 0.7 OR query is ambiguous
- Provide clarification_question as a user-friendly prompt
- Examples: "recently" → "Did you mean last 7, 30, or 90 days?"
- If clear, set clarification_question=null

INTENT CLASSIFICATION RULES (READ CAREFULLY):

COST_TREND: Sequential evolution ("monthly comparison over <range>", "month by month", "monthly costs", "cost trend"). Not comparing two discrete labelled periods; wants a series.
COMPARATIVE: Explicit contrasting of TWO periods/groups (contains "vs" / "versus" / both "this month" and "last month" / "Q3 vs Q4" / "dev vs prod"). Word "comparison" alone without "vs" does NOT trigger COMPARATIVE.
COST_BREAKDOWN: Distribution across a dimension at a point ("break down by service", "cost by region").
TOP_N_RANKING: Ranking ("top N", "most expensive", "highest cost drivers").

DIMENSION EXTRACTION GUIDELINES:
The "dimensions" field captures what the user wants to group/break down by:
- "group by service" / "grouped by services" / "by service" / "breakdown by service" → ["service"]
- "by region" / "regional breakdown" / "group by region" → ["region"]  
- "by account" / "per account" / "group by account" → ["account"]
- "by usage type" / "breakdown by usage" → ["usage_type"]
- "by operation" / "breakdown by operation" → ["operation"]
- "by resource" / "resource breakdown" → ["resource"]
- Multiple: "by service and region" → ["service", "region"]
- If user wants service-level detail in a trend: "monthly costs by service" → ["service"]
- Empty array if no grouping/breakdown requested

FILTER EXTRACTION RULES:
- `exclude_charge_types`: user excludes taxes/credits/fees/support/etc. Map to canonical CUR types (Tax, Credit, Refund, Fee, Support, EdpDiscount, DiscountedUsage, SavingsPlanCoveredUsage, SavingsPlanRecurringCharge).
- `include_charge_types`: user wants ONLY a specific charge type ("only taxes", "just RI fees").
- `purchase_options`: normalize to ["On-Demand", "Reserved", "Spot", "SavingsPlan"].
- `platforms`: normalize to operating systems ("Linux", "Windows", "Red Hat Enterprise Linux", "SUSE Linux", "Ubuntu").
- `database_engines`: normalize to CUR engines ("MySQL", "PostgreSQL", "Aurora", "SQL Server", "Oracle", "MariaDB").
- `tags`: dictionary where each key maps to list of values (e.g., {"Environment": ["prod", "staging"]}). Accept Environment=prod, env:prod, tag:CostCenter=media, etc. Normalize keys to TitleCase without spaces.
- Only set these fields if user explicitly mentioned them. Otherwise leave null/empty.

{{
  "intent": string (one of: COST_BREAKDOWN, TOP_N_RANKING, COST_TREND, COMPARATIVE, OPTIMIZATION, UTILIZATION, ANOMALY_ANALYSIS, GOVERNANCE, DATA_METADATA, OTHER),
  "confidence": number 0-1,
  "needs_clarification": boolean,
  "clarification_question": string | null,
  "entities": {{
    "services": [string],
    "regions": [string],
    "accounts": [string],
    "dimensions": [string],
        "exclude_charge_types": [string],
        "include_charge_types": [string],
        "purchase_options": [string],
        "database_engines": [string],
        "platforms": [string],
        "tags": {{ "TagKey": [string] }},
    "time_range": {{
      "start_date": "YYYY-MM-DD",
      "end_date": "YYYY-MM-DD",
      "description": string,
      "explicit": boolean,
      "source": string
    }} | null
  }},
  "operations": {{
    "aggregation": [string],
    "compare_periods": boolean,
    "top_n": number | null
  }},
  "reasoning": string,
  "raw_query": string
}}
Guidelines:
- If query asks for "top N" include top_n number.
- If query asks for "highest", "most expensive", "largest", "biggest" without a number, set top_n to 1.
- If timeframe implied but not stated, set explicit=false.
- Do NOT invent services or regions; empty array if absent.
- Use rolling interpretation for expressions like "last 30 days".
Return ONLY JSON. No markdown fences, no commentary.
Query: "{query}"""  # noqa: E501


class UPSExtractor:
    def __init__(self):
        self.schema_version = SCHEMA_VERSION

    async def extract(self, query: str, context: Optional[Dict[str, Any]] = None) -> UPSOutput:
        """Run LLM extraction with conversation context awareness; fallback to heuristics if needed."""
        raw_response = None
        try:
            if os.getenv("UPS_DISABLE_LLM") == "1":
                raise RuntimeError("LLM disabled via UPS_DISABLE_LLM env var")
            
            # Build context information for LLM prompt
            context_info = "No previous conversation context."
            if context and any(context.get(k) for k in ["conversation_history", "last_query", "last_intent", "time_range", "services"]):
                context_parts = []
                
                # Add conversation history
                if context.get("conversation_history"):
                    history = context["conversation_history"][-4:]  # Last 2 exchanges (4 messages)
                    history_str = "\n".join([
                        f"  {msg.get('role', 'unknown').upper()}: {msg.get('content', '')[:150]}"
                        for msg in history
                    ])
                    context_parts.append(f"Recent Conversation:\n{history_str}")
                
                # Add last query and intent
                if context.get("last_query"):
                    context_parts.append(f"Previous Query: \"{context['last_query']}\"")
                if context.get("last_intent"):
                    context_parts.append(f"Previous Intent: {context['last_intent']}")
                
                # Add inherited parameters
                inherited_params = []
                if context.get("time_range"):
                    tr = context["time_range"]
                    inherited_params.append(f"  - Time Range: {tr.get('start_date')} to {tr.get('end_date')} ({tr.get('description', 'N/A')})")
                if context.get("services"):
                    inherited_params.append(f"  - Services: {', '.join(context['services'][:5])}")
                if context.get("regions"):
                    inherited_params.append(f"  - Regions: {', '.join(context['regions'][:5])}")
                if context.get("accounts"):
                    inherited_params.append(f"  - Accounts: {', '.join(context['accounts'][:3])}")
                if context.get("dimensions"):
                    inherited_params.append(f"  - Dimensions: {', '.join(context['dimensions'][:3])}")
                
                if inherited_params:
                    context_parts.append("Previous Parameters (inherit if current query doesn't specify):\n" + "\n".join(inherited_params))
                
                if context_parts:
                    context_info = "\n\n".join(context_parts)
            
            # Get current date for LLM to calculate date ranges
            current_date = datetime.now().strftime("%Y-%m-%d")
            
            # Choose prompt template based on context availability
            if context and context.get("conversation_history"):
                prompt = PROMPT_TEMPLATE_WITH_CONTEXT.format(
                    query=query, 
                    context_info=context_info,
                    current_date=current_date
                )
            else:
                prompt = PROMPT_TEMPLATE_NO_CONTEXT.format(
                    query=query,
                    current_date=current_date
                )
            
            raw_response = await llm_service.call_llm(
                prompt=prompt,
                system_prompt=(
                    "You are an expert at understanding queries in conversations. "
                    "When users ask follow-ups, intelligently inherit context from previous queries. "
                    "CRITICAL: When uncertain or the query is ambiguous, ALWAYS set needs_clarification=true and provide a helpful question. "
                    "DO NOT guess or assume defaults when information is missing. "
                    "Better to ask for clarification than return incorrect data. "
                    "Produce strictly valid compact JSON per schema."
                )
            )
            cleaned = raw_response.strip()
            # Quick fence stripping if model ignored instruction
            if cleaned.startswith("```"):
                lines = [ln for ln in cleaned.splitlines() if not ln.strip().startswith("```json") and ln.strip() != "```"]
                cleaned = "\n".join(lines).strip()
            # Attempt immediate parse, then repair if invalid
            try:
                data = json.loads(cleaned)
            except Exception:
                cleaned = await repair_json(cleaned, prompt)
                data = json.loads(cleaned)
            output = UPSOutput.parse_obj(data)
            
            # ========================================================================
            # VALIDATION LAYER: Validate filter values against canonical values (Option 2)
            # ========================================================================
            output.entities, validation_info = FilterValidator.validate_and_normalize_filters(
                output.entities
            )
            
            # Log validation results
            if validation_info['invalid_filters']:
                logger.warning(
                    "Filter validation found invalid values",
                    invalid=validation_info['invalid_filters']
                )
            
            # Trigger clarification for invalid filters (Option 3)
            if validation_info['needs_clarification']:
                output.needs_clarification = True
                
                # Generate clarification question if not already set by LLM
                if not output.clarification_question:
                    output.clarification_question = FilterValidator.generate_clarification_question(
                        validation_info
                    )
                else:
                    # Append filter clarification to existing question
                    filter_question = FilterValidator.generate_clarification_question(validation_info)
                    output.clarification_question = f"{output.clarification_question}\n\n{filter_question}"
                
                # Update reasoning
                invalid_count = sum(len(v) for v in validation_info['invalid_filters'].values())
                filter_note = f" | {invalid_count} invalid filter value(s) detected"
                if output.reasoning:
                    output.reasoning += filter_note
                else:
                    output.reasoning = f"{invalid_count} invalid filter value(s) detected"
                
                logger.info(
                    "Invalid filter values - asking for clarification",
                    query=query,
                    invalid_filters=validation_info['invalid_filters'],
                    clarification_question=output.clarification_question
                )
            
            # Validate time_range if present
            if output.entities.time_range:
                is_valid, error_msg = TimeRangeValidator.validate(output.entities.time_range)
                if not is_valid:
                    logger.warning(
                        "Time range validation failed",
                        error=error_msg,
                        time_range=output.entities.time_range.dict()
                    )
                    # Set needs_clarification and generate helpful question
                    output.needs_clarification = True
                    output.clarification_question = f"The time range appears invalid: {error_msg}. Could you specify the time period you'd like to analyze? (e.g., 'last 30 days', 'this month', 'Q3 2025')"
                    if output.reasoning:
                        output.reasoning += f" | Time range validation error: {error_msg}"
                    else:
                        output.reasoning = f"Time range validation error: {error_msg}"
            
            # Flag for clarification if confidence is low on date extraction
            if output.entities.time_range and output.confidence < 0.7:
                output.needs_clarification = True
                time_desc = output.entities.time_range.description or "unspecified"
                
                # Generate user-friendly clarification question if LLM didn't provide one
                if not output.clarification_question:
                    # Generate specific clarification based on the interpretation
                    if "recently" in query.lower() or "lately" in query.lower():
                        output.clarification_question = "I interpreted 'recently' as the last 30 days. Did you mean last 7 days, last 30 days, or last 90 days?"
                    elif "few months" in query.lower():
                        output.clarification_question = "I interpreted 'few months' as 3 months. Did you mean last 3 months or last 6 months?"
                    elif "several months" in query.lower():
                        output.clarification_question = "I interpreted 'several months' as 6 months. Did you mean last 3, 6, or 12 months?"
                    elif not output.entities.time_range.explicit:
                        output.clarification_question = f"I'm assuming '{time_desc}'. Is this the time period you want to analyze?"
                    else:
                        output.clarification_question = f"I interpreted the time period as '{time_desc}'. Is this correct?"
                
                clarification_note = f" | Low confidence on date interpretation: {time_desc}"
                if output.reasoning:
                    output.reasoning += clarification_note
                else:
                    output.reasoning = f"Low confidence on date interpretation: {time_desc}"
                
                logger.info(
                    "Low confidence time range extraction - asking for clarification",
                    query=query,
                    confidence=output.confidence,
                    time_range_description=time_desc,
                    clarification_question=output.clarification_question,
                    start_date=output.entities.time_range.start_date,
                    end_date=output.entities.time_range.end_date
                )
            
            # Filter out overly generic service names
            # When user says "AWS" or "Amazon", they mean ALL services, not a specific service
            generic_service_names = {"aws", "amazon", "cloud", "our", "the", "my", "all"}
            if output.entities.services:
                filtered_services = [
                    svc for svc in output.entities.services
                    if svc.lower() not in generic_service_names
                ]
                if len(filtered_services) != len(output.entities.services):
                    removed = set(output.entities.services) - set(filtered_services)
                    logger.info(
                        "Filtered out generic service names",
                        removed=list(removed),
                        original=output.entities.services,
                        filtered=filtered_services
                    )
                    output.entities.services = filtered_services
            
            # --------------------------------------------------------------------
            # CRITICAL: Inherit time_range from context if not extracted
            # --------------------------------------------------------------------
            # When user asks follow-up questions like "What are my top 5 most expensive services?"
            # without specifying a time period, we should use the time range from the previous query
            if not output.entities.time_range and context and context.get("time_range"):
                prev_tr = context["time_range"]
                try:
                    output.entities.time_range = UPSTimeRange(
                        start_date=prev_tr.get("start_date"),
                        end_date=prev_tr.get("end_date"),
                        description=prev_tr.get("description", "inherited from previous query"),
                        explicit=False,
                        source="inherited_from_context"
                    )
                    logger.info(
                        "Inherited time_range from conversation context",
                        query=query,
                        inherited_time_range={
                            "start_date": output.entities.time_range.start_date,
                            "end_date": output.entities.time_range.end_date,
                            "description": output.entities.time_range.description
                        }
                    )
                    # Don't ask for clarification if we inherited time range
                    if output.needs_clarification and output.clarification_question and "time period" in output.clarification_question.lower():
                        output.needs_clarification = False
                        output.clarification_question = None
                        logger.info("Cleared time period clarification after inheriting from context")
                except Exception as inherit_err:
                    logger.warning(
                        "Failed to inherit time_range from context",
                        error=str(inherit_err),
                        context_time_range=prev_tr
                    )

            # --------------------------------------------------------------------
            # LLM-only mode: do not infer purchase options from keywords.
            
            # --------------------------------------------------------------------
            # LLM-only mode: do not infer exclude_line_item_types from keywords.
            
            # Log context-aware extraction for debugging
            logger.info(
                "UPS extraction with context",
                query=query,
                has_context=bool(context),
                has_history=bool(context and context.get("conversation_history")),
                extracted_services=output.entities.services,
                extracted_time_range=output.entities.time_range.dict() if output.entities.time_range else None,
                extracted_purchase_options=output.entities.purchase_options,
                intent=output.intent
            )

            # LLM-only mode: do not inject dimensions via keyword checks.
            
            return output
        except Exception as e:
            error_str = str(e)
            # Check if this is a transient error (access denied, timeout, etc) vs parsing error
            is_transient_error = any(x in error_str.lower() for x in [
                'access', 'denied', 'permission', 'timeout', 'throttl', 'unavailable',
                'bedrock', 'model', 'invoke'
            ])
            
            # LLM-only mode: do not perform heuristic extraction. Always return clarification.
            return UPSOutput(
                intent="COST_BREAKDOWN",
                confidence=0.0,
                needs_clarification=True,
                clarification_question=(
                    "I'm experiencing technical difficulties accessing the AI service. Please try again in a moment or contact support if this persists."
                ) if is_transient_error else (
                    "I couldn't interpret your request due to an AI processing error. Could you rephrase or specify the time period and dimensions (e.g., 'last 30 days', 'by service')?"
                ),
                entities=UPSEntities(),
                reasoning=(
                    f"LLM processing error: {error_str}"
                )
            )

    # Heuristic extraction removed to ensure LLM-only behavior.


ups_extractor = UPSExtractor()
