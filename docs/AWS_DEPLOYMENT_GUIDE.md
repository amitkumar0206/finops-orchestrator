# AWS Deployment Guide - FinOps AI Cost Intelligence Platform

## 🎯 Overview

This guide provides comprehensive instructions for deploying the FinOps AI Cost Intelligence Platform on AWS, supporting both **fresh infrastructure setup** and **updates to existing deployments**.

### Deployment Modes

1. **Fresh Install**: Complete infrastructure setup from scratch (including one-time components)
2. **Update Deployment**: Update existing infrastructure with new code/configuration
3. **Rebuild**: Destroy and recreate infrastructure (see cleanup options below)
4. **Complete Cleanup**: Remove all resources including historical data (⚠️ DATA LOSS WARNING)

---

## 📋 Part 1: Prerequisites and Preparation

### 1.1 Pre-Flight Checklist

Before running the deployment, ensure all prerequisites are met. The deployment script includes **automated pre-flight validation** that checks:

**✓ Required Tools:**
- AWS CLI v2+ installed and accessible
- Docker Desktop installed and running
- jq (optional, for enhanced JSON processing)

**✓ AWS Credentials:**
- Valid AWS credentials configured
- Credentials have not expired
- Access to target AWS region

**✓ IAM Permissions:**
- CloudFormation (full access)
- ECS, ECR (container management)
- RDS, ElastiCache (databases)
- S3 (storage)
- VPC, EC2, ELB (networking)
- IAM (role creation)
- Bedrock (LLM access)
- Athena, Glue (data analytics)

**✓ Bedrock Model Access:**
- Amazon Nova Premier/Pro/Lite models enabled
- Model access validated via test invocation

**✓ System Resources:**
- Minimum 10GB free disk space for Docker builds
- Stable internet connection for AWS API calls

**✓ Optional:**
- Custom domain and Route 53 hosted zone (if using custom domain)
- Session Manager Plugin (for ECS Exec migration validation)

### 1.2 AWS Account Requirements

**Required Permissions:**

**Critical Permissions (deployment will fail without these):**
- CloudFormation: `cloudformation:*`
- ECS: `ecs:*`
- ECR: `ecr:*`
- RDS: `rds:*`
- S3: `s3:*`
- VPC/EC2/ELB: `ec2:*`, `elasticloadbalancing:*`
- IAM: `iam:CreateRole`, `iam:PutRolePolicy`, `iam:PassRole`

**Recommended Permissions (warnings without these):**
- Bedrock: `bedrock:InvokeModel`, `bedrock:ListFoundationModels`
- Athena: `athena:*`
- Glue: `glue:*`
- SSM: `ssm:PutParameter`, `ssm:GetParameter` (for password storage)

**Note:** The deployment script includes automated permission validation during pre-flight checks.

**Verification:**

```bash
# The deployment script automatically validates these, but you can check manually:

# 1. Verify AWS CLI and credentials
aws --version  # Should be 2.x or higher
aws sts get-caller-identity  # Should show your account and user/role
aws configure get region  # Should show target region (e.g., us-east-1)

# 2. Test CloudFormation access
aws cloudformation list-stacks --region us-east-1 --max-results 1

# 3. Test ECR access
aws ecr describe-repositories --region us-east-1 --max-results 1

# 4. Test Bedrock access
aws bedrock list-foundation-models --region us-east-1 --max-results 1

# Note: All these checks are performed automatically during deployment
```

### 1.2 Local Development Tools

**Required:**

- Docker Desktop (for building images)
- Git
- Bash/Zsh shell
- jq (optional, for JSON parsing)

**Verification:**

```bash
docker --version && docker ps
git --version
jq --version  # optional
```

### 1.3 AWS Bedrock Model Access

The platform defaults to **Amazon Nova Pro** which requires model access enabled.

**Enable via AWS Console:**

```bash
# Open Bedrock Model Access page
open "https://us-east-1.console.aws.amazon.com/bedrock/home?region=us-east-1#/modelaccess"

# Steps:
# 1. Click "Modify model access"
# 2. Select: Amazon Nova Pro, Nova Lite, Nova Micro
# 3. Optional: Meta Llama 3 70B, Mistral Large
# 4. Click "Save changes"
# 5. Wait for "Access granted" status (usually instant)
```

**Verify Model Access:**

```bash
# Test default model (Amazon Nova Pro)
aws bedrock-runtime invoke-model \
  --model-id us.amazon.nova-pro-v1:0 \
    --body '{"messages":[{"role":"user","content":[{"text":"Test"}]}],"inferenceConfig":{"max_new_tokens":100}}' \
    --cli-binary-format raw-in-base64-out \
    --region us-east-1 \
    /tmp/test.json && echo "✅ Bedrock access confirmed"
```

---

## 🚀 Part 2: Quick Start Deployment

### 2.1 Automated Deployment with Pre-Flight Validation (Recommended)

The deployment script includes comprehensive pre-flight validation to catch issues before deployment begins.

**For First-Time Installation:**

