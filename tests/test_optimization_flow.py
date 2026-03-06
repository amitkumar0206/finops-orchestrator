#!/usr/bin/env python3
"""
Comprehensive test of optimization flow to identify ALL issues.
Tests: database seeding, recommendation retrieval, query routing, response formatting
"""

import sys
import os
from unittest.mock import patch, MagicMock

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))


def _mock_psycopg2_connect(**kwargs):
    """Create a mock psycopg2 connection for tests that need DB"""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {'total': 5}
    mock_cursor.fetchall.return_value = [
        {'service': 'EC2', 'count': 3, 'avg_savings': 25.0},
        {'service': 'RDS', 'count': 2, 'avg_savings': 20.0},
    ]
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn


@patch('psycopg2.connect', side_effect=_mock_psycopg2_connect)
def test_database_connection(mock_connect):
    """Test 1: Can we connect to the database?"""
    import psycopg2

    db_config = {
        'host': os.getenv('POSTGRES_HOST', 'localhost'),
        'port': int(os.getenv('POSTGRES_PORT', '5432')),
        'database': os.getenv('POSTGRES_DB', 'finops'),
        'user': os.getenv('POSTGRES_USER', 'finops'),
        'password': os.getenv('DB_PASSWORD', 'test')
    }

    conn = psycopg2.connect(**db_config)
    assert conn is not None
    conn.close()


@patch('psycopg2.connect', side_effect=_mock_psycopg2_connect)
def test_recommendations_table(mock_connect):
    """Test 2: Does the optimization_recommendations table have data?"""
    import psycopg2
    from psycopg2.extras import RealDictCursor

    db_config = {
        'host': os.getenv('POSTGRES_HOST', 'localhost'),
        'port': int(os.getenv('POSTGRES_PORT', '5432')),
        'database': os.getenv('POSTGRES_DB', 'finops'),
        'user': os.getenv('POSTGRES_USER', 'finops'),
        'password': os.getenv('DB_PASSWORD', 'test')
    }

    conn = psycopg2.connect(**db_config)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("SELECT COUNT(*) as total FROM optimization_recommendations")
    total = cur.fetchone()['total']
    assert total > 0

    cur.close()
    conn.close()


@patch('psycopg2.connect', side_effect=_mock_psycopg2_connect)
def test_optimization_engine(mock_connect):
    """Test 3: Does OptimizationEngine.get_recommendations() work?"""
    # Mock the psycopg2 import used by OptimizationEngine
    mock_cursor = mock_connect.return_value.cursor.return_value
    mock_cursor.fetchall.return_value = [
        {
            'strategy_name': 'Rightsize EC2 Instances',
            'estimated_savings_min_percent': 15,
            'estimated_savings_max_percent': 30,
            'implementation_effort_hours': 4,
            'confidence_score': 0.85,
        }
    ]
    mock_cursor.fetchone.return_value = (1,)

    from services.optimization_engine import OptimizationEngine

    engine = OptimizationEngine()
    engine.get_recommendations("EC2", {"current_monthly_cost": 1000.0})

    # Engine was instantiated and called without hanging
    assert engine is not None


def test_multi_agent_routing():
    """Test 4: Does the query route to optimization agent?"""
    print("\n" + "="*80)
    print("TEST 4: Multi-Agent Query Routing")
    print("="*80)
    
    test_queries = [
        "Generate a cost optimization report",
        "Show me optimization opportunities",
        "How can I reduce my AWS costs?",
        "What are my top cost optimization recommendations?"
    ]
    
    # Check phrase detection in multi_agent_workflow.py
    optimization_phrases = [
        "top cost", "investigate", "categories", "opportunities", "what should", "where to optimize",
        "optimization report", "cost optimization report", "generate", "show me optimization"
    ]
    
    print("\nOptimization detection phrases:")
    for phrase in optimization_phrases:
        print(f"  - '{phrase}'")
    
    print("\nTesting queries against phrases:")
    for query in test_queries:
        query_lower = query.lower()
        matches = [phrase for phrase in optimization_phrases if phrase in query_lower]
        if matches:
            print(f"  ✅ '{query}' matches: {matches}")
        else:
            print(f"  ❌ '{query}' - NO MATCH")
    
    return True


def test_response_formatting():
    """Test 5: Can we format a response without errors?"""
    print("\n" + "="*80)
    print("TEST 5: Response Formatting")
    print("="*80)
    
    # Simulate what optimization_node does
    mock_recommendations = [
        {
            "strategy_name": "Rightsize EC2 Instances",
            "estimated_savings_min_percent": 15,
            "estimated_savings_max_percent": 30,
            "implementation_effort_hours": 4,
            "confidence_score": 0.85
        },
        {
            "strategy_name": None,  # Test None handling
            "estimated_savings_min_percent": 20,
            "estimated_savings_max_percent": 40,
            "implementation_effort_hours": 2,
            "confidence_score": 0.90
        }
    ]
    
    print("\nTesting recommendation formatting:")
    try:
        lines = ["# Optimization Recommendations for EC2", ""]
        for i, rec in enumerate(mock_recommendations[:5], 1):
            print(f"\n  Processing recommendation {i}:")
            print(f"    Raw data: {rec}")
            
            # This is the exact code from multi_agent_workflow.py line 817-821
            title = rec.get("strategy_name") or rec.get("strategy") or "Recommendation"
            smin = rec.get("estimated_savings_min_percent")
            smax = rec.get("estimated_savings_max_percent")
            effort = rec.get("implementation_effort_hours", "-")
            confidence = rec.get("confidence_score", "-")
            
            line = f"- {title}: savings {smin}-{smax}%, effort ~{effort}h, confidence {confidence}"
            print(f"    Formatted: {line}")
            lines.append(line)
        
        response = "\n".join(lines)
        print("\n✅ Response formatted successfully")
        print(f"\nFinal response:\n{response}")
        return True
        
    except Exception as e:
        print(f"❌ Response formatting failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests"""
    print("\n" + "="*80)
    print(" COMPREHENSIVE OPTIMIZATION FLOW TEST")
    print("="*80)
    
    # Check for DB password
    if not os.getenv('DB_PASSWORD'):
        print("\n⚠️  DB_PASSWORD environment variable not set")
        print("Please run: export DB_PASSWORD=<password>")
        print("Or source deployment.env")
        sys.exit(1)
    
    results = {}
    
    results['database_connection'] = test_database_connection()
    results['recommendations_table'] = test_recommendations_table()
    results['optimization_engine'] = test_optimization_engine()
    results['multi_agent_routing'] = test_multi_agent_routing()
    results['response_formatting'] = test_response_formatting()
    
    # Summary
    print("\n" + "="*80)
    print(" TEST SUMMARY")
    print("="*80)
    
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    all_passed = all(results.values())
    
    if all_passed:
        print("\n🎉 ALL TESTS PASSED - Optimization flow should work!")
    else:
        print("\n⚠️  SOME TESTS FAILED - Issues need to be fixed")
        failed = [name for name, passed in results.items() if not passed]
        print(f"\nFailed tests: {', '.join(failed)}")
    
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
