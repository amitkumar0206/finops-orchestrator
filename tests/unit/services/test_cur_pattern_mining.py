"""
Tests for backend/services/cur_pattern_mining_signals.py — Connected Mode.

The service depends on Athena (via EnhancedAthenaQueryExecutor) and Cost
Explorer; both are stubbed so the test never opens a real boto3 session.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from backend.models.opportunities import OpportunityCategory, OpportunitySource


# ---------------------------------------------------------------------------
# Fixtures — patch every boto3 entry point so no real AWS call is made
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_executor():
    ex = MagicMock()
    ex._execute_athena_query = AsyncMock(return_value=[])
    return ex


@pytest.fixture
def svc(mock_executor):
    """CURPatternMiningSignalsService with all AWS sessions stubbed."""
    with patch(
        "backend.services.cur_pattern_mining_signals.create_aws_session"
    ) as mock_sess, patch(
        "backend.services.cur_pattern_mining_signals.EnhancedAthenaQueryExecutor",
        return_value=mock_executor,
    ):
        mock_sess.return_value = MagicMock()
        from backend.services.cur_pattern_mining_signals import (
            CURPatternMiningSignalsService,
        )

        s = CURPatternMiningSignalsService(
            account_id="123456789012",
            organization_id=uuid4(),
            executor=mock_executor,
        )
        # Replace lazy CE client with a plain mock so .get_anomalies / .get_cost_and_usage
        # can be configured per-test.
        s._ce_client = MagicMock()
        yield s


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def test_helper_f_coerces_safely():
    from backend.services.cur_pattern_mining_signals import _f

    assert _f("12.5") == 12.5
    assert _f(None) == 0.0
    assert _f("") == 0.0
    assert _f("not-a-number") == 0.0
    assert _f(7) == 7.0


def test_helper_monthly_extrapolation():
    from backend.services.cur_pattern_mining_signals import _monthly

    assert _monthly(100.0, 30) == 100.0
    assert _monthly(50.0, 15) == 100.0
    assert _monthly(10.0, 0) == 300.0  # days clamped to 1


# ---------------------------------------------------------------------------
# Athena-backed detectors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mine_ri_unused_hours_builds_opportunity(svc, mock_executor):
    mock_executor._execute_athena_query.return_value = [
        {
            "reservation_arn": "arn:aws:ec2::ri/abc",
            "service": "AmazonEC2",
            "region": "us-east-1",
            "unused_cost_usd": "60.0",
            "unused_hours": "120",
            "amortized_cost_usd": "200.0",
        }
    ]
    out = await svc._mine_ri_unused_hours("2025-01-01", "2025-01-31")
    assert len(out) == 1
    opp = out[0]
    assert opp["source"] == OpportunitySource.CUR_ANALYSIS.value
    assert opp["category"] == OpportunityCategory.RESERVED_INSTANCES.value
    assert opp["resource_id"] == "arn:aws:ec2::ri/abc"
    assert opp["estimated_monthly_savings"] > 0
    # cur_validation_sql is populated so users can re-run the query themselves
    assert "reservation" in opp["cur_validation_sql"].lower()


@pytest.mark.asyncio
async def test_mine_sp_unused_commitment(svc, mock_executor):
    mock_executor._execute_athena_query.return_value = [
        {
            "savings_plan_arn": "arn:aws:savingsplans::sp/xyz",
            "region": "us-east-1",
            "unused_commitment_usd": "150.0",
            "committed_usd": "200.0",
            "used_usd": "50.0",
        }
    ]
    out = await svc._mine_sp_unused_commitment("2025-01-01", "2025-01-31")
    assert len(out) == 1
    opp = out[0]
    assert opp["category"] == OpportunityCategory.SAVINGS_PLANS.value
    assert opp["evidence"]["utilization_pct"] == pytest.approx(25.0)


@pytest.mark.asyncio
async def test_mine_cross_region_data_transfer(svc, mock_executor):
    mock_executor._execute_athena_query.return_value = [
        {
            "region": "us-east-1",
            "service": "AWSDataTransfer",
            "cost_usd": "300.0",
            "gb_transferred": "1500",
        }
    ]
    out = await svc._mine_cross_region_data_transfer("2025-01-01", "2025-01-31")
    assert len(out) == 1
    opp = out[0]
    assert opp["category"] == OpportunityCategory.DATA_TRANSFER.value
    # Saving estimate is 50% of monthly transfer cost
    assert opp["estimated_monthly_savings"] == pytest.approx(
        opp["current_monthly_cost"] * 0.5
    )


@pytest.mark.asyncio
async def test_mine_idle_resources(svc, mock_executor):
    mock_executor._execute_athena_query.return_value = [
        {
            "resource_id": "vol-deadbeef",
            "service": "AmazonEC2",
            "region": "us-east-1",
            "usage_type": "EBS:VolumeUsage.gp2",
            "cost_usd": "45.0",
        }
    ]
    out = await svc._mine_idle_resources("2025-01-01", "2025-01-31")
    assert len(out) == 1
    assert out[0]["category"] == OpportunityCategory.IDLE_RESOURCES.value
    assert out[0]["resource_id"] == "vol-deadbeef"


@pytest.mark.asyncio
async def test_mine_on_demand_steady_state_db(svc, mock_executor):
    mock_executor._execute_athena_query.return_value = [
        {
            "resource_id": "arn:aws:rds::db:prod",
            "instance_type": "db.r5.large",
            "region": "us-east-1",
            "run_hours": "720",
            "active_days": "30",
            "avg_hours_per_day": "24",
            "cost_usd": "180.0",
        }
    ]
    out = await svc._mine_on_demand_steady_state_db("2025-01-01", "2025-01-31")
    assert len(out) == 1
    opp = out[0]
    assert opp["category"] == OpportunityCategory.RESERVED_INSTANCES.value
    assert opp["resource_type"] == "db.r5.large"
    # ~40% savings on $180/mo
    assert 60 < opp["estimated_monthly_savings"] < 80


@pytest.mark.asyncio
async def test_max_findings_per_detector_caps_output(svc, mock_executor):
    svc.max_findings_per_detector = 2
    mock_executor._execute_athena_query.return_value = [
        {"resource_id": f"vol-{i}", "service": "EC2", "region": "us-east-1", "cost_usd": "20"}
        for i in range(10)
    ]
    out = await svc._mine_idle_resources("2025-01-01", "2025-01-31")
    assert len(out) == 2


# ---------------------------------------------------------------------------
# Cost Explorer detectors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_cost_anomaly_signals(svc):
    svc._ce_client.get_anomalies.return_value = {
        "Anomalies": [
            {
                "AnomalyId": "anom-123",
                "AnomalyStartDate": "2025-01-10",
                "AnomalyEndDate": "2025-01-12",
                "Impact": {"TotalImpact": 250.0},
                "AnomalyScore": {"CurrentScore": 0.9},
                "RootCauses": [
                    {"Service": "Amazon EC2", "Region": "us-east-1", "UsageType": "BoxUsage"}
                ],
            },
            {
                # Zero-impact anomaly should be skipped
                "AnomalyId": "anom-zero",
                "Impact": {"TotalImpact": 0.0},
                "RootCauses": [{}],
            },
        ]
    }
    out = await svc.fetch_cost_anomaly_signals()
    assert len(out) == 1
    opp = out[0]
    assert opp["service"] == "Amazon EC2"
    assert opp["resource_id"] == "anom-123"
    assert opp["api_trace"]["api"] == "ce:GetAnomalies"
    assert opp["estimated_monthly_savings"] == pytest.approx(250.0)


@pytest.mark.asyncio
async def test_fetch_cost_anomaly_signals_handles_client_error(svc):
    from botocore.exceptions import ClientError

    svc._ce_client.get_anomalies.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "nope"}}, "GetAnomalies"
    )
    out = await svc.fetch_cost_anomaly_signals()
    assert out == []  # logged + swallowed, never raised


@pytest.mark.asyncio
async def test_fetch_service_cost_trend_signals(svc):
    """Service whose projected month-end exceeds the trailing average by >threshold%."""
    svc.mom_increase_threshold_pct = 40.0

    today = date.today()
    days_in_current = max((today - today.replace(day=1)).days, 1)
    # Choose mtd so that mtd * 30 / days_in_current ≈ $300 (well above $100 baseline)
    mtd = 300.0 * days_in_current / 30.0

    svc._ce_client.get_cost_and_usage.return_value = {
        "ResultsByTime": [
            {  # month -3
                "Groups": [
                    {"Keys": ["Amazon EC2"], "Metrics": {"UnblendedCost": {"Amount": "100"}}}
                ]
            },
            {  # month -2
                "Groups": [
                    {"Keys": ["Amazon EC2"], "Metrics": {"UnblendedCost": {"Amount": "100"}}}
                ]
            },
            {  # month -1
                "Groups": [
                    {"Keys": ["Amazon EC2"], "Metrics": {"UnblendedCost": {"Amount": "100"}}}
                ]
            },
            {  # current MTD — projects to ~$300
                "Groups": [
                    {
                        "Keys": ["Amazon EC2"],
                        "Metrics": {"UnblendedCost": {"Amount": str(mtd)}},
                    }
                ]
            },
        ]
    }
    out = await svc.fetch_service_cost_trend_signals()
    assert len(out) == 1
    opp = out[0]
    assert opp["service"] == "Amazon EC2"
    assert opp["api_trace"]["api"] == "ce:GetCostAndUsage"
    assert opp["evidence"]["trailing_3mo_avg_usd"] == pytest.approx(100.0)
    assert opp["evidence"]["increase_pct"] >= 40.0


# ---------------------------------------------------------------------------
# fetch_all_cur_signals — aggregation + fault tolerance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_all_cur_signals_aggregates_and_skips_failures(svc, mock_executor):
    """One Athena detector returns rows, the rest empty; one CE detector raises."""

    def athena_side_effect(sql):
        if "savings_plan" in sql.lower():
            return [
                {
                    "savings_plan_arn": "arn:aws:savingsplans::sp/xyz",
                    "region": "us-east-1",
                    "unused_commitment_usd": "150.0",
                    "committed_usd": "200.0",
                    "used_usd": "50.0",
                }
            ]
        return []

    mock_executor._execute_athena_query.side_effect = athena_side_effect
    svc._ce_client.get_anomalies.side_effect = RuntimeError("network down")
    svc._ce_client.get_cost_and_usage.return_value = {"ResultsByTime": []}

    signals = await svc.fetch_all_cur_signals()

    # SP detector produced one signal; nothing else; CE failure swallowed
    assert len(signals) == 1
    assert signals[0]["category"] == OpportunityCategory.SAVINGS_PLANS.value
    assert all(s["source"] == OpportunitySource.CUR_ANALYSIS.value for s in signals)


# ---------------------------------------------------------------------------
# SQL templates — basic safety / shape checks
# ---------------------------------------------------------------------------


def test_pattern_mining_templates_validate_dates():
    from backend.services.athena_cur_templates import CURPatternMiningTemplates

    t = CURPatternMiningTemplates(database="db", table="tbl")
    with pytest.raises(ValueError):
        t.idle_resources_with_cost("2025-13-01", "2025-01-31")


def test_pattern_mining_templates_threshold_cast_to_float():
    """Numeric kwargs are cast to float so a malicious string cannot inject SQL."""
    from backend.services.athena_cur_templates import CURPatternMiningTemplates

    t = CURPatternMiningTemplates(database="db", table="tbl")
    with pytest.raises((ValueError, TypeError)):
        t.idle_resources_with_cost(
            "2025-01-01", "2025-01-31", min_cost="5; DROP TABLE x"  # type: ignore[arg-type]
        )


def test_pattern_mining_templates_emit_expected_columns():
    from backend.services.athena_cur_templates import CURPatternMiningTemplates

    t = CURPatternMiningTemplates(database="db", table="tbl")
    sql = t.ri_unused_hours("2025-01-01", "2025-01-31")
    assert "reservation" in sql.lower()
    assert "db.tbl" in sql

    sql = t.sp_unused_commitment("2025-01-01", "2025-01-31")
    assert "savings_plan" in sql.lower()

    sql = t.on_demand_steady_state_db("2025-01-01", "2025-01-31")
    assert "instanceusage" in sql.lower() or "instance" in sql.lower()
