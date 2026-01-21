"""
Time Range Module - Parse and merge time ranges for FinOps queries

This module provides:
- parse_time_range(text, tz) -> (start, end, granularity)
- merge_time_range(prev_context, new_request) -> TimeRangeResult

Precedence rules for merge_time_range:
1. Explicit time in user message overrides
2. Else inherit conversation time window
3. "compare to previous period" derives secondary range deterministically
"""

from datetime import datetime, date, timedelta
from typing import Dict, Any, Optional, Tuple, List
from enum import Enum
from dataclasses import dataclass, field
import re
import pytz
from dateutil.relativedelta import relativedelta
import structlog

logger = structlog.get_logger(__name__)


class Granularity(str, Enum):
    """Time granularity for cost analysis"""
    HOURLY = "HOURLY"
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    YEARLY = "YEARLY"


@dataclass
class TimeRange:
    """Represents a time range with metadata"""
    start: datetime
    end: datetime
    granularity: Granularity
    description: str
    source: str  # 'explicit', 'inherited', 'default', 'comparison'
    period_type: str  # 'rolling', 'calendar', 'specific', 'comparison'
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "start_date": self.start.strftime("%Y-%m-%d"),
            "end_date": self.end.strftime("%Y-%m-%d"),
            "start_datetime": self.start.isoformat(),
            "end_datetime": self.end.isoformat(),
            "granularity": self.granularity.value,
            "description": self.description,
            "source": self.source,
            "period_type": self.period_type,
            "metadata": self.metadata
        }

    def to_scope_string(self) -> str:
        """Generate scope string for chat responses"""
        return f"{self.start.strftime('%B %d, %Y')} to {self.end.strftime('%B %d, %Y')}"

    @property
    def days(self) -> int:
        """Number of days in the range"""
        return (self.end - self.start).days + 1


@dataclass
class TimeRangeResult:
    """Result of time range parsing/merging with optional comparison period"""
    primary: TimeRange
    comparison: Optional[TimeRange] = None
    is_comparison_request: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        result = {
            "primary": self.primary.to_dict(),
            "is_comparison": self.is_comparison_request
        }
        if self.comparison:
            result["comparison"] = self.comparison.to_dict()
        return result

    def to_scope_dict(self) -> Dict[str, Any]:
        """Generate scope dictionary for API responses"""
        scope = {
            "time_range": self.primary.to_scope_string(),
            "start_date": self.primary.start.strftime("%Y-%m-%d"),
            "end_date": self.primary.end.strftime("%Y-%m-%d"),
            "granularity": self.primary.granularity.value,
            "period_description": self.primary.description
        }
        if self.comparison:
            scope["comparison_range"] = self.comparison.to_scope_string()
            scope["comparison_start_date"] = self.comparison.start.strftime("%Y-%m-%d")
            scope["comparison_end_date"] = self.comparison.end.strftime("%Y-%m-%d")
        return scope


