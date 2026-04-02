"""
Tests for backend/services/cur_csv_analyzer.py — Advisory Mode (CUR CSV upload).

Covers:
- Column-name normalisation across the 3 AWS CUR header conventions
- load_dataframe() bytes / gzip / DataFrame paths + required-column validation
- Each of the seven detectors firing on synthetic CUR rows
- Summary aggregation (rows_analyzed, period_days, estimated_monthly_savings_usd)
- Opportunity dicts are tagged source=cur_analysis so they flow into the
  org-scoped Opportunities store
"""

from __future__ import annotations

import gzip
import io
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pandas as pd
import pytest

from backend.models.opportunities import OpportunityCategory, OpportunitySource
from backend.services.cur_csv_analyzer import CURCSVAnalyzer, _canonicalise


# ---------------------------------------------------------------------------
# Synthetic CUR fixture
# ---------------------------------------------------------------------------


def _hours(start: datetime, n: int):
    return [start + timedelta(hours=i) for i in range(n)]


@pytest.fixture
def synthetic_cur_df() -> pd.DataFrame:
    """
    A 30-day hourly CUR slice with at least one row per detector signal.
    Headers use the Billing-console ``lineItem/UsageStartDate`` convention so
    column normalisation is exercised end-to-end.
    """
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows: list[dict] = []

    # 1) usage_type_cost_drivers — large BoxUsage spend so it's the top family
    rows.append(
        {
            "lineItem/UsageStartDate": start,
            "lineItem/LineItemType": "Usage",
            "lineItem/UsageType": "USE1-BoxUsage:m5.large",
            "lineItem/ProductCode": "AmazonEC2",
            "lineItem/UnblendedCost": 1200.0,
            "lineItem/UsageAmount": 720.0,
            "lineItem/ResourceId": "i-cost-driver",
            "lineItem/UsageAccountId": "123456789012",
            "product/region": "us-east-1",
            "pricing/term": "OnDemand",
        }
    )

    # 2) ri_unused_hours — RIFee row with unused fees > $1
    rows.append(
        {
            "lineItem/UsageStartDate": start,
            "lineItem/LineItemType": "RIFee",
            "lineItem/ProductCode": "AmazonEC2",
            "lineItem/UnblendedCost": 0.0,
            "reservation/ReservationARN": "arn:aws:ec2:us-east-1:123:ri/abc",
            "reservation/UnusedAmortizedUpfrontFeeForBillingPeriod": 30.0,
            "reservation/UnusedRecurringFee": 20.0,
            "reservation/UnusedQuantity": 100.0,
            "product/region": "us-east-1",
            "lineItem/UsageAccountId": "123456789012",
        }
    )

    # 3) sp_unused_commitment — SavingsPlanRecurringFee with unused > $1
    rows.append(
        {
            "lineItem/UsageStartDate": start,
            "lineItem/LineItemType": "SavingsPlanRecurringFee",
            "lineItem/UnblendedCost": 0.0,
            "savingsPlan/SavingsPlanARN": "arn:aws:savingsplans::123:sp/xyz",
            "savingsPlan/TotalCommitmentToDate": 200.0,
            "savingsPlan/UsedCommitment": 50.0,
            "product/region": "us-east-1",
            "lineItem/UsageAccountId": "123456789012",
        }
    )

    # 4) cross_region_data_transfer — InterRegion usage > $10
    rows.append(
        {
            "lineItem/UsageStartDate": start,
            "lineItem/LineItemType": "Usage",
            "lineItem/UsageType": "USE1-USW2-AWS-InterRegion-Bytes",
            "lineItem/ProductCode": "AWSDataTransfer",
            "lineItem/UnblendedCost": 75.0,
            "lineItem/UsageAmount": 500.0,
            "lineItem/ResourceId": "",
            "product/region": "us-east-1",
            "lineItem/UsageAccountId": "123456789012",
        }
    )

    # 5) idle_resources — non-zero cost, zero usage
    rows.append(
        {
            "lineItem/UsageStartDate": start,
            "lineItem/LineItemType": "Usage",
            "lineItem/UsageType": "USE1-EBS:VolumeUsage.gp2",
            "lineItem/ProductCode": "AmazonEC2",
            "lineItem/UnblendedCost": 25.0,
            "lineItem/UsageAmount": 0.0,
            "lineItem/ResourceId": "vol-idle-0001",
            "product/region": "us-east-1",
            "lineItem/UsageAccountId": "123456789012",
        }
    )

    # 6) on_demand_steady_state_db — RDS InstanceUsage 24h/day for 30 days, OnDemand
    for ts in _hours(start, 30 * 24):
        rows.append(
            {
                "lineItem/UsageStartDate": ts,
                "lineItem/LineItemType": "Usage",
                "lineItem/UsageType": "USE1-InstanceUsage:db.r5.large",
                "lineItem/ProductCode": "AmazonRDS",
                "lineItem/UnblendedCost": 0.25,
                "lineItem/UsageAmount": 1.0,
                "lineItem/ResourceId": "arn:aws:rds:us-east-1:123:db:steady",
                "product/region": "us-east-1",
                "product/instanceType": "db.r5.large",
                "pricing/term": "OnDemand",
                "lineItem/UsageAccountId": "123456789012",
            }
        )

    # 7) scheduling_candidates — EC2 BoxUsage 24×7 (≥40% off-hours share)
    for ts in _hours(start, 7 * 24):
        rows.append(
            {
                "lineItem/UsageStartDate": ts,
                "lineItem/LineItemType": "Usage",
                "lineItem/UsageType": "USE1-BoxUsage:t3.medium",
                "lineItem/ProductCode": "AmazonEC2",
                "lineItem/UnblendedCost": 0.05,
                "lineItem/UsageAmount": 1.0,
                "lineItem/ResourceId": "i-flat-247",
                "product/region": "us-east-1",
                "pricing/term": "OnDemand",
                "lineItem/UsageAccountId": "123456789012",
            }
        )

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Column normalisation
# ---------------------------------------------------------------------------


