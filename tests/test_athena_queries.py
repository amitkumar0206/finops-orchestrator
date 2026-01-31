
import pytest
from unittest.mock import MagicMock, patch
from datetime import date
from backend.services.athena_executor import EnhancedAthenaQueryExecutor
from backend.agents.intent_classifier import IntentType
from backend.services.athena_query_service import AthenaQueryService

@pytest.fixture
def executor():
    with patch('backend.services.athena_executor.create_aws_session'):
        executor = EnhancedAthenaQueryExecutor()
        executor.templates = MagicMock()
        return executor

@pytest.mark.asyncio
async def test_reserved_instances_cost_query_generation(executor):
    # Mock template method
    executor.templates.top_n_services.return_value = "SELECT * FROM mock_table"
    
    intent = IntentType.OPTIMIZATION
    params = {
        "services": ["AmazonEC2"],
        "time_range": {"start_date": "2023-01-01", "end_date": "2023-01-31"},
        "metadata": {"explanation_request": False}
    }
    # Query asking for COST/SPEND
    query_text = "how much are we spending on reserved instances"
    
    # Execute
    await executor.execute_query_for_intent(intent, params, query_text)
    
    # Verify that top_n_services was called with include_line_item_types
    executor.templates.top_n_services.assert_called_with(
        "2023-01-01", 
        "2023-01-31", 
        limit=10, 
        include_line_item_types=['RIFee', 'Fee']
    )

@pytest.mark.asyncio
async def test_reserved_instances_savings_query_generation(executor):
    # Mock template method
    executor.templates.ec2_reserved_savings_projection.return_value = "SELECT * FROM mock_table"
    
    intent = IntentType.OPTIMIZATION
    params = {
        "services": ["AmazonEC2"],
        "time_range": {"start_date": "2023-01-01", "end_date": "2023-01-31"},
    }
    # Query asking for SAVINGS (default)
    query_text = "how much can we save with reserved instances"
    
    # Execute
    await executor.execute_query_for_intent(intent, params, query_text)
    
    # Verify that ec2_reserved_savings_projection was called
    executor.templates.ec2_reserved_savings_projection.assert_called()

@pytest.mark.asyncio
async def test_comparison_query_generation_with_date_objects(executor):
    # Mock template method
    executor.templates.period_over_period_comparison.return_value = "SELECT * FROM mock_table"
    
    intent = IntentType.COMPARATIVE
    # Pass date objects in params (simulating what other agents might do)
    start_date = date(2023, 2, 1)
    end_date = date(2023, 2, 28)
    params = {
        "services": [],
        "time_range": {"start_date": start_date, "end_date": end_date},
        "comparison_entities": {} 
    }
    query_text = "compare with previous period"
    
    # Execute
    await executor.execute_query_for_intent(intent, params, query_text)
    
    # Verify template call
    executor.templates.period_over_period_comparison.assert_called()
    # Check arguments
    call_args = executor.templates.period_over_period_comparison.call_args
    assert str(call_args.kwargs['current_start']) == "2023-02-01"
    assert str(call_args.kwargs['current_end']) == "2023-02-28"

@pytest.mark.asyncio
async def test_athena_query_service_filters_removed():
    with patch('backend.services.athena_query_service.create_aws_session'):
        service = AthenaQueryService()
        time_range = {"start_date": "2023-01-01", "end_date": "2023-01-31"}
        
        # Test top services query
        sql = service._generate_top_services_query(time_range)
        assert "line_item_line_item_type = 'Usage'" not in sql
        
        # Test daily costs query
        sql = service._generate_daily_costs_query(time_range)
        assert "line_item_line_item_type = 'Usage'" not in sql
        
        # Test service breakdown query
        sql = service._generate_service_breakdown_query(time_range)
        assert "line_item_line_item_type = 'Usage'" not in sql
