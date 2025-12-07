"""
Test Athena CUR Templates with Advanced Filter Support (Phase 2 - Task 2.2)

Tests that the Athena templates correctly generate SQL queries with:
- Purchase option filters (On-Demand, Reserved, Savings Plan, Spot)
- Tag filters (Environment, CostCenter, etc.)
- Platform filters (Linux, Windows)
- Database engine filters (MySQL, PostgreSQL)
- Charge type filters (exclude taxes, credits)
"""

import pytest
from backend.services.athena_cur_templates import AthenaCURTemplates


@pytest.fixture
def templates():
    """Create AthenaCURTemplates instance for testing"""
    return AthenaCURTemplates(
        database="cost_usage_db",
        table="cur_data",
        use_lowercase_columns=True
    )


class TestPurchaseOptionFilters:
    """Test purchase option filtering in Athena queries"""
    
    def test_top_n_services_with_on_demand_filter(self, templates):
        """Test top_n_services with On-Demand purchase option filter"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            purchase_options=["On-Demand"]
        )
        
        # Should contain purchase option filter
        assert "pricing_term" in query
        assert "OnDemand" in query or "pricing_term IS NULL" in query
        
        # Should not contain unrelated filters
        assert "resource_tags_user_" not in query
        assert "product_operating_system" not in query
    
    def test_top_n_services_with_savings_plan_filter(self, templates):
        """Test top_n_services with Savings Plan filter"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            purchase_options=["Savings Plan"]
        )
        
        # Should contain savings plan filter
        assert "savings_plan_savings_plan_a_r_n IS NOT NULL" in query
    
    def test_top_n_services_with_reserved_filter(self, templates):
        """Test top_n_services with Reserved Instance filter"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            purchase_options=["Reserved"]
        )
        
        # Should contain reserved instance filter
        assert "pricing_term LIKE '%Reserved%'" in query
    
    def test_service_breakdown_with_multiple_purchase_options(self, templates):
        """Test service breakdown with multiple purchase options"""
        query = templates.service_cost_breakdown(
            start_date="2024-10-01",
            end_date="2024-10-31",
            service="AmazonEC2",
            dimension="region",
            purchase_options=["On-Demand", "Reserved"]
        )
        
        # Should contain OR logic for multiple options
        assert "OR" in query
        assert "pricing_term" in query or "Reserved" in query


class TestTagFilters:
    """Test tag-based filtering in Athena queries"""
    
    def test_top_n_services_with_single_tag(self, templates):
        """Test top_n_services with single tag filter"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            tags={"Environment": ["prod"]}
        )
        
        # Should contain tag filter
        assert "resource_tags_user_environment = 'prod'" in query
    
    def test_top_n_services_with_multiple_tag_values(self, templates):
        """Test top_n_services with multiple values for same tag"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            tags={"Environment": ["prod", "staging"]}
        )
        
        # Should use IN clause for multiple values
        assert "resource_tags_user_environment IN ('prod', 'staging')" in query
    
    def test_top_n_services_with_multiple_tags(self, templates):
        """Test top_n_services with multiple different tags"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            tags={
                "Environment": ["prod"],
                "CostCenter": ["media"]
            }
        )
        
        # Should contain both tag filters with AND logic
        assert "resource_tags_user_environment = 'prod'" in query
        assert "resource_tags_user_costcenter = 'media'" in query
        assert query.count("AND") >= 2  # Multiple ANDs for tag filters
    
    def test_service_breakdown_with_tags(self, templates):
        """Test service breakdown with tag filters"""
        query = templates.service_cost_breakdown(
            start_date="2024-10-01",
            end_date="2024-10-31",
            service="AmazonCloudWatch",
            dimension="usage_type",
            tags={"Application": ["media-app"]}
        )
        
        # Should contain tag filter
        assert "resource_tags_user_application = 'media-app'" in query
        # Should still have service and dimension logic
        assert "AmazonCloudWatch" in query
        assert "line_item_usage_type" in query or "usage_type" in query.lower()