```bash
# Clone repository
git clone <repository-url>
cd finops-orchestrator

# Make deploy script executable
chmod +x deploy.sh

# Run deployment with automated pre-flight validation
./deploy.sh deploy

# Pre-flight validation will check (automatically):
# [1/7] Required tools (AWS CLI, Docker, jq)
# [2/7] AWS credentials and authentication
# [3/7] AWS region configuration
# [4/7] IAM permissions (CloudFormation, ECS, RDS, etc.)
# [5/7] Bedrock model access
# [6/7] Disk space for Docker builds
# [7/7] Deployment configuration

# If validation passes, deployment proceeds:
# ✓ Detects existing infrastructure (none for first install)
# ✓ Sets up one-time components (S3, Glue, Athena)
# ✓ Deploys CloudFormation stack (10-15 min)
# ✓ Builds and pushes Docker images (5-10 min)
# ✓ Deploys ECS services (5 min)
# ✓ Runs database migrations with validation
# ✓ Validates deployment health
# ✓ Saves configuration to deployment.env
# ✓ Provides application URL

# Total time: ~25-35 minutes (first-time installation)
```

**If Pre-Flight Validation Fails:**

The script will display specific errors and provide remediation steps:

```bash
# Example: Missing AWS credentials
[ERROR] AWS credentials validation failed.
To fix this issue:
  1. Run: aws configure
  2. Verify your credentials are valid in the AWS Console

# Example: Missing Bedrock access
[WARNING] Bedrock model access failed.
Enable model access at:
https://console.aws.amazon.com/bedrock/home?region=us-east-1#/modelaccess

# You can choose to continue with warnings or fix issues first
Continue deployment despite warnings? (yes/no):
```

**For Updating Existing Deployment:**

```bash
# Run deployment (automatically detects existing infrastructure)
./deploy.sh deploy

# Pre-flight validation runs first
# Then you'll be prompted:
# Options:
#   1) Update existing infrastructure (recommended)
#   2) Fresh install (destroys everything - DATA LOSS)
#   3) Cancel

# Choose option 1 for updates
# The script will update infrastructure and redeploy services

# Or for faster service-only updates (no infrastructure changes):
./deploy.sh update
```

### 2.2 What Gets Validated During Pre-Flight

The automated pre-flight validation ensures a smooth deployment by checking:

**1. Tool Availability:**
- AWS CLI installed (v2+ recommended)
- Docker installed and daemon running
- jq available (optional, enhances JSON processing)

**2. Authentication & Authorization:**
- AWS credentials valid and not expired
- Access to target AWS region
- CloudFormation permissions (critical)
- ECR permissions for image push
- Bedrock permissions for LLM access

**3. Resource Requirements:**
- Minimum 10GB disk space available
- Docker daemon responsive
- Internet connectivity for AWS API calls

**4. Bedrock Configuration:**
- Target model accessible (e.g., us.amazon.nova-premier-v1:0)
- Model access enabled in AWS Console
- Test invocation successful

**5. Existing Infrastructure:**
- Detection of existing CloudFormation stacks
- Glue database existence check
- Athena workgroup availability
- S3 bucket configuration

**6. Migration Readiness:**
- Database migration scripts accessible
- ECS task execution permissions
- RDS connectivity (for existing deployments)

All validation is **non-destructive** and provides clear guidance on fixing any issues before deployment begins.

### 2.3 Deployment Modes

**For Complete Rebuild (preserves data exports):**

```bash
# Destroy infrastructure (keeps CUR, S3, Glue, Athena)
./deploy.sh destroy

# Then deploy fresh
./deploy.sh deploy
```

**For Complete Cleanup (removes everything):**

```bash
# ⚠️ WARNING: Deletes EVERYTHING including all historical data
./deploy.sh destroyAll
```

### 2.4 Complete Deployment Flow

**First-Time Installation (25-35 minutes):**

```
1. Pre-Flight Validation (2-3 min)
   • Tool availability (AWS CLI, Docker, jq)
   • AWS credentials and permissions
   • Bedrock model access
   • Disk space verification

2. Infrastructure Detection (30 sec)
   • Check existing CloudFormation stacks
   • Determine deployment mode

3. One-Time Setup (3-5 min)
   • Create S3 buckets
   • Set up Glue database
   • Configure Athena workgroup
   
4. CloudFormation Deployment (10-15 min)
   • Deploy infrastructure stack
   • VPC, RDS, ElastiCache, ECS, ALB

5. Docker Build & Push (5-10 min)
   • Build backend and frontend images
   • Push to ECR

6. ECS Deployment (5 min)
   • Deploy services stack
   • Launch ECS tasks

7. Database Migrations (2-3 min)
   • Run Alembic migrations
   • Validate schema

8. Post-Deployment Validation (1 min)
   • Health checks
   • Configuration save
```

### 2.5 What the Deployment Script Does

**Infrastructure Detection:**

- Checks for existing CloudFormation stack
- Checks for Standard Data Exports or Legacy CUR reports
- Checks for Glue database and Athena workgroup
- Prompts for appropriate action based on findings

**One-Time Setup (Fresh Install Only):**

The deployment script now provides **three options** for data export setup:

1. **Skip data export setup** (recommended for quick start)
   - Platform works immediately with AWS Cost Explorer API
   - Provides 13 months of historical data with no configuration
   - Best for getting started quickly

2. **Automatic data export setup** (for 13+ month history)
   - Automatically creates AWS Standard Data Export
   - Creates S3 bucket with proper policies
   - Sets up Glue database and crawler
   - Configures Athena workgroup
   - **Reuses existing S3 bucket** from previous deployments if available

3. **Use existing CUR/data export bucket**
   - Connect to previously configured CUR or Data Export
   - Specify bucket name, prefix, and Glue database

**Note:** Data exports are optional. The platform provides full functionality with Cost Explorer API alone. Only use data exports if you need detailed analysis beyond 13 months or resource-level attribution.

**Main Deployment:**

