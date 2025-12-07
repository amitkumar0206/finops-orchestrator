#!/usr/bin/env python3
"""
Test human-like conversation understanding for context management
Tests all scenarios: preserve, add, replace, remove, clear
"""
import sys
sys.path.insert(0, '/Users/Amit.Kumar2/Documents/Code/finops-orchestrator/backend')

from services.conversation_context import ConversationContext

def print_section(title):
    print("\n" + "="*80)
    print(f"  {title}")
    print("="*80)

def print_test(test_num, scenario, query, expected_behavior):
    print(f"\n{test_num}. SCENARIO: {scenario}")
    print(f"   Query: '{query}'")
    print(f"   Expected: {expected_behavior}")

def verify_result(actual_services, expected_services, actual_time, expected_time_desc=None):
    """Verify test results"""
    services_match = actual_services == expected_services
    time_match = True
    if expected_time_desc:
        time_match = expected_time_desc.lower() in (actual_time or {}).get('description', '').lower()
    
    if services_match and time_match:
        print(f"   ✅ PASS")
        print(f"      Services: {actual_services}")
        if expected_time_desc:
            print(f"      Time: {actual_time.get('description')}")
        return True
    else:
        print(f"   ❌ FAIL")
        print(f"      Expected Services: {expected_services}")
        print(f"      Actual Services:   {actual_services}")
        if expected_time_desc:
            print(f"      Expected Time: {expected_time_desc}")
            print(f"      Actual Time:   {actual_time.get('description', 'None')}")
        return False

