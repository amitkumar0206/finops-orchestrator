-- ============================================================================
-- Sample Athena Queries for CUR Data Validation and Testing
-- ============================================================================
-- 
-- These queries help validate your CUR table setup and demonstrate
-- common cost analysis patterns for the FinOps Intelligence Platform.
--
-- Replace ${DATABASE} and ${TABLE} with your actual values:
-- - DATABASE: cost_usage_db (default)
-- - TABLE: cur_data (default)
-- ============================================================================

-- ============================================================================
-- 1. VALIDATION QUERIES
-- ============================================================================

-- 1.1 Verify table exists and partitions are discovered
SHOW PARTITIONS ${DATABASE}.${TABLE};

-- Expected: List of year=YYYY/month=MM partitions

-- 1.2 Count total records by partition
SELECT 
  year,
  month,
  COUNT(*) as record_count,
  SUM(line_item_unblended_cost) as total_cost
FROM ${DATABASE}.${TABLE}
GROUP BY year, month
ORDER BY year DESC, month DESC
LIMIT 12;

-- Expected: Recent months show data with costs > 0

-- 1.3 Check current month data availability
SELECT 
  DATE_FORMAT(line_item_usage_start_date, '%Y-%m-%d') as usage_date,
  COUNT(*) as line_items,
  ROUND(SUM(line_item_unblended_cost), 2) as daily_cost
FROM ${DATABASE}.${TABLE}
WHERE year = CAST(YEAR(CURRENT_DATE) AS VARCHAR)
  AND month = CAST(MONTH(CURRENT_DATE) AS VARCHAR)
  AND line_item_line_item_type != 'Tax'
GROUP BY DATE_FORMAT(line_item_usage_start_date, '%Y-%m-%d')
ORDER BY usage_date DESC
LIMIT 7;

-- Expected: Daily cost data for current month (last 7 days)

-- 1.4 Verify split cost allocation columns exist (for ECS/EKS)
SELECT 
  COUNT(*) as records_with_split_cost,
  SUM(split_line_item_split_cost) as total_split_cost,
  SUM(split_line_item_unused_cost) as total_unused_cost
FROM ${DATABASE}.${TABLE}
WHERE year = CAST(YEAR(CURRENT_DATE) AS VARCHAR)
  AND month = CAST(MONTH(CURRENT_DATE) AS VARCHAR)
  AND split_line_item_split_cost IS NOT NULL
LIMIT 10;

-- Expected: If using ECS/EKS, should show records with split costs

-- ============================================================================
-- 2. COST ANALYSIS QUERIES
-- ============================================================================

-- 2.1 Top 10 most expensive services this month
SELECT 
  line_item_product_code as service,
  ROUND(SUM(line_item_unblended_cost), 2) as cost,
  COUNT(DISTINCT line_item_usage_account_id) as account_count,
  COUNT(DISTINCT line_item_resource_id) as resource_count
FROM ${DATABASE}.${TABLE}
WHERE year = CAST(YEAR(CURRENT_DATE) AS VARCHAR)
  AND month = CAST(MONTH(CURRENT_DATE) AS VARCHAR)
  AND line_item_line_item_type != 'Tax'
GROUP BY line_item_product_code
ORDER BY cost DESC
LIMIT 10;

-- 2.2 Daily cost trend for last 30 days
SELECT 
  DATE_FORMAT(line_item_usage_start_date, '%Y-%m-%d') as date,
  ROUND(SUM(line_item_unblended_cost), 2) as daily_cost,
  COUNT(DISTINCT line_item_product_code) as services_used
FROM ${DATABASE}.${TABLE}
WHERE line_item_usage_start_date >= DATE_ADD('day', -30, CURRENT_DATE)
  AND line_item_line_item_type != 'Tax'
GROUP BY DATE_FORMAT(line_item_usage_start_date, '%Y-%m-%d')
ORDER BY date DESC;

-- 2.3 Cost by account (multi-account analysis)
SELECT 
  line_item_usage_account_id as account_id,
  ROUND(SUM(line_item_unblended_cost), 2) as total_cost,
  COUNT(DISTINCT line_item_product_code) as services_count,
  ROUND(AVG(line_item_unblended_cost), 4) as avg_line_cost
FROM ${DATABASE}.${TABLE}
WHERE year = CAST(YEAR(CURRENT_DATE) AS VARCHAR)
  AND month = CAST(MONTH(CURRENT_DATE) AS VARCHAR)
  AND line_item_line_item_type != 'Tax'