- Deploys/updates CloudFormation infrastructure
- Creates VPC, subnets, security groups
- Provisions RDS database and ElastiCache
- Creates ECS cluster and load balancer
- Builds and pushes Docker images to ECR
- Deploys ECS services (backend and frontend)

### 2.3 Custom Domain Configuration (Optional)

**Purpose:** Use a persistent custom domain (e.g., `finops.yourdomain.com`) instead of ALB DNS name that changes with each rebuild.

**When to Configure:**

- ✅ You have a Route 53 hosted zone for your domain
- ✅ Want a stable URL across infrastructure rebuilds
- ✅ Need HTTPS/SSL support
- ⚠️ **Optional** - platform works with ALB DNS name

**Prerequisites:**

```bash
# 1. Create or identify your Route 53 hosted zone
aws route53 list-hosted-zones --query "HostedZones[].{Name:Name,Id:Id}" --output table

# 2. Note your Hosted Zone ID (e.g., Z1234567890ABC)
HOSTED_ZONE_ID="Z1234567890ABC"

# 3. Choose your subdomain (e.g., finops.yourdomain.com)
DOMAIN_NAME="finops.yourdomain.com"
```

**Automated Setup:**

During `./deploy.sh deploy`, you'll be prompted:

```bash
Configure custom domain with Route 53? (y/n, default: n): y
Enter custom domain name (e.g., finops.yourdomain.com): finops.yourdomain.com
Enter Route 53 Hosted Zone ID: Z1234567890ABC
Create ACM certificate for HTTPS? (y/n, default: y): y
```

**What Happens:**

1. **ACM Certificate** (if enabled):
   - Creates SSL/TLS certificate for your domain
   - Uses DNS validation (automatic)
   - Certificate ARN saved to deployment state
   - Validation takes 5-10 minutes

2. **Route 53 A Record**:
   - Creates/updates A record pointing to ALB
   - Uses alias record (no additional charges)
   - Propagates within 60 seconds

3. **Persistence**:
   - Domain name saved to `deployment.env`
   - Reused automatically on rebuilds
   - ALB changes, Route 53 record auto-updates

**Verification:**

```bash
# Wait for DNS propagation
dig finops.yourdomain.com +short

# Test HTTP access
curl -I http://finops.yourdomain.com

# Test HTTPS (if certificate enabled)
curl -I https://finops.yourdomain.com

# Check certificate status
aws acm list-certificates --region us-east-1 \
    --query "CertificateSummaryList[?DomainName=='finops.yourdomain.com']"
```

**Manual Route 53 Setup (if script fails):**

```bash
# Get ALB DNS name
ALB_DNS=$(aws cloudformation describe-stacks \
    --stack-name finops-intelligence-platform \
    --query 'Stacks[0].Outputs[?OutputKey==`LoadBalancerDNSName`].OutputValue' \
    --output text)

# Create Route 53 record set change batch
cat > change-batch.json <<EOF
{
  "Changes": [{
    "Action": "UPSERT",
    "ResourceRecordSet": {
      "Name": "finops.yourdomain.com",
      "Type": "A",
      "AliasTarget": {
        "HostedZoneId": "Z35SXDOTRQ7X7K",
        "DNSName": "$ALB_DNS",
        "EvaluateTargetHealth": false
      }
    }
  }]
}
EOF

# Apply change
aws route53 change-resource-record-sets \
    --hosted-zone-id Z1234567890ABC \
    --change-batch file://change-batch.json
```

---

## 🏗️ Part 3: One-Time Infrastructure Components

These components are created once and persist across deployments. **Only required for fresh installations.**

### 3.1 Cost & Usage Data Strategies (Legacy CUR vs Standard Data Export)

**Purpose:** Provides detailed cost data beyond the 13 months available via Cost Explorer API.

You can operate the platform in one of two modes:

1. Legacy CUR (traditional Cost & Usage Reports) – simplest if you already have a CUR bucket managed by your FinOps / Billing team.
2. Standard Data Export (recommended for new green‑field setups) – modern replacement with richer schema and improved partitioning.

We now default to **Legacy CUR only mode** (`USE_LEGACY_CUR_ONLY=true`). This is the simplest approach for teams with existing CUR buckets. To enable Standard Data Export mode instead, set `USE_LEGACY_CUR_ONLY=false` before deployment.

Key differences:

| Aspect | Legacy CUR | Standard Data Export |
|--------|-----------|----------------------|
| Creation mechanism | Billing Console (Cost & Usage Reports) | Billing Console (Data Exports) or API (`bcm-data-exports`) |
| API Namespace | `cur` | `bcm-data-exports` |
| Recommended by AWS going forward | Deprecated (will persist for some time) | Yes |
| Glue crawler name in this project | `<stack>-cur-crawler` (CloudFormation) | `finops-cost-export-crawler` (script) |
| Setup location in repo | CloudFormation parameters (`CurReportBucketName`, etc.) | `scripts/setup/setup-cur.sh` |
| Schedule default | 2 AM UTC | 3 AM UTC |

If you choose Legacy CUR ONLY (the default), set your CUR bucket/prefix via CloudFormation parameters. The platform automatically runs in this mode unless you set `USE_LEGACY_CUR_ONLY=false`.

**What Changed:**

- **Default**: Legacy CUR only mode (`USE_LEGACY_CUR_ONLY=true` by default)
- **Opt-in**: Standard Data Export available by setting `USE_LEGACY_CUR_ONLY=false`
- **Benefit**: Simpler default setup; no extra crawlers unless explicitly requested

**When to Use Each:**

Legacy CUR only (default):