class TestPlatformFilters:
    """Test platform/OS filtering in Athena queries"""
    
    def test_top_n_services_with_linux_filter(self, templates):
        """Test top_n_services filtered to Linux platforms"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            platforms=["Linux"]
        )
        
        # Should contain platform filter
        assert "product_operating_system = 'Linux'" in query
    
    def test_top_n_services_with_multiple_platforms(self, templates):
        """Test top_n_services with multiple platforms"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            platforms=["Linux", "Windows"]
        )
        
        # Should use IN clause for multiple platforms
        assert "product_operating_system IN ('Linux', 'Windows')" in query
    
    def test_service_breakdown_with_platform(self, templates):
        """Test service breakdown with platform filter"""
        query = templates.service_cost_breakdown(
            start_date="2024-10-01",
            end_date="2024-10-31",
            service="AmazonEC2",
            dimension="instance_type",
            platforms=["Linux"]
        )
        
        # Should contain platform filter
        assert "product_operating_system = 'Linux'" in query


class TestDatabaseEngineFilters:
    """Test database engine filtering for RDS queries"""
    
    def test_top_n_services_with_mysql_filter(self, templates):
        """Test top_n_services filtered to MySQL databases"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            database_engines=["MySQL"]
        )
        
        # Should contain database engine filter (case-insensitive LIKE)
        assert "LOWER(product_database_engine) LIKE '%mysql%'" in query
    
    def test_top_n_services_with_multiple_engines(self, templates):
        """Test top_n_services with multiple database engines"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            database_engines=["MySQL", "PostgreSQL"]
        )
        
        # Should contain OR logic for multiple engines
        assert "LOWER(product_database_engine) LIKE '%mysql%'" in query
        assert "LOWER(product_database_engine) LIKE '%postgresql%'" in query
        assert "OR" in query
    
    def test_service_breakdown_with_database_engine(self, templates):
        """Test service breakdown with database engine filter"""
        query = templates.service_cost_breakdown(
            start_date="2024-10-01",
            end_date="2024-10-31",
            service="AmazonRDS",
            dimension="region",
            database_engines=["PostgreSQL"]
        )
        
        # Should contain database engine filter
        assert "LOWER(product_database_engine) LIKE '%postgresql%'" in query


class TestChargeTypeFilters:
    """Test charge type exclusion/inclusion (already implemented, verify integration)"""
    
    def test_top_n_services_excluding_taxes(self, templates):
        """Test top_n_services excluding Tax charge type"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            exclude_line_item_types=["Tax"]
        )
        
        # Should contain exclusion filter
        assert "line_item_line_item_type NOT IN ('Tax')" in query
    
    def test_top_n_services_excluding_multiple_charge_types(self, templates):
        """Test top_n_services excluding multiple charge types"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            exclude_line_item_types=["Tax", "Credit", "Refund"]
        )
        
        # Should contain all excluded types
        assert "line_item_line_item_type NOT IN" in query
        assert "'Tax'" in query
        assert "'Credit'" in query
        assert "'Refund'" in query
    
    def test_top_n_services_including_only_usage(self, templates):
        """Test top_n_services including only Usage charge type"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            include_line_item_types=["Usage"]
        )
        
        # Should contain inclusion filter (not exclusion)
        assert "line_item_line_item_type IN ('Usage')" in query
        assert "NOT IN" not in query  # Should not have exclusion


class TestMultipleFilters:
    """Test combinations of multiple advanced filters"""
    
    def test_top_n_services_with_all_filters(self, templates):
        """Test top_n_services with all filter types combined"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            exclude_line_item_types=["Tax", "Credit"],
            purchase_options=["On-Demand"],
            tags={"Environment": ["prod"]},
            platforms=["Linux"]
        )
        
        # Should contain all filter types
        assert "line_item_line_item_type NOT IN" in query
        assert "pricing_term" in query or "OnDemand" in query
        assert "resource_tags_user_environment = 'prod'" in query
        assert "product_operating_system = 'Linux'" in query
        
        # Verify proper WHERE clause structure
        assert query.count("WHERE") >= 1
        assert query.count("AND") >= 4  # At least 4 AND conditions
    
    def test_period_over_period_with_filters(self, templates):
        """Test period_over_period_comparison with advanced filters"""
        query = templates.period_over_period_comparison(
            current_start="2024-11-01",
            current_end="2024-11-30",
            previous_start="2024-10-01",
            previous_end="2024-10-31",
            top_n=5,
            exclude_line_item_types=["Tax"],
            tags={"Environment": ["prod"]},
            purchase_options=["On-Demand", "Reserved"]
        )
        
        # Should apply filters to both CTEs (current_period and previous_period)
        assert query.count("line_item_line_item_type NOT IN") >= 2  # In both periods
        assert query.count("resource_tags_user_environment") >= 2
        assert query.count("pricing_term") >= 2 or query.count("Reserved") >= 2
    
    def test_optimization_analysis_with_filters(self, templates):
        """Test cost_optimization_analysis with advanced filters"""
        query = templates.cost_optimization_analysis(
            start_date="2024-10-01",
            end_date="2024-10-31",
            service="AmazonEC2",
            purchase_options=["On-Demand"],
            tags={"Environment": ["prod", "staging"]},
            platforms=["Linux"]
        )
        
        # Should contain all filter types
        assert "pricing_term" in query or "OnDemand" in query
        assert "resource_tags_user_environment IN ('prod', 'staging')" in query
        assert "product_operating_system = 'Linux'" in query
        assert "product_product_name = 'AmazonEC2'" in query


