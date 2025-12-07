-- Seed Optimization Recommendations Table (Fixed for actual schema)
-- This script populates the optimization_recommendations table with initial recommendations

-- Clear existing recommendations (if any)
TRUNCATE TABLE optimization_recommendations CASCADE;

-- Seed recommendations matching the actual schema
INSERT INTO optimization_recommendations (
    service, strategy_id, strategy_name, description,
    estimated_savings_min_percent, estimated_savings_max_percent,
    implementation_effort_hours, implementation_difficulty,
    confidence_score, recommendation_steps,
    prerequisites, risks, status, created_at, updated_at
) VALUES
('CloudWatch', 'cloudwatch_log_filtering', 'Enable CloudWatch Log Filtering',
 'Reduce CloudWatch Logs costs by filtering out non-essential log events before ingestion',
 30.0, 50.0, 4, 'low', 0.95,
 '["Identify high-volume log groups", "Analyze log patterns to find unnecessary entries", "Create subscription filters to drop verbose logs", "Monitor log volume reduction", "Validate application functionality"]'::jsonb,
 '["Access to CloudWatch Logs", "Understanding of application logging"]'::jsonb,
 '["Potential loss of debug information", "Need to adjust filters over time"]'::jsonb,
 'pending', NOW(), NOW()),

('CloudWatch', 'cloudwatch_retention_reduction', 'Reduce Log Retention Period',
 'Decrease log retention from indefinite to 30-90 days based on compliance needs',
 20.0, 70.0, 2, 'low', 0.98,
 '["Review compliance and audit requirements", "Identify log groups with indefinite retention", "Set retention to 30, 60, or 90 days", "Export old logs to S3 if needed", "Monitor cost reduction"]'::jsonb,
 '["Understanding of compliance requirements"]'::jsonb,
 '["Loss of historical logs", "Compliance violations if not carefully planned"]'::jsonb,
 'pending', NOW(), NOW()),

('CloudWatch', 'cloudwatch_metrics_optimization', 'Optimize Custom Metrics Usage',
 'Reduce custom metrics costs by consolidating metrics and using metric math',
 15.0, 35.0, 6, 'medium', 0.88,
 '["Audit all custom metrics", "Identify redundant or unused metrics", "Use metric math to derive metrics instead of storing them", "Consolidate similar metrics", "Increase metric collection intervals where appropriate"]'::jsonb,
 '["Inventory of all custom metrics", "Understanding of metric dependencies"]'::jsonb,
 '["Loss of granularity", "Potential gaps in monitoring"]'::jsonb,
 'pending', NOW(), NOW()),

-- EC2 Recommendations
('EC2', 'ec2_rightsizing', 'Rightsize Overprovisioned Instances',
 'Analyze CPU and memory metrics to identify underutilized EC2 instances and downsize them',
 15.0, 40.0, 8, 'medium', 0.85,
 '["Enable CloudWatch detailed monitoring", "Analyze CPU, memory, network, and disk metrics over 2-4 weeks", "Identify instances with <40% average utilization", "Test smaller instance types in non-production", "Schedule maintenance window for production changes", "Monitor performance after changes"]'::jsonb,
 '["CloudWatch monitoring enabled", "Historical metrics available", "Maintenance window availability"]'::jsonb,
 '["Performance degradation if undersized", "Application downtime during resize", "Need to stop instance to change type"]'::jsonb,
 'pending', NOW(), NOW()),

('EC2', 'ec2_spot_instances', 'Migrate to Spot Instances',
 'Use EC2 Spot Instances for fault-tolerant, flexible workloads to save up to 90%',
 50.0, 90.0, 12, 'high', 0.75,
 '["Identify stateless, fault-tolerant workloads", "Implement spot interruption handling", "Use Spot Fleet or Auto Scaling with mixed instance types", "Test interruption scenarios", "Gradually shift workloads from On-Demand"]'::jsonb,
 '["Application supports interruptions", "Auto Scaling configured"]'::jsonb,
 '["Spot interruptions", "Increased complexity"]'::jsonb,
 'pending', NOW(), NOW()),