- You already have a governed CUR bucket
- Want minimal change / faster approval
- Don't need immediate migration to new export format
- **No action needed** - this is the default

Standard Data Export (opt-in):

- New deployment without existing CUR
- Desire improved schema evolution and future‑proofing
- Planning deprecation of legacy CUR internally
- **Action**: Set `export USE_LEGACY_CUR_ONLY=false` before deploying

**Automated Setup (Standard Data Export path – skip if using Legacy CUR only):**

Run the setup script (also invoked automatically from `deploy.sh` on fresh installs):

```bash
scripts/setup/setup-cur.sh
```

The script will:

- Reuse the S3 bucket from deploy.sh
- Create Standard Data Export (CREATE_NEW_REPORT mode - preserves historical data)
- Set up bucket policies for both bcm-data-exports and legacy CUR
- Create Glue database and crawler
- Configure Athena workgroup
- Configuration is saved to deployment.env

**Key Features (Standard Data Export path):**

- ✅ Bucket reuse (no duplicates)
- ✅ CREATE_NEW_REPORT mode preserves historical data
- ✅ Glue + Athena auto setup
- ✅ Coexists with legacy CUR during transition

**Legacy CUR Only Mode (Default):**

1. Ensure a CUR report already delivers Parquet files to an existing bucket/prefix (e.g. `s3://your-cur-bucket/cost-reports/`).
2. Run deployment (no special flags needed - this is the default):

   ```bash
   ./deploy.sh deploy
   ```

3. Provide the bucket/prefix when prompted so CloudFormation creates only the `CurGlueCrawler`.
4. If you previously had the Standard Data Export crawler, clean it up:

   ```bash
   ./scripts/utilities/cleanup-export-crawler.sh
   ```

5. Configuration is automatically saved in deployment.env during deployment.

Verification after deploy (Legacy CUR only):

```bash
aws glue get-crawler --name <your-stack-name>-cur-crawler --region us-east-1 --query 'Crawler.State'
aws glue get-crawlers --region us-east-1 --query 'Crawlers[?Name==`finops-cost-export-crawler`]' # should return []
```

**Manual Setup (if needed):**

```bash
# Variables (reuse bucket from deploy.sh state)
STACK_NAME="finops-intelligence-platform"
AWS_REGION="us-east-1"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Reuse bucket
if [ -f "deployment.env" ]; then
    CUR_BUCKET=$(awk -F'=' '$1=="S3_BUCKET"{print $2}' "deployment.env")
else
    # Ensure globally unique bucket name by appending AWS account ID
    CUR_BUCKET="finops-intelligence-platform-data-${AWS_ACCOUNT_ID}"
fi

# 1. Create S3 bucket (if needed)
aws s3api head-bucket --bucket "$CUR_BUCKET" 2>/dev/null || \
    aws s3 mb s3://$CUR_BUCKET --region $AWS_REGION

# 2. Create dual-service bucket policy
cat > /tmp/cur-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BCMDataExports",
      "Effect": "Allow",
      "Principal": {"Service": "bcm-data-exports.amazonaws.com"},
      "Action": ["s3:GetBucketAcl", "s3:GetBucketPolicy", "s3:PutObject"],
      "Resource": ["arn:aws:s3:::$CUR_BUCKET", "arn:aws:s3:::$CUR_BUCKET/*"],
      "Condition": {
        "StringLike": {
          "aws:SourceArn": "arn:aws:bcm-data-exports:*:$AWS_ACCOUNT_ID:export/*"
        }
      }
    },
    {
      "Sid": "LegacyCUR",
      "Effect": "Allow",
      "Principal": {"Service": "billingreports.amazonaws.com"},
      "Action": ["s3:GetBucketAcl", "s3:GetBucketPolicy", "s3:PutObject"],
      "Resource": ["arn:aws:s3:::$CUR_BUCKET", "arn:aws:s3:::$CUR_BUCKET/*"],
      "Condition": {
        "StringLike": {
          "aws:SourceArn": "arn:aws:cur:us-east-1:$AWS_ACCOUNT_ID:definition/*"
        }
      }
    }
  ]
}
EOF

aws s3api put-bucket-policy --bucket $CUR_BUCKET --policy file:///tmp/cur-policy.json

# 3. Create Standard Data Export (OVERWRITE mode)
cat > /tmp/data-export.json << EOF
{
  "Export": {
    "Name": "finops-cost-export",
    "DataQuery": {
      "QueryStatement": "SELECT * FROM COST_AND_USAGE_REPORT",
      "TableConfigurations": {
        "COST_AND_USAGE_REPORT": {
          "TIME_GRANULARITY": "DAILY",
          "INCLUDE_RESOURCES": "TRUE"
        }
      }
    },
    "DestinationConfigurations": {
      "S3Destination": {
        "S3Bucket": "$CUR_BUCKET",
        "S3Prefix": "cost-exports",
        "S3Region": "$AWS_REGION",
        "S3OutputConfigurations": {
          "OutputType": "CUSTOM",
          "Format": "PARQUET",
          "Compression": "PARQUET",
          "Overwrite": "CREATE_NEW_REPORT"
        }
      }
    },
    "RefreshCadence": {"Frequency": "SYNCHRONOUS"}
  }
}
EOF

aws bcm-data-exports create-export --cli-input-json file:///tmp/data-export.json --region us-east-1

echo "✅ Standard Data Export created (CREATE_NEW_REPORT mode - preserves all historical data)"
}
EOF

# Create report (CUR API only works in us-east-1)
aws cur put-report-definition \
  --report-definition file:///tmp/cur-definition.json \
  --region us-east-1

# 4. Configuration will be saved to deployment.env during deployment

echo "✅ CUR setup complete. First report available in 24 hours."
```

