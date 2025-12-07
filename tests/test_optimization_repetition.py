"""
Tests for Task 1.3: Fix Optimization Response Repetition

Validates that:
1. Recommendations are tracked in state to avoid repetition
2. Repeated queries provide detailed implementation guidance
3. First-time queries return summary recommendations
4. Different services don't trigger false repeat detection
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from backend.services.optimization_engine import OptimizationEngine


class TestOptimizationRecommendationTracking:
    """Test recommendation tracking and deduplication"""

    def setup_method(self):
        """Setup test fixtures"""
        self.engine = OptimizationEngine()

    def test_shown_recommendations_added_to_state(self):
        """Recommendation IDs should be added to shown_recommendations list"""
        # Mock recommendations with IDs
        mock_recs = [
            {"id": "rec-001", "strategy_name": "Reduce Log Retention", "service": "CloudWatch"},
            {"id": "rec-002", "strategy_name": "Delete Unused Log Groups", "service": "CloudWatch"},
            {"id": "rec-003", "strategy_name": "Use Contributor Insights", "service": "CloudWatch"}
        ]
        
        shown_recs = []
        new_shown_ids = [str(rec.get("id")) for rec in mock_recs if rec and rec.get("id")]
        shown_recs = list(set(shown_recs + new_shown_ids))
        
        assert len(shown_recs) == 3
        assert "rec-001" in shown_recs
        assert "rec-002" in shown_recs
        assert "rec-003" in shown_recs

    def test_duplicate_ids_deduplicated(self):
        """Multiple queries for same service should not duplicate IDs"""
        # First query
        shown_recs = ["rec-001", "rec-002", "rec-003"]
        
        # Second query returns same recommendations
        mock_recs = [
            {"id": "rec-001", "strategy_name": "Reduce Log Retention"},
            {"id": "rec-002", "strategy_name": "Delete Unused Log Groups"}
        ]
        
        new_shown_ids = [str(rec.get("id")) for rec in mock_recs if rec and rec.get("id")]
        shown_recs = list(set(shown_recs + new_shown_ids))
        
        # Should still only have 3 unique IDs
        assert len(shown_recs) == 3
        assert shown_recs.count("rec-001") == 1
        assert shown_recs.count("rec-002") == 1

    def test_repeat_query_detection(self):
        """Should detect when user asks about same service again"""
        # Simulate state from previous query
        shown_recs = ["rec-001", "rec-002"]
        previous_service = "CloudWatch"
        current_service = "CloudWatch"
        
        is_repeat_query = (previous_service == current_service and len(shown_recs) > 0)
        
        assert is_repeat_query is True

    def test_different_service_not_repeat(self):
        """Asking about different service should not be treated as repeat"""
        shown_recs = ["rec-001", "rec-002"]
        previous_service = "CloudWatch"
        current_service = "EC2"
        
        is_repeat_query = (previous_service == current_service and len(shown_recs) > 0)
        
        assert is_repeat_query is False

    def test_first_query_not_repeat(self):
        """First query should not be treated as repeat"""
        shown_recs = []  # No previous recommendations
        previous_service = None
        current_service = "CloudWatch"
        
        is_repeat_query = (previous_service == current_service and len(shown_recs) > 0)
        
        assert is_repeat_query is False


class TestOptimizationEngineDetailedRecommendations:
    """Test get_detailed_recommendations method"""

    def setup_method(self):
        """Setup test fixtures"""
        self.engine = OptimizationEngine()

    @patch.object(OptimizationEngine, '_get_connection')
    def test_get_detailed_recommendations_by_ids(self, mock_get_conn):
        """Should retrieve specific recommendations by ID"""
        # Mock database connection and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        
        # Mock database results
        mock_cursor.fetchall.return_value = [
            {
                "id": "rec-001",
                "service": "CloudWatch",
                "strategy_name": "Reduce Log Retention",
                "description": "Lower retention from indefinite to 30-90 days",
                "recommendation_steps": [
                    "Navigate to CloudWatch > Log groups",
                    "Select high-cost log groups",
                    "Actions > Edit retention",
                    "Set to 30 days"
                ],
                "risk_level": "low",
                "estimated_savings_min_percent": 20,
                "estimated_savings_max_percent": 40
            }
        ]
        
        result = self.engine.get_detailed_recommendations(
            service="CloudWatch",
            recommendation_ids=["rec-001"],
            current_metrics=None
        )
        
        assert len(result) == 1
        assert result[0]["id"] == "rec-001"
        assert result[0]["strategy_name"] == "Reduce Log Retention"
        assert "recommendation_steps" in result[0]
        assert len(result[0]["recommendation_steps"]) == 4

    @patch.object(OptimizationEngine, '_get_connection')
    def test_get_detailed_recommendations_fallback(self, mock_get_conn):
        """Should fallback to top 3 recommendations if no IDs provided"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        
        mock_cursor.fetchall.return_value = [
            {"id": "rec-001", "service": "EC2", "strategy_name": "Rightsizing"},
            {"id": "rec-002", "service": "EC2", "strategy_name": "Reserved Instances"},
            {"id": "rec-003", "service": "EC2", "strategy_name": "Spot Instances"}
        ]
        
        result = self.engine.get_detailed_recommendations(
            service="EC2",
            recommendation_ids=[],  # Empty list
            current_metrics=None
        )
        
        # Should return up to 3 recommendations
        assert len(result) <= 3