def test_all_scenarios():
    """Test all context management scenarios"""
    
    print_section("HUMAN-LIKE CONTEXT UNDERSTANDING TEST SUITE")
    
    results = []
    
    # Test 1: Preserve services when time changes
    print_section("TEST GROUP 1: PRESERVE (Time changes, keep filters)")
    
    context = ConversationContext("test-preserve")
    
    # Setup: Filter for EC2 and Lambda
    context.update(
        query="for ec2 and lambda",
        intent="COST_BREAKDOWN",
        extracted_params={
            "services": ["Amazon Elastic Compute Cloud - Compute", "AWS Lambda"],
            "time_range": {"description": "Last 30 days", "start_date": "2024-10-04", "end_date": "2024-11-03"}
        },
        results_count=2,
        total_cost=50.65
    )
    print("\n   Initial Context: EC2 + Lambda for 30 days")
    
    print_test(
        "1a",
        "Time change only",
        "for last 100 days",
        "PRESERVE EC2 + Lambda, change time to 100 days"
    )
    refined = context.apply_follow_up_refinement(
        "for last 100 days",
        {"time_range": {"description": "Last 100 days", "start_date": "2024-07-26", "end_date": "2024-11-03"}}
    )
    results.append(verify_result(
        refined.get('services'),
        ["Amazon Elastic Compute Cloud - Compute", "AWS Lambda"],
        refined.get('time_range'),
        "100 days"
    ))
    
    # Test 2: Replace services
    print_section("TEST GROUP 2: REPLACE (Change filters)")
    
    context2 = ConversationContext("test-replace")
    context2.update(
        query="for ec2 and lambda",
        intent="COST_BREAKDOWN",
        extracted_params={
            "services": ["Amazon Elastic Compute Cloud - Compute", "AWS Lambda"],
            "time_range": {"description": "Last 30 days"}
        },
        results_count=2
    )
    print("\n   Initial Context: EC2 + Lambda")
    
    print_test(
        "2a",
        "Explicit replacement",
        "only for S3",
        "REPLACE with S3 only"
    )
    refined = context2.apply_follow_up_refinement(
        "only for S3",
        {"services": ["Amazon Simple Storage Service"]}
    )
    results.append(verify_result(
        refined.get('services'),
        ["Amazon Simple Storage Service"],
        None
    ))
    
    # Test 3: Add services
    print_section("TEST GROUP 3: ADD (Expand filters)")
    
    context3 = ConversationContext("test-add")
    context3.update(
        query="for ec2 and lambda",
        intent="COST_BREAKDOWN",
        extracted_params={
            "services": ["Amazon Elastic Compute Cloud - Compute", "AWS Lambda"],
            "time_range": {"description": "Last 30 days"}
        },
        results_count=2
    )
    print("\n   Initial Context: EC2 + Lambda")
    
    print_test(
        "3a",
        "Adding services",
        "also include S3",
        "ADD S3 to existing (EC2 + Lambda + S3)"
    )
    refined = context3.apply_follow_up_refinement(
        "also include S3",
        {"services": ["Amazon Simple Storage Service"]}
    )
    expected = ["Amazon Elastic Compute Cloud - Compute", "AWS Lambda", "Amazon Simple Storage Service"]
    results.append(verify_result(
        refined.get('services'),
        expected,
        None
    ))
    
    # Test 4: No filters initially, time change
    print_section("TEST GROUP 4: NO PREVIOUS FILTERS")
    
    context4 = ConversationContext("test-no-filters")
    context4.update(
        query="show me costs",
        intent="COST_BREAKDOWN",
        extracted_params={
            "time_range": {"description": "Last 30 days"}
        },
        results_count=38
    )
    print("\n   Initial Context: All services, 30 days")
    
    print_test(
        "4a",
        "Time change with no filters",
        "for last 200 days",
        "Change time to 200 days, no services to preserve"
    )
    refined = context4.apply_follow_up_refinement(
        "for last 200 days",
        {"time_range": {"description": "Last 200 days", "start_date": "2024-04-17", "end_date": "2024-11-03"}}
    )
    results.append(verify_result(
        refined.get('services'),
        None,  # No services should be set
        refined.get('time_range'),
        "200 days"
    ))
    
    # Test 5: Complex scenario - multiple follow-ups
    print_section("TEST GROUP 5: MULTIPLE FOLLOW-UPS")
    
    context5 = ConversationContext("test-complex")
    
    # Step 1: Start with all costs
    context5.update(
        query="show costs",
        intent="COST_BREAKDOWN",
        extracted_params={"time_range": {"description": "Last 30 days"}},
        results_count=38
    )
    print("\n   Step 1: All services, 30 days")
    
    # Step 2: Filter to EC2 and Lambda
    refined = context5.apply_follow_up_refinement(
        "for ec2 and lambda",
        {"services": ["Amazon Elastic Compute Cloud - Compute", "AWS Lambda"]}
    )
    context5.update(
        query="for ec2 and lambda",
        intent="COST_BREAKDOWN",
        extracted_params=refined,
        results_count=2
    )
    print("   Step 2: Filtered to EC2 + Lambda")
    
    # Step 3: Change time to 100 days (should preserve EC2 + Lambda)
    print_test(
        "5a",
        "Chained follow-up",
        "for last 100 days",
        "PRESERVE EC2 + Lambda from step 2"
    )
    refined = context5.apply_follow_up_refinement(
        "for last 100 days",
        {"time_range": {"description": "Last 100 days"}}
    )
    results.append(verify_result(
        refined.get('services'),
        ["Amazon Elastic Compute Cloud - Compute", "AWS Lambda"],
        refined.get('time_range'),
        "100 days"
    ))
    
    # Summary
    print_section("TEST SUMMARY")
    
    total = len(results)
    passed = sum(results)
    failed = total - passed
    
    print(f"\nTotal Tests: {total}")
    print(f"Passed:      {passed} ✅")
    print(f"Failed:      {failed} {'❌' if failed > 0 else ''}")
    
    if failed == 0:
        print("\n🎉 ALL TESTS PASSED - Human-like context understanding works!")
        return True
    else:
        print(f"\n⚠️  {failed} test(s) failed")
        return False

if __name__ == "__main__":
    success = test_all_scenarios()
    sys.exit(0 if success else 1)