('EC2', 'ec2_savings_plans', 'Purchase EC2 Savings Plans',
 'Commit to consistent EC2 usage for 1 or 3 years to save 30-72% vs On-Demand',
 30.0, 72.0, 4, 'low', 0.92,
 '["Analyze historical EC2 usage patterns", "Identify stable baseline usage", "Choose Compute or EC2 Instance Savings Plans", "Select 1-year or 3-year term", "Choose All Upfront, Partial, or No Upfront payment", "Purchase through AWS Cost Explorer"]'::jsonb,
 '["At least 3-6 months of usage history", "Budget for upfront payment if chosen"]'::jsonb,
 '["Commitment inflexibility", "Over-commitment if usage decreases"]'::jsonb,
 'pending', NOW(), NOW()),

('EC2', 'ec2_reserved_instances', 'Purchase Reserved Instances',
 'Reserve specific EC2 instance types for 1 or 3 years to save up to 75%',
 40.0, 75.0, 4, 'low', 0.90,
 '["Identify consistent instance type usage", "Choose Standard or Convertible RIs", "Select 1-year or 3-year term", "Choose payment option (All/Partial/No Upfront)", "Purchase RIs matching your usage pattern"]'::jsonb,
 '["Stable instance type requirements", "Budget availability"]'::jsonb,
 '["Less flexible than Savings Plans", "Over-commitment risk"]'::jsonb,
 'pending', NOW(), NOW()),

('EC2', 'ec2_instance_scheduling', 'Implement Instance Scheduling',
 'Automatically stop non-production instances outside business hours',
 30.0, 70.0, 6, 'medium', 0.90,
 '["Identify dev/test/non-production instances", "Define business hours schedule", "Implement AWS Instance Scheduler or Lambda automation", "Tag instances for scheduling", "Test schedule with one instance", "Roll out to all non-prod instances"]'::jsonb,
 '["Ability to stop/start instances without data loss", "Tag management"]'::jsonb,
 '["Service unavailability outside scheduled hours", "Startup time when instances resume"]'::jsonb,
 'pending', NOW(), NOW()),

('EC2', 'ec2_ebs_optimization', 'Optimize EBS Volumes',
 'Delete unattached EBS volumes and snapshots, downgrade volume types',
 10.0, 30.0, 4, 'low', 0.95,
 '["Identify unattached EBS volumes", "Confirm volumes are truly unused", "Create final snapshots if needed", "Delete unattached volumes", "Review snapshot retention policies", "Identify over-provisioned gp3/io2 volumes and downgrade to gp2"]'::jsonb,
 '["Inventory of EBS volumes", "Understanding of volume dependencies"]'::jsonb,
 '["Accidental deletion of needed volumes", "Performance impact if volume type downgraded inappropriately"]'::jsonb,
 'pending', NOW(), NOW()),

-- S3 Recommendations
('S3', 's3_lifecycle_policies', 'Implement S3 Lifecycle Policies',
 'Automatically transition objects to cheaper storage classes and delete expired data',
 30.0, 60.0, 4, 'low', 0.92,
 '["Analyze object access patterns", "Define lifecycle rules for each bucket", "Transition to S3-IA after 30-90 days of no access", "Transition to Glacier after 180 days", "Set expiration for temporary/log data", "Test policies on non-critical bucket first"]'::jsonb,
 '["Understanding of data access patterns", "Compliance requirements for data retention"]'::jsonb,
 '["Retrieval costs if data accessed unexpectedly", "Accidental deletion of important data"]'::jsonb,
 'pending', NOW(), NOW()),

('S3', 's3_intelligent_tiering', 'Enable S3 Intelligent-Tiering',
 'Automatically move objects between access tiers based on usage patterns',
 20.0, 45.0, 2, 'low', 0.88,
 '["Identify buckets with unknown or changing access patterns", "Enable Intelligent-Tiering on bucket or prefix level", "Monitor tiering transitions", "Compare costs vs manual lifecycle policies"]'::jsonb,
 '["Objects larger than 128 KB"]'::jsonb,
 '["Small monitoring fee per object", "May not be cost-effective for small objects"]'::jsonb,
 'pending', NOW(), NOW()),

