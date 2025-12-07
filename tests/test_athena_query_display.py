"""
Test Suite for Task 1.5: Athena Query Display in UI

This test suite verifies that SQL queries executed by Athena are properly:
1. Captured in multi_agent_workflow
2. Passed through the chat API
3. Included in the ChatResponse schema
4. Available for frontend display

Tests cover:
- SQL query presence in cost analysis responses
- Proper handling when no SQL query is executed
- Query format and structure validation
- Integration with existing response metadata
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from models.schemas import ChatRequest, ChatResponse
from api.chat import chat
from fastapi import BackgroundTasks
from fastapi.requests import Request


class TestAthenaQueryInResponse:
    """Test that athena_query field is properly included in responses"""

    @pytest.mark.asyncio
    async def test_athena_query_in_chat_response_schema(self):
        """Verify ChatResponse schema includes athena_query field"""
        # Create a ChatResponse with athena_query
        response = ChatResponse(
            message="Here are your costs for the last 30 days.",
            conversation_id="test-123",
            charts=[],
            insights=[],
            action_items=[],
            suggestions=[],
            agent_responses=[],
            reasoning=None,
            context={},
            user_intent="cost_analysis",
            athena_query="SELECT * FROM cost_data WHERE date >= '2024-01-01'",
            execution_time=1.5,
            timestamp=datetime.utcnow()
        )

        # Verify athena_query is accessible
        assert response.athena_query is not None
        assert "SELECT" in response.athena_query
        assert "cost_data" in response.athena_query

    @pytest.mark.asyncio
    async def test_athena_query_optional_field(self):
        """Verify athena_query is optional and can be None"""
        # Create a ChatResponse without athena_query (e.g., for optimization requests)
        response = ChatResponse(
            message="Here are optimization recommendations.",
            conversation_id="test-456",
            charts=[],
            insights=[],
            action_items=[],
            suggestions=[],
            agent_responses=[],
            reasoning=None,
            context={},
            user_intent="optimization",
            athena_query=None,
            execution_time=0.8,
            timestamp=datetime.utcnow()
        )

        # Verify None is accepted
        assert response.athena_query is None

    @pytest.mark.asyncio
    async def test_chat_api_extracts_athena_query(self):
        """Test that chat API extracts athena_query from multi-agent response"""
        # Mock conversation manager
        mock_conv_manager = MagicMock()
        mock_conv_manager.create_thread.return_value = "test-thread-123"
        mock_conv_manager.add_message.return_value = "msg-123"
        mock_conv_manager.get_context_for_query.return_value = {}

        # Mock multi-agent workflow response with SQL query
        mock_multi_agent_response = {
            "final_response": "Your AWS costs for the last 30 days total $1,234.56",
            "charts": [{"type": "line", "data": []}],
            "suggestions": ["Review EC2 usage"],
            "context": {"time_range": "last_30_days"},
            "metadata": {"supervisor_reasoning": "cost_analysis"},
            "athena_query": "SELECT line_item_usage_account_id, SUM(line_item_unblended_cost) AS total_cost FROM cost_data WHERE line_item_usage_start_date >= date_add('day', -30, current_date) GROUP BY line_item_usage_account_id"
        }

        with patch('api.chat.conversation_manager', mock_conv_manager):
            with patch('api.chat.execute_multi_agent_query', new_callable=AsyncMock) as mock_execute:
                mock_execute.return_value = mock_multi_agent_response

                # Create test request
                request = ChatRequest(
                    message="Show my costs for the last 30 days",
                    conversation_id=None,
                    chat_history=[],
                    include_reasoning=False,
                    context={}
                )

                # Mock FastAPI dependencies
                background_tasks = BackgroundTasks()
                http_request = MagicMock(spec=Request)
                http_request.client.host = "127.0.0.1"

                # Call chat endpoint
                response = await chat(request, background_tasks, http_request)

                # Verify athena_query is extracted and included
                assert isinstance(response, ChatResponse)
                assert response.athena_query is not None
                assert "SELECT" in response.athena_query
                assert "cost_data" in response.athena_query
                assert "SUM(line_item_unblended_cost)" in response.athena_query

    @pytest.mark.asyncio
    async def test_chat_api_handles_missing_athena_query(self):
        """Test that chat API handles responses without athena_query gracefully"""
        # Mock conversation manager
        mock_conv_manager = MagicMock()
        mock_conv_manager.create_thread.return_value = "test-thread-456"
        mock_conv_manager.add_message.return_value = "msg-456"
        mock_conv_manager.get_context_for_query.return_value = {}

        # Mock multi-agent workflow response WITHOUT SQL query (optimization request)
        mock_multi_agent_response = {
            "final_response": "I recommend right-sizing your EC2 instances to save 30% on compute costs.",
            "charts": [],
            "suggestions": ["Review instance types", "Enable auto-scaling"],
            "context": {},
            "metadata": {"supervisor_reasoning": "optimization"}
            # Note: No athena_query field
        }

        with patch('api.chat.conversation_manager', mock_conv_manager):
            with patch('api.chat.execute_multi_agent_query', new_callable=AsyncMock) as mock_execute:
                mock_execute.return_value = mock_multi_agent_response

                # Create test request
                request = ChatRequest(
                    message="How can I optimize my EC2 costs?",
                    conversation_id=None,
                    chat_history=[],
                    include_reasoning=False,
                    context={}
                )

                # Mock FastAPI dependencies
                background_tasks = BackgroundTasks()
                http_request = MagicMock(spec=Request)
                http_request.client.host = "127.0.0.1"

                # Call chat endpoint
                response = await chat(request, background_tasks, http_request)

                # Verify athena_query is None when not provided
                assert isinstance(response, ChatResponse)
                assert response.athena_query is None


class TestMultiAgentWorkflowSQLCapture:
    """Test that multi_agent_workflow properly captures SQL queries"""

    @pytest.mark.asyncio
    async def test_cost_analysis_includes_sql_query(self):
        """Test that cost analysis agent returns athena_query in response"""
        from agents.multi_agent_workflow import execute_multi_agent_query

        # Mock all the dependencies
        with patch('agents.multi_agent_workflow.intent_classifier') as mock_classifier, \
             patch('agents.multi_agent_workflow.query_processor') as mock_query_proc, \
             patch('agents.multi_agent_workflow.cost_data_processor') as mock_cost_proc, \
             patch('agents.multi_agent_workflow.response_formatter') as mock_formatter, \
             patch('agents.multi_agent_workflow.recommendation_engine') as mock_rec_engine:

            # Mock intent classifier to route to cost analysis
            mock_intent = MagicMock()
            mock_intent.intent = "cost_analysis"
            mock_intent.confidence = 0.95
            mock_intent.extracted_params = {
                "time_range": "last_30_days",
                "dimension": "service",
                "top_n": 10
            }
            mock_classifier.classify_intent = AsyncMock(return_value=mock_intent)

            # Mock query processor
            mock_query_proc.extract_query_parameters = AsyncMock(return_value={
                "time_range": "last_30_days",
                "dimension": "service",
                "top_n": 10
            })

            # Mock cost data processor with SQL query
            test_sql = "SELECT service, SUM(cost) as total_cost FROM cost_data WHERE date >= '2024-11-01' GROUP BY service ORDER BY total_cost DESC LIMIT 10"
            mock_cost_proc.process_cost_query = AsyncMock(return_value={
                "data": [
                    {"service": "EC2", "total_cost": 500.00},
                    {"service": "S3", "total_cost": 150.00}
                ],
                "sql_query": test_sql,
                "metadata": {"rows_returned": 2}
            })

            # Mock response formatter
            mock_formatter.format_response = MagicMock(return_value="Here are your costs by service.")

            # Mock recommendation engine
            mock_rec_engine.generate_recommendations = AsyncMock(return_value={
                "suggestions": ["Review EC2 instance types"],
                "drill_down_options": [],
                "optimization_asked": False
            })

            # Execute workflow
            response = await execute_multi_agent_query(
                query="Show my costs for the last 30 days",
                conversation_id="test-789",
                chat_history=[],
                previous_context={}
            )

            # Verify athena_query is in response
            assert "athena_query" in response
            assert response["athena_query"] is not None
            assert response["athena_query"] == test_sql
            assert "SELECT" in response["athena_query"]
            assert "cost_data" in response["athena_query"]

    @pytest.mark.asyncio
    async def test_optimization_request_no_sql_query(self):
        """Test that optimization requests don't include athena_query"""
        from agents.multi_agent_workflow import execute_multi_agent_query

        # Mock dependencies for optimization flow
        with patch('agents.multi_agent_workflow.intent_classifier') as mock_classifier, \
             patch('agents.multi_agent_workflow.recommendation_engine') as mock_rec_engine, \
             patch('agents.multi_agent_workflow.response_formatter') as mock_formatter:

            # Mock intent classifier to route to optimization
            mock_intent = MagicMock()
            mock_intent.intent = "optimization"
            mock_intent.confidence = 0.92
            mock_intent.extracted_params = {"optimization_type": "general"}
            mock_classifier.classify_intent = AsyncMock(return_value=mock_intent)

            # Mock recommendation engine
            mock_rec_engine.generate_recommendations = AsyncMock(return_value={
                "recommendations": [
                    {"type": "EC2", "savings": 500, "action": "Right-size instances"}
                ],
                "total_savings": 500
            })

            # Mock response formatter
            mock_formatter.format_optimization_response = MagicMock(
                return_value="I recommend right-sizing your EC2 instances to save $500/month."
            )

            # Execute workflow
            response = await execute_multi_agent_query(
                query="How can I optimize my AWS costs?",
                conversation_id="test-opt-123",
                chat_history=[],
                previous_context={}
            )

            # Verify athena_query is None or not present for optimization
            athena_query = response.get("athena_query")
            assert athena_query is None or athena_query == ""


