from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from backend.aasmaa.time_range import Granularity, TimeRange, TimeRangeResult
from backend.agents.multi_agent_workflow import (
    _is_explicit_cost_analysis_query,
    execute_multi_agent_query,
)


def _make_time_range_result(is_comparison: bool = False) -> TimeRangeResult:
    end = datetime(2026, 3, 31)
    start = end - timedelta(days=29)
    primary = TimeRange(
        start=start,
        end=end,
        granularity=Granularity.DAILY,
        description="Last 30 days",
        source="default",
        period_type="rolling",
    )
    return TimeRangeResult(primary=primary, comparison=None, is_comparison_request=is_comparison)


def test_explicit_cost_breakdown_by_region_detected_as_cost_analysis():
    tr = _make_time_range_result()

    assert _is_explicit_cost_analysis_query(
        "Break down AmazonCloudWatch costs by region",
        tr,
        previous_context=None,
    ) is True


def test_followup_drilldown_inherits_cost_analysis_context():
    tr = _make_time_range_result()

    assert _is_explicit_cost_analysis_query(
        "Break down by region",
        tr,
        previous_context={"last_intent": "COST_BREAKDOWN"},
    ) is True


def test_explicit_optimization_query_not_forced_to_cost_analysis():
    tr = _make_time_range_result()

    assert _is_explicit_cost_analysis_query(
        "How can I optimize AmazonCloudWatch costs?",
        tr,
        previous_context={"last_intent": "COST_BREAKDOWN"},
    ) is False


@pytest.mark.asyncio
async def test_execute_multi_agent_query_routes_drilldown_to_text_to_sql():
    tr = _make_time_range_result()

    mock_optimizer = AsyncMock()
    mock_optimizer.is_optimization_query_async.return_value = True
    mock_optimizer.process_query.return_value = {"message": "optimization"}

    text_to_sql_response = {
        "message": "CloudWatch by region",
        "summary": "",
        "insights": [],
        "recommendations": [],
        "results": [{"region": "us-east-1", "cost_usd": 12.34}],
        "charts": [{"type": "column", "title": "CloudWatch by region"}],
        "suggestions": [],
        "athena_query": "SELECT ...",
        "context": {},
        "metadata": {"query_type": "regional"},
    }

    with patch("backend.agents.multi_agent_workflow.merge_time_range", return_value=tr), \
         patch("backend.agents.multi_agent_workflow.get_optimization_agent", return_value=mock_optimizer), \
         patch("backend.agents.execute_query_v2.execute_query_simple", new=AsyncMock(return_value=text_to_sql_response)) as mock_execute:
        result = await execute_multi_agent_query(
            query="Break down AmazonCloudWatch costs by region",
            conversation_id="conv-1",
            previous_context={"last_intent": "COST_BREAKDOWN"},
        )

    mock_execute.assert_awaited_once()
    mock_optimizer.process_query.assert_not_awaited()
    assert result["message"] == "CloudWatch by region"
    assert result["charts"]
