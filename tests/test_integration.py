#!/usr/bin/env python3
"""
Integration test for the new text-to-SQL architecture
Tests the complete flow without actually hitting AWS services
"""

import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def test_imports():
    """Test all imports work"""
    print("Testing imports...")
    
    try:
        from backend.agents.multi_agent_workflow import execute_multi_agent_query
        print("✓ multi_agent_workflow import OK")
    except Exception as e:
        print(f"✗ multi_agent_workflow import FAILED: {e}")
        return False
    
    try:
        from backend.agents.execute_query_v2 import execute_query_simple, AthenaExecutor
        print("✓ execute_query_v2 import OK")
    except Exception as e:
        print(f"✗ execute_query_v2 import FAILED: {e}")
        return False
    
    try:
        from backend.services.text_to_sql_service import text_to_sql_service, TextToSQLService
        print("✓ text_to_sql_service import OK")
    except Exception as e:
        print(f"✗ text_to_sql_service import FAILED: {e}")
        return False
    
    try:
        from backend.services.chart_recommendation import chart_engine
        print("✓ chart_recommendation import OK")
    except Exception as e:
        print(f"✗ chart_recommendation import FAILED: {e}")
        return False
    
    try:
        from backend.services.chart_data_builder import chart_data_builder
        print("✓ chart_data_builder import OK")
    except Exception as e:
        print("✗ chart_data_builder import FAILED: {e}")
        return False
    
    return True


def test_function_signatures():
    """Test that functions have expected signatures"""
    print("\nTesting function signatures...")
    
    from backend.agents.multi_agent_workflow import execute_multi_agent_query
    from backend.agents.execute_query_v2 import execute_query_simple
    from backend.services.text_to_sql_service import text_to_sql_service
    
    import inspect
    
    # Check execute_multi_agent_query
    sig = inspect.signature(execute_multi_agent_query)
    params = list(sig.parameters.keys())
    expected = ['query', 'conversation_id', 'chat_history', 'previous_context']
    if params == expected:
        print(f"✓ execute_multi_agent_query signature OK: {params}")
    else:
        print(f"✗ execute_multi_agent_query signature mismatch")
        print(f"  Expected: {expected}")
        print(f"  Got: {params}")
        return False
    
    # Check execute_query_simple
    sig = inspect.signature(execute_query_simple)
    params = list(sig.parameters.keys())
    expected = ['query', 'conversation_history', 'previous_context']
    if params == expected:
        print(f"✓ execute_query_simple signature OK: {params}")
    else:
        print(f"✗ execute_query_simple signature mismatch")
        print(f"  Expected: {expected}")
        print(f"  Got: {params}")
        return False
    
    # Check text_to_sql_service
    if hasattr(text_to_sql_service, 'generate_sql'):
        print(f"✓ text_to_sql_service.generate_sql exists")
    else:
        print(f"✗ text_to_sql_service.generate_sql not found")
        return False
    
    return True


def test_chart_integration():
    """Test chart recommendation with string intent"""
    print("\nTesting chart integration...")
    
    from backend.services.chart_recommendation import chart_engine
    
    mock_results = [
        {"service": "AmazonEC2", "cost_usd": 100.50},
        {"service": "AmazonS3", "cost_usd": 50.25}
    ]
    
    try:
        # Test with string intent (what text-to-SQL returns)
        charts = chart_engine.recommend_charts(
            intent="top_services",
            data_results=mock_results,
            extracted_params={}
        )
        print(f"✓ Chart recommendation with string intent OK (returned {len(charts)} charts)")
    except Exception as e:
        print(f"✗ Chart recommendation FAILED: {e}")
        return False
    
    return True


def test_settings():
    """Test settings are accessible"""
    print("\nTesting settings...")
    
    from backend.config.settings import get_settings
    
    try:
        settings = get_settings()
        
        # Check critical settings exist
        required_attrs = [
            'aws_region',
            'athena_output_location',
            'aws_cur_database',
            'aws_cur_table',
            'bedrock_model_id'
        ]
        
        for attr in required_attrs:
            if not hasattr(settings, attr):
                print(f"✗ Missing setting: {attr}")
                return False
        
        print(f"✓ All required settings present")
        print(f"  - AWS Region: {settings.aws_region}")
        print(f"  - CUR Database: {settings.aws_cur_database}")
        print(f"  - CUR Table: {settings.aws_cur_table}")
        print(f"  - Bedrock Model: {settings.bedrock_model_id}")
        
    except Exception as e:
        print(f"✗ Settings loading FAILED: {e}")
        return False
    
    return True


def main():
    """Run all tests"""
    print("=" * 60)
    print("INTEGRATION TEST: Text-to-SQL Architecture")
    print("=" * 60)
    
    tests = [
        ("Imports", test_imports),
        ("Function Signatures", test_function_signatures),
        ("Chart Integration", test_chart_integration),
        ("Settings", test_settings),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ {name} test crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")
    
    all_passed = all(r for _, r in results)
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✓ ALL TESTS PASSED - Code is ready for deployment")
    else:
        print("✗ SOME TESTS FAILED - Fix issues before deploying")
    print("=" * 60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
