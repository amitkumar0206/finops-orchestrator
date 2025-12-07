import math

from backend.services.chart_data_builder import ChartDataBuilder


def test_column_chart_others_aggregation_uses_full_dataset():
    builder = ChartDataBuilder()
    spec = {
        "type": "column",
        "x": "dimension_value",
        "y": "cost_usd",
        "title": "Cost breakdown",
        "limit": 6,  # small limit to surface regression when dataset is larger
    }
    data_results = [
        {"dimension_value": f"Item {i}", "cost_usd": 100 - i}
        for i in range(10)
    ]

    chart = builder._build_single_chart(spec, data_results)

    assert chart is not None

    labels = chart["data"]["labels"]
    values = chart["data"]["datasets"][0]["data"]

    assert labels[-1] == "Others (5 items)", "chart should aggregate hidden rows into Others with full count"

    expected_others_total = sum(row["cost_usd"] for row in data_results[5:])
    assert math.isclose(values[-1], expected_others_total, rel_tol=1e-6)
