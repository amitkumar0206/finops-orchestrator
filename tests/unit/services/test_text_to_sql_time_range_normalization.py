from backend.services.conversation_context import ConversationContext
from backend.services.text_to_sql_service import text_to_sql_service


def test_followup_explicit_time_range_overrides_how_about_phrase():
    context = ConversationContext("test-conversation")
    context.last_time_range = {
        "description": "Last 30 days",
        "start_date": "2026-03-05",
        "end_date": "2026-04-04",
        "source": "explicit",
    }
    context.last_params = {
        "time_range": context.last_time_range.copy(),
        "services": ["AmazonCloudWatch"],
    }

    refined = context.apply_follow_up_refinement(
        query="how about last 60 days",
        new_params={
            "time_range": {
                "description": "Last 60 days",
                "start_date": "2026-02-03",
                "end_date": "2026-04-04",
                "source": "explicit",
                "metadata": {"days": 60},
            }
        },
    )

    assert refined["time_range"]["description"] == "Last 60 days"
    assert refined["time_range"]["start_date"] == "2026-02-03"
    assert refined["time_range"]["end_date"] == "2026-04-04"
    assert refined["services"] == ["AmazonCloudWatch"]


def test_apply_resolved_time_range_rewrites_simple_date_filters():
    sql = """
SELECT line_item_product_code AS service, SUM(line_item_unblended_cost) AS cost_usd
FROM cost_usage_db.cur_data
WHERE CAST(line_item_usage_start_date AS DATE) >= DATE '2025-11-03'
  AND CAST(line_item_usage_start_date AS DATE) <= DATE '2026-04-04'
GROUP BY line_item_product_code
""".strip()

    normalized = text_to_sql_service._apply_resolved_time_range(
        sql,
        {
            "description": "Last 60 days",
            "start_date": "2026-02-03",
            "end_date": "2026-04-04",
            "metadata": {"days": 60},
        },
    )

    assert "DATE '2026-02-03'" in normalized
    assert "DATE '2025-11-03'" not in normalized


def test_normalize_explanation_time_range_updates_day_count_phrase():
    explanation = "**Summary:** Your total AWS spend is $123.45 across 10 services for the last 30 days."

    normalized = text_to_sql_service._normalize_explanation_time_range(
        explanation,
        {
            "description": "Last 60 days",
            "start_date": "2026-02-03",
            "end_date": "2026-04-04",
            "metadata": {"days": 60},
        },
    )

    assert "last 60 days" in normalized.lower()
    assert "last 30 days" not in normalized.lower()