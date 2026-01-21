# Scripts Directory Documentation

This directory contains operational scripts for deployment, setup, and maintenance of the FinOps Intelligence Platform.

## Directory Structure

```
scripts/
├── deployment/          # Deployment and migration scripts
├── setup/              # Initial setup and verification scripts
├── lambda/             # AWS Lambda functions (if any)
└── cleanup-orphaned-resources.sh
```

---

## Deployment Scripts (`deployment/`)

### `aws_run_migrations.sh`
**Purpose:** Run Alembic database migrations on AWS ECS  
**Usage:**
```bash
# Run migrations via ECS Exec (if container running and Session Manager Plugin installed)
./scripts/deployment/aws_run_migrations.sh exec \
  --region us-east-1 \
  --cluster finops-intelligence-platform-cluster \
  --service finops-intelligence-platform-backend \
  --container backend

# Run migrations via one-off Fargate task (fallback method)
./scripts/deployment/aws_run_migrations.sh run \
  --region us-east-1 \
  --cluster finops-intelligence-platform-cluster \
  --task-def <task-definition-arn> \
  --subnets subnet-xxx,subnet-yyy \
  --security-groups sg-zzz
```

**When to Use:**
- After CloudFormation deployment to initialize database schema
- After code updates that include new Alembic migrations
- When database schema is out of sync with code

**Called By:** `deploy.sh` automatically during deployment

---

### `redeploy-backend.sh`
**Purpose:** Quick redeploy of backend service only (faster than full deployment)  
**Usage:**
```bash
./scripts/deployment/redeploy-backend.sh
```

**What it does:**
1. Rebuilds backend Docker image
2. Pushes to ECR
3. Forces ECS service to redeploy with new image

**When to Use:**
- Backend code changes only (no infrastructure changes)
- Faster iteration during development
- Bug fixes that don't require CloudFormation updates

---

### `setup_cur_view.sh`
**Purpose:** Create unified Athena view from CUR manifest tables  
**Usage:**
```bash
./scripts/deployment/setup_cur_view.sh /path/to/deployment.env
```

**What it does:**
1. Discovers all timestamped CUR manifest tables in Glue catalog
2. Creates unified `cur_data` view with UNION ALL
3. Enables querying all CUR versions through single table

**When to Use:**
- After CUR data arrives in S3 (first 24-72 hours)
- After Glue Crawler runs and creates manifest tables
- When CUR manifest version changes

**Called By:** `deploy.sh` during initial deployment

---

### `create_cur_with_crawler.sh`
**Purpose:** Set up Glue Crawler for CUR data discovery  
**Usage:**
```bash
./scripts/deployment/create_cur_with_crawler.sh
```

**What it does:**
1. Creates Glue Crawler for CUR S3 location
2. Configures crawler to discover Parquet partitions
3. Runs crawler to populate Glue catalog

**When to Use:**
- Alternative to manual Athena table creation
- When CUR schema changes and needs rediscovery
- For dynamic CUR manifest version handling

---

## Setup Scripts (`setup/`)

### `setup-athena-cur.sh`
**Purpose:** Create Athena table with partition projection for CUR data  
**Usage:**
```bash
./scripts/setup/setup-athena-cur.sh \
  <cur-bucket> \
  <cur-prefix> \
  <database-name> \
  <table-name> \
  <region> \
  <athena-output-location>
```

**Example:**
```bash
./scripts/setup/setup-athena-cur.sh \
  finops-intelligence-platform-data-515966519020 \
  cost-exports/finops-cost-export \
  cost_usage_db \
  cur_data \
  us-east-1 \
  s3://finops-intelligence-platform-data-515966519020/athena-results/
```

**What it does:**
1. Creates Athena table with partition projection
2. Configures month/year partitioning for efficient queries
3. Works even before CUR data arrives

**When to Use:**
- During initial deployment (called by `deploy.sh`)
- When recreating Athena infrastructure
- After changing CUR S3 location

---

### `setup-cur.sh`
**Purpose:** **DEPRECATED** - Original CUR setup script (use AWS Console instead)  
**Status:** Kept for reference only  
**Recommendation:** Follow [SETUP_CUR.md](../docs/SETUP_CUR.md) for manual AWS Console configuration

---

### `setup_cur_pipeline.sh`
**Purpose:** Legacy script for CUR 2.0 setup  
**Status:** May be deprecated depending on CUR version strategy  
**Usage:** Not recommended for new deployments

---

### `verify-cur-setup.sh`
**Purpose:** Validate CUR configuration and data availability  
**Usage:**
```bash
./scripts/setup/verify-cur-setup.sh
```

**What it checks:**
- S3 bucket exists and is accessible
- CUR data files present in S3
- Athena database and table exist
- Sample query executes successfully
- Partition projection is working

**When to Use:**
- After configuring CUR in AWS Console
- After running `deploy.sh`
- Troubleshooting CUR data issues

---

### `verify-deployment-env.sh`
**Purpose:** Validate `deployment.env` file has required variables
**Usage:**
```bash
./scripts/setup/verify-deployment-env.sh
```

**What it checks:**
- All required environment variables present
- Database password is set
- AWS region configured
- CUR paths are valid

**When to Use:**
- Before running `deploy.sh`
- Troubleshooting deployment failures
- After manual `deployment.env` edits

---