# Time range patterns for parsing
TIME_PATTERNS = [
    # Specific dates
    (r"(\d{4})-(\d{2})-(\d{2})\s*(?:to|through|-)\s*(\d{4})-(\d{2})-(\d{2})", "_parse_date_range"),
    (r"(\d{4})-(\d{2})-(\d{2})", "_parse_single_date"),

    # Month names with year
    (r"(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(\d{4})", "_parse_month_day_year"),
    (r"(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{4})", "_parse_month_year"),
    (r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+(\d{4})", "_parse_month_abbrev_year"),

    # Relative periods
    (r"\btoday\b", "_parse_today"),
    (r"\byesterday\b", "_parse_yesterday"),
    (r"last\s+(\d+)\s+days?", "_parse_last_n_days"),
    (r"past\s+(\d+)\s+days?", "_parse_last_n_days"),
    (r"last\s+(\d+)\s+months?", "_parse_last_n_months"),
    (r"past\s+(\d+)\s+months?", "_parse_last_n_months"),
    (r"last\s+(\d+)\s+weeks?", "_parse_last_n_weeks"),
    (r"past\s+(\d+)\s+weeks?", "_parse_last_n_weeks"),
    (r"last\s+(\d+)\s+years?", "_parse_last_n_years"),
    (r"past\s+(\d+)\s+years?", "_parse_last_n_years"),

    # Calendar periods
    (r"this\s+month", "_parse_this_month"),
    (r"current\s+month", "_parse_this_month"),
    (r"last\s+month", "_parse_last_month"),
    (r"previous\s+month", "_parse_last_month"),
    (r"this\s+week", "_parse_this_week"),
    (r"current\s+week", "_parse_this_week"),
    (r"last\s+week", "_parse_last_week"),
    (r"previous\s+week", "_parse_last_week"),
    (r"this\s+quarter", "_parse_this_quarter"),
    (r"current\s+quarter", "_parse_this_quarter"),
    (r"last\s+quarter", "_parse_last_quarter"),
    (r"previous\s+quarter", "_parse_last_quarter"),
    (r"q([1-4])\s+(\d{4})", "_parse_specific_quarter"),
    (r"q([1-4])\b", "_parse_quarter_current_year"),
    (r"this\s+year", "_parse_this_year"),
    (r"current\s+year", "_parse_this_year"),
    (r"last\s+year", "_parse_last_year"),
    (r"previous\s+year", "_parse_last_year"),
    (r"(?:ytd|year[\s-]to[\s-]date)", "_parse_ytd"),
    (r"(?:mtd|month[\s-]to[\s-]date)", "_parse_mtd"),
    (r"(?:wtd|week[\s-]to[\s-]date)", "_parse_wtd"),

    # Full year
    (r"(?:whole|entire|full)\s+year\s*(\d{4})?", "_parse_full_year"),
]

# Comparison patterns
COMPARISON_PATTERNS = [
    r"compar(?:e|ed|ing)\s+(?:to|with)\s+(?:the\s+)?(?:previous|prior|last)\s+(?:period|month|week|quarter|year)",
    r"(?:vs|versus|against)\s+(?:previous|prior|last)\s+(?:period|month|week|quarter|year)",
    r"(?:month|week|quarter|year)[\s-]over[\s-](?:month|week|quarter|year)",
    r"(?:mom|wow|qoq|yoy)\b",
    r"period[\s-]over[\s-]period",
    r"compare\s+periods?",
]


class TimeRangeParser:
    """Parse natural language time expressions into absolute date ranges"""

    MONTH_MAP = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
        "jan": 1, "feb": 2, "mar": 3, "apr": 4,
        "jun": 6, "jul": 7, "aug": 8,
        "sep": 9, "oct": 10, "nov": 11, "dec": 12
    }

    def __init__(self, tz: str = "UTC"):
        """Initialize parser with timezone"""
        self.tz = pytz.timezone(tz) if isinstance(tz, str) else tz

    def _now(self) -> datetime:
        """Get current datetime in configured timezone"""
        return datetime.now(self.tz)

    def _today(self) -> date:
        """Get today's date in configured timezone"""
        return self._now().date()

    def _determine_granularity(self, days: int) -> Granularity:
        """Determine appropriate granularity based on date range"""
        if days <= 2:
            return Granularity.HOURLY
        elif days <= 31:
            return Granularity.DAILY
        elif days <= 90:
            return Granularity.DAILY
        elif days <= 365:
            return Granularity.MONTHLY
        else:
            return Granularity.MONTHLY

    def _make_time_range(
        self,
        start: date,
        end: date,
        description: str,
        source: str = "explicit",
        period_type: str = "calendar",
        granularity: Optional[Granularity] = None,
        metadata: Optional[Dict] = None
    ) -> TimeRange:
        """Create a TimeRange object from dates"""
        start_dt = datetime.combine(start, datetime.min.time()).replace(tzinfo=self.tz)
        end_dt = datetime.combine(end, datetime.max.time().replace(microsecond=0)).replace(tzinfo=self.tz)

        days = (end - start).days + 1
        if granularity is None:
            granularity = self._determine_granularity(days)

        return TimeRange(
            start=start_dt,
            end=end_dt,
            granularity=granularity,
            description=description,
            source=source,
            period_type=period_type,
            metadata=metadata or {}
        )

    # Parser methods for each pattern
    def _parse_today(self, match: re.Match) -> TimeRange:
        today = self._today()
        return self._make_time_range(
            today, today,
            "Today",
            period_type="single_day",
            granularity=Granularity.HOURLY
        )

    def _parse_yesterday(self, match: re.Match) -> TimeRange:
        yesterday = self._today() - timedelta(days=1)
        return self._make_time_range(
            yesterday, yesterday,
            "Yesterday",
            period_type="single_day",
            granularity=Granularity.HOURLY
        )

    def _parse_last_n_days(self, match: re.Match) -> TimeRange:
        n = int(match.group(1))
        end_date = self._today()
        start_date = end_date - timedelta(days=n)
        return self._make_time_range(
            start_date, end_date,
            f"Last {n} days",
            period_type="rolling",
            metadata={"days": n}
        )

    def _parse_last_n_weeks(self, match: re.Match) -> TimeRange:
        n = int(match.group(1))
        end_date = self._today()
        start_date = end_date - timedelta(weeks=n)
        return self._make_time_range(
            start_date, end_date,
            f"Last {n} weeks",
            period_type="rolling",
            metadata={"weeks": n}
        )

    def _parse_last_n_months(self, match: re.Match) -> TimeRange:
        n = int(match.group(1))
        today = self._today()
        # Calculate N complete calendar months
        first_of_current = today.replace(day=1)
        end_date = first_of_current - timedelta(days=1)
        start_date = (end_date.replace(day=1) - relativedelta(months=n-1))
        return self._make_time_range(
            start_date, end_date,
            f"Last {n} complete calendar months",
            period_type="calendar_months",
            metadata={"months": n}
        )

    def _parse_last_n_years(self, match: re.Match) -> TimeRange:
        n = int(match.group(1))
        end_date = self._today()
        start_date = end_date - relativedelta(years=n)
        return self._make_time_range(
            start_date, end_date,
            f"Last {n} years",
            period_type="rolling",
            granularity=Granularity.MONTHLY,
            metadata={"years": n}
        )

    def _parse_this_month(self, match: re.Match) -> TimeRange:
        today = self._today()
        start_date = today.replace(day=1)
        return self._make_time_range(
            start_date, today,
            f"{start_date.strftime('%B %Y')} (month-to-date)",
            period_type="calendar_month_partial"
        )

    def _parse_last_month(self, match: re.Match) -> TimeRange:
        today = self._today()
        first_this_month = today.replace(day=1)
        end_date = first_this_month - timedelta(days=1)
        start_date = end_date.replace(day=1)
        return self._make_time_range(
            start_date, end_date,
            f"{start_date.strftime('%B %Y')} (full month)",
            period_type="calendar_month_full"
        )

    def _parse_this_week(self, match: re.Match) -> TimeRange:
        today = self._today()
        start_date = today - timedelta(days=today.weekday())  # Monday
        return self._make_time_range(
            start_date, today,
            "This week (week-to-date)",
            period_type="calendar_week_partial"
        )

    def _parse_last_week(self, match: re.Match) -> TimeRange:
        today = self._today()
        this_monday = today - timedelta(days=today.weekday())
        last_sunday = this_monday - timedelta(days=1)
        last_monday = last_sunday - timedelta(days=6)
        return self._make_time_range(
            last_monday, last_sunday,
            "Last week (full week)",
            period_type="calendar_week_full"
        )

    def _parse_this_quarter(self, match: re.Match) -> TimeRange:
        today = self._today()
        quarter = (today.month - 1) // 3 + 1
        quarter_start_month = (quarter - 1) * 3 + 1
        start_date = today.replace(month=quarter_start_month, day=1)
        return self._make_time_range(
            start_date, today,
            f"Q{quarter} {today.year} (quarter-to-date)",
            period_type="calendar_quarter_partial",
            metadata={"quarter": quarter, "year": today.year}
        )

    def _parse_last_quarter(self, match: re.Match) -> TimeRange:
        today = self._today()
        current_quarter = (today.month - 1) // 3 + 1

        if current_quarter == 1:
            quarter = 4
            year = today.year - 1
        else:
            quarter = current_quarter - 1
            year = today.year

        start_month = (quarter - 1) * 3 + 1
        start_date = date(year, start_month, 1)

        end_month = start_month + 2
        if end_month == 12:
            end_date = date(year, 12, 31)
        else:
            end_date = date(year, end_month + 1, 1) - timedelta(days=1)

        return self._make_time_range(
            start_date, end_date,
            f"Q{quarter} {year} (full quarter)",
            period_type="calendar_quarter_full",
            metadata={"quarter": quarter, "year": year}
        )

    def _parse_specific_quarter(self, match: re.Match) -> TimeRange:
        quarter = int(match.group(1))
        year = int(match.group(2))

        start_month = (quarter - 1) * 3 + 1
        start_date = date(year, start_month, 1)

        end_month = start_month + 2
        if end_month == 12:
            end_date = date(year, 12, 31)
        else:
            end_date = date(year, end_month + 1, 1) - timedelta(days=1)

        return self._make_time_range(
            start_date, end_date,
            f"Q{quarter} {year}",
            period_type="calendar_quarter_full",
            metadata={"quarter": quarter, "year": year}
        )

    def _parse_quarter_current_year(self, match: re.Match) -> TimeRange:
        quarter = int(match.group(1))
        year = self._today().year

        start_month = (quarter - 1) * 3 + 1
        start_date = date(year, start_month, 1)

        end_month = start_month + 2
        if end_month == 12:
            end_date = date(year, 12, 31)
        else:
            end_date = date(year, end_month + 1, 1) - timedelta(days=1)

        return self._make_time_range(
            start_date, end_date,
            f"Q{quarter} {year}",
            period_type="calendar_quarter_full",
            metadata={"quarter": quarter, "year": year}
        )

    def _parse_this_year(self, match: re.Match) -> TimeRange:
        today = self._today()
        start_date = date(today.year, 1, 1)
        return self._make_time_range(
            start_date, today,
            f"{today.year} (year-to-date)",
            period_type="calendar_year_partial",
            granularity=Granularity.MONTHLY
        )

    def _parse_last_year(self, match: re.Match) -> TimeRange:
        year = self._today().year - 1
        start_date = date(year, 1, 1)
        end_date = date(year, 12, 31)
        return self._make_time_range(
            start_date, end_date,
            f"{year} (full year)",
            period_type="calendar_year_full",
            granularity=Granularity.MONTHLY
        )

    def _parse_ytd(self, match: re.Match) -> TimeRange:
        today = self._today()
        start_date = date(today.year, 1, 1)
        return self._make_time_range(
            start_date, today,
            f"Year-to-date {today.year}",
            period_type="calendar_year_partial",
            granularity=Granularity.MONTHLY
        )

    def _parse_mtd(self, match: re.Match) -> TimeRange:
        today = self._today()
        start_date = today.replace(day=1)
        return self._make_time_range(
            start_date, today,
            f"Month-to-date ({today.strftime('%B %Y')})",
            period_type="calendar_month_partial"
        )

    def _parse_wtd(self, match: re.Match) -> TimeRange:
        today = self._today()
        start_date = today - timedelta(days=today.weekday())
        return self._make_time_range(
            start_date, today,
            "Week-to-date",
            period_type="calendar_week_partial"
        )

    def _parse_full_year(self, match: re.Match) -> TimeRange:
        year_str = match.group(1)
        if year_str:
            year = int(year_str)
        else:
            year = self._today().year - 1  # Default to last year

        start_date = date(year, 1, 1)
        end_date = date(year, 12, 31)
        return self._make_time_range(
            start_date, end_date,
            f"{year} (full year)",
            period_type="calendar_year_full",
            granularity=Granularity.MONTHLY
        )

    def _parse_month_year(self, match: re.Match) -> TimeRange:
        month_name = match.group(1).lower()
        year = int(match.group(2))
        month = self.MONTH_MAP[month_name]

        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year, 12, 31)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)

        return self._make_time_range(
            start_date, end_date,
            f"{start_date.strftime('%B %Y')} (full month)",
            period_type="calendar_month_full",
            metadata={"month": month, "year": year}
        )

    def _parse_month_abbrev_year(self, match: re.Match) -> TimeRange:
        month_abbrev = match.group(1).lower()
        year = int(match.group(2))
        month = self.MONTH_MAP[month_abbrev]

        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year, 12, 31)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)

        return self._make_time_range(
            start_date, end_date,
            f"{start_date.strftime('%B %Y')} (full month)",
            period_type="calendar_month_full",
            metadata={"month": month, "year": year}
        )

    def _parse_month_day_year(self, match: re.Match) -> TimeRange:
        month_name = match.group(1).lower()
        day = int(match.group(2))
        year = int(match.group(3))
        month = self.MONTH_MAP[month_name]

        specific_date = date(year, month, day)
        return self._make_time_range(
            specific_date, specific_date,
            specific_date.strftime("%B %d, %Y"),
            period_type="specific_date",
            granularity=Granularity.HOURLY
        )

    def _parse_date_range(self, match: re.Match) -> TimeRange:
        start_year = int(match.group(1))
        start_month = int(match.group(2))
        start_day = int(match.group(3))
        end_year = int(match.group(4))
        end_month = int(match.group(5))
        end_day = int(match.group(6))

        start_date = date(start_year, start_month, start_day)
        end_date = date(end_year, end_month, end_day)

        return self._make_time_range(
            start_date, end_date,
            f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}",
            period_type="specific_range"
        )

    def _parse_single_date(self, match: re.Match) -> TimeRange:
        year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))

        single_date = date(year, month, day)
        return self._make_time_range(
            single_date, single_date,
            single_date.strftime("%B %d, %Y"),
            period_type="specific_date",
            granularity=Granularity.HOURLY
        )

    def _default_time_range(self) -> TimeRange:
        """Return default 30-day rolling window"""
        end_date = self._today()
        start_date = end_date - timedelta(days=30)
        return self._make_time_range(
            start_date, end_date,
            "Last 30 days (default)",
            source="default",
            period_type="rolling",
            metadata={"days": 30}
        )

    def parse(self, text: str) -> TimeRange:
        """
        Parse time range from natural language text.

        Args:
            text: Natural language query containing time references

        Returns:
            TimeRange object with parsed dates
        """
        text_lower = text.lower().strip()

        for pattern, handler_name in TIME_PATTERNS:
            match = re.search(pattern, text_lower, re.IGNORECASE)
            if match:
                try:
                    handler = getattr(self, handler_name)
                    time_range = handler(match)
                    logger.info(
                        "Time range parsed",
                        pattern=pattern,
                        description=time_range.description,
                        start=time_range.start.strftime("%Y-%m-%d"),
                        end=time_range.end.strftime("%Y-%m-%d")
                    )
                    return time_range
                except Exception as e:
                    logger.warning(f"Error parsing time with pattern {pattern}: {e}")
                    continue

        logger.info("No time range found, using default 30 days")
        return self._default_time_range()

    def is_comparison_request(self, text: str) -> bool:
        """Check if the query requests period comparison"""
        text_lower = text.lower()
        for pattern in COMPARISON_PATTERNS:
            if re.search(pattern, text_lower):
                return True
        return False

    def derive_comparison_period(self, primary: TimeRange) -> TimeRange:
        """
        Derive comparison period based on primary period type.
        Uses deterministic rules based on period type.
        """
        days = primary.days

        # Calculate comparison start and end
        comparison_end = primary.start - timedelta(days=1)
        comparison_start = comparison_end - timedelta(days=days - 1)

        # Determine comparison description
        if primary.period_type == "calendar_month_full":
            # Previous month
            comparison_end = primary.start - timedelta(days=1)
            comparison_start = comparison_end.replace(day=1)
            description = f"{comparison_start.strftime('%B %Y')} (comparison)"
        elif primary.period_type == "calendar_quarter_full":
            # Previous quarter
            quarter = primary.metadata.get("quarter", 1)
            year = primary.metadata.get("year", self._today().year)
            if quarter == 1:
                prev_quarter = 4
                prev_year = year - 1
            else:
                prev_quarter = quarter - 1
                prev_year = year

            start_month = (prev_quarter - 1) * 3 + 1
            comparison_start = date(prev_year, start_month, 1)
            end_month = start_month + 2
            if end_month == 12:
                comparison_end = date(prev_year, 12, 31)
            else:
                comparison_end = date(prev_year, end_month + 1, 1) - timedelta(days=1)
            description = f"Q{prev_quarter} {prev_year} (comparison)"
        elif primary.period_type == "calendar_year_full":
            # Previous year
            year = primary.metadata.get("year", self._today().year - 1)
            prev_year = year - 1
            comparison_start = date(prev_year, 1, 1)
            comparison_end = date(prev_year, 12, 31)
            description = f"{prev_year} (comparison)"
        else:
            # Default: same number of days before
            description = f"Previous {days} days (comparison)"

        return self._make_time_range(
            comparison_start if isinstance(comparison_start, date) else comparison_start.date(),
            comparison_end if isinstance(comparison_end, date) else comparison_end.date(),
            description,
            source="comparison",
            period_type="comparison",
            granularity=primary.granularity
        )


