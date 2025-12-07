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