class TestSQLQueryFormat:
    """Test SQL query format and structure validation"""

    def test_sql_query_is_string(self):
        """Verify athena_query is always a string when present"""
        response = ChatResponse(
            message="Test",
            conversation_id="test",
            athena_query="SELECT * FROM cost_data",
            execution_time=1.0,
            timestamp=datetime.utcnow()
        )

        assert isinstance(response.athena_query, str)

    def test_sql_query_contains_valid_syntax(self):
        """Verify athena_query contains valid SQL keywords"""
        test_query = """
        SELECT 
            line_item_usage_account_id,
            line_item_product_code,
            SUM(line_item_unblended_cost) AS total_cost
        FROM cost_data
        WHERE line_item_usage_start_date >= date_add('day', -30, current_date)
        GROUP BY line_item_usage_account_id, line_item_product_code
        ORDER BY total_cost DESC
        LIMIT 10
        """

        response = ChatResponse(
            message="Test",
            conversation_id="test",
            athena_query=test_query,
            execution_time=1.0,
            timestamp=datetime.utcnow()
        )

        # Verify SQL keywords are present
        query = response.athena_query.upper()
        assert "SELECT" in query
        assert "FROM" in query
        assert "WHERE" in query or "GROUP BY" in query or "ORDER BY" in query