('S3', 's3_request_optimization', 'Optimize S3 Request Costs',
 'Reduce PUT/COPY/POST/LIST requests and use CloudFront for GET requests',
 10.0, 30.0, 8, 'medium', 0.82,
 '["Analyze S3 request metrics", "Implement CloudFront for frequently accessed objects", "Batch small objects into larger ones", "Reduce LIST operations by using partitioned key names", "Enable S3 Transfer Acceleration for large uploads"]'::jsonb,
 '["S3 request metrics enabled", "Understanding of access patterns"]'::jsonb,
 '["Architectural changes required", "CloudFront costs may offset savings"]'::jsonb,
 'pending', NOW(), NOW()),

-- RDS Recommendations
('RDS', 'rds_rightsizing', 'Rightsize RDS Instances',
 'Analyze CloudWatch metrics to identify oversized RDS instances',
 20.0, 50.0, 6, 'medium', 0.85,
 '["Review CPU, memory, IOPS, and connection metrics", "Identify instances with <40% average utilization", "Test smaller instance classes in non-production", "Schedule maintenance window", "Modify instance class", "Monitor performance after change"]'::jsonb,
 '["CloudWatch Enhanced Monitoring enabled", "Maintenance window availability"]'::jsonb,
 '["Performance degradation", "Downtime during modification"]'::jsonb,
 'pending', NOW(), NOW()),

('RDS', 'rds_reserved_instances', 'Purchase RDS Reserved Instances',
 'Commit to RDS usage for 1 or 3 years to save up to 69%',
 40.0, 69.0, 3, 'low', 0.93,
 '["Analyze stable RDS instance usage", "Choose instance class and engine", "Select 1-year or 3-year term", "Choose payment option", "Purchase RIs"]'::jsonb,
 '["At least 3 months of usage history", "Budget availability"]'::jsonb,
 '["Commitment inflexibility", "Cannot change instance family"]'::jsonb,
 'pending', NOW(), NOW()),

('RDS', 'rds_aurora_serverless', 'Migrate to Aurora Serverless',
 'Use Aurora Serverless v2 for variable workloads to pay only for capacity used',
 30.0, 70.0, 16, 'high', 0.75,
 '["Identify databases with variable or intermittent load", "Test Aurora Serverless v2 compatibility", "Migrate dev/test databases first", "Configure min/max ACU capacity", "Monitor scaling behavior", "Migrate production with blue/green deployment"]'::jsonb,
 '["Compatible with Aurora (MySQL/PostgreSQL)", "Application supports connection interruptions during scaling"]'::jsonb,
 '["Cold start latency", "Scaling delays", "Migration complexity"]'::jsonb,
 'pending', NOW(), NOW()),

('RDS', 'rds_stop_unused', 'Stop Idle RDS Instances',
 'Automatically stop dev/test RDS instances when not in use',
 50.0, 90.0, 4, 'low', 0.90,
 '["Identify non-production RDS instances", "Implement automated stop/start schedule", "Use AWS Instance Scheduler or custom Lambda", "Test stop/start process", "Document startup procedures for teams"]'::jsonb,
 '["Ability to stop instances without data loss", "No critical dependencies"]'::jsonb,
 '["Startup time (several minutes)", "Automatic restart after 7 days"]'::jsonb,
 'pending', NOW(), NOW()),

-- Lambda Recommendations
('Lambda', 'lambda_memory_optimization', 'Optimize Lambda Memory Allocation',
 'Right-size Lambda memory to balance cost and performance (CPU scales with memory)',
 15.0, 40.0, 8, 'medium', 0.85,
 '["Enable Lambda Insights or X-Ray", "Analyze memory usage and duration metrics", "Test functions with different memory settings", "Find sweet spot where duration*memory cost is minimized", "Update function configurations", "Monitor after changes"]'::jsonb,
 '["CloudWatch Logs or Lambda Insights enabled", "Representative test workload"]'::jsonb,
 '["Performance degradation if under-allocated", "Increased duration if CPU-bound and memory reduced"]'::jsonb,
 'pending', NOW(), NOW()),

