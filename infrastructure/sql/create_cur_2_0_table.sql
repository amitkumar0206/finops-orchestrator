-- ============================================================================
-- AWS CUR 2.0 Athena Table (Non-Partitioned)
-- ============================================================================
-- 
-- This DDL creates an Athena table for AWS CUR 2.0 format.
-- CUR 2.0 uses date-range directories (YYYYMMDD-YYYYMMDD) instead of
-- Hive-style partitions (year=YYYY/month=MM).
--
-- TRADE-OFFS:
-- - Works immediately with CUR 2.0 data structure
-- - Higher query costs (scans all data, not just needed partitions)
-- - Slower query performance on large datasets
-- - No partition pruning benefits
--
-- STRUCTURE COMPARISON:
-- Legacy CUR: s3://bucket/prefix/year=2024/month=10/
-- CUR 2.0:    s3://bucket/prefix/20241001-20241101/
--
-- USAGE:
-- 1. Replace ${CUR_S3_BUCKET} with your bucket name
-- 2. Replace ${CUR_S3_PREFIX} with your S3 prefix
-- 3. Replace ${CUR_DATABASE} with your Athena database name
-- 4. Replace ${CUR_TABLE_NAME} with desired table name
-- 5. Execute in Athena Console or via AWS CLI
-- ============================================================================

-- Create database if not exists
CREATE DATABASE IF NOT EXISTS ${CUR_DATABASE};

-- Drop existing table if it exists
DROP TABLE IF EXISTS ${CUR_DATABASE}.${CUR_TABLE_NAME};

-- Create table without partitions (scans entire S3 prefix)
CREATE EXTERNAL TABLE ${CUR_DATABASE}.${CUR_TABLE_NAME} (
  -- Identity Columns
  identity_line_item_id STRING,
  identity_time_interval STRING,
  
  -- Bill Columns
  bill_invoice_id STRING,
  bill_invoicing_entity STRING,
  bill_billing_entity STRING,
  bill_bill_type STRING,
  bill_payer_account_id STRING,
  bill_billing_period_start_date TIMESTAMP,
  bill_billing_period_end_date TIMESTAMP,
  
  -- Line Item Columns (Core)
  line_item_usage_account_id STRING,
  line_item_line_item_type STRING,
  line_item_usage_start_date TIMESTAMP,
  line_item_usage_end_date TIMESTAMP,
  line_item_product_code STRING,
  line_item_usage_type STRING,
  line_item_operation STRING,
  line_item_availability_zone STRING,
  line_item_resource_id STRING,
  line_item_usage_amount DOUBLE,
  line_item_normalization_factor DOUBLE,
  line_item_normalized_usage_amount DOUBLE,
  line_item_currency_code STRING,
  line_item_unblended_rate STRING,
  line_item_unblended_cost DOUBLE,
  line_item_blended_rate STRING,
  line_item_blended_cost DOUBLE,
  line_item_line_item_description STRING,
  line_item_tax_type STRING,
  line_item_legal_entity STRING,
  
  -- Product Columns (Detailed)
  product_product_name STRING,
  product_availability STRING,
  product_availability_zone STRING,
  product_product_family STRING,
  product_region STRING,
  product_servicecode STRING,
  product_sku STRING,
  product_usagetype STRING,
  product_operation STRING,
  product_instance_type STRING,
  product_instance_type_family STRING,
  product_location STRING,
  product_location_type STRING,
  product_tenancy STRING,
  product_operating_system STRING,
  product_license_model STRING,
  product_marketoption STRING,
  product_database_engine STRING,
  product_database_edition STRING,
  product_deployment_option STRING,
  product_cache_engine STRING,
  product_storage STRING,
  product_transfer_type STRING,
  product_from_location STRING,
  product_from_location_type STRING,
  product_to_location STRING,
  product_to_location_type STRING,
  product_physical_processor STRING,
  product_processor_features STRING,
  product_clock_speed STRING,
  product_ecu STRING,
  product_network_performance STRING,
  product_memory STRING,
  product_vcpu STRING,
  product_enhanced_networking_supported STRING,
  product_gpu STRING,
  product_current_generation STRING,
  product_pre_installed_sw STRING,
  product_processor_architecture STRING,
  
  -- Pricing Columns
  pricing_rate_code STRING,
  pricing_rate_id STRING,
  pricing_currency STRING,
  pricing_public_on_demand_cost DOUBLE,
  pricing_public_on_demand_rate STRING,
  pricing_term STRING,
  pricing_unit STRING,
  pricing_lease_contract_length STRING,
  pricing_offering_class STRING,
  pricing_purchase_option STRING,
  
  -- Reservation Columns
  reservation_amortized_upfront_cost_for_usage DOUBLE,
  reservation_amortized_upfront_fee_for_billing_period DOUBLE,
  reservation_effective_cost DOUBLE,
  reservation_end_time STRING,
  reservation_modification_status STRING,
  reservation_normalized_units_per_reservation STRING,
  reservation_number_of_reservations STRING,
  reservation_recurring_fee_for_usage DOUBLE,
  reservation_start_time STRING,
  reservation_subscription_id STRING,
  reservation_total_reserved_normalized_units STRING,
  reservation_total_reserved_units STRING,
  reservation_units_per_reservation STRING,
  reservation_unused_amortized_upfront_fee_for_billing_period DOUBLE,
  reservation_unused_normalized_unit_quantity DOUBLE,
  reservation_unused_quantity DOUBLE,
  reservation_unused_recurring_fee DOUBLE,
  reservation_upfront_value DOUBLE,
  reservation_reservation_arn STRING,
  reservation_availability_zone STRING,
  
  -- Savings Plan Columns
  savings_plan_savings_plan_arn STRING,
  savings_plan_savings_plan_rate DOUBLE,
  savings_plan_used_commitment DOUBLE,
  savings_plan_savings_plan_effective_cost DOUBLE,
  savings_plan_amortized_upfront_commitment_for_billing_period DOUBLE,
  savings_plan_recurring_commitment_for_billing_period DOUBLE,
  savings_plan_total_commitment_to_date DOUBLE,
  savings_plan_start_time STRING,
  savings_plan_end_time STRING,
  savings_plan_offering_type STRING,
  savings_plan_payment_option STRING,
  savings_plan_purchase_term STRING,
  savings_plan_region STRING,
  
  -- Discount Columns
  discount_total_discount DOUBLE,
  discount_bundled_discount DOUBLE,
  discount_edp_discount DOUBLE,
  
  -- Resource Tags (Common - add more as needed)
  resource_tags_user_name STRING,
  resource_tags_user_environment STRING,
  resource_tags_user_application STRING,
  resource_tags_user_cost_center STRING,
  resource_tags_user_project STRING,
  resource_tags_user_team STRING,
  resource_tags_user_owner STRING,
  resource_tags_aws_created_by STRING,
  
  -- Cost Category
  cost_category STRING,
  
  -- Split Line Item Columns (Critical for ECS/EKS)
  split_line_item_split_cost DOUBLE,
  split_line_item_split_usage DOUBLE,
  split_line_item_unused_cost DOUBLE,
  split_line_item_unused_usage DOUBLE,
  split_line_item_public_on_demand_split_cost DOUBLE,
  split_line_item_reserved_usage DOUBLE,
  split_line_item_split_cost_sharing_method STRING,
  split_line_item_parent_resource_id STRING
)
STORED AS PARQUET
LOCATION 's3://${CUR_S3_BUCKET}/${CUR_S3_PREFIX}/'
TBLPROPERTIES (
  'parquet.compression' = 'SNAPPY',
  'classification' = 'parquet',
  'created_by' = 'finops-intelligence-platform',
  'description' = 'AWS CUR 2.0 format (non-partitioned for date-range directories)',
  'last_updated' = '2024-11-18'
);