def parse_time_range(text: str, tz: str = "UTC") -> Tuple[datetime, datetime, Granularity]:
    """
    Parse time range from natural language text.

    Args:
        text: Natural language query
        tz: Timezone string (default: UTC)

    Returns:
        Tuple of (start_datetime, end_datetime, granularity)
    """
    parser = TimeRangeParser(tz)
    time_range = parser.parse(text)
    return (time_range.start, time_range.end, time_range.granularity)


def merge_time_range(
    prev_context: Optional[Dict[str, Any]],
    new_request: str,
    tz: str = "UTC"
) -> TimeRangeResult:
    """
    Merge time range from previous context with new request.

    Precedence rules:
    1. Explicit time in user message overrides
    2. Else inherit conversation time window
    3. "compare to previous period" derives secondary range deterministically

    Args:
        prev_context: Previous conversation context with time_range info
        new_request: New user message
        tz: Timezone string

    Returns:
        TimeRangeResult with primary (and optional comparison) time range
    """
    parser = TimeRangeParser(tz)

    # Check if new request has explicit time reference
    explicit_time = None
    new_request_lower = new_request.lower()

    for pattern, _ in TIME_PATTERNS:
        if re.search(pattern, new_request_lower, re.IGNORECASE):
            explicit_time = parser.parse(new_request)
            explicit_time.source = "explicit"
            break

    # Determine primary time range
    if explicit_time:
        # Rule 1: Explicit time in user message overrides
        primary = explicit_time
        logger.info("Using explicit time range from user message", description=primary.description)
    elif prev_context and prev_context.get("time_range"):
        # Rule 2: Inherit from conversation context
        ctx_time = prev_context["time_range"]
        if isinstance(ctx_time, dict):
            # Reconstruct TimeRange from dict
            start = datetime.fromisoformat(ctx_time.get("start_datetime", ctx_time.get("start_date")))
            end = datetime.fromisoformat(ctx_time.get("end_datetime", ctx_time.get("end_date")))
            primary = TimeRange(
                start=start,
                end=end,
                granularity=Granularity(ctx_time.get("granularity", "DAILY")),
                description=ctx_time.get("description", "Inherited from context"),
                source="inherited",
                period_type=ctx_time.get("period_type", "unknown"),
                metadata=ctx_time.get("metadata", {})
            )
        elif isinstance(ctx_time, TimeRange):
            primary = ctx_time
            primary.source = "inherited"
        else:
            primary = parser._default_time_range()
        logger.info("Inheriting time range from context", description=primary.description)
    else:
        # No explicit time, no context - use default
        primary = parser._default_time_range()
        logger.info("Using default time range")

    # Rule 3: Check for comparison request
    is_comparison = parser.is_comparison_request(new_request)
    comparison = None

    if is_comparison:
        comparison = parser.derive_comparison_period(primary)
        logger.info("Derived comparison period", description=comparison.description)

    return TimeRangeResult(
        primary=primary,
        comparison=comparison,
        is_comparison_request=is_comparison
    )