**Important Notes:**

- ⚠️ **CREATE_NEW_REPORT is SAFE** - preserves all historical data, never overwrites
- ⏰ First data export takes up to 24 hours to generate
- 📍 Standard Data Exports API only works in `us-east-1` region
- 💰 Minimal cost: Storage costs based on actual data (~$5-20/month for typical usage)
- 🔄 Reports refresh daily with new partitions (year/month/day structure)
- 📊 Glue crawler automatically discovers all time partitions

**Verification:**

```bash
# Check data export status
aws bcm-data-exports list-exports --region us-east-1 \
    --query 'Exports[?Export.Name==`finops-cost-export`]'

# List S3 bucket contents (after 24 hours)
aws s3 ls s3://$CUR_BUCKET/cost-exports/ --recursive

# Expected structure (CREATE_NEW_REPORT mode):
# cost-exports/finops-cost-export/20241101-20241201/  (date range folders)
# cost-exports/finops-cost-export/20241201-20250101/
# Each folder contains: data files partitioned by year/month/day
```

### 3.2 AWS Glue Database and Crawler

**Purpose:** Crawls CUR data in S3 and creates Athena-queryable tables.

**Automated Setup:**

```bash
# Created automatically during fresh install via deploy.sh
# No manual action required if using automated deployment
```

**Manual Setup:**

```bash
# Create Glue database
aws glue create-database \
    --database-input '{"Name":"cost_usage_db","Description":"Database for AWS Cost and Usage Reports"}' \
    --region $AWS_REGION

# Get IAM role ARN for Glue (or create one)
GLUE_ROLE_ARN="arn:aws:iam::$AWS_ACCOUNT_ID:role/AWSGlueServiceRole-FinOps"

# Create Glue crawler
aws glue create-crawler \
    --name finops-cur-crawler \
    --role $GLUE_ROLE_ARN \
    --database-name cost_usage_db \
    --targets "{\"S3Targets\":[{\"Path\":\"s3://$CUR_BUCKET/cost-reports/finops-cost-report/finops-cost-report/\"}]}" \
    --schedule "cron(0 2 * * ? *)" \
    --region $AWS_REGION

# Run crawler manually (first time)
aws glue start-crawler --name finops-cur-crawler --region $AWS_REGION

# Check crawler status
aws glue get-crawler --name finops-cur-crawler --region $AWS_REGION \
    --query 'Crawler.{State:State,LastCrawl:LastCrawl.Status}'
```

**Verification:**

```bash
# List tables created by crawler
aws glue get-tables --database-name cost_usage_db --region $AWS_REGION \
    --query 'TableList[].Name'

# Expected output: finops_cost_report (or similar based on CUR path)

# View table schema
aws glue get-table --database-name cost_usage_db --name finops_cost_report \
    --region $AWS_REGION --query 'Table.StorageDescriptor.Columns[].Name'
```

### 3.3 Amazon Athena Workgroup

**Purpose:** Queries CUR data stored in S3 via Glue tables.

**Automated Setup:**

```bash
# Created automatically during fresh install via deploy.sh
# No manual action required
```

**Manual Setup:**

```bash
# Create Athena workgroup
aws athena create-work-group \
    --name finops-workgroup \
    --configuration "ResultConfiguration={OutputLocation=s3://$CUR_BUCKET/athena-results/}" \
    --region $AWS_REGION

# Verify workgroup
aws athena get-work-group --work-group finops-workgroup \
    --region $AWS_REGION --query 'WorkGroup.Name'
```

**Test Athena Query:**

```bash
# Run test query
QUERY_ID=$(aws athena start-query-execution \
    --query-string "SELECT line_item_product_code, SUM(line_item_unblended_cost) as total_cost FROM cost_usage_db.finops_cost_report GROUP BY line_item_product_code ORDER BY total_cost DESC LIMIT 10;" \
    --work-group finops-workgroup \
    --region $AWS_REGION \
    --query 'QueryExecutionId' \
    --output text)

echo "Query ID: $QUERY_ID"

# Wait for completion
sleep 5

# Check status
aws athena get-query-execution --query-execution-id $QUERY_ID \
    --region $AWS_REGION --query 'QueryExecution.Status.State'

# Get results (if SUCCEEDED)
aws athena get-query-results --query-execution-id $QUERY_ID \
    --region $AWS_REGION --output table
```

---

## 📦 Part 4: Main Application Deployment

### 4.1 CloudFormation Infrastructure Stack

The main CloudFormation stack creates:

- VPC with public/private subnets
- Security groups
- RDS PostgreSQL database
- ElastiCache Valkey cluster
- ECS Fargate cluster
- Application Load Balancer
- IAM roles and policies
- S3 bucket for application data
- CloudWatch log groups

**Automated Deployment:**

```bash
# Via deploy.sh script (recommended)
./deploy.sh deploy

# Script prompts for:
# - Bedrock model selection
# - Database password (auto-generated or reused)
# - CUR bucket name (optional)
# - Glue database configuration (optional)
```

**Manual Deployment:**