GROUP BY line_item_usage_account_id
ORDER BY total_cost DESC;

-- 2.4 Cost by region
SELECT 
  product_region as region,
  line_item_product_code as service,
  ROUND(SUM(line_item_unblended_cost), 2) as cost
FROM ${DATABASE}.${TABLE}
WHERE year = CAST(YEAR(CURRENT_DATE) AS VARCHAR)
  AND month = CAST(MONTH(CURRENT_DATE) AS VARCHAR)
  AND line_item_line_item_type != 'Tax'
  AND product_region IS NOT NULL
  AND product_region != ''
GROUP BY product_region, line_item_product_code
ORDER BY cost DESC
LIMIT 20;

-- ============================================================================
-- 3. SAVINGS PLAN & RESERVED INSTANCE ANALYSIS
-- ============================================================================

-- 3.1 Savings Plan coverage and savings
SELECT 
  DATE_FORMAT(line_item_usage_start_date, '%Y-%m') as month,
  ROUND(SUM(CASE WHEN line_item_line_item_type = 'SavingsPlanCoveredUsage' 
                 THEN savings_plan_savings_plan_effective_cost 
                 ELSE 0 END), 2) as sp_covered_cost,
  ROUND(SUM(CASE WHEN line_item_line_item_type = 'Usage' 
                 THEN line_item_unblended_cost 
                 ELSE 0 END), 2) as on_demand_cost,
  ROUND(SUM(CASE WHEN line_item_line_item_type = 'SavingsPlanCoveredUsage' 
                 THEN savings_plan_savings_plan_effective_cost 
                 ELSE 0 END) / 
        NULLIF(SUM(line_item_unblended_cost), 0) * 100, 2) as sp_coverage_pct
FROM ${DATABASE}.${TABLE}
WHERE year = CAST(YEAR(CURRENT_DATE) AS VARCHAR)
  AND month = CAST(MONTH(CURRENT_DATE) AS VARCHAR)
  AND line_item_line_item_type IN ('SavingsPlanCoveredUsage', 'Usage')
GROUP BY DATE_FORMAT(line_item_usage_start_date, '%Y-%m');

-- 3.2 Reserved Instance utilization
SELECT 
  line_item_product_code as service,
  ROUND(SUM(reservation_effective_cost), 2) as ri_cost,
  ROUND(SUM(reservation_unused_recurring_fee), 2) as unused_ri_cost,
  ROUND((SUM(reservation_unused_recurring_fee) / NULLIF(SUM(reservation_effective_cost), 0)) * 100, 2) as waste_pct
FROM ${DATABASE}.${TABLE}
WHERE year = CAST(YEAR(CURRENT_DATE) AS VARCHAR)
  AND month = CAST(MONTH(CURRENT_DATE) AS VARCHAR)
  AND line_item_line_item_type = 'DiscountedUsage'
GROUP BY line_item_product_code
ORDER BY unused_ri_cost DESC;

-- ============================================================================
-- 4. RESOURCE-LEVEL ANALYSIS
-- ============================================================================

-- 4.1 Top 10 most expensive EC2 instances
SELECT 
  line_item_resource_id as instance_id,
  product_instance_type as instance_type,
  product_region as region,
  ROUND(SUM(line_item_unblended_cost), 2) as cost,
  ROUND(SUM(line_item_usage_amount), 2) as usage_hours
FROM ${DATABASE}.${TABLE}
WHERE year = CAST(YEAR(CURRENT_DATE) AS VARCHAR)
  AND month = CAST(MONTH(CURRENT_DATE) AS VARCHAR)
  AND line_item_product_code = 'AmazonEC2'
  AND line_item_line_item_type != 'Tax'
  AND line_item_resource_id IS NOT NULL
  AND line_item_resource_id != ''
GROUP BY line_item_resource_id, product_instance_type, product_region
ORDER BY cost DESC
LIMIT 10;

-- 4.2 S3 storage cost by bucket (requires resource tags)
SELECT 
  line_item_resource_id as bucket,
  line_item_operation as operation,
  ROUND(SUM(line_item_unblended_cost), 2) as cost,
  ROUND(SUM(line_item_usage_amount), 2) as usage_amount