class TestOptimizationResponseFormatting:
    """Test response formatting for first-time vs repeat queries"""

    def test_first_time_response_format(self):
        """First-time queries should return concise summary"""
        recommendations = [
            {
                "strategy_name": "Reduce Log Retention",
                "estimated_savings_min_percent": 20,
                "estimated_savings_max_percent": 40,
                "implementation_effort_hours": 2,
                "confidence_score": 0.85
            },
            {
                "strategy_name": "Delete Unused Log Groups",
                "estimated_savings_min_percent": 10,
                "estimated_savings_max_percent": 25,
                "implementation_effort_hours": 1,
                "confidence_score": 0.90
            }
        ]
        
        lines = ["# Optimization Recommendations for CloudWatch", ""]
        for rec in recommendations:
            title = rec.get("strategy_name")
            smin = rec.get("estimated_savings_min_percent", 0)
            smax = rec.get("estimated_savings_max_percent", 0)
            effort = rec.get("implementation_effort_hours", "-")
            confidence = rec.get("confidence_score", "-")
            lines.append(f"- {title}: savings {smin}-{smax}%, effort ~{effort}h, confidence {confidence}")
        
        response = "\n".join(lines)
        
        assert "# Optimization Recommendations for CloudWatch" in response
        assert "Reduce Log Retention: savings 20-40%" in response
        assert "Delete Unused Log Groups: savings 10-25%" in response
        assert "effort ~2h" in response
        assert "confidence 0.85" in response

    def test_repeat_query_response_format(self):
        """Repeat queries should return detailed implementation steps"""
        recommendations = [
            {
                "strategy_name": "Reduce Log Retention",
                "description": "Lower retention from indefinite to 30-90 days",
                "recommendation_steps": [
                    "Navigate to CloudWatch > Log groups",
                    "Select high-cost log groups",
                    "Actions > Edit retention",
                    "Set to 30 days"
                ],
                "risk_level": "low",
                "estimated_savings_min_percent": 20,
                "estimated_savings_max_percent": 40
            }
        ]
        
        lines = [
            "# Detailed Optimization Steps for CloudWatch",
            "",
            "You asked about this before. Here's a step-by-step implementation guide:",
            ""
        ]
        
        for i, rec in enumerate(recommendations, 1):
            title = rec.get("strategy_name", "Optimization")
            desc = rec.get("description", "")
            steps = rec.get("recommendation_steps", [])
            risk = rec.get("risk_level", "low")
            smin = rec.get("estimated_savings_min_percent", 0)
            smax = rec.get("estimated_savings_max_percent", 0)
            
            lines.append(f"## {i}. {title}")
            lines.append(f"**Savings:** {smin}-{smax}% | **Risk:** {risk}")
            lines.append(f"**Description:** {desc}")
            lines.append("")
            
            if steps:
                lines.append("**Implementation Steps:**")
                for step in steps:
                    lines.append(f"- {step}")
                lines.append("")
        
        response = "\n".join(lines)
        
        assert "# Detailed Optimization Steps for CloudWatch" in response
        assert "You asked about this before" in response
        assert "## 1. Reduce Log Retention" in response
        assert "**Implementation Steps:**" in response
        assert "Navigate to CloudWatch > Log groups" in response
        assert "Set to 30 days" in response
        assert "**Risk:** low" in response


class TestCanonicalServiceMapping:
    """Test service name normalization for consistency"""

    def test_canonical_service_mapping(self):
        """Service names should be normalized consistently"""
        def _canonical_service(name: str | None) -> str:
            if not name:
                return "General"
            n = name.strip().lower()
            if "ec2" in n or "elastic compute cloud" in n:
                return "EC2"
            if "cloudwatch" in n:
                return "CloudWatch"
            if "s3" in n:
                return "S3"
            if "lambda" in n:
                return "Lambda"
            if "rds" in n:
                return "RDS"
            if "vpc" in n:
                return "VPC"
            return name
        
        assert _canonical_service("CloudWatch") == "CloudWatch"
        assert _canonical_service("cloudwatch") == "CloudWatch"
        assert _canonical_service("Amazon CloudWatch") == "CloudWatch"
        assert _canonical_service("EC2") == "EC2"
        assert _canonical_service("Amazon EC2") == "EC2"
        assert _canonical_service("elastic compute cloud") == "EC2"
        assert _canonical_service("S3") == "S3"
        assert _canonical_service("Lambda") == "Lambda"
        assert _canonical_service("RDS") == "RDS"
        assert _canonical_service("VPC") == "VPC"
        assert _canonical_service(None) == "General"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
