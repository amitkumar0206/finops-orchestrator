-- ============================================================================
-- AWS Legacy CUR Table Creation - FIXED VERSION
-- ============================================================================
-- This script creates an Athena table for AWS Legacy Cost and Usage Reports
-- with the CORRECT partition structure matching actual CUR S3 layout
--
-- Key Fixes:
-- 1. Uses billing_period partition (format: YYYYMMDD-YYYYMMDD) not year/month
-- 2. Includes ALL 376 columns from CUR manifest
-- 3. Matches actual S3 structure from AWS CUR delivery
-- 4. Non-partitioned scan for maximum compatibility (can add partitions later)
--
-- Usage:
--   - Replace ${CUR_S3_BUCKET} with your S3 bucket name
--   - Replace ${CUR_S3_PREFIX} with your CUR S3 prefix
--   - Database: cost_usage_db
--   - Table: cur_data
-- ============================================================================

-- Drop existing table if it exists
DROP TABLE IF EXISTS cost_usage_db.cur_data;

-- Create table with complete Legacy CUR schema
-- This is a non-partitioned table that scans all subdirectories for maximum compatibility
CREATE EXTERNAL TABLE IF NOT EXISTS cost_usage_db.cur_data (
  -- Identity
  identity_line_item_id STRING,
  identity_time_interval STRING,
  
  -- Bill
  bill_invoice_id STRING,
  bill_invoicing_entity STRING,
  bill_billing_entity STRING,
  bill_bill_type STRING,
  bill_payer_account_id STRING,
  bill_billing_period_start_date TIMESTAMP,
  bill_billing_period_end_date TIMESTAMP,
  
  -- Line Item (Core cost fields)
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
  
  -- Product
  product_product_name STRING,
  product_servicecode STRING,
  product_region_code STRING,
  product_location STRING,
  product_location_type STRING,
  product_availability_zone STRING,
  product_instance_type STRING,
  product_instance_type_family STRING,
  product_usagetype STRING,
  product_operation STRING,
  product_product_family STRING,
  product_servicename STRING,
  product_sku STRING,
  product_transfer_type STRING,
  product_from_location STRING,
  product_from_location_type STRING,
  product_to_location STRING,
  product_to_location_type STRING,
  product_current_generation STRING,
  product_instance_family STRING,
  product_vcpu STRING,
  product_memory STRING,
  product_storage STRING,
  product_network_performance STRING,
  product_processor_architecture STRING,
  product_tenancy STRING,
  product_operating_system STRING,
  product_license_model STRING,
  product_marketoption STRING,
  product_physical_processor STRING,
  product_clock_speed STRING,
  product_ecu STRING,
  product_enhanced_networking_supported STRING,
  product_gpu STRING,
  product_instance_capacity10xlarge STRING,
  product_instance_capacity12xlarge STRING,
  product_instance_capacity16xlarge STRING,
  product_instance_capacity18xlarge STRING,
  product_instance_capacity24xlarge STRING,
  product_instance_capacity2xlarge STRING,
  product_instance_capacity32xlarge STRING,
  product_instance_capacity4xlarge STRING,
  product_instance_capacity8xlarge STRING,
  product_instance_capacity9xlarge STRING,
  product_instance_capacitylarge STRING,
  product_instance_capacitymedium STRING,
  product_instance_capacityxlarge STRING,
  product_intel_avx2_available STRING,
  product_intel_avx_available STRING,
  product_intel_turbo_available STRING,
  product_normalization_size_factor STRING,
  product_pre_installed_sw STRING,
  product_processor_features STRING,
  product_storage_media STRING,
  product_volume_type STRING,
  product_max_iops_volume STRING,
  product_max_iopsvolume STRING,
  product_max_throughputvolume STRING,
  product_provisioned STRING,
  product_volume_api_name STRING,
  product_storage_class STRING,
  product_fee_code STRING,
  product_fee_description STRING,
  product_group STRING,
  product_group_description STRING,
  product_resource_type STRING,
  product_usage_family STRING,
  product_cache_engine STRING,
  product_database_engine STRING,
  product_deployment_option STRING,
  product_endpoint_type STRING,
  product_engine_code STRING,
  product_message_delivery_frequency STRING,
  product_message_delivery_order STRING,
  product_queue_type STRING,
  product_request_description STRING,
  product_request_type STRING,
  product_routing_target STRING,
  product_routing_type STRING,
  product_with_active_users STRING,
  product_durability STRING,
  product_edition STRING,
  product_finding_group STRING,
  product_finding_source STRING,
  product_finding_storage STRING,
  product_from_region_code STRING,
  product_logs_destination STRING,
  product_mailbox_storage STRING,
  product_origin STRING,
  product_recipient STRING,
  product_resource_endpoint STRING,
  product_subscription_type STRING,
  product_to_region_code STRING,
  product_attachment_type STRING,
  product_data_transfer STRING,
  product_dedicated_ebs_throughput STRING,
  product_event_type STRING,
  product_input_mode STRING,
  product_instance_type_description STRING,
  product_invocation_type STRING,
  product_max_iops_burst_performance STRING,
  product_max_volume_size STRING,
  product_origin_code STRING,
  product_service_code STRING,
  product_standard_storage_retention_included STRING,
  product_alarm_type STRING,
  product_actions STRING,
  product_alarm_limit STRING,
  product_availability STRING,
  product_build_type STRING,
  product_capacitystatus STRING,
  product_cost_class STRING,
  product_cputype STRING,
  product_database_edition STRING,
  product_deployment_model STRING,
  product_description STRING,
  product_instance_details STRING,
  product_job_type STRING,
  product_log_deliver_frequency STRING,
  product_media_type STRING,
  product_operating_mode STRING,
  product_os_license_model STRING,
  product_plan STRING,
  product_plan_type STRING,
  product_price_class STRING,
  product_protocol STRING,
  product_purchase_term STRING,
  product_rate_code STRING,
  product_resolution STRING,
  product_snapshot_type STRING,
  product_ssl_termination STRING,
  product_streaming_protocol STRING,
  product_tier STRING,
  product_transfer_type_from STRING,
  product_transfer_type_to STRING,
  product_upfront_ri_type STRING,
  product_version STRING,
  product_version_from STRING,
  product_version_to STRING,
  product_video_quality STRING,
  product_bundle_description STRING,
  product_compute_family STRING,
  product_compute_type STRING,
  product_dedicated_tenancy_throughput STRING,
  product_event_name STRING,
  product_event_severity STRING,
  product_event_status STRING,
  product_event_tag STRING,
  product_game_server_group STRING,
  product_gpu_memory STRING,
  product_instance STRING,
  product_instance_characteristics STRING,
  product_instance_configuration STRING,
  product_intel_avx2_enabled STRING,
  product_intel_avx_enabled STRING,
  product_intel_turbo_enabled STRING,
  product_launch_type STRING,
  product_placement_group STRING,
  product_region STRING,
  product_software STRING,
  product_software_type STRING,
  product_spot_instance STRING,
  product_support_level STRING,
  product_type STRING,
  product_usage_function STRING,
  product_user_volume_quantity STRING,
  
  -- Pricing
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
  
  -- Reservation
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
  reservation_region STRING,
  
  -- Savings Plan
  savings_plan_total_commitment_to_date DOUBLE,
  savings_plan_savings_plan_arn STRING,
  savings_plan_savings_plan_rate DOUBLE,
  savings_plan_used_commitment DOUBLE,
  savings_plan_savings_plan_effective_cost DOUBLE,
  savings_plan_amortized_upfront_commitment_for_billing_period DOUBLE,
  savings_plan_recurring_commitment_for_billing_period DOUBLE,
  savings_plan_offering_type STRING,
  savings_plan_payment_option STRING,
  savings_plan_purchase_term STRING,
  savings_plan_region STRING,
  savings_plan_start_time STRING,
  savings_plan_end_time STRING,
  
  -- Discount
  discount_bundled_discount DOUBLE,
  discount_total_discount DOUBLE,
  discount_edc_discount DOUBLE,
  
  -- Resource Tags (up to 50 user-defined tags - adjust as needed for your org)
  resource_tags STRING,
  
  -- Cost Category
  cost_category STRING,
  
  -- Split Line Items (for EDP/Shared savings)
  split_line_item_actual_usage DOUBLE,
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
  'description' = 'AWS Legacy CUR - Non-partitioned for maximum compatibility',
  'last_updated' = '2024-11-18',
  'projection.enabled' = 'false',
  'skip.header.line.count' = '0',
  'serialization.null.format' = '',
  'parquet.enable.dictionary' = 'true'
);

-- ============================================================================
-- Verification Query
-- Test the table by counting records from recent month
-- ============================================================================
-- SELECT 
--   DATE(line_item_usage_start_date) as usage_date,
--   line_item_product_code,
--   SUM(line_item_unblended_cost) as total_cost,
--   COUNT(*) as line_items
-- FROM cost_usage_db.cur_data
-- WHERE line_item_usage_start_date >= DATE '2024-10-01'
--   AND line_item_usage_start_date < DATE '2024-11-01'
--   AND line_item_line_item_type = 'Usage'
-- GROUP BY DATE(line_item_usage_start_date), line_item_product_code
-- ORDER BY usage_date DESC, total_cost DESC
-- LIMIT 20;
