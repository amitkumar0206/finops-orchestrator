#!/usr/bin/env python3
"""
Test context preservation for service filters when time range changes
Issue: "for last 100 days" after "for ec2 and lambda" should preserve EC2 and Lambda filters
"""
import sys
sys.path.insert(0, '/Users/Amit.Kumar2/Documents/Code/finops-orchestrator/backend')

from services.conversation_context import ConversationContext

def test_service_preservation_on_time_change():
    """Test that services are preserved when only time range changes"""
    
    print("="*80)
    print("TEST: Service Preservation When Time Range Changes")
    print("="*80)
    
    # Create conversation context
    context = ConversationContext("test-conversation")
    
    # Simulate first query: "Show me my AWS costs for the last 30 days"
    print("\n1. Initial Query: 'Show me my AWS costs for the last 30 days'")
    context.update(
        query="Show me my AWS costs for the last 30 days",
        intent="COST_BREAKDOWN",
        extracted_params={
            "time_range": {
                "description": "Last 30 days",
                "start_date": "2024-10-04",
                "end_date": "2024-11-03"
            },
            "start_date": "2024-10-04",
            "end_date": "2024-11-03"
        },
        results_count=38,
        total_cost=647.64
    )
    print(f"   ✓ Services: {context.last_params.get('services', 'None')}")
    print(f"   ✓ Time Range: {context.last_time_range.get('description')}")
    
    # Simulate second query: "for ec2 and lambda"
    print("\n2. Follow-up Query: 'for ec2 and lambda'")
    new_params = {
        "services": ["Amazon Elastic Compute Cloud - Compute", "AWS Lambda"]
    }
    refined_params = context.apply_follow_up_refinement(
        query="for ec2 and lambda",
        new_params=new_params
    )
    
    # Update context with refined params
    context.update(
        query="for ec2 and lambda",
        intent="COST_BREAKDOWN",
        extracted_params=refined_params,
        results_count=2,
        total_cost=50.65
    )
    print(f"   ✓ Services: {context.last_params.get('services')}")
    print(f"   ✓ Time Range: {context.last_time_range.get('description')}")
    
    # Simulate third query: "for last 100 days" (SHOULD PRESERVE EC2 AND LAMBDA!)
    print("\n3. Follow-up Query: 'for last 100 days'")
    print("   EXPECTATION: Should preserve EC2 and Lambda services")
    
    new_params = {
        "time_range": {
            "description": "Last 100 days",
            "start_date": "2024-07-26",
            "end_date": "2024-11-03"
        },
        "start_date": "2024-07-26",
        "end_date": "2024-11-03"
    }
    refined_params = context.apply_follow_up_refinement(
        query="for last 100 days",
        new_params=new_params
    )
    
    print(f"   Services in refined params: {refined_params.get('services')}")
    print(f"   Time Range: {refined_params.get('time_range', {}).get('description')}")
    
    # Verify the fix
    expected_services = ["Amazon Elastic Compute Cloud - Compute", "AWS Lambda"]
    actual_services = refined_params.get('services', [])
    
    print("\n" + "="*80)
    print("RESULTS:")
    print("="*80)
    
    if actual_services == expected_services:
        print("✅ SUCCESS: Services were preserved correctly!")
        print(f"   Expected: {expected_services}")
        print(f"   Actual:   {actual_services}")
        return True
    else:
        print("❌ FAILURE: Services were NOT preserved!")
        print(f"   Expected: {expected_services}")
        print(f"   Actual:   {actual_services}")
        return False

def test_explicit_service_change_overrides():
    """Test that explicit service changes still work (not everything is inherited)"""
    
    print("\n" + "="*80)
    print("TEST: Explicit Service Changes Should Override")
    print("="*80)
    
    context = ConversationContext("test-conversation-2")
    
    # Setup with EC2 and Lambda
    context.update(
        query="for ec2 and lambda",
        intent="COST_BREAKDOWN",
        extracted_params={
            "services": ["Amazon Elastic Compute Cloud - Compute", "AWS Lambda"],
            "time_range": {"description": "Last 30 days"}
        },
        results_count=2,
        total_cost=50.65
    )
    
    print("\n1. Initial: EC2 and Lambda for 30 days")
    print(f"   Services: {context.last_params.get('services')}")
    
    # Now change to "only for S3"
    print("\n2. Follow-up: 'only for S3'")
    new_params = {
        "services": ["Amazon Simple Storage Service"]
    }
    refined_params = context.apply_follow_up_refinement(
        query="only for S3",
        new_params=new_params
    )
    
    expected_services = ["Amazon Simple Storage Service"]
    actual_services = refined_params.get('services', [])
    
    print(f"   Expected: {expected_services}")
    print(f"   Actual:   {actual_services}")
    
    if actual_services == expected_services:
        print("✅ SUCCESS: Explicit service change worked!")
        return True
    else:
        print("❌ FAILURE: Explicit service change did not work!")
        return False

if __name__ == "__main__":
    print("\nContext Preservation Test Suite")
    print("Testing fix for: 'for last 100 days' should preserve EC2 and Lambda filters\n")
    
    test1_passed = test_service_preservation_on_time_change()
    test2_passed = test_explicit_service_change_overrides()
    
    print("\n" + "="*80)
    print("OVERALL TEST RESULTS")
    print("="*80)
    print(f"Test 1 (Service Preservation): {'✅ PASSED' if test1_passed else '❌ FAILED'}")
    print(f"Test 2 (Explicit Override):     {'✅ PASSED' if test2_passed else '❌ FAILED'}")
    
    if test1_passed and test2_passed:
        print("\n🎉 ALL TESTS PASSED!")
        sys.exit(0)
    else:
        print("\n⚠️  SOME TESTS FAILED")
        sys.exit(1)
