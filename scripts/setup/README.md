# Resource Inventory Ingestion (EC2)

This setup ingests EC2 instance inventory into S3 as Parquet and registers a Glue table used for ARN-based cost grouping.

## Prerequisites
- AWS credentials with permissions: `ec2:DescribeInstances`, `sts:GetCallerIdentity`, `s3:PutObject`, `glue:GetTable`, `glue:CreateTable`, `glue:UpdateTable`.
- Env vars in `deployment.env`:
  - `RESOURCE_INVENTORY_ENABLED=1`
  - `RESOURCE_INVENTORY_DB=resource_inventory`
  - `RESOURCE_INVENTORY_TABLE=resources`
  - `RESOURCE_INVENTORY_S3_BUCKET=<your-bucket>`
  - `RESOURCE_INVENTORY_S3_PREFIX=resource-inventory/`

## Usage

Set the environment and run ingestion locally:

```zsh
export AWS_REGION=us-east-1
export RESOURCE_INVENTORY_S3_BUCKET=finops-intelligence-platform-data-515966519020
export RESOURCE_INVENTORY_S3_PREFIX=resource-inventory/
export RESOURCE_INVENTORY_DB=resource_inventory
export RESOURCE_INVENTORY_TABLE=resources

python3 scripts/setup/ec2_inventory_ingest.py
```

This will:
- List EC2 instances in `AWS_REGION`
- Write a parquet file to `s3://$RESOURCE_INVENTORY_S3_BUCKET/$RESOURCE_INVENTORY_S3_PREFIX`
- Ensure a Glue table `resource_inventory.resources` pointing at the prefix

## Verification

Run a query in Athena:

```sql
SELECT account_id, region, service, arn, instance_type, platform_details, state, name
FROM resource_inventory.resources
LIMIT 10;
```

Then try an ARN grouping query in the app (ensure deployment includes `RESOURCE_INVENTORY_ENABLED=1`).

## Notes
- To ingest all regions, edit `ec2_inventory_ingest.py` to use `describe_regions` and set `regions = all_regions`.
- Extend similarly for other services (RDS, Lambda, ECS) by mapping their ARNs and resource IDs.

---

# Optimization Opportunities Ingestion

The `opportunities_ingest.py` script fetches optimization recommendations from AWS services and stores them in the database.

## Prerequisites
- AWS credentials with permissions:
  - `ce:GetRightsizingRecommendation` (Cost Explorer)
  - `support:DescribeTrustedAdvisorCheckResult` (Trusted Advisor - requires Business/Enterprise Support)
  - `compute-optimizer:GetEC2InstanceRecommendations` (Compute Optimizer - requires opt-in)
- Database connection string in `DATABASE_URL` environment variable

## Usage

### Dry Run (preview without storing)
```bash
python3 scripts/setup/opportunities_ingest.py --dry-run
```

### Full Ingestion
```bash
export DATABASE_URL="postgresql://user:pass@host:5432/dbname"
python3 scripts/setup/opportunities_ingest.py
```

### Filter by Account IDs
```bash
python3 scripts/setup/opportunities_ingest.py --account-ids 123456789012,234567890123
```

### Select Specific Sources
```bash
# Only Cost Explorer and Compute Optimizer (skip Trusted Advisor)
python3 scripts/setup/opportunities_ingest.py --sources cost-explorer,compute-optimizer
```

## Output
The script will:
1. Fetch recommendations from selected AWS services
2. Display summary of findings and potential savings
3. Store new opportunities in the database
4. Update existing opportunities (matched by source_id)

## Scheduled Ingestion
For production, set up a cron job or AWS EventBridge rule to run daily:

```bash
# Example cron entry (runs at 2 AM UTC daily)
0 2 * * * /path/to/venv/bin/python /path/to/scripts/setup/opportunities_ingest.py >> /var/log/opportunities-ingest.log 2>&1
```

## Verification
After ingestion, verify opportunities in the app:
```bash
curl "http://localhost:8000/api/v1/opportunities?page=1&page_size=10" | jq
```

Or via chat:
> "Show me optimization opportunities"
