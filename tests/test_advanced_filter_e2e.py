"""
End-to-End Integration Tests for Advanced Filter Support (Phase 2 - Task 2.4)

Tests SQL generation flow with advanced filters through the Athena templates.
Validates that all filter types are properly integrated into SQL queries.
"""

import pytest
from backend.services.athena_cur_templates import AthenaCURTemplates


@pytest.fixture
def templates():
    """Create Athena Templates instance"""
    return AthenaCURTemplates(
        database="cost_usage_db",
        table="cur_data",
        use_lowercase_columns=True
    )


class TestChargeTypeExclusionsE2E:
    """Test end-to-end SQL generation for charge type exclusions"""
    
    def test_exclude_taxes_sql(self, templates):
        """Test: Show costs excluding taxes - SQL generation"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            exclude_line_item_types=["Tax"]
        )
        
        # Verify SQL contains exclusion clause
        assert "line_item_line_item_type NOT IN ('Tax')" in query
        assert "SELECT" in query
        assert "GROUP BY" in query
    
    def test_exclude_taxes_and_credits_sql(self, templates):
        """Test: Show costs excluding taxes and credits - SQL generation"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            exclude_line_item_types=["Tax", "Credit"]
        )
        
        # Verify SQL contains both exclusions
        assert "line_item_line_item_type NOT IN ('Tax', 'Credit')" in query
    
    def test_include_only_usage_sql(self, templates):
        """Test: Include only Usage charge type - SQL generation"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            include_line_item_types=["Usage"]
        )
        
        # Verify SQL contains inclusion clause
        assert "line_item_line_item_type IN ('Usage')" in query


class TestPurchaseOptionFilteringE2E:
    """Test end-to-end SQL generation for purchase option filtering"""
    
    def test_on_demand_filter_sql(self, templates):
        """Test: On-demand instances only - SQL generation"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            purchase_options=["On-Demand"]
        )
        
        # Verify SQL contains purchase option filter
        assert "pricing_term" in query
        assert ("OnDemand" in query or "pricing_term IS NULL" in query)
    
    def test_reserved_instance_filter_sql(self, templates):
        """Test: Reserved instances only - SQL generation"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            purchase_options=["Reserved"]
        )
        
        # Verify SQL contains reserved instance filter
        assert "pricing_term LIKE '%Reserved%'" in query
    
    def test_savings_plan_filter_sql(self, templates):
        """Test: Savings Plans only - SQL generation"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            purchase_options=["Savings Plan"]
        )
        
        # Verify SQL contains savings plan filter
        assert "savings_plan_savings_plan_a_r_n IS NOT NULL" in query
    
    def test_multiple_purchase_options_sql(self, templates):
        """Test: Multiple purchase options - SQL generation"""
        query = templates.service_cost_breakdown(
            start_date="2024-10-01",
            end_date="2024-10-31",
            service="AmazonEC2",
            dimension="region",
            purchase_options=["On-Demand", "Reserved"]
        )
        
        # Verify SQL contains OR logic for multiple options
        assert "OR" in query
        assert "pricing_term" in query