class TestColumnNormalisation:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("lineItem/UsageStartDate", "line_item_usage_start_date"),
            ("lineItem/UnblendedCost", "line_item_unblended_cost"),
            ("product/region", "product_region"),
            ("savingsPlan/SavingsPlanARN", "savings_plan_savings_plan_a_r_n"),
            ("reservation/ReservationARN", "reservation_reservation_a_r_n"),
            # Already-canonical Glue snake_case passes through unchanged
            ("line_item_unblended_cost", "line_item_unblended_cost"),
        ],
    )
    def test_canonicalise(self, raw, expected):
        assert _canonicalise(raw) == expected

    def test_normalise_rejects_non_cur_csv(self):
        with pytest.raises(ValueError, match="AWS CUR export"):
            CURCSVAnalyzer.load_dataframe(pd.DataFrame({"foo": [1], "bar": [2]}))

    def test_normalise_coerces_numeric_strings(self):
        df = CURCSVAnalyzer.load_dataframe(
            pd.DataFrame(
                {
                    "lineItem/LineItemType": ["Usage"],
                    "lineItem/UnblendedCost": ["12.50"],
                }
            )
        )
        assert df["line_item_unblended_cost"].iloc[0] == pytest.approx(12.50)


# ---------------------------------------------------------------------------
# load_dataframe()
# ---------------------------------------------------------------------------


class TestLoadDataframe:
    def _csv_bytes(self) -> bytes:
        buf = io.StringIO()
        pd.DataFrame(
            {
                "lineItem/LineItemType": ["Usage"],
                "lineItem/UnblendedCost": [1.0],
                "lineItem/UsageStartDate": ["2025-01-01T00:00:00Z"],
            }
        ).to_csv(buf, index=False)
        return buf.getvalue().encode("utf-8")

    def test_from_bytes(self):
        df = CURCSVAnalyzer.load_dataframe(self._csv_bytes(), filename="cur.csv")
        assert "line_item_unblended_cost" in df.columns
        assert len(df) == 1

    def test_from_gzipped_bytes(self):
        gz = gzip.compress(self._csv_bytes())
        df = CURCSVAnalyzer.load_dataframe(gz, filename="cur.csv.gz")
        assert "line_item_unblended_cost" in df.columns

    def test_from_gzipped_bytes_magic_no_extension(self):
        """gzip is detected from the magic header even when filename omits .gz."""
        gz = gzip.compress(self._csv_bytes())
        df = CURCSVAnalyzer.load_dataframe(gz, filename="cur.csv")
        assert len(df) == 1

    def test_max_rows_truncates(self):
        many = pd.DataFrame(
            {
                "lineItem/LineItemType": ["Usage"] * 10,
                "lineItem/UnblendedCost": [1.0] * 10,
            }
        )
        buf = io.StringIO()
        many.to_csv(buf, index=False)
        df = CURCSVAnalyzer.load_dataframe(buf.getvalue().encode(), max_rows=3)
        assert len(df) == 3


# ---------------------------------------------------------------------------
# analyze() — full detector run
# ---------------------------------------------------------------------------