class TestIntegrationWithExistingMetadata:
    """Test that athena_query integrates properly with existing metadata flow"""

    @pytest.mark.asyncio
    async def test_athena_query_with_charts_and_metadata(self):
        """Test that athena_query works alongside charts and other metadata"""
        response = ChatResponse(
            message="Your top 5 services by cost",
            conversation_id="test-int-123",
            charts=[
                {
                    "type": "bar",
                    "title": "Top 5 Services",
                    "data": {"labels": ["EC2", "S3"], "values": [500, 150]}
                }
            ],
            insights=[],
            action_items=[],
            suggestions=["Review EC2 usage"],
            agent_responses=[],
            reasoning=None,
            context={"time_range": "last_30_days", "dimension": "service"},
            user_intent="cost_analysis",
            athena_query="SELECT service, SUM(cost) FROM cost_data GROUP BY service",
            execution_time=1.2,
            timestamp=datetime.utcnow()
        )

        # Verify all fields coexist properly
        assert response.athena_query is not None
        assert len(response.charts) > 0
        assert len(response.suggestions) > 0
        assert response.context is not None
        assert "time_range" in response.context

    def test_json_serialization_with_athena_query(self):
        """Test that ChatResponse with athena_query serializes to JSON properly"""
        response = ChatResponse(
            message="Test message",
            conversation_id="test-json-123",
            charts=[],
            insights=[],
            action_items=[],
            suggestions=[],
            agent_responses=[],
            reasoning=None,
            context={},
            user_intent="cost_analysis",
            athena_query="SELECT * FROM cost_data LIMIT 10",
            execution_time=0.5,
            timestamp=datetime.utcnow()
        )

        # Convert to dict (simulates JSON serialization)
        response_dict = response.model_dump()

        # Verify athena_query is in serialized output
        assert "athena_query" in response_dict
        assert response_dict["athena_query"] == "SELECT * FROM cost_data LIMIT 10"