class TestTagFilteringE2E:
    """Test end-to-end SQL generation for tag-based filtering"""
    
    def test_single_tag_sql(self, templates):
        """Test: Single tag filter - SQL generation"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            tags={"Environment": ["prod"]}
        )
        
        # Verify SQL contains tag filter
        assert "resource_tags_user_environment = 'prod'" in query
    
    def test_multiple_tag_values_sql(self, templates):
        """Test: Multiple values for same tag - SQL generation"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            tags={"Environment": ["prod", "staging"]}
        )
        
        # Verify SQL uses IN clause
        assert "resource_tags_user_environment IN ('prod', 'staging')" in query
    
    def test_multiple_tags_sql(self, templates):
        """Test: Multiple different tags - SQL generation"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            tags={"Environment": ["prod"], "CostCenter": ["media"]}
        )
        
        # Verify SQL contains both tag filters with AND logic
        assert "resource_tags_user_environment = 'prod'" in query
        assert "resource_tags_user_costcenter = 'media'" in query
        assert query.count("AND") >= 2


class TestPlatformFilteringE2E:
    """Test end-to-end SQL generation for platform filtering"""
    
    def test_linux_platform_sql(self, templates):
        """Test: Linux platform filter - SQL generation"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            platforms=["Linux"]
        )
        
        # Verify SQL contains platform filter
        assert "product_operating_system = 'Linux'" in query
    
    def test_windows_platform_sql(self, templates):
        """Test: Windows platform filter - SQL generation"""
        query = templates.service_cost_breakdown(
            start_date="2024-10-01",
            end_date="2024-10-31",
            service="AmazonEC2",
            dimension="region",
            platforms=["Windows"]
        )
        
        # Verify SQL contains platform filter
        assert "product_operating_system = 'Windows'" in query
    
    def test_multiple_platforms_sql(self, templates):
        """Test: Multiple platforms - SQL generation"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            platforms=["Linux", "Windows"]
        )
        
        # Verify SQL uses IN clause
        assert "product_operating_system IN ('Linux', 'Windows')" in query


class TestDatabaseEngineFilteringE2E:
    """Test end-to-end SQL generation for database engine filtering"""
    
    def test_mysql_engine_sql(self, templates):
        """Test: MySQL database engine filter - SQL generation"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            database_engines=["MySQL"]
        )
        
        # Verify SQL contains database engine filter
        assert "LOWER(product_database_engine) LIKE '%mysql%'" in query
    
    def test_postgresql_engine_sql(self, templates):
        """Test: PostgreSQL database engine filter - SQL generation"""
        query = templates.service_cost_breakdown(
            start_date="2024-10-01",
            end_date="2024-10-31",
            service="AmazonRDS",
            dimension="region",
            database_engines=["PostgreSQL"]
        )
        
        # Verify SQL contains database engine filter
        assert "LOWER(product_database_engine) LIKE '%postgresql%'" in query
    
    def test_multiple_engines_sql(self, templates):
        """Test: Multiple database engines - SQL generation"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            database_engines=["MySQL", "PostgreSQL"]
        )
        
        # Verify SQL contains OR logic
        assert "LOWER(product_database_engine) LIKE '%mysql%'" in query
        assert "LOWER(product_database_engine) LIKE '%postgresql%'" in query
        assert "OR" in query


class TestMultiFilterCombinationsE2E:
    """Test end-to-end SQL generation with multiple filters combined"""
    
    def test_all_filters_combined_sql(self, templates):
        """Test: All filter types combined - SQL generation"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            exclude_line_item_types=["Tax", "Credit"],
            purchase_options=["On-Demand"],
            tags={"Environment": ["prod"]},
            platforms=["Linux"]
        )
        
        # Verify SQL contains all filter types
        assert "line_item_line_item_type NOT IN" in query
        assert "pricing_term" in query or "OnDemand" in query
        assert "resource_tags_user_environment = 'prod'" in query
        assert "product_operating_system = 'Linux'" in query
        
        # Verify proper AND chaining
        assert query.count("AND") >= 4
    
    def test_period_comparison_with_filters_sql(self, templates):
        """Test: Period-over-period comparison with filters - SQL generation"""
        query = templates.period_over_period_comparison(
            current_start="2024-11-01",
            current_end="2024-11-30",
            previous_start="2024-10-01",
            previous_end="2024-10-31",
            top_n=5,
            exclude_line_item_types=["Tax"],
            tags={"Environment": ["prod"]},
            purchase_options=["On-Demand"]
        )
        
        # Verify filters appear in BOTH CTEs
        assert query.count("line_item_line_item_type NOT IN") >= 2
        assert query.count("resource_tags_user_environment") >= 2
    
    def test_optimization_with_filters_sql(self, templates):
        """Test: Optimization analysis with filters - SQL generation"""
        query = templates.cost_optimization_analysis(
            start_date="2024-10-01",
            end_date="2024-10-31",
            service="AmazonEC2",
            purchase_options=["On-Demand"],
            tags={"Environment": ["prod"]},
            platforms=["Linux"]
        )
        
        # Verify filters in optimization query
        assert "pricing_term" in query or "OnDemand" in query
        assert "resource_tags_user_environment = 'prod'" in query
        assert "product_operating_system = 'Linux'" in query
    
    def test_service_breakdown_with_multiple_filters_sql(self, templates):
        """Test: Service breakdown with multiple filters - SQL generation"""
        query = templates.service_cost_breakdown(
            start_date="2024-10-01",
            end_date="2024-10-31",
            service="AmazonEC2",
            dimension="region",
            include_line_item_types=["Usage"],
            purchase_options=["Reserved"],
            tags={"Environment": ["prod"], "CostCenter": ["media"]},
            platforms=["Linux"]
        )
        
        # Verify all filters present
        assert "line_item_line_item_type IN ('Usage')" in query
        assert "pricing_term LIKE '%Reserved%'" in query
        assert "resource_tags_user_environment = 'prod'" in query
        assert "resource_tags_user_costcenter = 'media'" in query
        assert "product_operating_system = 'Linux'" in query