('Lambda', 'lambda_provisioned_concurrency', 'Remove Unnecessary Provisioned Concurrency',
 'Eliminate provisioned concurrency where cold starts are acceptable',
 40.0, 80.0, 2, 'low', 0.88,
 '["Review all functions with provisioned concurrency", "Measure actual cold start impact", "Test without provisioned concurrency in non-prod", "Remove provisioned concurrency if cold starts acceptable", "Consider Snapstart for Java functions"]'::jsonb,
 '["Understanding of cold start requirements"]'::jsonb,
 '["Increased latency from cold starts", "User experience impact"]'::jsonb,
 'pending', NOW(), NOW()),

('Lambda', 'lambda_timeout_reduction', 'Reduce Lambda Timeout Settings',
 'Lower timeout values to prevent runaway functions from accumulating costs',
 5.0, 20.0, 4, 'low', 0.92,
 '["Analyze Lambda duration metrics", "Identify functions with timeout much higher than actual duration", "Set timeout to p99 duration + 20% buffer", "Update function configurations", "Monitor for timeout errors"]'::jsonb,
 '["Historical duration metrics"]'::jsonb,
 '["Function timeouts if duration spikes", "Need for proper error handling"]'::jsonb,
 'pending', NOW(), NOW()),

-- VPC Recommendations
('VPC', 'vpc_nat_gateway_optimization', 'Optimize NAT Gateway Usage',
 'Reduce NAT Gateway costs by eliminating unnecessary gateways and optimizing routing',
 20.0, 60.0, 6, 'medium', 0.82,
 '["Audit all NAT Gateways", "Identify idle or low-traffic NAT Gateways", "Share NAT Gateway across multiple subnets if possible", "Migrate eligible workloads to use VPC endpoints", "Consider NAT instance for dev/test environments", "Remove unused NAT Gateways"]'::jsonb,
 '["Network architecture understanding", "VPC flow logs"]'::jsonb,
 '["Connectivity loss if misconfigured", "Single point of failure if consolidating"]'::jsonb,
 'pending', NOW(), NOW()),

('VPC', 'vpc_endpoints', 'Use VPC Endpoints for AWS Services',
 'Eliminate NAT Gateway data transfer costs by using VPC endpoints',
 30.0, 70.0, 8, 'medium', 0.88,
 '["Identify traffic to AWS services via NAT Gateway", "Create VPC endpoints for S3, DynamoDB, and other services", "Update route tables", "Modify security groups", "Test connectivity", "Remove NAT Gateway routing where possible"]'::jsonb,
 '["VPC endpoint support for target services", "Security group management"]'::jsonb,
 '["Endpoint costs (Gateway endpoints are free, Interface endpoints charge hourly)", "Complexity increase"]'::jsonb,
 'pending', NOW(), NOW()),

('VPC', 'vpc_data_transfer_optimization', 'Reduce VPC Data Transfer Costs',
 'Minimize cross-AZ and cross-region data transfer by optimizing architecture',
 15.0, 50.0, 12, 'high', 0.75,
 '["Analyze VPC Flow Logs for data transfer patterns", "Identify cross-AZ traffic", "Co-locate frequently communicating resources in same AZ", "Use CloudFront or S3 Transfer Acceleration for external transfers", "Enable VPC peering instead of internet routing", "Compress data where possible"]'::jsonb,
 '["VPC Flow Logs enabled", "Architecture flexibility"]'::jsonb,
 '["Reduced availability if multi-AZ removed", "Architectural complexity"]'::jsonb,
 'pending', NOW(), NOW()),

