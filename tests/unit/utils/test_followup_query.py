from backend.utils.followup_query import (
    build_contextual_followup_query,
    is_time_only_followup_query,
)


def test_detects_time_only_followup():
    assert is_time_only_followup_query("how about last 100 days") is True
    assert is_time_only_followup_query("for last 3 months") is True


def test_rewrites_time_only_followup_with_previous_query_context():
    rewritten = build_contextual_followup_query(
        "how about last 100 days",
        {
            "last_query": "Break down AmazonCloudWatch costs by region for last 30 days",
            "last_query_type": "regional",
            "is_optimization": False,
        },
    )

    assert rewritten == "Break down AmazonCloudWatch costs by region for last 100 days"


def test_appends_time_when_previous_query_has_no_time_phrase():
    rewritten = build_contextual_followup_query(
        "last 100 days",
        {
            "last_query": "Break down AmazonCloudWatch costs by region",
            "last_query_type": "regional",
        },
    )

    assert rewritten == "Break down AmazonCloudWatch costs by region for last 100 days"


def test_does_not_rewrite_non_time_followup():
    unchanged = build_contextual_followup_query(
        "show by service",
        {
            "last_query": "Break down AmazonCloudWatch costs by region for last 30 days",
            "last_query_type": "regional",
        },
    )

    assert unchanged == "show by service"


def test_does_not_rewrite_optimization_context():
    unchanged = build_contextual_followup_query(
        "how about last 100 days",
        {
            "last_query": "Show me optimization opportunities",
            "is_optimization": True,
        },
    )

    assert unchanged == "how about last 100 days"


def test_rewrites_when_last_query_is_current_message_using_history():
    rewritten = build_contextual_followup_query(
        "how about last 100 days",
        {
            "last_query": "how about last 100 days",
            "conversation_history": [
                {"role": "user", "content": "Show me my AWS costs for the last 30 days"},
                {"role": "assistant", "content": "..."},
                {"role": "user", "content": "Break down AmazonCloudWatch costs by region"},
                {"role": "assistant", "content": "..."},
                {"role": "user", "content": "how about last 100 days"},
            ],
        },
    )

    assert rewritten == "Break down AmazonCloudWatch costs by region for last 100 days"