FROM ${DATABASE}.${TABLE}
WHERE year = CAST(YEAR(CURRENT_DATE) AS VARCHAR)
  AND month = CAST(MONTH(CURRENT_DATE) AS VARCHAR)
  AND line_item_product_code = 'AmazonS3'
  AND line_item_line_item_type != 'Tax'
GROUP BY line_item_resource_id, line_item_operation
ORDER BY cost DESC
LIMIT 20;

-- 4.3 RDS database costs
SELECT 
  line_item_resource_id as db_instance,
  product_database_engine as engine,
  product_instance_type as instance_type,
  product_deployment_option as deployment,
  ROUND(SUM(line_item_unblended_cost), 2) as cost
FROM ${DATABASE}.${TABLE}
WHERE year = CAST(YEAR(CURRENT_DATE) AS VARCHAR)
  AND month = CAST(MONTH(CURRENT_DATE) AS VARCHAR)
  AND line_item_product_code = 'AmazonRDS'
  AND line_item_line_item_type != 'Tax'
  AND line_item_resource_id IS NOT NULL
GROUP BY line_item_resource_id, product_database_engine, product_instance_type, product_deployment_option
ORDER BY cost DESC;

-- ============================================================================
-- 5. TAG-BASED COST ALLOCATION
-- ============================================================================

-- 5.1 Cost by environment tag
SELECT 
  COALESCE(resource_tags_user_environment, 'untagged') as environment,
  line_item_product_code as service,
  ROUND(SUM(line_item_unblended_cost), 2) as cost
FROM ${DATABASE}.${TABLE}
WHERE year = CAST(YEAR(CURRENT_DATE) AS VARCHAR)
  AND month = CAST(MONTH(CURRENT_DATE) AS VARCHAR)
  AND line_item_line_item_type != 'Tax'
GROUP BY resource_tags_user_environment, line_item_product_code
ORDER BY cost DESC
LIMIT 20;

-- 5.2 Cost by project/application
SELECT 
  COALESCE(resource_tags_user_project, resource_tags_user_application, 'untagged') as project,
  ROUND(SUM(line_item_unblended_cost), 2) as cost,
  COUNT(DISTINCT line_item_resource_id) as resource_count
FROM ${DATABASE}.${TABLE}
WHERE year = CAST(YEAR(CURRENT_DATE) AS VARCHAR)
  AND month = CAST(MONTH(CURRENT_DATE) AS VARCHAR)
  AND line_item_line_item_type != 'Tax'
GROUP BY resource_tags_user_project, resource_tags_user_application
ORDER BY cost DESC;

-- 5.3 Untagged resources (cost optimization opportunity)
SELECT 
  line_item_product_code as service,
  line_item_resource_id as resource,
  ROUND(SUM(line_item_unblended_cost), 2) as cost
FROM ${DATABASE}.${TABLE}
WHERE year = CAST(YEAR(CURRENT_DATE) AS VARCHAR)
  AND month = CAST(MONTH(CURRENT_DATE) AS VARCHAR)
  AND line_item_line_item_type != 'Tax'
  AND resource_tags_user_environment IS NULL
  AND resource_tags_user_project IS NULL
  AND resource_tags_user_application IS NULL
  AND line_item_resource_id IS NOT NULL
  AND line_item_resource_id != ''
GROUP BY line_item_product_code, line_item_resource_id
ORDER BY cost DESC
LIMIT 50;

-- ============================================================================
-- 6. ECS/EKS CONTAINER COST ANALYSIS (Split Cost Allocation)
-- ============================================================================

-- 6.1 ECS task-level costs
SELECT 
  split_line_item_parent_resource_id as task_arn,
  line_item_product_code as service,
  ROUND(SUM(split_line_item_split_cost), 2) as task_cost,
  ROUND(SUM(split_line_item_unused_cost), 2) as unused_cost
FROM ${DATABASE}.${TABLE}
WHERE year = CAST(YEAR(CURRENT_DATE) AS VARCHAR)
  AND month = CAST(MONTH(CURRENT_DATE) AS VARCHAR)
  AND split_line_item_split_cost IS NOT NULL
  AND line_item_product_code = 'AmazonECS'
GROUP BY split_line_item_parent_resource_id, line_item_product_code
ORDER BY task_cost DESC
LIMIT 20;

-- 6.2 EKS pod-level costs
SELECT 
  split_line_item_parent_resource_id as pod_resource,
  ROUND(SUM(split_line_item_split_cost), 2) as pod_cost,
  ROUND(SUM(split_line_item_unused_cost), 2) as unused_cost,
  split_line_item_split_cost_sharing_method as allocation_method
