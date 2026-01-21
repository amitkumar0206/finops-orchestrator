"""
Tests for the time_range module.

Tests cover:
- parse_time_range function
- merge_time_range function with precedence rules
- Various time expressions (rolling, calendar, specific)
- Comparison period derivation
"""

import pytest
from datetime import datetime, date, timedelta
from freezegun import freeze_time
import pytz

from backend.finops.time_range import (
    parse_time_range,
    merge_time_range,
    TimeRange,
    TimeRangeResult,
    Granularity,
    TimeRangeParser,
)


@pytest.fixture
def parser():
    """Create a parser instance"""
    return TimeRangeParser(tz="UTC")


class TestParseTimeRange:
    """Test the parse_time_range function"""

    @freeze_time("2026-01-21")
    def test_last_30_days(self):
        """Test 'last 30 days' parsing"""
        start, end, granularity = parse_time_range("Show me costs for the last 30 days")

        assert start.date() == date(2025, 12, 22)
        assert end.date() == date(2026, 1, 21)
        assert granularity == Granularity.DAILY

    @freeze_time("2026-01-21")
    def test_last_7_days(self):
        """Test 'last 7 days' parsing"""
        start, end, granularity = parse_time_range("costs for last 7 days")

        assert start.date() == date(2026, 1, 14)
        assert end.date() == date(2026, 1, 21)
        assert granularity == Granularity.DAILY

    @freeze_time("2026-01-21")
    def test_this_month(self):
        """Test 'this month' parsing"""
        start, end, granularity = parse_time_range("show me this month's costs")

        assert start.date() == date(2026, 1, 1)
        assert end.date() == date(2026, 1, 21)

    @freeze_time("2026-01-21")
    def test_last_month(self):
        """Test 'last month' parsing"""
        start, end, granularity = parse_time_range("what were costs last month")

        assert start.date() == date(2025, 12, 1)
        assert end.date() == date(2025, 12, 31)

    @freeze_time("2026-01-21")
    def test_specific_month_year(self):
        """Test 'November 2025' parsing"""
        start, end, granularity = parse_time_range("show me November 2025 costs")

        assert start.date() == date(2025, 11, 1)
        assert end.date() == date(2025, 11, 30)

    @freeze_time("2026-01-21")
    def test_specific_date_range(self):
        """Test explicit date range parsing"""
        start, end, granularity = parse_time_range(
            "show costs from 2025-11-01 to 2025-11-15"
        )

        assert start.date() == date(2025, 11, 1)
        assert end.date() == date(2025, 11, 15)

    @freeze_time("2026-01-21")
    def test_ytd(self):
        """Test 'year-to-date' parsing"""
        start, end, granularity = parse_time_range("show YTD costs")

        assert start.date() == date(2026, 1, 1)
        assert end.date() == date(2026, 1, 21)
        assert granularity == Granularity.MONTHLY

    @freeze_time("2026-01-21")
    def test_last_quarter(self):
        """Test 'last quarter' parsing"""
        start, end, granularity = parse_time_range("show last quarter")

        assert start.date() == date(2025, 10, 1)
        assert end.date() == date(2025, 12, 31)

    @freeze_time("2026-01-21")
    def test_specific_quarter(self):
        """Test 'Q3 2025' parsing"""
        start, end, granularity = parse_time_range("show Q3 2025 costs")

        assert start.date() == date(2025, 7, 1)
        assert end.date() == date(2025, 9, 30)

    @freeze_time("2026-01-21")
    def test_today(self):
        """Test 'today' parsing"""
        start, end, granularity = parse_time_range("show today's costs")

        assert start.date() == date(2026, 1, 21)
        assert end.date() == date(2026, 1, 21)
        assert granularity == Granularity.HOURLY

    @freeze_time("2026-01-21")
    def test_yesterday(self):
        """Test 'yesterday' parsing"""
        start, end, granularity = parse_time_range("what was yesterday's spend")

        assert start.date() == date(2026, 1, 20)
        assert end.date() == date(2026, 1, 20)
        assert granularity == Granularity.HOURLY

    @freeze_time("2026-01-21")
    def test_default_when_no_time_found(self):
        """Test default 30-day range when no time expression found"""
        start, end, granularity = parse_time_range("show me EC2 costs by region")

        # Should default to last 30 days
        assert start.date() == date(2025, 12, 22)
        assert end.date() == date(2026, 1, 21)