-- DynamoDB Recommendations
('DynamoDB', 'dynamodb_on_demand', 'Switch to On-Demand Capacity',
 'Use on-demand capacity for unpredictable or bursty workloads',
 20.0, 60.0, 2, 'low', 0.85,
 '["Analyze table traffic patterns", "Identify tables with sporadic or unpredictable traffic", "Switch from provisioned to on-demand capacity", "Monitor costs", "Switch back to provisioned if traffic becomes predictable"]'::jsonb,
 '["Understanding of access patterns"]'::jsonb,
 '["Higher per-request cost", "May be more expensive for consistent traffic"]'::jsonb,
 'pending', NOW(), NOW()),

('DynamoDB', 'dynamodb_auto_scaling', 'Enable DynamoDB Auto Scaling',
 'Automatically adjust provisioned capacity based on actual usage',
 30.0, 60.0, 3, 'low', 0.90,
 '["Configure auto scaling for tables with variable traffic", "Set min/max capacity limits", "Configure target utilization (70-80%)", "Monitor scaling actions", "Tune scaling parameters based on behavior"]'::jsonb,
 '["Provisioned capacity mode", "CloudWatch alarms"]'::jsonb,
 '["Scaling delays during sudden traffic spikes", "Potential throttling during scale-up"]'::jsonb,
 'pending', NOW(), NOW()),

('DynamoDB', 'dynamodb_ttl', 'Implement DynamoDB TTL',
 'Automatically delete expired items to reduce storage costs',
 15.0, 40.0, 2, 'low', 0.92,
 '["Identify tables with temporary or expiring data", "Add TTL attribute to items", "Enable TTL on table", "Monitor deletion activity", "Adjust TTL values as needed"]'::jsonb,
 '["Items have expiration logic"]'::jsonb,
 '["Accidental deletion if TTL misconfigured", "DeletionTime can lag by up to 48 hours"]'::jsonb,
 'pending', NOW(), NOW()),

('DynamoDB', 'dynamodb_table_class', 'Use DynamoDB Standard-IA Table Class',
 'Switch to Standard-Infrequent Access for tables with low throughput',
 25.0, 60.0, 1, 'low', 0.88,
 '["Identify tables accessed less frequently", "Analyze read/write patterns", "Switch table class to Standard-IA", "Monitor costs", "Calculate break-even for your usage"]'::jsonb,
 '["Low access frequency (< 1 read/write per second)"]'::jsonb,
 '["Higher per-request costs", "May increase costs for frequently accessed tables"]'::jsonb,
 'pending', NOW(), NOW()),

-- General AWS Recommendations
('General', 'unused_resources_cleanup', 'Delete Unused AWS Resources',
 'Identify and remove idle resources across all services',
 10.0, 50.0, 8, 'medium', 0.85,
 '["Use AWS Trusted Advisor or Cost Explorer", "Identify idle load balancers, IP addresses, unused volumes", "Tag resources with owner and purpose", "Set up alerts for idle resources", "Implement regular cleanup schedule", "Delete confirmed unused resources"]'::jsonb,
 '["Resource tagging strategy", "Approval process for deletion"]'::jsonb,
 '["Accidental deletion of needed resources", "Service interruption"]'::jsonb,
 'pending', NOW(), NOW()),

('General', 'aws_budgets_alerts', 'Implement AWS Budgets and Alerts',
 'Set up cost budgets and anomaly detection to prevent overspending',
 5.0, 15.0, 3, 'low', 0.95,
 '["Define monthly/quarterly cost budgets per service or project", "Create AWS Budgets with thresholds at 50%, 80%, 100%", "Enable anomaly detection", "Set up SNS notifications to teams", "Review budget reports monthly"]'::jsonb,
 '["Historical cost data", "Budget planning"]'::jsonb,
 '["Alert fatigue if thresholds too low", "No direct cost savings without action"]'::jsonb,
 'pending', NOW(), NOW());

-- Output summary
SELECT 
    service, 
    COUNT(*) as recommendation_count,
    ROUND(AVG(estimated_savings_max_percent::numeric), 1) as avg_max_savings_pct
FROM optimization_recommendations
GROUP BY service
ORDER BY recommendation_count DESC;

SELECT COUNT(*) as total_recommendations FROM optimization_recommendations;