FROM ${DATABASE}.${TABLE}
WHERE year = CAST(YEAR(CURRENT_DATE) AS VARCHAR)
  AND month = CAST(MONTH(CURRENT_DATE) AS VARCHAR)
  AND split_line_item_split_cost IS NOT NULL
  AND line_item_product_code = 'AmazonEKS'
GROUP BY split_line_item_parent_resource_id, split_line_item_split_cost_sharing_method
ORDER BY pod_cost DESC
LIMIT 20;

-- ============================================================================
-- 7. PERFORMANCE TESTING QUERIES
-- ============================================================================

-- 7.1 Small partition-pruned query (should be fast)
SELECT COUNT(*) as record_count
FROM ${DATABASE}.${TABLE}
WHERE year = '2024' 
  AND month = '11'
LIMIT 1;

-- Expected: < 5 seconds

-- 7.2 Multi-month aggregate (tests partition projection)
SELECT 
  year,
  month,
  ROUND(SUM(line_item_unblended_cost), 2) as monthly_cost
FROM ${DATABASE}.${TABLE}
WHERE year = '2024'
  AND month IN ('09', '10', '11')
  AND line_item_line_item_type != 'Tax'
GROUP BY year, month
ORDER BY year, month;

-- Expected: < 15 seconds

-- 7.3 Year-to-date summary
SELECT 
  line_item_product_code as service,
  ROUND(SUM(line_item_unblended_cost), 2) as ytd_cost,
  COUNT(*) as line_items
FROM ${DATABASE}.${TABLE}
WHERE year = CAST(YEAR(CURRENT_DATE) AS VARCHAR)
  AND line_item_line_item_type != 'Tax'
GROUP BY line_item_product_code
ORDER BY ytd_cost DESC
LIMIT 10;

-- Expected: < 30 seconds (depends on year-to-date data volume)

-- ============================================================================
-- 8. DATA QUALITY CHECKS
-- ============================================================================

-- 8.1 Check for null costs
SELECT 
  COUNT(*) as null_cost_records,
  line_item_line_item_type as line_type
FROM ${DATABASE}.${TABLE}
WHERE year = CAST(YEAR(CURRENT_DATE) AS VARCHAR)
  AND month = CAST(MONTH(CURRENT_DATE) AS VARCHAR)
  AND line_item_unblended_cost IS NULL
GROUP BY line_item_line_item_type;

-- Expected: Minimal or zero null costs

-- 8.2 Check for negative costs (credits/refunds)
SELECT 
  line_item_line_item_type as line_type,
  COUNT(*) as negative_records,
  ROUND(SUM(line_item_unblended_cost), 2) as total_credits
FROM ${DATABASE}.${TABLE}
WHERE year = CAST(YEAR(CURRENT_DATE) AS VARCHAR)
  AND month = CAST(MONTH(CURRENT_DATE) AS VARCHAR)
  AND line_item_unblended_cost < 0
GROUP BY line_item_line_item_type
ORDER BY total_credits;

-- Expected: Credits, EdpDiscount, etc. line types

-- 8.3 Check data freshness
SELECT 
  MAX(line_item_usage_start_date) as latest_usage_date,
  DATE_DIFF('day', MAX(line_item_usage_start_date), CURRENT_DATE) as days_behind
FROM ${DATABASE}.${TABLE}
WHERE year = CAST(YEAR(CURRENT_DATE) AS VARCHAR)
  AND month = CAST(MONTH(CURRENT_DATE) AS VARCHAR);

-- Expected: latest_usage_date within 1-2 days of current date

-- ============================================================================
-- NOTES
-- ============================================================================
--
-- Query Optimization Tips:
-- 1. Always filter by year/month partitions (reduces data scanned by 97%)
-- 2. Exclude 'Tax' line items for cost analysis
-- 3. Use ROUND() for currency values (avoid floating point display issues)
-- 4. Filter for non-null/non-empty resource IDs when analyzing specific resources
-- 5. Use LIMIT when exploring data to avoid large result sets
--
-- Cost Calculation Best Practices:
-- - Use line_item_unblended_cost for standard cost analysis
-- - Use reservation_effective_cost for RI-covered usage
-- - Use savings_plan_savings_plan_effective_cost for SP-covered usage
-- - Consider split_line_item_split_cost for ECS/EKS container-level costs
--
-- ============================================================================