class TestAnalyze:
    def test_all_seven_detectors_fire(self, synthetic_cur_df):
        analyzer = CURCSVAnalyzer(organization_id=uuid4())
        df = CURCSVAnalyzer.load_dataframe(synthetic_cur_df)
        result = analyzer.analyze(df)

        summary = result["summary"]
        assert summary["rows_analyzed"] == len(df)
        assert summary["period_days"] >= 29  # 30-day window in fixture
        assert summary["total_opportunities"] == len(result["opportunities"])
        assert summary["estimated_monthly_savings_usd"] >= 0

        # Every detector should have produced ≥ 1 finding
        by_det = summary["by_detector"]
        for label in (
            "usage_type_cost_drivers",
            "ri_unused_hours",
            "sp_unused_commitment",
            "cross_region_data_transfer",
            "idle_resources",
            "on_demand_steady_state_db",
            "scheduling_candidates",
        ):
            assert by_det.get(label, 0) >= 1, f"detector {label} produced no findings"

        # Categories present
        cats = {o["category"] for o in result["opportunities"]}
        assert OpportunityCategory.RESERVED_INSTANCES.value in cats
        assert OpportunityCategory.SAVINGS_PLANS.value in cats
        assert OpportunityCategory.DATA_TRANSFER.value in cats
        assert OpportunityCategory.IDLE_RESOURCES.value in cats
        assert OpportunityCategory.SCHEDULING.value in cats
        assert OpportunityCategory.ARCHITECTURE.value in cats

    def test_account_id_inferred_from_data(self, synthetic_cur_df):
        analyzer = CURCSVAnalyzer()
        df = CURCSVAnalyzer.load_dataframe(synthetic_cur_df)
        analyzer.analyze(df)
        assert analyzer.account_id == "123456789012"

    def test_opportunities_tagged_cur_analysis(self, synthetic_cur_df):
        analyzer = CURCSVAnalyzer(organization_id=uuid4())
        df = CURCSVAnalyzer.load_dataframe(synthetic_cur_df)
        result = analyzer.analyze(df)
        assert result["opportunities"], "expected at least one opportunity"
        for opp in result["opportunities"]:
            assert opp["source"] == OpportunitySource.CUR_ANALYSIS.value
            assert opp["api_trace"]["api"] == "advisory:cur-csv-upload"
            assert opp["status"] == "open"
            assert opp["estimated_annual_savings"] == pytest.approx(
                opp["estimated_monthly_savings"] * 12.0
            )

    def test_idle_detector_finds_zero_usage_resource(self, synthetic_cur_df):
        analyzer = CURCSVAnalyzer()
        df = CURCSVAnalyzer.load_dataframe(synthetic_cur_df)
        result = analyzer.analyze(df)
        idle = [
            o
            for o in result["opportunities"]
            if o["category"] == OpportunityCategory.IDLE_RESOURCES.value
        ]
        assert any(o["resource_id"] == "vol-idle-0001" for o in idle)

    def test_steady_state_db_recommends_ri_with_savings(self, synthetic_cur_df):
        analyzer = CURCSVAnalyzer()
        df = CURCSVAnalyzer.load_dataframe(synthetic_cur_df)
        result = analyzer.analyze(df)
        ri_candidates = [
            o
            for o in result["opportunities"]
            if o["resource_id"] == "arn:aws:rds:us-east-1:123:db:steady"
        ]
        assert ri_candidates, "expected RDS steady-state RI candidate"
        opp = ri_candidates[0]
        assert opp["category"] == OpportunityCategory.RESERVED_INSTANCES.value
        # 720h × $0.25 = $180/mo on-demand → ~40% savings ≈ $72/mo
        assert 50 < opp["estimated_monthly_savings"] < 100

    def test_missing_optional_columns_skip_detector_gracefully(self):
        """A minimal CUR with only required columns must not crash."""
        analyzer = CURCSVAnalyzer()
        df = CURCSVAnalyzer.load_dataframe(
            pd.DataFrame(
                {
                    "lineItem/LineItemType": ["Usage"],
                    "lineItem/UnblendedCost": [10.0],
                }
            )
        )
        result = analyzer.analyze(df)
        # No detector should crash; most will return [] for missing columns
        assert result["summary"]["rows_analyzed"] == 1
        assert isinstance(result["opportunities"], list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_monthly_extrapolation():
    assert CURCSVAnalyzer._monthly(100.0, 30) == 100.0
    assert CURCSVAnalyzer._monthly(100.0, 15) == 200.0
    assert CURCSVAnalyzer._monthly(100.0, 0) == 3000.0  # days clamped to 1
