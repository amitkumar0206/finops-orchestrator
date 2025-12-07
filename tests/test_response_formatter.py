from backend.services.response_formatter import response_formatter
from backend.agents.intent_classifier import IntentType


def test_response_formatter_optimization_summary():
    data = [
        {
            "family": "m5",
            "on_demand_cost": 8200.0,
            "ri_equivalent_cost": 5330.0,
            "est_savings_usd": 2870.0,
            "est_savings_pct": 35.0,
        },
        {
            "family": "c6g",
            "on_demand_cost": 6100.0,
            "ri_equivalent_cost": 3965.0,
            "est_savings_usd": 2135.0,
            "est_savings_pct": 35.0,
        },
    ]

    params = {
        "start_date": "2024-08-01",
        "end_date": "2024-08-31",
        "time_range": {"description": "August 2024"},
    }

    response = response_formatter.format_response(
        intent=IntentType.OPTIMIZATION,
        query="Estimate savings if we reserved EC2",
        data_results=data,
        extracted_params=params,
        insights=None,
        chart_data=None,  # Updated parameter name from chart_specs to chart_data
        metadata=None,
    )

    assert "**Summary:**" in response  # Fixed: now includes colon
    assert "Identified **$5,005.00** optimization headroom" in response
    assert "**Insights:**" in response  # Fixed: now includes colon
    assert "Savings runway" in response