-- ============================================================================
-- Verify Table Creation
-- ============================================================================

-- Show table structure
SHOW CREATE TABLE ${CUR_DATABASE}.${CUR_TABLE_NAME};

-- Count total rows (may be slow on large datasets)
SELECT COUNT(*) as total_rows
FROM ${CUR_DATABASE}.${CUR_TABLE_NAME};

-- Get cost data for last 30 days
SELECT 
  DATE_TRUNC('day', line_item_usage_start_date) as usage_date,
  line_item_product_code as service,
  SUM(line_item_unblended_cost) as total_cost
FROM ${CUR_DATABASE}.${CUR_TABLE_NAME}
WHERE line_item_usage_start_date >= CURRENT_DATE - INTERVAL '30' DAY
  AND line_item_line_item_type != 'Tax'
GROUP BY 1, 2
ORDER BY 3 DESC
LIMIT 10;

-- ============================================================================
-- IMPORTANT NOTES
-- ============================================================================

-- 1. COST WARNING:
--    This non-partitioned table scans ALL Parquet files in the S3 prefix
--    for every query. With 27+ MB of data across 3 months, each query will
--    scan ~27 MB minimum. At $5/TB, this is ~$0.00014 per query.
--
-- 2. PERFORMANCE WARNING:
--    Queries will be slower than partitioned tables because Athena cannot
--    skip irrelevant date ranges.
--
-- 3. RECOMMENDED MIGRATION PATH:
--    - Use this table as temporary solution
--    - Migrate to Legacy CUR format for production use
--    - See CUR_ISSUE_QUICK_REF.md for migration guide
--
-- 4. QUERY OPTIMIZATION:
--    Always include date filters in WHERE clause to leverage Parquet
--    row group statistics:
--    
--    WHERE line_item_usage_start_date >= DATE '2024-10-01'
--      AND line_item_usage_start_date < DATE '2024-11-01'
--
-- 5. ALTERNATIVE APPROACH:
--    If you need partitioning, you can:
--    - Use Glue Crawler to auto-discover CUR 2.0 partitions
--    - Cost: ~$0.44/month for crawler runs
--    - Benefit: Better query performance and lower costs
--
-- ============================================================================
