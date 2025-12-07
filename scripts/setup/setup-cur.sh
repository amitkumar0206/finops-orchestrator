#!/bin/bash

# FinOps Platform - Cost and Usage Data Export Setup Script
# This script sets up AWS Standard Data Exports (replaces legacy CUR)
# 
# NOTE: Data exports are OPTIONAL. The platform works immediately with Cost Explorer API (13 months).
# Only run this script if you need detailed analysis beyond 13 months of history.

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Check if running from deploy.sh or standalone
if [ -z "$RUNNING_FROM_DEPLOY" ]; then
    echo ""
    echo "======================================================================"
    echo "     AWS Standard Data Export Setup - OPTIONAL (Standalone Mode)    "
    echo "======================================================================"
    echo ""
    echo "ℹ️  NOTE: This setup is OPTIONAL"
    echo ""
    echo "The FinOps platform works immediately with AWS Cost Explorer API,"
    echo "which provides 13 months of historical data with no setup required."
    echo ""
    echo "Data exports are only needed if you want:"
    echo "  • Detailed analysis beyond 13 months"
    echo "  • Resource-level cost attribution"
    echo "  • Custom reporting via Athena"
    echo ""
    read -p "Do you want to continue with data export setup? (yes/no): " CONTINUE_SETUP

    if [ "$CONTINUE_SETUP" != "yes" ]; then
        echo ""
        log_info "Data export setup cancelled. Your platform will use Cost Explorer API."
        log_info "You can run this script again anytime to enable data exports."
        echo ""
        exit 0
    fi

    echo ""
    log_info "Proceeding with data export setup..."
    echo ""
fi

# Configuration
STACK_NAME="${STACK_NAME:-finops-intelligence-platform}"
AWS_REGION="${AWS_REGION:-us-east-1}"
STATE_FILE=".deploy-state.env"
EXPORT_NAME="finops-cost-export"

# Reuse bucket from state file or deployment.env if it exists
if [ -f "$STATE_FILE" ]; then
    EXISTING_BUCKET=$(awk -F'=' '$1=="S3_BUCKET"{print $2}' "$STATE_FILE")
    if [ -n "$EXISTING_BUCKET" ]; then
        CUR_BUCKET_NAME="$EXISTING_BUCKET"
        log_info "Reusing existing S3 bucket from state: $CUR_BUCKET_NAME"
    fi
elif [ -f "deployment.env" ]; then
    EXISTING_BUCKET=$(awk -F'=' '$1=="S3_BUCKET"{print $2}' "deployment.env")
    if [ -n "$EXISTING_BUCKET" ]; then
        CUR_BUCKET_NAME="$EXISTING_BUCKET"
        log_info "Reusing existing S3 bucket from deployment: $CUR_BUCKET_NAME"
    fi
fi

# Determine results bucket (from deployment.env if available), else default canonical
ATHENA_RESULTS_BUCKET=""
if [ -f "deployment.env" ]; then
  ATHENA_RESULTS_BUCKET=$(awk -F'=' '$1=="ATHENA_RESULTS_BUCKET"{print $2}' deployment.env)
fi
if [ -z "$ATHENA_RESULTS_BUCKET" ]; then
  AWS_ACCOUNT_ID_DETECT=$(aws sts get-caller-identity --query Account --output text)
  ATHENA_RESULTS_BUCKET="finops-intelligence-platform-athena-results-${AWS_ACCOUNT_ID_DETECT}"
fi

# Get AWS Account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# If no existing bucket, create new bucket name with AWS account ID for global uniqueness
if [ -z "$CUR_BUCKET_NAME" ]; then
    CUR_BUCKET_NAME="finops-intelligence-platform-data-${AWS_ACCOUNT_ID}"
    log_info "No existing bucket found. Will create: $CUR_BUCKET_NAME"
fi

log_info "Setting up AWS Standard Data Exports..."
log_info "Stack Name: $STACK_NAME"
log_info "Region: $AWS_REGION"
log_info "S3 Bucket: $CUR_BUCKET_NAME"
log_info "Export Name: $EXPORT_NAME"
log_info "AWS Account ID: $AWS_ACCOUNT_ID"