### `opportunities_ingest.py`
**Purpose:** Ingest optimization recommendations from AWS services into the opportunities database
**Usage:**
```bash
# Dry run (preview without storing)
python scripts/setup/opportunities_ingest.py --dry-run

# Full ingestion with all sources
python scripts/setup/opportunities_ingest.py

# Filter by account IDs
python scripts/setup/opportunities_ingest.py --account-ids 123456789012,234567890123

# Select specific sources
python scripts/setup/opportunities_ingest.py --sources cost-explorer,compute-optimizer
```

**What it does:**
1. Fetches rightsizing recommendations from AWS Cost Explorer
2. Fetches cost optimization checks from AWS Trusted Advisor
3. Fetches EC2 recommendations from AWS Compute Optimizer
4. Stores recommendations in the `opportunities` database table
5. Updates existing recommendations, creates new ones

**Sources:**
- **Cost Explorer**: EC2 rightsizing recommendations
- **Trusted Advisor**: Low utilization EC2, idle load balancers, underutilized EBS, idle RDS, etc.
- **Compute Optimizer**: EC2 instance optimization based on CPU/memory utilization

**Required AWS Permissions:**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Action": "ce:GetRightsizingRecommendation", "Resource": "*"},
    {"Effect": "Allow", "Action": "support:DescribeTrustedAdvisorCheckResult", "Resource": "*"},
    {"Effect": "Allow", "Action": "compute-optimizer:GetEC2InstanceRecommendations", "Resource": "*"}
  ]
}
```

**Environment Variables:**
- `DATABASE_URL`: PostgreSQL connection string (required for non-dry-run)
- `AWS_REGION`: AWS region for API calls (default: us-east-1)

**When to Use:**
- Initial setup to populate optimization opportunities
- Scheduled cron job for regular updates (e.g., daily)
- After enabling new AWS accounts in the organization

**Notes:**
- Trusted Advisor requires Business or Enterprise Support plan
- Compute Optimizer requires opt-in (enable in AWS Console first)
- Run with `--dry-run` first to preview recommendations

---

## Maintenance Scripts

### `cleanup-orphaned-resources.sh`
**Purpose:** Clean up orphaned AWS resources after failed deployments  
**Usage:**
```bash
./scripts/cleanup-orphaned-resources.sh
```

**What it cleans:**
- Orphaned security group rules
- Unused Elastic IPs
- Dangling network interfaces (ENIs)
- Incomplete CloudFormation resources

**When to Use:**
- After `deploy.sh destroy` fails
- When CloudFormation rollback leaves orphans
- Before redeploying after infrastructure errors

**⚠️ Warning:** Review resources before confirming deletion

---

## Removed Scripts (December 2025 Cleanup)

### Removed from `scripts/`:
- ~~`keep-db-alive.sh`~~ - No longer needed (RDS auto-manages connections)
- ~~`deployment/run_migrations.sh`~~ - Superseded by `aws_run_migrations.sh`

### Reason for Removal:
- Obsolete functionality
- Better alternatives available
- Reduced maintenance burden

---

## Script Usage Best Practices

1. **Always run from repository root:**
   ```bash
   cd /path/to/finops-orchestrator
   ./scripts/deployment/redeploy-backend.sh  # ✅ Correct
   ```

2. **Check script permissions:**
   ```bash
   chmod +x scripts/**/*.sh  # Make all scripts executable
   ```

3. **Review logs:**
   - All scripts output to stdout/stderr
   - Use `tee` to capture logs: `./script.sh 2>&1 | tee deployment.log`

4. **Environment variables:**
   - Most scripts read from `deployment.env`
   - Some accept command-line arguments (check `--help`)

5. **AWS credentials:**
   - Ensure AWS CLI configured: `aws sts get-caller-identity`
   - Use appropriate IAM role/permissions

---

## Troubleshooting

### Script fails with "permission denied"
```bash
chmod +x scripts/path/to/script.sh
```

### Script can't find `deployment.env`
```bash
# Run deploy.sh first to create it
./deploy.sh deploy
```

### AWS CLI errors
```bash
# Verify AWS credentials
aws sts get-caller-identity

# Check AWS region
echo $AWS_REGION  # or check deployment.env
```

### Migration script fails
```bash
# Check ECS service status
aws ecs describe-services --cluster <cluster> --services <service> --region us-east-1

# Check CloudWatch logs
aws logs tail /ecs/finops-intelligence-platform/backend --follow --region us-east-1
```

---

## Development Guidelines

### Adding New Scripts

1. **Place in appropriate directory:**
   - `deployment/` - Deployment, migration, service management
   - `setup/` - Initial setup, configuration, verification
   - Root level - Only cross-cutting maintenance scripts

2. **Include header documentation:**
   ```bash
   #!/bin/bash
   # Script Name: deploy-feature.sh
   # Purpose: Deploy new feature with zero downtime
   # Usage: ./deploy-feature.sh <feature-name>
   # Dependencies: AWS CLI, Docker, jq
   ```

3. **Add to this README:**
   - Document purpose, usage, when to use
   - Include examples
   - Note any dependencies

4. **Test before committing:**
   - Test on clean AWS account
   - Test failure scenarios
   - Verify idempotency (safe to run multiple times)

---

## Related Documentation

- [AWS Deployment Guide](../docs/AWS_DEPLOYMENT_GUIDE.md) - Full deployment process
- [CUR Setup Guide](../docs/SETUP_CUR.md) - Manual CUR configuration
- [Troubleshooting](../docs/TROUBLESHOOTING.md) - Common issues
- [Backend Architecture](../docs/BACKEND_ARCHITECTURE.md) - System design

---

**Last Updated:** December 2, 2025  
**Maintainer:** Amit Kumar (amit.kumar2@dazn.com)