```bash
# Set variables
STACK_NAME="finops-intelligence-platform"
AWS_REGION="us-east-1"
ENVIRONMENT="production"
S3_BUCKET="${STACK_NAME}-data"
DB_PASSWORD=$(openssl rand -base64 32 | tr -dc 'A-Za-z0-9!#$%&*+<=>?^_~' | head -c 32)

# Deploy stack
aws cloudformation deploy \
    --template-file infrastructure/cloudformation/main-stack.yaml \
    --stack-name $STACK_NAME \
    --parameter-overrides \
        Environment=$ENVIRONMENT \
        DatabasePassword=$DB_PASSWORD \
        BedrockModelId=us.amazon.nova-pro-v1:0 \
        S3BucketName=$S3_BUCKET \
    --capabilities CAPABILITY_NAMED_IAM \
    --region $AWS_REGION

# Monitor progress
watch -n 10 "aws cloudformation describe-stacks --stack-name $STACK_NAME --region $AWS_REGION --query 'Stacks[0].StackStatus'"
```

**Stack Outputs:**

```bash
# Get stack outputs
aws cloudformation describe-stacks --stack-name $STACK_NAME --region $AWS_REGION \
    --query 'Stacks[0].Outputs' --output table

# Key outputs:
# - LoadBalancerDNS: Application URL
# - DatabaseEndpoint: RDS endpoint
# - ValkeyEndpoint: ElastiCache endpoint
# - ECSClusterName: ECS cluster name
# - VPCId: VPC identifier
```

### 4.2 Build and Push Docker Images

**Automated Build:**

```bash
# Via deploy.sh (included in main deployment)
./deploy.sh deploy

# Or update images only:
./deploy.sh update
```

**Manual Build:**

```bash
# Get AWS account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

# Create ECR repositories (if they don't exist)
aws ecr create-repository --repository-name finops-backend --region $AWS_REGION 2>/dev/null || true
aws ecr create-repository --repository-name finops-frontend --region $AWS_REGION 2>/dev/null || true

# Login to ECR
aws ecr get-login-password --region $AWS_REGION | \
    docker login --username AWS --password-stdin $ECR_REGISTRY

# Build and push backend
docker build --platform linux/amd64 -t finops-backend ./backend
docker tag finops-backend:latest ${ECR_REGISTRY}/finops-backend:latest
docker push ${ECR_REGISTRY}/finops-backend:latest

# Build and push frontend
docker build --platform linux/amd64 -t finops-frontend ./frontend
docker tag finops-frontend:latest ${ECR_REGISTRY}/finops-frontend:latest
docker push ${ECR_REGISTRY}/finops-frontend:latest
```

### 4.3 Deploy ECS Services

**Automated Deployment:**

```bash
# Via deploy.sh (included in main deployment)
./deploy.sh deploy
```

**Manual Deployment:**

```bash
# Get infrastructure outputs
DB_ENDPOINT=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --region $AWS_REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`DatabaseEndpoint`].OutputValue' --output text)

VALKEY_ENDPOINT=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --region $AWS_REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`ValkeyEndpoint`].OutputValue' --output text)

# Deploy ECS services stack
aws cloudformation deploy \
    --template-file infrastructure/cloudformation/ecs-services.yaml \
    --stack-name "${STACK_NAME}-services" \
    --parameter-overrides \
        ParentStackName=$STACK_NAME \
        BackendImageUri=${ECR_REGISTRY}/finops-backend:latest \
        FrontendImageUri=${ECR_REGISTRY}/finops-frontend:latest \
        DatabaseEndpoint=$DB_ENDPOINT \
        ValkeyEndpoint=$VALKEY_ENDPOINT \
        DatabasePassword=$DB_PASSWORD \
        BedrockModelId=us.amazon.nova-pro-v1:0 \
        # Nova 2 default model
        S3BucketName=$S3_BUCKET \
    --capabilities CAPABILITY_IAM \
    --region $AWS_REGION

# Monitor service startup
ECS_CLUSTER=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --region $AWS_REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`ECSClusterName`].OutputValue' --output text)

watch -n 10 "aws ecs describe-services --cluster $ECS_CLUSTER --services finops-backend finops-frontend --region $AWS_REGION --query 'services[].{Name:serviceName,Running:runningCount,Desired:desiredCount}' --output table"
```

---

## ✅ Part 5: Post-Deployment Verification

### 5.1 Check Stack Status

```bash
# CloudFormation stack status
aws cloudformation describe-stacks --stack-name $STACK_NAME --region $AWS_REGION \
    --query 'Stacks[0].StackStatus'

# Should return: CREATE_COMPLETE or UPDATE_COMPLETE
```

### 5.2 Get Application URL

```bash
# Get load balancer DNS
ALB_DNS=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --region $AWS_REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`LoadBalancerDNS`].OutputValue' --output text)

echo "🌐 Application URL: http://$ALB_DNS"
echo "📊 API Documentation: http://$ALB_DNS/docs"
```

### 5.3 Verify Services

```bash
# Check ECS services
ECS_CLUSTER=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --region $AWS_REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`ECSClusterName`].OutputValue' --output text)

aws ecs describe-services \
    --cluster $ECS_CLUSTER \
    --services finops-backend finops-frontend \
    --region $AWS_REGION \
    --query 'services[].{Name:serviceName,Status:status,Running:runningCount,Desired:desiredCount}' \
    --output table

# Check health endpoint
curl -f http://$ALB_DNS/health || echo "Services still starting..."

# Wait if needed
sleep 60
curl -f http://$ALB_DNS/health && echo "✅ Backend healthy"
```

### 5.4 Test API

```bash
# Test chat endpoint
curl -X POST http://$ALB_DNS/api/v1/chat \
    -H "Content-Type: application/json" \
    -d '{"message": "Hello, can you help me with AWS costs?"}' | jq

# Test Athena endpoints (if CUR configured)
curl http://$ALB_DNS/docs | grep -i athena
```