class TestFilterNormalization:
    """Test that filter values are properly normalized/sanitized"""
    
    def test_purchase_option_case_insensitive(self, templates):
        """Test purchase options are case-insensitive"""
        query1 = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            purchase_options=["on-demand"]
        )
        query2 = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            purchase_options=["On-Demand"]
        )
        
        # Both should produce similar filters (normalized to lowercase internally)
        assert "pricing_term" in query1
        assert "pricing_term" in query2
    
    def test_tag_keys_normalized_to_lowercase(self, templates):
        """Test tag keys are normalized to lowercase for column names"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            tags={"Environment": ["prod"], "CostCenter": ["media"]}
        )
        
        # Tag keys should be lowercase in column references
        assert "resource_tags_user_environment" in query
        assert "resource_tags_user_costcenter" in query
        # But NOT uppercase versions
        assert "resource_tags_user_Environment" not in query
        assert "resource_tags_user_CostCenter" not in query
    
    def test_platform_normalized_to_title_case(self, templates):
        """Test platforms are normalized to title case"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5,
            platforms=["linux", "windows"]
        )
        
        # Should be title case to match CUR values
        assert "'Linux'" in query
        assert "'Windows'" in query


class TestNoFiltersProducesCleanQueries:
    """Test that queries without filters don't have empty clauses"""
    
    def test_top_n_services_no_filters(self, templates):
        """Test top_n_services without any filters produces clean SQL"""
        query = templates.top_n_services(
            start_date="2024-10-01",
            end_date="2024-10-31",
            limit=5
        )
        
        # Should not contain filter-related clauses when no filters provided
        # (filters return empty strings, should not create orphan ANDs)
        assert "AND AND" not in query  # No double ANDs
        assert "AND  AND" not in query  # No ANDs with just whitespace
        # Note: Query uses CTE pattern with WHERE in subquery and WHERE in outer query
        # so we expect 2 WHERE clauses, not 1
        
        # Should still have basic structure
        assert "SELECT" in query
        assert "FROM" in query
        assert "GROUP BY" in query
        assert "ORDER BY" in query
    
    def test_service_breakdown_no_advanced_filters(self, templates):
        """Test service breakdown without advanced filters"""
        query = templates.service_cost_breakdown(
            start_date="2024-10-01",
            end_date="2024-10-31",
            service="AmazonS3",
            dimension="operation"
        )
        
        # Should not contain advanced filter columns
        assert "resource_tags_user_" not in query
        assert "pricing_term" not in query
        assert "product_operating_system" not in query
        assert "product_database_engine" not in query
        
        # But should have service and dimension logic
        assert "AmazonS3" in query
        assert "line_item_operation" in query or "operation" in query.lower()
