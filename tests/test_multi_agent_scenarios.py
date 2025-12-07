"""
Test Multi-Agent System with Scenario-Based Validation
Tests the four key scenarios that were failing with the original system.
"""

import asyncio
import pytest
from typing import Dict, Any, List

# Import the multi-agent workflow
import sys
sys.path.append('../')

from backend.agents.multi_agent_workflow import execute_multi_agent_query


class TestMultiAgentScenarios:
    """Test suite for multi-agent followup scenarios."""
    
    @pytest.mark.asyncio
    async def test_scenario_1_service_drilldown(self):
        """
        Scenario 1: Service Drill-Down
        Query 1: What are my top 5 most expensive services?
        Query 2: Drill down into AmazonCloudWatch to identify specific cost drivers
        Expected: CloudWatch costs broken down by usage type (Logs, Metrics, etc.)
        """
        conversation_id = "test-scenario-1"
        
        # Query 1: Get top services
        response1 = await execute_multi_agent_query(
            query="What are my top 5 most expensive services?",
            conversation_id=conversation_id,
            chat_history=[],
            previous_context={}
        )
        
        print("\n=== SCENARIO 1 - QUERY 1 ===")
        print(f"Message: {response1['message'][:200]}...")
        print(f"Agent Routing: {response1['metadata']['agent_routing']}")
        print(f"Context: {response1['context']}")
        
        # Verify response has top services
        assert response1['message'], "Response should contain a message"
        assert response1['context'], "Context should be stored"
        
        # Query 2: Drill down into CloudWatch
        chat_history = [
            {"role": "user", "content": "What are my top 5 most expensive services?"},
            {"role": "assistant", "content": response1['message']}
        ]
        
        response2 = await execute_multi_agent_query(
            query="Drill down into AmazonCloudWatch to identify specific cost drivers by region or account",
            conversation_id=conversation_id,
            chat_history=chat_history,
            previous_context=response1['context']
        )
        
        print("\n=== SCENARIO 1 - QUERY 2 ===")
        print(f"Message: {response2['message'][:200]}...")
        print(f"Agent Routing: {response2['metadata']['agent_routing']}")
        print(f"Context: {response2['context']}")
        
        # Verify drill-down works
        assert "CloudWatch" in response2['message'] or "cloudwatch" in response2['message'].lower()
        assert response2['context'].get('services'), "Services should be in context"
        assert "AmazonCloudWatch" in str(response2['context'].get('services', [])) or \
               "cloudwatch" in str(response2['context'].get('services', [])).lower()
        
        print("\n✅ Scenario 1 PASSED: Service drill-down working correctly")
    
    @pytest.mark.asyncio
    async def test_scenario_2_time_range_update(self):
        """
        Scenario 2: Time Range Update
        Query 1: Show me my AWS costs for the last 30 days
        Query 2: for 100 days
        Expected: Same data but for 100-day period
        """
        conversation_id = "test-scenario-2"
        
        # Query 1: Get costs for 30 days
        response1 = await execute_multi_agent_query(
            query="Show me my AWS costs for the last 30 days",
            conversation_id=conversation_id,
            chat_history=[],
            previous_context={}
        )
        
        print("\n=== SCENARIO 2 - QUERY 1 ===")
        print(f"Message: {response1['message'][:200]}...")
        print(f"Time Range: {response1['context'].get('time_range')}")
        
        # Verify 30-day range
        assert response1['context'].get('time_range'), "Time range should be in context"
        
        # Query 2: Update to 100 days
        chat_history = [
            {"role": "user", "content": "Show me my AWS costs for the last 30 days"},
            {"role": "assistant", "content": response1['message']}
        ]
        
        response2 = await execute_multi_agent_query(
            query="for 100 days",
            conversation_id=conversation_id,
            chat_history=chat_history,
            previous_context=response1['context']
        )
        
        print("\n=== SCENARIO 2 - QUERY 2 ===")
        print(f"Message: {response2['message'][:200]}...")
        print(f"Time Range: {response2['context'].get('time_range')}")
        
        # Verify time range updated
        assert response2['context'].get('time_range'), "Time range should be updated"
        assert "No cost data" not in response2['message'], "Should have cost data for 100 days"
        
        print("\n✅ Scenario 2 PASSED: Time range update working correctly")
    
    @pytest.mark.asyncio
    async def test_scenario_3_specific_optimization(self):
        """
        Scenario 3: Specific Optimization
        Query 1: Show me my AWS costs
        Query 2: Investigate top cost categories for optimization opportunities
        Query 3: Show me step by step method on how to save on CloudWatch costs
        Expected: Specific CloudWatch optimization strategies
        """
        conversation_id = "test-scenario-3"
        
        # Query 1: Get costs
        response1 = await execute_multi_agent_query(
            query="Show me my AWS costs for the last 30 days",
            conversation_id=conversation_id,
            chat_history=[],
            previous_context={}
        )
        
        print("\n=== SCENARIO 3 - QUERY 1 ===")
        print(f"Agent Routing: {response1['metadata']['agent_routing']}")
        
        # Query 2: Optimization opportunities
        chat_history = [
            {"role": "user", "content": "Show me my AWS costs for the last 30 days"},
            {"role": "assistant", "content": response1['message']}
        ]
        
        response2 = await execute_multi_agent_query(
            query="Investigate top cost categories for optimization opportunities",
            conversation_id=conversation_id,
            chat_history=chat_history,
            previous_context=response1['context']
        )
        
        print("\n=== SCENARIO 3 - QUERY 2 ===")
        print(f"Message: {response2['message'][:200]}...")
        print(f"Agent Routing: {response2['metadata']['agent_routing']}")
        
        # Verify optimization response
        assert "optimization" in str(response2['metadata']['agent_routing']), \
            "Should route to optimization agent"
        
        # Query 3: Specific CloudWatch optimization
        chat_history.extend([
            {"role": "user", "content": "Investigate top cost categories for optimization opportunities"},
            {"role": "assistant", "content": response2['message']}
        ])
        
        response3 = await execute_multi_agent_query(
            query="can you show me step by step method on how to save on cloudwatch costs",
            conversation_id=conversation_id,
            chat_history=chat_history,
            previous_context=response2['context']
        )
        
        print("\n=== SCENARIO 3 - QUERY 3 ===")
        print(f"Message: {response3['message'][:300]}...")
        print(f"Agent Routing: {response3['metadata']['agent_routing']}")
        
        # Verify specific CloudWatch optimization
        assert response3['message'] != response2['message'], \
            "Response should be different, not repeated"
        assert "CloudWatch" in response3['message'] or "cloudwatch" in response3['message'].lower(), \
            "Should mention CloudWatch specifically"
        
        print("\n✅ Scenario 3 PASSED: Specific optimization working correctly")
    
    @pytest.mark.asyncio
    async def test_scenario_4_infrastructure_analysis(self):
        """
        Scenario 4: Infrastructure Analysis
        Query: How can I optimize my EC2 costs?
        Expected: Specific strategies based on infrastructure analysis
        """
        conversation_id = "test-scenario-4"
        
        response = await execute_multi_agent_query(
            query="How can I optimize my EC2 costs?",
            conversation_id=conversation_id,
            chat_history=[],
            previous_context={}
        )
        
        print("\n=== SCENARIO 4 ===")
        print(f"Message: {response['message'][:300]}...")
        print(f"Agent Routing: {response['metadata']['agent_routing']}")
        
        # Verify infrastructure analysis or optimization
        message_lower = response['message'].lower()
        routing = str(response['metadata']['agent_routing'])
        
        assert "infrastructure" in routing or "optimization" in routing, \
            "Should route to infrastructure or optimization agent"
        assert "ec2" in message_lower, "Should mention EC2"
        assert any(keyword in message_lower for keyword in [
            "downsize", "rightsizing", "instance", "utilization", "optimize", "savings"
        ]), "Should provide specific optimization strategies"
        
        print("\n✅ Scenario 4 PASSED: Infrastructure analysis working correctly")