# Check if bucket already exists
BUCKET_EXISTS=false
if aws s3api head-bucket --bucket "$CUR_BUCKET_NAME" 2>/dev/null; then
    log_info "S3 bucket $CUR_BUCKET_NAME already exists"
    BUCKET_EXISTS=true
else
    # Skip bucket creation if called from deploy.sh (CloudFormation will create it)
    if [ "$RUNNING_FROM_DEPLOY" = "true" ] && [ "$SKIP_BUCKET_CREATION" = "true" ]; then
        log_warning "S3 bucket does not exist yet - CloudFormation will create it"
        log_warning "Skipping bucket policy setup for now (will be applied after bucket creation)"
    else
        # Create S3 bucket for data exports
        log_info "Creating S3 bucket for data exports..."
        aws s3 mb "s3://$CUR_BUCKET_NAME" --region "$AWS_REGION"
        log_success "S3 bucket created successfully"
        BUCKET_EXISTS=true
    fi
fi

# Only apply bucket policy if bucket exists
if [ "$BUCKET_EXISTS" = false ]; then
    log_warning "Skipping bucket policy setup - bucket will be created by CloudFormation"
    log_info "Please run 'scripts/setup/setup-cur.sh' again after deployment completes to apply bucket policy and setup data exports"
    exit 0
fi

