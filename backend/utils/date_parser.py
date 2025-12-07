"""
Date Parsing Utility - Comprehensive time range resolution for FinOps queries

⚠️ DEPRECATION NOTICE ⚠️
This regex-based date parser is being phased out in favor of LLM-based extraction.
New code should use UPSExtractor for date interpretation, which provides:
- Better semantic understanding (handles "last months", "recent months", etc.)
- Context-aware interpretation
- Confidence scores for ambiguous dates
- Self-improving via prompt refinement

This module is maintained only for backward compatibility with:
- conversation_context.py (legacy fallback)
- response_formatter.py (date formatting utilities)
- athena_executor.py (default date calculation)

For new features, use: backend/services/ups_extractor.py with LLM-based date extraction.
See: ARCHITECTURE_IMPROVEMENT_PROPOSAL.md for migration strategy.

Legacy Description:
Converts relative dates (last 30 days, this month, Q1, YTD) to absolute date ranges
Default: Last 30 days rolling if no timeframe specified
"""

from typing import Dict, Tuple, Optional, Any
from datetime import datetime, timedelta, date
from dateutil.relativedelta import relativedelta
import re
import structlog

logger = structlog.get_logger(__name__)


class DateParser:
    """
    ⚠️ DEPRECATED: Use UPSExtractor for date extraction in new code.
    
    Parse natural language time expressions into absolute date ranges.
    Implements TIME PARSING RULES from specification.
    """
    
    def __init__(self):
        """Initialize date parser with patterns"""
        self.pattern_handlers = [
            (r"\byesterday\b", self._parse_yesterday),
            (r"\btoday\b", self._parse_today),
            (r"last\s+(\d+)\s+days?", self._parse_last_n_days),
            (r"past\s+(\d+)\s+days?", self._parse_last_n_days),
            (r"for\s+(\d+)\s+days?", self._parse_last_n_days),  # Support "for N days"
            (r"last\s+(\d+)\s+months?", self._parse_last_n_months),
            (r"past\s+(\d+)\s+months?", self._parse_last_n_months),
            (r"for\s+(\d+)\s+months?", self._parse_last_n_months),  # Support "for N months"
            (r"last\s+months", self._parse_last_months_plural),  # Support "last months" (defaults to 12)
            (r"past\s+months", self._parse_last_months_plural),  # Support "past months" (defaults to 12)
            (r"last\s+(\d+)\s+years?", self._parse_last_n_years),
            (r"past\s+(\d+)\s+years?", self._parse_last_n_years),
            (r"for\s+(\d+)\s+years?", self._parse_last_n_years),  # Support "for N years"
            (r"(?:last|whole|entire|full)\s+year", self._parse_last_full_year),
            (r"(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(\d{4})", self._parse_month_day_year),
            (r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(\d{4})?", self._parse_month_abbrev_day),
            (r"this\s+month", self._parse_this_month),
            (r"current\s+month", self._parse_this_month),
            (r"last\s+month", self._parse_last_month),
            (r"previous\s+month", self._parse_last_month),
            (r"this\s+week", self._parse_this_week),
            (r"last\s+week", self._parse_last_week),
            (r"this\s+quarter", self._parse_this_quarter),
            (r"last\s+quarter", self._parse_last_quarter),
            (r"q([1-4])\s+(\d{4})", self._parse_specific_quarter),
            (r"q([1-4])", self._parse_quarter_current_year),
            (r"ytd", self._parse_ytd),
            (r"year\s+to\s+date", self._parse_ytd),
            (r"this\s+year", self._parse_this_year),
            (r"last\s+year", self._parse_last_year),
            (r"(\d{4})-(\d{2})-(\d{2})", self._parse_specific_date_range),
            (r"(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{4})", self._parse_month_year),
            (r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+(\d{4})", self._parse_month_abbrev_year),
        ]
    
    def parse_time_range(self, query: str) -> Tuple[str, str, Dict[str, Any]]:
        """
        Parse time range from query text.
        
        Args:
            query: Natural language query
            
        Returns:
            Tuple of (start_date, end_date, metadata) in YYYY-MM-DD format
            Default: Last 30 days if no timeframe found
        """
        query_lower = query.lower().strip()
        
        # Try each pattern handler
        for pattern, handler in self.pattern_handlers:
            match = re.search(pattern, query_lower, re.IGNORECASE)
            if match:
                try:
                    start_date, end_date, metadata = handler(match)
                    metadata["source"] = "explicit"
                    metadata["pattern_matched"] = pattern
                    
                    logger.info(
                        "Time range parsed",
                        start_date=start_date,
                        end_date=end_date,
                        source=metadata.get("description")
                    )
                    
                    return start_date, end_date, metadata
                except Exception as e:
                    logger.warning(f"Error parsing date with pattern {pattern}: {e}")
                    continue
        
        # Default: Last 30 days rolling
        logger.info("No timeframe specified, defaulting to last 30 days")
        return self._default_last_30_days()
    
    def _default_last_30_days(self) -> Tuple[str, str, Dict[str, Any]]:
        """Default to last 30 days rolling"""
        end_date = date.today()
        start_date = end_date - timedelta(days=30)
        
        return (
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d"),
            {
                "description": "Last 30 days (default)",
                "source": "default",
                "period_type": "rolling",
                "days": 30
            }
        )
    
    def _parse_today(self, match: re.Match) -> Tuple[str, str, Dict[str, Any]]:
        """Parse 'today' → today to today"""
        today = date.today()
        today_str = today.strftime("%Y-%m-%d")
        return (
            today_str,
            today_str,
            {
                "description": "Today",
                "period_type": "single_day",
                "days": 1
            }
        )
    
    def _parse_yesterday(self, match: re.Match) -> Tuple[str, str, Dict[str, Any]]:
        """Parse 'yesterday' → previous day"""
        yesterday = date.today() - timedelta(days=1)
        yesterday_str = yesterday.strftime("%Y-%m-%d")
        return (
            yesterday_str,
            yesterday_str,
            {
                "description": "Yesterday",
                "period_type": "single_day",
                "days": 1
            }
        )
    
    def _parse_last_n_days(self, match: re.Match) -> Tuple[str, str, Dict[str, Any]]:
        """Parse 'last N days' or 'past N days'"""
        n = int(match.group(1))
        end_date = date.today()
        start_date = end_date - timedelta(days=n)
        
        return (
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d"),
            {
                "description": f"Last {n} days (rolling)",
                "period_type": "rolling",
                "days": n
            }
        )
    
    def _parse_last_n_months(self, match: re.Match) -> Tuple[str, str, Dict[str, Any]]:
        """Parse 'last N months' or 'past N months' - returns N complete calendar months"""
        n = int(match.group(1))
        today = date.today()
        
        # Calculate N complete calendar months (excluding current partial month)
        # End date: last day of previous month
        first_of_current_month = today.replace(day=1)
        end_date = first_of_current_month - timedelta(days=1)
        
        # Start date: first day of month N months before end_date
        start_date = (end_date.replace(day=1) - relativedelta(months=n-1))
        
        return (
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d"),
            {
                "description": f"Last {n} complete calendar months",
                "period_type": "calendar_months",
                "months": n,
                "days": (end_date - start_date).days + 1
            }
        )
    
    def _parse_last_months_plural(self, match: re.Match) -> Tuple[str, str, Dict[str, Any]]:
        """Parse 'last months' or 'past months' without number (defaults to 12 complete calendar months)"""
        n = 12  # Default to 12 months when plural "months" is used without a number
        today = date.today()
        
        # Calculate N complete calendar months (excluding current partial month)
        # End date: last day of previous month
        first_of_current_month = today.replace(day=1)
        end_date = first_of_current_month - timedelta(days=1)
        
        # Start date: first day of month N months before end_date
        start_date = (end_date.replace(day=1) - relativedelta(months=n-1))
        
        return (
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d"),
            {
                "description": f"Last {n} complete calendar months (inferred from 'months' plural)",
                "period_type": "calendar_months",
                "months": n,
                "days": (end_date - start_date).days + 1
            }
        )
    
    def _parse_last_n_years(self, match: re.Match) -> Tuple[str, str, Dict[str, Any]]:
        """Parse 'last N years' or 'past N years'"""
        n = int(match.group(1))
        end_date = date.today()
        start_date = end_date - relativedelta(years=n)
        
        return (
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d"),
            {
                "description": f"Last {n} years (rolling)",
                "period_type": "rolling",
                "years": n,
                "days": (end_date - start_date).days
            }
        )
    
    def _parse_this_month(self, match: re.Match) -> Tuple[str, str, Dict[str, Any]]:
        """Parse 'this month' → 1st of current month → today"""
        today = date.today()
        start_date = today.replace(day=1)
        end_date = today
        
        return (
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d"),
            {
                "description": f"{start_date.strftime('%B %Y')} (month-to-date)",
                "period_type": "calendar_month_partial",
                "month": start_date.month,
                "year": start_date.year
            }
        )
    
    def _parse_last_month(self, match: re.Match) -> Tuple[str, str, Dict[str, Any]]:
        """Parse 'last month' → previous full calendar month"""
        today = date.today()
        first_this_month = today.replace(day=1)
        last_day_last_month = first_this_month - timedelta(days=1)
        first_last_month = last_day_last_month.replace(day=1)
        
        return (
            first_last_month.strftime("%Y-%m-%d"),
            last_day_last_month.strftime("%Y-%m-%d"),
            {
                "description": f"{first_last_month.strftime('%B %Y')} (full month)",
                "period_type": "calendar_month_full",
                "month": first_last_month.month,
                "year": first_last_month.year
            }
        )
    
    def _parse_this_week(self, match: re.Match) -> Tuple[str, str, Dict[str, Any]]:
        """Parse 'this week' → Monday to today"""
        today = date.today()
        start_date = today - timedelta(days=today.weekday())
        
        return (
            start_date.strftime("%Y-%m-%d"),
            today.strftime("%Y-%m-%d"),
            {
                "description": "This week (week-to-date)",
                "period_type": "calendar_week_partial"
            }
        )
    
    def _parse_last_week(self, match: re.Match) -> Tuple[str, str, Dict[str, Any]]:
        """Parse 'last week' → previous full week (Mon-Sun)"""
        today = date.today()
        this_monday = today - timedelta(days=today.weekday())
        last_sunday = this_monday - timedelta(days=1)
        last_monday = last_sunday - timedelta(days=6)
        
        return (
            last_monday.strftime("%Y-%m-%d"),
            last_sunday.strftime("%Y-%m-%d"),
            {
                "description": "Last week (full week)",
                "period_type": "calendar_week_full"
            }
        )
    
    def _parse_this_quarter(self, match: re.Match) -> Tuple[str, str, Dict[str, Any]]:
        """Parse 'this quarter' → first day of quarter → today"""
        today = date.today()
        quarter = (today.month - 1) // 3 + 1
        quarter_start_month = (quarter - 1) * 3 + 1
        start_date = today.replace(month=quarter_start_month, day=1)
        
        return (
            start_date.strftime("%Y-%m-%d"),
            today.strftime("%Y-%m-%d"),
            {
                "description": f"Q{quarter} {today.year} (quarter-to-date)",
                "period_type": "calendar_quarter_partial",
                "quarter": quarter,
                "year": today.year
            }
        )
    
    def _parse_last_quarter(self, match: re.Match) -> Tuple[str, str, Dict[str, Any]]:
        """Parse 'last quarter' → previous full quarter"""
        today = date.today()
        current_quarter = (today.month - 1) // 3 + 1
        
        if current_quarter == 1:
            # Last Q4 of previous year
            quarter = 4
            year = today.year - 1
        else:
            quarter = current_quarter - 1
            year = today.year
        
        start_month = (quarter - 1) * 3 + 1
        start_date = date(year, start_month, 1)
        
        # End of quarter
        end_month = start_month + 2
        if end_month == 12:
            end_date = date(year, 12, 31)
        else:
            end_date = date(year, end_month + 1, 1) - timedelta(days=1)
        
        return (
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d"),
            {
                "description": f"Q{quarter} {year} (full quarter)",
                "period_type": "calendar_quarter_full",
                "quarter": quarter,
                "year": year
            }
        )
    
    def _parse_specific_quarter(self, match: re.Match) -> Tuple[str, str, Dict[str, Any]]:
        """Parse 'Q1 2024' → specific quarter and year"""
        quarter = int(match.group(1))
        year = int(match.group(2))
        
        start_month = (quarter - 1) * 3 + 1
        start_date = date(year, start_month, 1)
        
        end_month = start_month + 2
        if end_month == 12:
            end_date = date(year, 12, 31)
        else:
            end_date = date(year, end_month + 1, 1) - timedelta(days=1)
        
        return (
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d"),
            {
                "description": f"Q{quarter} {year} (full quarter)",
                "period_type": "calendar_quarter_full",
                "quarter": quarter,
                "year": year
            }
        )
    
    def _parse_quarter_current_year(self, match: re.Match) -> Tuple[str, str, Dict[str, Any]]:
        """Parse 'Q1' → quarter in current year"""
        quarter = int(match.group(1))
        year = date.today().year
        
        start_month = (quarter - 1) * 3 + 1
        start_date = date(year, start_month, 1)
        
        end_month = start_month + 2
        if end_month == 12:
            end_date = date(year, 12, 31)
        else:
            end_date = date(year, end_month + 1, 1) - timedelta(days=1)
        
        return (
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d"),
            {
                "description": f"Q{quarter} {year} (full quarter)",
                "period_type": "calendar_quarter_full",
                "quarter": quarter,
                "year": year
            }
        )
    
    def _parse_ytd(self, match: re.Match) -> Tuple[str, str, Dict[str, Any]]:
        """Parse 'YTD' or 'year to date' → Jan 1 → today"""
        today = date.today()
        start_date = date(today.year, 1, 1)
        
        return (
            start_date.strftime("%Y-%m-%d"),
            today.strftime("%Y-%m-%d"),
            {
                "description": f"Year-to-date {today.year}",
                "period_type": "calendar_year_partial",
                "year": today.year
            }
        )
    
    def _parse_this_year(self, match: re.Match) -> Tuple[str, str, Dict[str, Any]]:
        """Parse 'this year' → Jan 1 → today"""
        return self._parse_ytd(match)
    
    def _parse_last_year(self, match: re.Match) -> Tuple[str, str, Dict[str, Any]]:
        """Parse 'last year' → full previous calendar year"""
        today = date.today()
        year = today.year - 1
        start_date = date(year, 1, 1)
        end_date = date(year, 12, 31)
        
        return (
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d"),
            {
                "description": f"{year} (full year)",
                "period_type": "calendar_year_full",
                "year": year
            }
        )
    
    def _parse_last_full_year(self, match: re.Match) -> Tuple[str, str, Dict[str, Any]]:
        """Parse 'last year', 'whole year', 'entire year', 'full year' → full previous calendar year (Jan 1 - Dec 31)"""
        today = date.today()
        year = today.year - 1
        start_date = date(year, 1, 1)
        end_date = date(year, 12, 31)
        
        return (
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d"),
            {
                "description": f"{year} (full year)",
                "period_type": "calendar_year_full",
                "year": year
            }
        )
    
    def _parse_specific_date_range(self, match: re.Match) -> Tuple[str, str, Dict[str, Any]]:
        """Parse explicit date like '2025-09-01'"""
        # This will be expanded if two dates are provided
        year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))
        
        single_date = date(year, month, day)
        
        return (
            single_date.strftime("%Y-%m-%d"),
            single_date.strftime("%Y-%m-%d"),
            {
                "description": f"Specific date: {single_date.strftime('%B %d, %Y')}",
                "period_type": "specific_date"
            }
        )
    
    def _parse_month_year(self, match: re.Match) -> Tuple[str, str, Dict[str, Any]]:
        """Parse 'September 2025' → full month"""
        month_name = match.group(1).lower()
        year = int(match.group(2))
        
        month_map = {
            "january": 1, "february": 2, "march": 3, "april": 4,
            "may": 5, "june": 6, "july": 7, "august": 8,
            "september": 9, "october": 10, "november": 11, "december": 12
        }
        
        month = month_map[month_name]
        start_date = date(year, month, 1)
        
        # Last day of month
        if month == 12:
            end_date = date(year, 12, 31)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)
        
        return (
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d"),
            {
                "description": f"{start_date.strftime('%B %Y')} (full month)",
                "period_type": "calendar_month_full",
                "month": month,
                "year": year
            }
        )
    
    def _parse_month_day_year(self, match: re.Match) -> Tuple[str, str, Dict[str, Any]]:
        """Parse 'February 6, 2025' or 'February 6 2025' → specific date"""
        month_name = match.group(1).lower()
        day = int(match.group(2))
        year = int(match.group(3))
        
        month_map = {
            "january": 1, "february": 2, "march": 3, "april": 4,
            "may": 5, "june": 6, "july": 7, "august": 8,
            "september": 9, "october": 10, "november": 11, "december": 12
        }
        
        month = month_map[month_name]
        specific_date = date(year, month, day)
        
        return (
            specific_date.strftime("%Y-%m-%d"),
            specific_date.strftime("%Y-%m-%d"),
            {
                "description": specific_date.strftime("%B %d, %Y"),
                "period_type": "specific_date",
                "date": specific_date.strftime("%Y-%m-%d")
            }
        )
    
    def _parse_month_abbrev_day(self, match: re.Match) -> Tuple[str, str, Dict[str, Any]]:
        """Parse 'feb 6' or 'sep 6 2025' → specific date (current year if not specified)"""
        month_abbrev = match.group(1).lower()
        day = int(match.group(2))
        year_str = match.group(3)
        
        # Default to current year if not specified
        year = int(year_str) if year_str else date.today().year
        
        month_map = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4,
            "may": 5, "jun": 6, "jul": 7, "aug": 8,
            "sep": 9, "oct": 10, "nov": 11, "dec": 12
        }
        
        month = month_map[month_abbrev]
        specific_date = date(year, month, day)
        
        return (
            specific_date.strftime("%Y-%m-%d"),
            specific_date.strftime("%Y-%m-%d"),
            {
                "description": specific_date.strftime("%B %d, %Y"),
                "period_type": "specific_date",
                "date": specific_date.strftime("%Y-%m-%d")
            }
        )
    
    def _parse_month_abbrev_year(self, match: re.Match) -> Tuple[str, str, Dict[str, Any]]:
        """Parse 'Sep 2025' → full month"""
        month_abbrev = match.group(1).lower()
        year = int(match.group(2))
        
        month_map = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4,
            "may": 5, "jun": 6, "jul": 7, "aug": 8,
            "sep": 9, "oct": 10, "nov": 11, "dec": 12
        }
        
        month = month_map[month_abbrev]
        start_date = date(year, month, 1)
        
        # Last day of month
        if month == 12:
            end_date = date(year, 12, 31)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)
        
        return (
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d"),
            {
                "description": f"{start_date.strftime('%B %Y')} (full month)",
                "period_type": "calendar_month_full",
                "month": month,
                "year": year
            }
        )
    
    def format_scope_period(self, start_date: str, end_date: str, metadata: Dict[str, Any]) -> str:
        """
        Format time range for Scope section.
        
        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            metadata: Time range metadata
            
        Returns:
            Formatted period string for Scope
        """
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            
            # Format as "MMM DD, YYYY → MMM DD, YYYY"
            if start_date == end_date:
                return start_dt.strftime("%B %d, %Y")
            else:
                return f"{start_dt.strftime('%B %d, %Y')} → {end_dt.strftime('%B %d, %Y')}"
        except:
            return f"{start_date} to {end_date}"


# Global instance
date_parser = DateParser()
