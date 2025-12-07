import pytest

from backend.services.conversation_manager import ConversationManager


def test_get_context_for_query_merges_dimensions(monkeypatch):
    cm = ConversationManager()

    intents = [
        {
            "id": "i1",
            "extracted_dimensions": {
                "time_range": {
                    "description": "Last 30 days",
                    "start_date": "2025-10-13",
                    "end_date": "2025-11-12",
                },
                "services": ["AmazonCloudWatch", "AmazonEC2"],
                "regions": ["us-east-1"],
                "dimensions": ["Service"],
            },
        },
        {
            "id": "i2",
            "extracted_dimensions": {
                "services": ["AmazonS3"],
                "accounts": ["111111111111"],
                "dimensions": ["Service", "Region"],
            },
        },
    ]

    messages = [
        {
            "id": "m1",
            "metadata": {
                "extracted_dimensions": {
                    "regions": ["us-west-2"],
                }
            },
        }
    ]

    monkeypatch.setattr(cm, "_fetch_recent_intents", lambda thread_id, limit: intents)
    monkeypatch.setattr(cm, "_fetch_recent_messages", lambda thread_id, limit: messages)

    ctx = cm.get_context_for_query("thread-123")

    assert ctx["date_range"]["description"] == "Last 30 days"
    # Services merged and unique, preserve order of first appearance
    assert ctx["services"] == ["AmazonCloudWatch", "AmazonEC2", "AmazonS3"]
    # Regions merged from intents first, then messages fallback
    assert ctx["regions"] == ["us-east-1", "us-west-2"]
    assert ctx["accounts"] == ["111111111111"]
    # Drill level based on max dimensions length
    assert ctx["drill_level"] == 2