async def run_manual_test():
    """Manual test for quick validation during development."""
    print("\n" + "="*80)
    print("MANUAL TEST - Multi-Agent System")
    print("="*80)
    
    # Test Scenario 1
    print("\n\n### TESTING SCENARIO 1: Service Drill-Down ###")
    conv_id = "manual-test-1"
    
    response1 = await execute_multi_agent_query(
        query="What are my top 5 most expensive services?",
        conversation_id=conv_id,
        chat_history=[],
        previous_context={}
    )
    
    print(f"\nQuery 1 Response:")
    print(f"Message: {response1['message'][:300]}...")
    print(f"Charts: {len(response1['charts'])} chart(s)")
    print(f"Context Services: {response1['context'].get('services', [])}")
    
    # Followup
    response2 = await execute_multi_agent_query(
        query="Drill down into AmazonCloudWatch to identify cost drivers",
        conversation_id=conv_id,
        chat_history=[
            {"role": "user", "content": "What are my top 5 most expensive services?"},
            {"role": "assistant", "content": response1['message']}
        ],
        previous_context=response1['context']
    )
    
    print(f"\nQuery 2 Response:")
    print(f"Message: {response2['message'][:300]}...")
    print(f"Charts: {len(response2['charts'])} chart(s)")
    print(f"Context Services: {response2['context'].get('services', [])}")
    print(f"Context Dimension: {response2['context'].get('dimension', 'N/A')}")
    
    print("\n" + "="*80)
    print("Manual test completed!")
    print("="*80)


if __name__ == "__main__":
    # Run manual test
    asyncio.run(run_manual_test())
    
    # Uncomment to run pytest
    # pytest.main([__file__, "-v", "-s"])
