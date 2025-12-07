-- ============================================================================
-- AWS Legacy CUR Athena Table with Partition Projection
-- ============================================================================
-- 
-- This DDL creates an Athena table for AWS Legacy Cost and Usage Report (CUR)
-- with automatic partition discovery using Partition Projection.
--
-- BENEFITS:
-- - No Glue Crawler required (saves ~$0.44/month)
-- - Automatic partition discovery for historical and future months
-- - Optimized query performance with partition pruning
-- - Works with 36-month backfilled data
--
-- PREREQUISITES:
-- - AWS Legacy CUR configured with hourly granularity
-- - Parquet format with split cost allocation enabled
-- - S3 path structure: s3://bucket/prefix/report-name/year=YYYY/month=MM/
--
-- USAGE:
-- 1. Replace ${CUR_S3_BUCKET} and ${CUR_S3_PREFIX} with your values
-- 2. Replace ${CUR_DATABASE} with your Athena database name
-- 3. Replace ${CUR_TABLE_NAME} with desired table name
-- 4. Execute in Athena Console or via AWS CLI
-- ============================================================================

-- Create database if not exists
CREATE DATABASE IF NOT EXISTS ${CUR_DATABASE};

-- Drop table if exists (for clean recreation)
-- DROP TABLE IF EXISTS ${CUR_DATABASE}.${CUR_TABLE_NAME};

-- Create table with partition projection
CREATE EXTERNAL TABLE IF NOT EXISTS ${CUR_DATABASE}.${CUR_TABLE_NAME} (
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
PARTITIONED BY (
  year STRING,
  month STRING
)
STORED AS PARQUET
LOCATION 's3://${CUR_S3_BUCKET}/${CUR_S3_PREFIX}/'
TBLPROPERTIES (
  'projection.enabled' = 'true',
  
  -- Year Partition Projection
  'projection.year.type' = 'integer',
  'projection.year.range' = '2021,2030',  -- Covers 36 months back from 2024 + future
  'projection.year.digits' = '4',
  
  -- Month Partition Projection  
  'projection.month.type' = 'integer',
  'projection.month.range' = '1,12',
  'projection.month.digits' = '2',
  
  -- Storage Location Template (matches AWS CUR S3 structure)
  'storage.location.template' = 's3://${CUR_S3_BUCKET}/${CUR_S3_PREFIX}/year=${year}/month=${month}',
  
  -- Performance Optimizations
  'parquet.compression' = 'SNAPPY',
  'classification' = 'parquet',
  
  -- Metadata
  'created_by' = 'finops-intelligence-platform',
  'description' = 'AWS Legacy CUR with automatic partition projection',
  'last_updated' = '2024-11-11'
);

-- ============================================================================
-- Verify Table Creation
-- ============================================================================

-- Show table properties (verify partition projection is enabled)
SHOW TBLPROPERTIES ${CUR_DATABASE}.${CUR_TABLE_NAME};

-- Show partitions (should automatically discover all year/month combinations)
SHOW PARTITIONS ${CUR_DATABASE}.${CUR_TABLE_NAME};

-- ============================================================================
-- Sample Validation Query
-- ============================================================================

-- Test query to verify data accessibility and cost calculation
SELECT 
  line_item_usage_account_id AS account_id,
  line_item_product_code AS service,
  DATE_FORMAT(line_item_usage_start_date, '%Y-%m') AS month,
  SUM(line_item_unblended_cost) AS total_cost,
  COUNT(*) AS line_items
FROM ${CUR_DATABASE}.${CUR_TABLE_NAME}
WHERE year = '2024' 
  AND month = '11'
  AND line_item_line_item_type != 'Tax'
GROUP BY 
  line_item_usage_account_id,
  line_item_product_code,
  DATE_FORMAT(line_item_usage_start_date, '%Y-%m')
ORDER BY total_cost DESC
LIMIT 10;

-- ============================================================================
-- Query Optimization Tips
-- ============================================================================
--
-- 1. ALWAYS filter by year and month partitions:
--    WHERE year = '2024' AND month = '11'
--
-- 2. Exclude tax line items for cost analysis:
--    WHERE line_item_line_item_type != 'Tax'
--
-- 3. Use effective cost for accurate calculations:
--    CASE 
--      WHEN line_item_line_item_type = 'SavingsPlanCoveredUsage' 
--        THEN savings_plan_savings_plan_effective_cost
--      WHEN line_item_line_item_type = 'DiscountedUsage'
--        THEN reservation_effective_cost
--      ELSE line_item_unblended_cost
--    END AS effective_cost
--
-- 4. Select only required columns (avoid SELECT *):
--    SELECT line_item_product_code, SUM(line_item_unblended_cost)
--
-- 5. Use date range filters efficiently:
--    WHERE year = '2024' 
--      AND month >= '10' 
--      AND month <= '12'
--      AND line_item_usage_start_date >= DATE('2024-10-01')
--      AND line_item_usage_start_date < DATE('2025-01-01')
--
-- ============================================================================
-- Cost Implications
-- ============================================================================
--
-- Athena charges $5 per TB of data scanned. Partition projection helps:
--
-- Without partition filtering:
-- - Query scans ALL 36 months: ~100 GB = $0.50 per query
--
-- With partition filtering (year='2024' AND month='11'):
-- - Query scans only 1 month: ~3 GB = $0.015 per query
--
-- SAVINGS: 97% reduction in query costs!
--
-- ============================================================================
-- Maintenance Notes
-- ============================================================================
--
-- Partition projection requires NO MAINTENANCE:
-- - No need to run MSCK REPAIR TABLE
-- - No Glue Crawler required
-- - Automatic discovery of new months as AWS creates them
-- - Works with historical backfill data automatically
--
-- To update table schema (add columns):
-- 1. Drop table: DROP TABLE ${CUR_DATABASE}.${CUR_TABLE_NAME};
-- 2. Re-run this DDL with updated columns
-- 3. No data loss (table is EXTERNAL)
--
-- ============================================================================