class TestMergeTimeRange:
    """Test the merge_time_range function with precedence rules"""

    @freeze_time("2026-01-21")
    def test_explicit_time_overrides_context(self):
        """Rule 1: Explicit time in user message overrides context"""
        prev_context = {
            "time_range": {
                "start_datetime": "2025-11-01T00:00:00+00:00",
                "end_datetime": "2025-11-30T23:59:59+00:00",
                "granularity": "DAILY",
                "description": "November 2025",
            }
        }

        result = merge_time_range(prev_context, "show me costs for December 2025")

        assert result.primary.start.date() == date(2025, 12, 1)
        assert result.primary.end.date() == date(2025, 12, 31)
        assert result.primary.source == "explicit"

    @freeze_time("2026-01-21")
    def test_inherit_from_context_when_no_explicit_time(self):
        """Rule 2: Inherit time from conversation context"""
        prev_context = {
            "time_range": {
                "start_datetime": "2025-11-01T00:00:00+00:00",
                "end_datetime": "2025-11-30T23:59:59+00:00",
                "granularity": "DAILY",
                "description": "November 2025",
                "period_type": "calendar_month_full",
            }
        }

        result = merge_time_range(prev_context, "break it down by service")

        # Should inherit November from context
        assert result.primary.start.month == 11
        assert result.primary.source == "inherited"

    @freeze_time("2026-01-21")
    def test_default_when_no_context_no_explicit(self):
        """Default to 30 days when no context and no explicit time"""
        result = merge_time_range(None, "show me EC2 costs")

        # Should default to last 30 days
        assert result.primary.source == "default"
        assert (result.primary.end - result.primary.start).days >= 30

    @freeze_time("2026-01-21")
    def test_comparison_request_derives_secondary_range(self):
        """Rule 3: Compare to previous period derives secondary range"""
        result = merge_time_range(
            None, "show me December 2025 costs compared to previous month"
        )

        assert result.is_comparison_request is True
        assert result.comparison is not None

        # Primary should be December 2025
        assert result.primary.start.date() == date(2025, 12, 1)
        assert result.primary.end.date() == date(2025, 12, 31)

        # Comparison should be November 2025
        assert result.comparison.start.month == 11
        assert result.comparison.source == "comparison"

    @freeze_time("2026-01-21")
    def test_mom_comparison_pattern(self):
        """Test month-over-month comparison detection"""
        result = merge_time_range(None, "show month-over-month trends")

        assert result.is_comparison_request is True

    @freeze_time("2026-01-21")
    def test_yoy_comparison_pattern(self):
        """Test year-over-year comparison detection"""
        result = merge_time_range(None, "show YoY growth for 2025")

        assert result.is_comparison_request is True


class TestTimeRangeParser:
    """Test the TimeRangeParser class directly"""

    @freeze_time("2026-01-21")
    def test_is_comparison_request(self, parser):
        """Test comparison request detection"""
        assert parser.is_comparison_request("compare to previous month") is True
        assert parser.is_comparison_request("show MoM changes") is True
        assert parser.is_comparison_request("year over year") is True
        assert parser.is_comparison_request("show me costs") is False

    @freeze_time("2026-01-21")
    def test_derive_comparison_period_month(self, parser):
        """Test deriving comparison period for calendar month"""
        primary = parser.parse("December 2025")
        comparison = parser.derive_comparison_period(primary)

        # Should be November 2025
        assert comparison.start.date() == date(2025, 11, 1)
        assert comparison.end.date() == date(2025, 11, 30)

    @freeze_time("2026-01-21")
    def test_derive_comparison_period_quarter(self, parser):
        """Test deriving comparison period for quarter"""
        primary = parser.parse("Q4 2025")
        comparison = parser.derive_comparison_period(primary)

        # Should be Q3 2025
        assert comparison.start.date() == date(2025, 7, 1)
        assert comparison.end.date() == date(2025, 9, 30)

    @freeze_time("2026-01-21")
    def test_granularity_determination(self, parser):
        """Test automatic granularity selection"""
        # 1 day -> HOURLY
        one_day = parser.parse("today")
        assert one_day.granularity == Granularity.HOURLY

        # 7 days -> DAILY
        week = parser.parse("last 7 days")
        assert week.granularity == Granularity.DAILY

        # 1 year -> MONTHLY
        year = parser.parse("last year")
        assert year.granularity == Granularity.MONTHLY


class TestTimeRangeResult:
    """Test TimeRangeResult class"""

    @freeze_time("2026-01-21")
    def test_to_scope_dict(self):
        """Test scope dictionary generation"""
        parser = TimeRangeParser("UTC")
        primary = parser.parse("December 2025")

        result = TimeRangeResult(primary=primary)
        scope = result.to_scope_dict()

        assert "time_range" in scope
        assert "start_date" in scope
        assert "end_date" in scope
        assert scope["start_date"] == "2025-12-01"
        assert scope["end_date"] == "2025-12-31"

    @freeze_time("2026-01-21")
    def test_to_scope_dict_with_comparison(self):
        """Test scope dictionary with comparison period"""
        parser = TimeRangeParser("UTC")
        primary = parser.parse("December 2025")
        comparison = parser.derive_comparison_period(primary)

        result = TimeRangeResult(
            primary=primary, comparison=comparison, is_comparison_request=True
        )
        scope = result.to_scope_dict()

        assert "comparison_range" in scope
        assert "comparison_start_date" in scope
        assert scope["comparison_start_date"] == "2025-11-01"


class TestTimeRangeToDict:
    """Test TimeRange serialization"""

    @freeze_time("2026-01-21")
    def test_to_dict(self):
        """Test TimeRange to_dict method"""
        parser = TimeRangeParser("UTC")
        time_range = parser.parse("November 2025")

        result = time_range.to_dict()

        assert result["start_date"] == "2025-11-01"
        assert result["end_date"] == "2025-11-30"
        assert result["granularity"] == "DAILY"
        assert "description" in result
        assert "source" in result

    @freeze_time("2026-01-21")
    def test_to_scope_string(self):
        """Test TimeRange scope string generation"""
        parser = TimeRangeParser("UTC")
        time_range = parser.parse("November 2025")

        scope_str = time_range.to_scope_string()

        assert "November" in scope_str
        assert "2025" in scope_str