### 5.5 Access Web Interface

```bash
# Open in browser
open "http://$ALB_DNS"

# Try these sample queries:
# - "Show me my AWS costs for the last 30 days"
# - "What are my top 5 most expensive services?"
# - "How can I optimize my EC2 costs?"
```

---

## 🔧 Part 6: Configuration and Customization

### 6.1 Environment Variables

Key environment variables configured in ECS task definitions:

```bash
# AWS Configuration
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=<from-task-role>
AWS_SECRET_ACCESS_KEY=<from-task-role>

# Bedrock Configuration
BEDROCK_MODEL_ID=us.amazon.nova-pro-v1:0
BEDROCK_REGION=us-east-1
MAX_TOKENS=4000
TEMPERATURE=0.7

# Athena Configuration
ATHENA_WORKGROUP=finops-workgroup
ATHENA_OUTPUT_LOCATION=s3://your-cur-bucket/athena-results/
ATHENA_DATABASE=cost_usage_db
ATHENA_TABLE=finops_cost_report

# Database Configuration
DATABASE_URL=postgresql+asyncpg://user:pass@rds-endpoint:5432/finops
VALKEY_URL=redis://elasticache-endpoint:6379

# Application Settings
LOG_LEVEL=INFO
ENVIRONMENT=production
```

### 6.2 Switch Bedrock Model

```bash
# Option 1: Via CloudFormation stack update
aws cloudformation update-stack \
    --stack-name $STACK_NAME \
    --use-previous-template \
    --parameters ParameterKey=BedrockModelId,ParameterValue=amazon.nova-lite-v1:0 \
    --capabilities CAPABILITY_NAMED_IAM \
    --region $AWS_REGION

# Option 2: Update ECS task definition and restart services
# (See AWS ECS documentation)
```

### 6.3 Scale Services

```bash
# Scale backend service
aws ecs update-service \
    --cluster $ECS_CLUSTER \
    --service finops-backend \
    --desired-count 3 \
    --region $AWS_REGION

# Scale frontend service
aws ecs update-service \
    --cluster $ECS_CLUSTER \
    --service finops-frontend \
    --desired-count 2 \
    --region $AWS_REGION
```

---

## 🔍 Part 7: Troubleshooting

### 7.1 Stack Deployment Failures

```bash
# Check stack events
aws cloudformation describe-stack-events --stack-name $STACK_NAME --region $AWS_REGION \
    --query 'StackEvents[?ResourceStatus==`CREATE_FAILED` || ResourceStatus==`UPDATE_FAILED`].{Resource:LogicalResourceId,Reason:ResourceStatusReason}' \
    --output table

# Common issues:
# - Service limits exceeded: Check AWS Service Quotas
# - IAM permissions: Verify your AWS credentials
# - Resource naming conflicts: Ensure unique S3 bucket names
```

### 7.2 ECS Service Issues

```bash
# Check service events
aws ecs describe-services --cluster $ECS_CLUSTER --services finops-backend \
    --region $AWS_REGION --query 'services[0].events[0:5]' --output table

# Check task logs
aws logs tail /ecs/finops-backend --follow --region $AWS_REGION

# Check task definition
aws ecs describe-task-definition --task-definition finops-backend \
    --region $AWS_REGION --query 'taskDefinition.containerDefinitions[0].environment'
```

### 7.3 Bedrock Access Errors

```bash
# Test model access
aws bedrock-runtime invoke-model \
    --model-id amazon.nova-pro-v1:0 \
    --body '{"messages":[{"role":"user","content":[{"text":"Test"}]}],"inferenceConfig":{"max_new_tokens":10}}' \
    --cli-binary-format raw-in-base64-out \
    --region us-east-1 \
    /tmp/test.json

# If AccessDeniedException:
# 1. Enable model in Bedrock console
# 2. Check IAM permissions
# 3. Verify model availability in your region
```

### 7.4 Athena Query Failures

```bash
# Check Glue database
aws glue get-database --name cost_usage_db --region $AWS_REGION

# Check Glue tables
aws glue get-tables --database-name cost_usage_db --region $AWS_REGION

# Check Athena workgroup
aws athena get-work-group --work-group finops-workgroup --region $AWS_REGION

# Run diagnostic query
./tests/test-athena-query.py
```

### 7.5 CUR Data Not Available

```bash
# Check CUR report status
aws cur describe-report-definitions --region us-east-1

# Check S3 bucket
aws s3 ls s3://$CUR_BUCKET/cost-reports/ --recursive

# Run Glue crawler manually
aws glue start-crawler --name finops-cur-crawler --region $AWS_REGION

# Verify first report (takes 24 hours)
```

---

## 🧹 Part 8: Cleanup and Maintenance

### 8.1 Destroy Infrastructure

There are two options for cleanup:

#### Option 1: Partial Destruction (Recommended for Testing)

Destroys CloudFormation stacks and ECR repositories but **keeps data exports and S3 buckets**:

```bash
# Destroys: CloudFormation stacks, ECR, RDS, ECS, VPC
# Keeps: CUR/Data Exports, S3 buckets, Glue database, Athena workgroups
./deploy.sh destroy
```

**What gets deleted:**

- ✅ CloudFormation stack: `finops-intelligence-platform`
- ✅ CloudFormation stack: `finops-intelligence-platform-services`
- ✅ ECR repositories: `finops-backend`, `finops-frontend`
- ✅ RDS databases (and all conversation data)
- ✅ ECS clusters and tasks
- ✅ VPC and networking resources

