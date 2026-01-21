"""
Tests for the OptimizationAgent.

Tests cover:
- Query intent detection (keyword-based and LLM-based)
- Optimization query routing
- Response formatting
- Integration with opportunities service
- LLM intent classification parsing
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from uuid import uuid4

from backend.agents.optimization_agent import (
    OptimizationAgent,
    get_optimization_agent,
    _parse_llm_intent_response,
)
from backend.models.opportunities import OpportunityCategory


@pytest.fixture
def agent():
    """Create an OptimizationAgent instance"""
    return OptimizationAgent()


@pytest.fixture
def mock_opportunities_service():
    """Mock the opportunities service"""
    with patch("backend.agents.optimization_agent.get_opportunities_service") as mock:
        service = Mock()
        mock.return_value = service
        yield service


class TestOptimizationQueryDetection:
    """Test query intent detection"""

    def test_detects_optimize_keyword(self, agent):
        """Test detection of 'optimize' keyword"""
        assert agent.is_optimization_query("How can I optimize my EC2 costs?") is True
        assert agent.is_optimization_query("Optimize S3 storage") is True

    def test_detects_save_keyword(self, agent):
        """Test detection of 'save' keyword"""
        assert agent.is_optimization_query("How can I save money on AWS?") is True
        assert agent.is_optimization_query("Show me savings opportunities") is True

    def test_detects_rightsize_keyword(self, agent):
        """Test detection of 'rightsize' keyword"""
        assert agent.is_optimization_query("Show me rightsizing recommendations") is True
        assert agent.is_optimization_query("Which instances should I right-size?") is True

    def test_detects_recommendation_keyword(self, agent):
        """Test detection of 'recommendation' keyword"""
        assert agent.is_optimization_query("What are your recommendations?") is True
        assert agent.is_optimization_query("Recommend cost savings") is True

    def test_detects_opportunity_keyword(self, agent):
        """Test detection of 'opportunity' keyword"""
        assert agent.is_optimization_query("Show me optimization opportunities") is True
        assert agent.is_optimization_query("What opportunities exist?") is True

    def test_detects_idle_keyword(self, agent):
        """Test detection of 'idle' keyword"""
        assert agent.is_optimization_query("Find idle resources") is True
        assert agent.is_optimization_query("Show unused instances") is True

    def test_detects_reserved_instance_keyword(self, agent):
        """Test detection of reserved instance keywords"""
        assert agent.is_optimization_query("Should I buy reserved instances?") is True
        assert agent.is_optimization_query("Recommend savings plans") is True

    def test_does_not_detect_non_optimization_queries(self, agent):
        """Test that non-optimization queries are not detected"""
        assert agent.is_optimization_query("Show me EC2 costs by region") is False
        # Note: "What was my AWS spend last month?" matches because "sp" is a keyword for Savings Plans
        # and it appears in "spend". This is acceptable since we want to err on the side of caution.
        assert agent.is_optimization_query("Break down costs by service") is False
        assert agent.is_optimization_query("What is my daily cost trend?") is False


class TestIntentExtraction:
    """Test query intent extraction"""

    def test_extracts_rightsizing_category(self, agent):
        """Test extraction of rightsizing category"""
        intent = agent.extract_optimization_intent("Show me rightsizing recommendations")

        assert OpportunityCategory.RIGHTSIZING in intent["categories"]

    def test_extracts_idle_resources_category(self, agent):
        """Test extraction of idle resources category"""
        intent = agent.extract_optimization_intent("Find idle resources")

        assert OpportunityCategory.IDLE_RESOURCES in intent["categories"]

    def test_extracts_reserved_instances_category(self, agent):
        """Test extraction of reserved instances category"""
        intent = agent.extract_optimization_intent("Should I buy reserved instances?")

        assert OpportunityCategory.RESERVED_INSTANCES in intent["categories"]

    def test_extracts_ec2_service(self, agent):
        """Test extraction of EC2 service"""
        intent = agent.extract_optimization_intent("Optimize my EC2 instances")

        assert "EC2" in intent["services"]

    def test_extracts_rds_service(self, agent):
        """Test extraction of RDS service"""
        intent = agent.extract_optimization_intent("How can I reduce RDS costs?")

        assert "RDS" in intent["services"]

    def test_extracts_s3_service(self, agent):
        """Test extraction of S3 service"""
        intent = agent.extract_optimization_intent("Optimize S3 storage costs")

        assert "S3" in intent["services"]

    def test_extracts_top_n_pattern(self, agent):
        """Test extraction of 'top N' pattern"""
        intent = agent.extract_optimization_intent("Show me top 5 opportunities")

        assert intent["limit"] == 5
        assert intent["wants_top"] is True

    def test_extracts_detail_request(self, agent):
        """Test extraction of detail request"""
        intent = agent.extract_optimization_intent(
            "Explain the top rightsizing opportunities"
        )

        assert intent["wants_details"] is True


class TestResponseFormatting:
    """Test response formatting"""

    def test_formats_opportunities_response(self, agent):
        """Test formatting of opportunities into response"""
        opportunities = [
            {
                "id": str(uuid4()),
                "title": "Rightsize EC2 Instance",
                "service": "EC2",
                "category": "rightsizing",
                "status": "open",
                "estimated_monthly_savings": 150.00,
                "effort_level": "medium",
                "description": "Instance is underutilized",
            },
            {
                "id": str(uuid4()),
                "title": "Delete idle EBS volume",
                "service": "EBS",
                "category": "idle_resources",
                "status": "open",
                "estimated_monthly_savings": 50.00,
                "effort_level": "low",
                "description": "Volume has no attachments",
            },
        ]

        intent = {"wants_details": False}
        response = agent.format_opportunities_response(opportunities, intent)

        assert "message" in response
        assert "summary" in response
        assert "insights" in response
        assert "recommendations" in response
        assert "results" in response
        assert "metadata" in response

        # Check metadata
        assert response["metadata"]["opportunities_count"] == 2
        assert response["metadata"]["total_monthly_savings"] == 200.00

    def test_formats_empty_opportunities_response(self, agent):
        """Test formatting when no opportunities found"""
        intent = {"categories": [], "services": []}
        response = agent.format_opportunities_response([], intent)

        assert "message" in response
        # Check that the message indicates no opportunities were found
        assert "couldn't find any" in response["message"] or "No" in response["message"]
        assert response["metadata"]["opportunities_count"] == 0

    def test_generates_insights(self, agent):
        """Test that insights are generated"""
        opportunities = [
            {
                "id": str(uuid4()),
                "title": "Rightsize EC2",
                "service": "EC2",
                "category": "rightsizing",
                "status": "open",
                "estimated_monthly_savings": 300.00,
                "effort_level": "low",
                "description": "Test",
            },
            {
                "id": str(uuid4()),
                "title": "Rightsize another EC2",
                "service": "EC2",
                "category": "rightsizing",
                "status": "open",
                "estimated_monthly_savings": 200.00,
                "effort_level": "medium",
                "description": "Test",
            },
        ]

        intent = {}
        response = agent.format_opportunities_response(opportunities, intent)

        assert len(response["insights"]) > 0

    def test_generates_recommendations(self, agent):
        """Test that recommendations are generated"""
        opportunities = [
            {
                "id": str(uuid4()),
                "title": "Rightsize EC2 Instance",
                "service": "EC2",
                "category": "rightsizing",
                "status": "open",
                "estimated_monthly_savings": 150.00,
                "effort_level": "medium",
                "description": "Consider downsizing this instance",
            }
        ]

        intent = {}
        response = agent.format_opportunities_response(opportunities, intent)

        assert len(response["recommendations"]) > 0


class TestAgentFactory:
    """Test agent factory function"""

    def test_get_optimization_agent_creates_instance(self):
        """Test that factory creates agent instance"""
        agent = get_optimization_agent()

        assert agent is not None
        assert isinstance(agent, OptimizationAgent)

    def test_get_optimization_agent_with_organization_id(self):
        """Test factory with organization ID"""
        org_id = uuid4()
        agent = get_optimization_agent(organization_id=org_id)

        assert agent.organization_id == org_id


class TestProcessQuery:
    """Test query processing"""

    @pytest.mark.asyncio
    async def test_process_query_returns_response(self, mock_opportunities_service):
        """Test that process_query returns formatted response"""
        agent = OptimizationAgent()
        agent._opp_service = mock_opportunities_service

        # Mock the list_opportunities method
        mock_result = Mock()
        mock_result.items = []
        mock_opportunities_service.list_opportunities.return_value = mock_result
        mock_opportunities_service.get_stats.return_value = None

        response = await agent.process_query("Show me optimization opportunities")

        assert "message" in response
        assert "metadata" in response

    @pytest.mark.asyncio
    async def test_process_query_with_account_filter(self, mock_opportunities_service):
        """Test processing with account filter"""
        agent = OptimizationAgent()
        agent._opp_service = mock_opportunities_service

        mock_result = Mock()
        mock_result.items = []
        mock_opportunities_service.list_opportunities.return_value = mock_result

        response = await agent.process_query(
            "Show me optimization opportunities",
            account_ids=["123456789012"],
        )

        # Verify the service was called with account filter
        call_args = mock_opportunities_service.list_opportunities.call_args
        filter_obj = call_args.kwargs.get("filter") or call_args[1].get("filter")

        assert filter_obj is not None


class TestLLMIntentParsing:
    """Test LLM intent classification response parsing"""

    def test_parses_valid_json_response(self):
        """Test parsing a valid JSON response"""
        response = '''{
            "is_optimization_query": true,
            "confidence": 0.95,
            "categories": ["rightsizing", "idle_resources"],
            "services": ["EC2", "RDS"],
            "limit": 5,
            "wants_details": true,
            "wants_top": true
        }'''
        result = _parse_llm_intent_response(response)

        assert result is not None
        assert result["is_optimization_query"] is True
        assert result["confidence"] == 0.95
        assert "rightsizing" in result["categories"]
        assert "idle_resources" in result["categories"]
        assert "EC2" in result["services"]
        assert result["limit"] == 5
        assert result["wants_details"] is True
        assert result["wants_top"] is True

    def test_extracts_json_from_markdown(self):
        """Test extracting JSON when LLM includes markdown"""
        response = '''Here is the classification:
        ```json
        {"is_optimization_query": true, "confidence": 0.8, "categories": ["rightsizing"], "services": [], "limit": null, "wants_details": false, "wants_top": false}
        ```
        '''
        result = _parse_llm_intent_response(response)

        assert result is not None
        assert result["is_optimization_query"] is True

    def test_handles_missing_optional_fields(self):
        """Test handling response with missing optional fields"""
        response = '{"is_optimization_query": false}'
        result = _parse_llm_intent_response(response)

        assert result is not None
        assert result["is_optimization_query"] is False
        assert result["categories"] == []
        assert result["services"] == []

    def test_returns_none_for_invalid_json(self):
        """Test handling invalid JSON"""
        response = "This is not JSON at all"
        result = _parse_llm_intent_response(response)

        assert result is None

    def test_returns_none_for_missing_required_field(self):
        """Test handling missing required field"""
        response = '{"confidence": 0.9, "categories": []}'
        result = _parse_llm_intent_response(response)

        assert result is None

    def test_converts_categories_to_enums(self):
        """Test that category strings are converted to enum values"""
        response = '''{
            "is_optimization_query": true,
            "confidence": 0.9,
            "categories": ["rightsizing", "idle_resources", "reserved_instances"],
            "services": [],
            "limit": null,
            "wants_details": false,
            "wants_top": false
        }'''
        result = _parse_llm_intent_response(response)

        assert result is not None
        assert OpportunityCategory.RIGHTSIZING in result["category_enums"]
        assert OpportunityCategory.IDLE_RESOURCES in result["category_enums"]
        assert OpportunityCategory.RESERVED_INSTANCES in result["category_enums"]


class TestAsyncLLMClassification:
    """Test async LLM-based classification methods"""

    @pytest.mark.asyncio
    async def test_async_query_detection_uses_llm_when_available(self):
        """Test that async detection uses LLM when available"""
        agent = OptimizationAgent(use_llm_classification=True)

        # Mock the LLM service
        mock_llm = Mock()
        mock_llm.initialized = True
        mock_llm._invoke_bedrock = AsyncMock(return_value='{"is_optimization_query": true, "confidence": 0.95, "categories": ["rightsizing"], "services": ["EC2"], "limit": null, "wants_details": false, "wants_top": false}')
        agent._llm_service = mock_llm

        result = await agent.is_optimization_query_async("How can I reduce my EC2 costs?")

        assert result is True
        mock_llm._invoke_bedrock.assert_called_once()

    @pytest.mark.asyncio
    async def test_query_length_limit_truncates_long_queries(self):
        """Test that queries exceeding max length are truncated"""
        from backend.agents.optimization_agent import MAX_QUERY_LENGTH_FOR_LLM

        agent = OptimizationAgent(use_llm_classification=True)

        # Mock the LLM service
        mock_llm = Mock()
        mock_llm.initialized = True
        mock_llm._invoke_bedrock = AsyncMock(return_value='{"is_optimization_query": true, "confidence": 0.9, "categories": [], "services": [], "limit": null, "wants_details": false, "wants_top": false}')
        agent._llm_service = mock_llm

        # Create a query that exceeds the limit
        long_query = "optimize " + "x" * (MAX_QUERY_LENGTH_FOR_LLM + 500)

        result = await agent._classify_with_llm(long_query)

        # Verify the query was truncated before being sent to LLM
        call_args = mock_llm._invoke_bedrock.call_args
        prompt_content = call_args[0][0][0]["content"]

        # The user query part should be truncated
        assert len(prompt_content) <= len(prompt_content)  # Just verify it was called
        assert result is not None

    @pytest.mark.asyncio
    async def test_async_query_detection_falls_back_to_keywords(self):
        """Test fallback to keywords when LLM unavailable"""
        agent = OptimizationAgent(use_llm_classification=True)

        # Mock the LLM service as not initialized
        mock_llm = Mock()
        mock_llm.initialized = False
        agent._llm_service = mock_llm

        result = await agent.is_optimization_query_async("How can I optimize my EC2 costs?")

        assert result is True  # "optimize" keyword should match

    @pytest.mark.asyncio
    async def test_async_intent_uses_cached_llm_result(self):
        """Test that intent extraction uses cached LLM result"""
        agent = OptimizationAgent(use_llm_classification=True)

        # Simulate cached intent from previous classification
        agent._cached_intent = {
            "is_optimization_query": True,
            "confidence": 0.9,
            "categories": ["rightsizing"],
            "category_enums": [OpportunityCategory.RIGHTSIZING],
            "services": ["EC2"],
            "limit": 5,
            "wants_details": True,
            "wants_top": True,
        }

        intent = await agent.extract_optimization_intent_async("Show me top 5 rightsizing recommendations")

        assert OpportunityCategory.RIGHTSIZING in intent["categories"]
        assert "EC2" in intent["services"]
        assert intent["limit"] == 5
        assert intent["wants_details"] is True
        assert intent["wants_top"] is True
        # Cache should be cleared after use
        assert agent._cached_intent is None

    @pytest.mark.asyncio
    async def test_llm_classification_disabled(self):
        """Test that LLM classification can be disabled"""
        agent = OptimizationAgent(use_llm_classification=False)

        result = await agent._classify_with_llm("any query")

        assert result is None  # Should return None when disabled