class TestEdgeCasesE2E:
    """Test edge cases in SQL generation"""
    
    def test_empty_filters_produce_clean_sql(self, templates):
        """Test: No filters provided produces clean SQL"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5
        )
        
        # Should not have orphan ANDs
        assert "AND AND" not in query
        assert "AND  AND" not in query
    
    def test_none_filter_values_handled(self, templates):
        """Test: None values for filters handled gracefully"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            purchase_options=None,
            tags=None,
            platforms=None,
            database_engines=None
        )
        
        # Should produce valid SQL
        assert "SELECT" in query
        assert "FROM" in query
    
    def test_empty_list_filters_handled(self, templates):
        """Test: Empty lists for filters handled gracefully"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            purchase_options=[],
            tags={},
            platforms=[],
            database_engines=[]
        )
        
        # Should not contain filter clauses
        assert "pricing_term" not in query
        assert "resource_tags_user_" not in query


class TestSQLValidationE2E:
    """Test generated SQL is valid and safe"""
    
    def test_date_format_in_sql(self, templates):
        """Test: Dates are properly formatted in SQL"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5
        )
        
        # Should have proper DATE casting
        assert "DATE '2024-10-01'" in query
        assert "DATE '2024-10-31'" in query
    
    def test_sql_structure_validity(self, templates):
        """Test: Generated SQL has valid structure"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            exclude_line_item_types=["Tax"],
            tags={"Environment": ["prod"]}
        )
        
        # Should have proper SQL structure
        assert query.count("SELECT") >= 2  # CTE + outer SELECT
        assert "WITH service_costs AS" in query
        assert "FROM cost_usage_db.cur_data" in query
        assert "GROUP BY 1" in query
        assert "ORDER BY cost DESC" in query
        assert "LIMIT 5" in query
    
    def test_filter_values_properly_quoted(self, templates):
        """Test: Filter values are properly quoted in SQL"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            tags={"Environment": ["prod"], "Application": ["app-1"]}
        )
        
        # All tag values should be single-quoted
        assert "'prod'" in query
        assert "'app-1'" in query


class TestIntegrationScenarios:
    """Test realistic integration scenarios"""
    
    def test_scenario_1_exclude_taxes_and_credits(self, templates):
        """Scenario: Show top 5 services excluding taxes and credits"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            exclude_line_item_types=["Tax", "Credit"]
        )
        
        assert "line_item_line_item_type NOT IN ('Tax', 'Credit')" in query
        assert "LIMIT 5" in query
    
    def test_scenario_2_prod_environment_only(self, templates):
        """Scenario: Show costs for production environment only"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=10,
            tags={"Environment": ["prod"]}
        )
        
        assert "resource_tags_user_environment = 'prod'" in query
    
    def test_scenario_3_compare_on_demand_vs_reserved(self, templates):
        """Scenario: Compare current period with previous period for on-demand instances"""
        query = templates.period_over_period_comparison(
            current_start="2024-11-01",
            current_end="2024-11-30",
            previous_start="2024-10-01",
            previous_end="2024-10-31",
            top_n=5,
            purchase_options=["On-Demand"]
        )
        
        # Filter should appear in both periods
        assert query.count("pricing_term") >= 2 or query.count("OnDemand") >= 2
    
    def test_scenario_4_linux_ec2_by_region(self, templates):
        """Scenario: Linux EC2 costs by region"""
        query = templates.service_cost_breakdown(
            start_date="2024-10-01",
            end_date="2024-10-31",
            service="AmazonEC2",
            dimension="region",
            platforms=["Linux"]
        )
        
        assert "product_operating_system = 'Linux'" in query
        assert "AmazonEC2" in query
    
    def test_scenario_5_prod_linux_on_demand_with_usage_only(self, templates):
        """Scenario: Production Linux EC2 on-demand usage costs (excluding fees/discounts)"""
        query = templates.service_cost_breakdown(
            start_date="2024-10-01",
            end_date="2024-10-31",
            service="AmazonEC2",
            dimension="usage_type",
            include_line_item_types=["Usage"],  # Only usage, exclude fees/discounts
            purchase_options=["On-Demand"],
            tags={"Environment": ["prod"]},
            platforms=["Linux"]
        )
        
        # All filters should be present
        assert "line_item_line_item_type IN ('Usage')" in query
        assert ("pricing_term" in query or "OnDemand" in query)
        assert "resource_tags_user_environment = 'prod'" in query
        assert "product_operating_system = 'Linux'" in query