# Create bucket policy for Data Exports (uses bcm-data-exports service)
log_info "Creating bucket policy to allow Data Exports service access..."
cat > /tmp/data-export-bucket-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DataExportsGetBucketInfo",
      "Effect": "Allow",
      "Principal": {
        "Service": "billingreports.amazonaws.com"
      },
      "Action": [
        "s3:GetBucketAcl",
        "s3:GetBucketPolicy"
      ],
      "Resource": "arn:aws:s3:::$CUR_BUCKET_NAME",
      "Condition": {
        "StringLike": {
          "aws:SourceArn": "arn:aws:cur:us-east-1:$AWS_ACCOUNT_ID:definition/*",
          "aws:SourceAccount": "$AWS_ACCOUNT_ID"
        }
      }
    },
    {
      "Sid": "DataExportsPutObject",
      "Effect": "Allow",
      "Principal": {
        "Service": "billingreports.amazonaws.com"
      },
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::$CUR_BUCKET_NAME/*",
      "Condition": {
        "StringLike": {
          "aws:SourceArn": "arn:aws:cur:us-east-1:$AWS_ACCOUNT_ID:definition/*",
          "aws:SourceAccount": "$AWS_ACCOUNT_ID"
        }
      }
    },
    {
      "Sid": "BCMDataExportsGetBucketInfo",
      "Effect": "Allow",
      "Principal": {
        "Service": "bcm-data-exports.amazonaws.com"
      },
      "Action": [
        "s3:GetBucketAcl",
        "s3:GetBucketPolicy"
      ],
      "Resource": "arn:aws:s3:::$CUR_BUCKET_NAME",
      "Condition": {
        "StringLike": {
          "aws:SourceArn": "arn:aws:bcm-data-exports:*:$AWS_ACCOUNT_ID:export/*",
          "aws:SourceAccount": "$AWS_ACCOUNT_ID"
        }
      }
    },
    {
      "Sid": "BCMDataExportsPutObject",
      "Effect": "Allow",
      "Principal": {
        "Service": "bcm-data-exports.amazonaws.com"
      },
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::$CUR_BUCKET_NAME/*",
      "Condition": {
        "StringLike": {
          "aws:SourceArn": "arn:aws:bcm-data-exports:*:$AWS_ACCOUNT_ID:export/*",
          "aws:SourceAccount": "$AWS_ACCOUNT_ID"
        }
      }
    }
  ]
}
EOF

# Apply bucket policy
aws s3api put-bucket-policy \
    --bucket "$CUR_BUCKET_NAME" \
    --policy file:///tmp/data-export-bucket-policy.json

log_success "Bucket policy applied successfully"

# Create Standard Data Export using bcm-data-exports
log_info "Creating Standard Data Export definition..."

# Check if export already exists
EXISTING_EXPORT=$(aws bcm-data-exports list-exports --region us-east-1 --query "Exports[?Export.Name=='$EXPORT_NAME'].Export.Name" --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_EXPORT" ]; then
    log_warning "Data export '$EXPORT_NAME' already exists"
    
    if [ -z "$RUNNING_FROM_DEPLOY" ]; then
        read -p "Do you want to delete and recreate it? (yes/no): " RECREATE
        
        if [ "$RECREATE" = "yes" ]; then
            log_info "Deleting existing data export..."
            EXPORT_ARN=$(aws bcm-data-exports list-exports --region us-east-1 --query "Exports[?Export.Name=='$EXPORT_NAME'].ExportArn" --output text)
            aws bcm-data-exports delete-export --export-arn "$EXPORT_ARN" --region us-east-1
            log_success "Existing data export deleted"
            sleep 5
        else
            log_info "Keeping existing data export"
            EXISTING_EXPORT=""  # Skip creation
        fi
    else
        log_info "Keeping existing data export (running from deploy.sh)"
        EXISTING_EXPORT=""  # Skip creation
    fi
fi

if [ -z "$EXISTING_EXPORT" ]; then
    # Skip CUR creation - requires billing/administrator permissions
    log_warning "⚠️  Skipping CUR report creation (requires administrator permissions)"
    log_info "CUR report must be created manually by an administrator with billing access"
    echo ""
    log_info "To create CUR manually:"
    log_info "  1. Go to AWS Billing Console → Cost & Usage Reports"
    log_info "  2. Create report with these settings:"
    log_info "     - Name: $EXPORT_NAME"
    log_info "     - Time granularity: Daily"
    log_info "     - Format: Parquet"
    log_info "     - Enable resource IDs: Yes"
    log_info "     - S3 bucket: $CUR_BUCKET_NAME"
    log_info "     - S3 prefix: cost-exports"
    log_info "     - Report versioning: Create new report version"
    log_info "     - Enable data integration: Amazon Athena"
    echo ""
    log_info "Platform will use Cost Explorer API (13 months) until CUR is manually created"
    echo ""
fi

# Set up Athena workgroup for data export queries
log_info "Setting up Athena workgroup..."
aws athena create-work-group \
  --name finops-workgroup \
  --configuration "ResultConfiguration={OutputLocation=s3://$ATHENA_RESULTS_BUCKET/}" \
  --region "$AWS_REGION" 2>/dev/null || log_info "Athena workgroup already exists"
log_success "Athena workgroup configured"

# Setup Glue database for data export tables
log_info "Setting up Glue database..."
aws glue create-database \
    --database-input "{\"Name\":\"cost_usage_db\",\"Description\":\"Database for AWS cost and usage data exports\"}" \
    --region "$AWS_REGION" 2>/dev/null || log_info "Glue database already exists"
log_success "Glue database configured"

# Create Glue crawler for data export
log_info "Setting up Glue crawler for data export..."

# Get or create IAM role for Glue
GLUE_ROLE_NAME="AWSGlueServiceRole-FinOps"
GLUE_ROLE_ARN="arn:aws:iam::$AWS_ACCOUNT_ID:role/$GLUE_ROLE_NAME"

# Check if role exists, if not provide instructions
if ! aws iam get-role --role-name "$GLUE_ROLE_NAME" &>/dev/null; then
    log_info "Creating Glue service role..."
    
    # Create trust policy
    cat > /tmp/glue-trust-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "glue.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF
    
    # Create role
    aws iam create-role \
        --role-name "$GLUE_ROLE_NAME" \
        --assume-role-policy-document file:///tmp/glue-trust-policy.json \
        --description "Service role for AWS Glue to access S3 and Glue resources" || true
    
    # Attach AWS managed policy
    aws iam attach-role-policy \
        --role-name "$GLUE_ROLE_NAME" \
        --policy-arn "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole" || true
    
    # Create inline policy for S3 access
    cat > /tmp/glue-s3-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject"
      ],
      "Resource": "arn:aws:s3:::$CUR_BUCKET_NAME/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:ListBucket"
      ],
      "Resource": "arn:aws:s3:::$CUR_BUCKET_NAME"
    }
  ]
}
EOF
    
    aws iam put-role-policy \
        --role-name "$GLUE_ROLE_NAME" \
        --policy-name "FinOpsS3Access" \
        --policy-document file:///tmp/glue-s3-policy.json || true
    
    log_success "Glue service role created"
    sleep 10  # Wait for role propagation
else
    log_info "Glue service role already exists"
fi

# Create Glue crawler for DETAILED CUR data (not historical backfill)
# Important: Point to the CUR export directory, not the parent cost-exports/
# This ensures we get the full 300+ column CUR schema, not the 19-column aggregated data
CRAWLER_NAME="finops-cost-export-crawler"
log_info "Creating Glue crawler: $CRAWLER_NAME"

# The CUR data is in: cost-exports/{export-name}/{YYYYMMDD-YYYYMMDD}/
# We point to cost-exports/{export-name}/ to pick up all date-partitioned CUR exports
# CRITICAL EXCLUSIONS:
# 1. **/{export-name}/** - Excludes historical backfill data (19 columns) to avoid schema conflicts
# 2. **/*Manifest.json - Excludes JSON manifest files that cause "Malformed Parquet" errors
# 3. **/*.json - Excludes all JSON files to prevent Athena query failures
log_info "Crawler will scan: s3://$CUR_BUCKET_NAME/cost-exports/$EXPORT_NAME/"
log_info "Exclusions: historical backfill + JSON manifest files"

# Check if crawler already exists and delete it to recreate with correct config
if aws glue get-crawler --name "$CRAWLER_NAME" --region "$AWS_REGION" &>/dev/null; then
    log_warning "Crawler already exists. Deleting and recreating with updated configuration..."
    aws glue delete-crawler --name "$CRAWLER_NAME" --region "$AWS_REGION" || true
    sleep 5
fi

aws glue create-crawler \
    --name "$CRAWLER_NAME" \
    --role "$GLUE_ROLE_ARN" \
    --database-name cost_usage_db \
    --targets "{\"S3Targets\":[{\"Path\":\"s3://$CUR_BUCKET_NAME/cost-exports/$EXPORT_NAME/\",\"Exclusions\":[\"**/$EXPORT_NAME/**\",\"**/*Manifest.json\",\"**/*.json\"]}]}" \
    --schedule "cron(0 3 * * ? *)" \
    --schema-change-policy "{\"UpdateBehavior\":\"UPDATE_IN_DATABASE\",\"DeleteBehavior\":\"LOG\"}" \
    --configuration "{\"Version\":1.0,\"CrawlerOutput\":{\"Partitions\":{\"AddOrUpdateBehavior\":\"InheritFromTable\"}},\"Grouping\":{\"TableGroupingPolicy\":\"CombineCompatibleSchemas\"}}" \
    --region "$AWS_REGION"
log_success "Glue crawler configured (will run daily at 3 AM UTC)"
log_info "✓ Excludes: historical backfill data and JSON manifest files"

# Create separate crawler for historical aggregated data (optional)
HISTORICAL_CRAWLER_NAME="finops-historical-aggregated-crawler"
log_info "Creating crawler for historical aggregated data: $HISTORICAL_CRAWLER_NAME"

# Check if historical crawler already exists
if aws glue get-crawler --name "$HISTORICAL_CRAWLER_NAME" --region "$AWS_REGION" &>/dev/null; then
    log_info "Historical crawler already exists"
else
    aws glue create-crawler \
        --name "$HISTORICAL_CRAWLER_NAME" \
        --role "$GLUE_ROLE_ARN" \
        --database-name cost_usage_db \
        --targets "{\"S3Targets\":[{\"Path\":\"s3://$CUR_BUCKET_NAME/cost-exports/$EXPORT_NAME/$EXPORT_NAME/\"}]}" \
        --schedule "cron(0 4 * * ? *)" \
        --schema-change-policy "{\"UpdateBehavior\":\"UPDATE_IN_DATABASE\",\"DeleteBehavior\":\"LOG\"}" \
        --configuration "{\"Version\":1.0,\"CrawlerOutput\":{\"Partitions\":{\"AddOrUpdateBehavior\":\"InheritFromTable\"}}}" \
        --region "$AWS_REGION"
    log_success "Historical data crawler configured"
fi

# Save configuration to file for future reference
log_info "Saving configuration..."
CREATED_TIMESTAMP=$(date -u +"%Y-%m-%d %H:%M:%S UTC")
cat > cur-config.env << EOF
# AWS Cost and Usage Data Export Configuration
CUR_BUCKET_NAME="$CUR_BUCKET_NAME"
EXPORT_NAME="$EXPORT_NAME"
AWS_REGION="$AWS_REGION"
ATHENA_WORKGROUP="finops-workgroup"
GLUE_DATABASE="cost_usage_db"
GLUE_CRAWLER="$CRAWLER_NAME"
GLUE_HISTORICAL_CRAWLER="$HISTORICAL_CRAWLER_NAME"
EXPORT_TYPE="CUR"
VERSIONING_MODE="CREATE_NEW_REPORT"
CREATED_AT="$CREATED_TIMESTAMP"
# Note: CUR table will be auto-created by crawler with name like: {date_range}
# Historical table will be: finops_cost_export (aggregated monthly data)
EOF

log_success "Configuration saved to cur-config.env"

# Clean up temp files
rm -f /tmp/data-export-bucket-policy.json /tmp/legacy-cur-definition.json
rm -f /tmp/glue-trust-policy.json /tmp/glue-s3-policy.json
rm -f /tmp/cur-error.log

echo ""
log_success "✅ AWS infrastructure setup completed!"
echo ""

# Verify what was actually created
log_info "Verifying created resources..."
echo ""

CUR_EXISTS=$(aws cur describe-report-definitions --region us-east-1 --query "ReportDefinitions[?ReportName=='$EXPORT_NAME'].ReportName" --output text 2>/dev/null || echo "")
GLUE_DB_EXISTS=$(aws glue get-database --name cost_usage_db --region "$AWS_REGION" 2>/dev/null && echo "yes" || echo "no")
ATHENA_WG_EXISTS=$(aws athena get-work-group --work-group finops-workgroup --region "$AWS_REGION" 2>/dev/null && echo "yes" || echo "no")
S3_BUCKET_EXISTS=$(aws s3 ls "s3://$CUR_BUCKET_NAME" 2>/dev/null && echo "yes" || echo "no")
CRAWLER_EXISTS=$(aws glue get-crawler --name "$CRAWLER_NAME" --region "$AWS_REGION" 2>/dev/null && echo "yes" || echo "no")

echo "📊 Resource Creation Status:"
if [ -n "$CUR_EXISTS" ]; then
    echo "   ✅ CUR Report: $EXPORT_NAME (already exists)"
else
    echo "   ⚠️  CUR Report: NOT CREATED (requires administrator to create manually)"
fi

if [ "$S3_BUCKET_EXISTS" = "yes" ]; then
    echo "   ✅ S3 Bucket: $CUR_BUCKET_NAME"
else
    echo "   ❌ S3 Bucket: NOT FOUND"
fi

if [ "$GLUE_DB_EXISTS" = "yes" ]; then
    echo "   ✅ Glue Database: cost_usage_db"
else
    echo "   ❌ Glue Database: NOT FOUND"
fi

if [ "$CRAWLER_EXISTS" = "yes" ]; then
    echo "   ✅ Glue Crawler: $CRAWLER_NAME"
else
    echo "   ❌ Glue Crawler: NOT FOUND"
fi

if [ "$ATHENA_WG_EXISTS" = "yes" ]; then
    echo "   ✅ Athena Workgroup: finops-workgroup"
else
    echo "   ❌ Athena Workgroup: NOT FOUND"
fi

echo ""

if [ -n "$CUR_EXISTS" ]; then
    echo "📊 CUR Configuration:"
    echo "   Report Name: $EXPORT_NAME"
    echo "   Report Type: Cost and Usage Report (CUR)"
    echo "   Versioning Mode: CREATE_NEW_REPORT (preserves all historical data)"
    echo "   S3 Bucket: $CUR_BUCKET_NAME"
    echo "   S3 Prefix: cost-exports/"
    echo "   Format: Parquet (optimized for Athena)"
    echo "   Frequency: Daily"
    echo "   Resources: Included"
    echo "   Glue Database: cost_usage_db"
    echo "   Glue Crawler: $CRAWLER_NAME (runs daily at 3 AM)"
    echo "   Athena Workgroup: finops-workgroup"
    echo ""
    echo "⏰ Note: It may take up to 24 hours for the first export to be generated."
    echo "📍 Exports will be stored at: s3://$CUR_BUCKET_NAME/cost-exports/"
    echo ""
    echo "✅ Historical Data Safety:"
    echo "   • CREATE_NEW_REPORT mode preserves ALL historical data"
    echo "   • Each month creates new versioned reports"
    echo "   • Old data is NEVER overwritten or deleted"
    echo "   • Glue crawler discovers all time partitions automatically"
    echo ""
    echo "🔄 Next Steps:"
    echo "   1. Wait 24 hours for first export"
    echo "   2. Run Glue crawler: aws glue start-crawler --name $CRAWLER_NAME --region $AWS_REGION"
else
    echo "⚠️  CUR Report Not Created"
    echo ""
    echo "Infrastructure created successfully but CUR report requires manual setup:"
    echo ""
    echo "✅ Created:"
    echo "   • S3 Bucket: $CUR_BUCKET_NAME"
    echo "   • Glue Database: cost_usage_db"
    echo "   • Glue Crawler: $CRAWLER_NAME"
    echo "   • Athena Workgroup: finops-workgroup"
    echo ""
    echo "⚠️  Manual Action Required:"
    echo "   Ask an AWS administrator to create CUR report with these settings:"
    echo "   → AWS Billing Console → Cost & Usage Reports → Create report"
    echo "   - Report name: $EXPORT_NAME"
    echo "   - Time granularity: Daily"
    echo "   - Report versioning: Create new report version"
    echo "   - Enable resource IDs: Yes"
    echo "   - Data integration: Amazon Athena"
    echo "   - S3 bucket: $CUR_BUCKET_NAME"
    echo "   - S3 prefix: cost-exports"
    echo "   - Format: Parquet"
    echo ""
    echo "💡 Your platform will work with Cost Explorer API (13 months) in the meantime."
    echo ""
fi

echo "🔄 Next Steps (continued):"
echo "   3. Verify tables: aws glue get-tables --database-name cost_usage_db --region $AWS_REGION"
echo "   4. Query via Athena workgroup: finops-workgroup"
echo ""
echo "💡 Data Strategy:"
echo "   • Recent queries (0-13 months): Cost Explorer API (fast)"
echo "   • Historical queries (13+ months): Data export via Athena (detailed)"
echo "   • Detailed CUR table: Full 300+ columns with resource-level data"
echo "   • Historical aggregated table: 19 columns with monthly summaries"
echo ""
echo "📊 Table Structure:"
echo "   • CUR table (detailed): s3://$CUR_BUCKET_NAME/cost-exports/$EXPORT_NAME/{YYYYMMDD-YYYYMMDD}/"
echo "   • Historical table (aggregated): s3://$CUR_BUCKET_NAME/cost-exports/$EXPORT_NAME/$EXPORT_NAME/year=YYYY/month=MM/"
echo ""
echo "🚀 Run './scripts/utilities/verify-athena-data.sh' to verify your complete data setup"
echo ""

# Provide helper commands
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Quick Commands:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "# Run crawlers manually (after CUR data is available):"
echo "aws glue start-crawler --name $CRAWLER_NAME --region $AWS_REGION"
echo "aws glue start-crawler --name $HISTORICAL_CRAWLER_NAME --region $AWS_REGION"
echo ""
echo "# Check crawler status:"
echo "aws glue get-crawler --name $CRAWLER_NAME --region $AWS_REGION | jq '.Crawler.State'"
echo ""
echo "# List tables:"
echo "aws glue get-tables --database-name cost_usage_db --region $AWS_REGION | jq '.TableList[].Name'"
echo ""
echo "# Verify table has detailed data:"
echo "./scripts/utilities/verify-athena-data.sh"
echo ""