**What is preserved:**

- ⚠️ CUR/Data Export reports (continue collecting cost data)
- ⚠️ S3 buckets (including historical cost data)
- ⚠️ Glue databases and tables
- ⚠️ Athena workgroups and query results

#### Option 2: Complete Destruction (Nuclear Option)

Destroys **EVERYTHING** including all data exports, S3 buckets, and historical data:

```bash
# ⚠️ WARNING: This deletes EVERYTHING - NO DATA CAN BE RECOVERED!
./deploy.sh destroyAll
```

This command will:

1. **Scan** all FinOps resources
2. **List** everything that will be deleted
3. **Require confirmation** (you must type `DELETE EVERYTHING`)
4. **Delete in order**:
   - Data Exports (both new and legacy CUR)
   - Glue databases and tables
   - Athena workgroups
   - CloudFormation stacks and ECR
   - S3 buckets (after emptying all contents and versions)
   - State files

**Example output:**

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THE FOLLOWING RESOURCES WILL BE PERMANENTLY DELETED:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ CloudFormation stack: finops-intelligence-platform
  ✓ CloudFormation stack: finops-intelligence-platform-services
  ✓ ECR repository: finops-backend
  ✓ ECR repository: finops-frontend
  ✓ Data Export: finops-cost-export
  ✓ S3 Bucket (with ALL data): finops-intelligence-platform-data-${AWS_ACCOUNT_ID}
  ✓ Glue Database: cost_usage_db (with all tables)
  ✓ Athena Workgroup: finops-workgroup
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Type 'DELETE EVERYTHING' to confirm complete destruction:
```

#### Manual Cleanup (Alternative)

If you prefer manual control:

```bash
# Delete CloudFormation stacks
aws cloudformation delete-stack --stack-name finops-intelligence-platform-services --region $AWS_REGION
aws cloudformation wait stack-delete-complete --stack-name finops-intelligence-platform-services --region $AWS_REGION

aws cloudformation delete-stack --stack-name finops-intelligence-platform --region $AWS_REGION
aws cloudformation wait stack-delete-complete --stack-name finops-intelligence-platform --region $AWS_REGION

# Delete ECR repositories
aws ecr delete-repository --repository-name finops-backend --force --region $AWS_REGION
aws ecr delete-repository --repository-name finops-frontend --force --region $AWS_REGION

# Delete Data Export (new API)
EXPORT_ARN=$(aws bcm-data-exports list-exports --region us-east-1 --query "Exports[?Export.Name=='finops-cost-export'].ExportArn" --output text)
aws bcm-data-exports delete-export --export-arn "$EXPORT_ARN" --region us-east-1

# Delete Glue database
aws glue delete-database --name cost_usage_db --region $AWS_REGION

# Delete Athena workgroup
aws athena delete-work-group --work-group finops-workgroup --recursive-delete-option --region $AWS_REGION

# Empty and delete S3 bucket
aws s3 rm s3://$CUR_BUCKET --recursive
aws s3 rb s3://$CUR_BUCKET --force
```

### 8.2 Regular Maintenance

```bash
# Update services with latest code
./deploy.sh update

# Check for AWS service updates
aws ecs describe-clusters --clusters $ECS_CLUSTER --region $AWS_REGION

# Review CloudWatch logs for errors
aws logs tail /ecs/finops-backend --since 1h --region $AWS_REGION | grep ERROR

# Monitor costs using the platform itself!
```

---

## 📚 Part 9: Additional Resources

### Scripts and Tools

- `deploy.sh` - Main deployment script with infrastructure detection
- `scripts/setup/setup-cur.sh` - CUR setup script (optional, can run standalone)
- `scripts/setup/verify-cur-setup.sh` - Verify CUR configuration
- `scripts/setup/verify-deployment-env.sh` - Verify deployment environment
- `scripts/utilities/convert_csv_to_parquet.py` - Convert CSV to Parquet format
- `scripts/fill_historical_data.py` - Backfill historical data

### Documentation

- [README.md](../README.md) - Project overview and quick start
- [QUICK_START.md](./QUICK_START.md) - Developer guide with examples
- [DEPLOYMENT_CHECKLIST.md](./DEPLOYMENT_CHECKLIST.md) - Pre-deployment verification
- [DEPLOYMENT_STRATEGY.md](./DEPLOYMENT_STRATEGY.md) - Deployment strategies
- [DATA_ARCHITECTURE.md](./DATA_ARCHITECTURE.md) - Data architecture guide
- [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) - Common issues and solutions

### AWS Documentation Links

- [AWS Cost and Usage Reports](https://docs.aws.amazon.com/cur/latest/userguide/)
- [Amazon Athena User Guide](https://docs.aws.amazon.com/athena/)
- [AWS Glue Developer Guide](https://docs.aws.amazon.com/glue/)
- [Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/)
- [AWS ECS Best Practices](https://docs.aws.amazon.com/AmazonECS/latest/bestpracticesguide/)

---

## 📞 Support

For issues or questions:

- Check troubleshooting section above
- Review CloudWatch logs
- Verify AWS service quotas
- Check CloudFormation stack events

**⚠️ Important Notes:**

- CUR setup is **optional** - platform works with Cost Explorer API
- First CUR report takes **24 hours** to generate
- Bedrock model access must be **enabled** before deployment
- Always test in non-production environment first
- Review AWS costs before large-scale deployment

**🎉 Deployment Complete!**

Your FinOps AI Cost Intelligence Platform is ready to use!
