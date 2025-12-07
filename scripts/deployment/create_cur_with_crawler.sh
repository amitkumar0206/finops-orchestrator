#!/usr/bin/env bash
# ============================================================================
# Use AWS Glue Crawler to Auto-Discover CUR Schema
# ============================================================================
# This approach is more reliable than manual CREATE TABLE because:
# 1. Glue automatically detects the correct Parquet schema
# 2. It excludes non-Parquet files (like Manifest.json)
# 3. It handles partition discovery
# 4. It's the AWS-recommended approach for CUR tables
# ============================================================================

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Load config
ENV_FILE="${1:-deployment.env}"
source "$ENV_FILE"

CUR_S3_BUCKET="${CUR_S3_BUCKET:-$S3_BUCKET}"
CUR_S3_PREFIX="${CUR_S3_PREFIX:-cost-exports/finops-cost-export}"
AWS_CUR_DATABASE="${AWS_CUR_DATABASE:-cost_usage_db}"
AWS_CUR_TABLE="${AWS_CUR_TABLE:-cur_data}"
AWS_REGION="${AWS_REGION:-us-east-1}"
# Results location for ad hoc queries
ATHENA_RESULTS_BUCKET="${ATHENA_RESULTS_BUCKET:-}"
if [ -z "$ATHENA_RESULTS_BUCKET" ]; then
    AWS_ACCOUNT_ID_DETECT=$(aws sts get-caller-identity --query Account --output text)
    ATHENA_RESULTS_BUCKET="finops-intelligence-platform-athena-results-${AWS_ACCOUNT_ID_DETECT}"
fi
ATHENA_OUTPUT_LOCATION="${ATHENA_OUTPUT_LOCATION:-s3://${ATHENA_RESULTS_BUCKET}/}"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
CRAWLER_NAME="finops-cur-crawler"
CRAWLER_ROLE_NAME="AWSGlueServiceRole-FinOpsCUR"

log_info "=== CUR Schema Auto-Discovery with Glue Crawler ==="
log_info "Database: $AWS_CUR_DATABASE"
log_info "Table: $AWS_CUR_TABLE"
log_info "S3 Path: s3://$CUR_S3_BUCKET/$CUR_S3_PREFIX/"

# ============================================================================
# Step 1: Create Glue Service Role (if needed)
# ============================================================================

log_info "Checking for Glue service role..."

if aws iam get-role --role-name "$CRAWLER_ROLE_NAME" --region "$AWS_REGION" > /dev/null 2>&1; then
    log_success "Glue role exists: $CRAWLER_ROLE_NAME"
else
    log_info "Creating Glue service role..."
    
    # Create trust policy
    cat > /tmp/glue-trust-policy.json <<EOF
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
        --role-name "$CRAWLER_ROLE_NAME" \
        --assume-role-policy-document file:///tmp/glue-trust-policy.json \
        --region "$AWS_REGION" > /dev/null
    
    # Attach AWS managed policy
    aws iam attach-role-policy \
        --role-name "$CRAWLER_ROLE_NAME" \
        --policy-arn "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole" \
        --region "$AWS_REGION"
    
    # Add S3 access policy
    cat > /tmp/glue-s3-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::$CUR_S3_BUCKET",
        "arn:aws:s3:::$CUR_S3_BUCKET/*"
      ]
    }
  ]
}
EOF
    
    aws iam put-role-policy \
        --role-name "$CRAWLER_ROLE_NAME" \
        --policy-name "FinOpsCURAccess" \
        --policy-document file:///tmp/glue-s3-policy.json \
        --region "$AWS_REGION"
    
    log_success "Glue role created: $CRAWLER_ROLE_NAME"
    log_info "Waiting 10 seconds for IAM propagation..."
    sleep 10
fi

CRAWLER_ROLE_ARN="arn:aws:iam::$AWS_ACCOUNT_ID:role/$CRAWLER_ROLE_NAME"

# ============================================================================
# Step 2: Delete old table if exists
# ============================================================================

log_info "Cleaning up old table..."
aws glue delete-table \
    --database-name "$AWS_CUR_DATABASE" \
    --name "$AWS_CUR_TABLE" \
    --region "$AWS_REGION" 2>/dev/null || true

# ============================================================================
# Step 3: Create or Update Crawler
# ============================================================================

log_info "Creating/updating Glue crawler..."

# Check if crawler exists
if aws glue get-crawler --name "$CRAWLER_NAME" --region "$AWS_REGION" > /dev/null 2>&1; then
    log_info "Updating existing crawler..."
    
    aws glue update-crawler \
        --name "$CRAWLER_NAME" \
        --role "$CRAWLER_ROLE_ARN" \
        --database-name "$AWS_CUR_DATABASE" \
        --targets "{\"S3Targets\":[{\"Path\":\"s3://$CUR_S3_BUCKET/$CUR_S3_PREFIX/\",\"Exclusions\":[\"**.json\",\"**.gz\",\"**.zip\"]}]}" \
        --table-prefix "" \
        --schema-change-policy "{\"UpdateBehavior\":\"UPDATE_IN_DATABASE\",\"DeleteBehavior\":\"LOG\"}" \
        --recrawl-policy "{\"RecrawlBehavior\":\"CRAWL_EVERYTHING\"}" \
        --configuration "{\"Version\":1.0,\"CrawlerOutput\":{\"Partitions\":{\"AddOrUpdateBehavior\":\"InheritFromTable\"},\"Tables\":{\"AddOrUpdateBehavior\":\"MergeNewColumns\"}}}" \
        --region "$AWS_REGION"
    
    log_success "Crawler updated"
else
    log_info "Creating new crawler..."
    
    aws glue create-crawler \
        --name "$CRAWLER_NAME" \
        --role "$CRAWLER_ROLE_ARN" \
        --database-name "$AWS_CUR_DATABASE" \
        --targets "{\"S3Targets\":[{\"Path\":\"s3://$CUR_S3_BUCKET/$CUR_S3_PREFIX/\",\"Exclusions\":[\"**.json\",\"**.gz\",\"**.zip\"]}]}" \
        --table-prefix "" \
        --schema-change-policy "{\"UpdateBehavior\":\"UPDATE_IN_DATABASE\",\"DeleteBehavior\":\"LOG\"}" \
        --recrawl-policy "{\"RecrawlBehavior\":\"CRAWL_EVERYTHING\"}" \
        --configuration "{\"Version\":1.0,\"CrawlerOutput\":{\"Partitions\":{\"AddOrUpdateBehavior\":\"InheritFromTable\"},\"Tables\":{\"AddOrUpdateBehavior\":\"MergeNewColumns\"}}}" \
        --region "$AWS_REGION"
    
    log_success "Crawler created"
fi

# ============================================================================
# Step 4: Run Crawler
# ============================================================================

log_info "Starting crawler (this may take 2-5 minutes)..."

aws glue start-crawler \
    --name "$CRAWLER_NAME" \
    --region "$AWS_REGION"

log_info "Waiting for crawler to complete..."

for i in {1..180}; do
    STATUS=$(aws glue get-crawler \
        --name "$CRAWLER_NAME" \
        --region "$AWS_REGION" \
        --query 'Crawler.State' \
        --output text)
    
    if [ "$STATUS" = "READY" ]; then
        LAST_CRAWL=$(aws glue get-crawler \
            --name "$CRAWLER_NAME" \
            --region "$AWS_REGION" \
            --query 'Crawler.LastCrawl' \
            --output json)
        
        if echo "$LAST_CRAWL" | grep -q "SUCCEEDED"; then
            log_success "Crawler completed successfully!"
            break
        elif echo "$LAST_CRAWL" | grep -q "FAILED"; then
            ERROR=$(echo "$LAST_CRAWL" | jq -r '.ErrorMessage // "Unknown error"')
            log_error "Crawler failed: $ERROR"
            exit 1
        fi
    fi
    
    if [ $((i % 10)) -eq 0 ]; then
        log_info "Still running... ($i seconds elapsed)"
    fi
    
    sleep 1
done

# ============================================================================
# Step 5: Rename Table if Needed
# ============================================================================

# Glue crawler creates table with sanitized S3 path name
# We need to rename it to our desired table name
CREATED_TABLE=$(aws glue get-tables \
    --database-name "$AWS_CUR_DATABASE" \
    --region "$AWS_REGION" \
    --query "TableList[?starts_with(Name, '2024') || starts_with(Name, '2025')].Name" \
    --output text | head -1)

if [ -n "$CREATED_TABLE" ] && [ "$CREATED_TABLE" != "$AWS_CUR_TABLE" ]; then
    log_info "Renaming table from '$CREATED_TABLE' to '$AWS_CUR_TABLE'..."
    
    # Get table definition
    TABLE_INPUT=$(aws glue get-table \
        --database-name "$AWS_CUR_DATABASE" \
        --name "$CREATED_TABLE" \
        --region "$AWS_REGION" \
        --query 'Table.{Name:Name,StorageDescriptor:StorageDescriptor,PartitionKeys:PartitionKeys,TableType:TableType,Parameters:Parameters}' \
        --output json)
    
    # Update name
    NEW_TABLE_INPUT=$(echo "$TABLE_INPUT" | jq ".Name = \"$AWS_CUR_TABLE\"")
    
    # Create new table
    echo "$NEW_TABLE_INPUT" > /tmp/table-input.json
    aws glue create-table \
        --database-name "$AWS_CUR_DATABASE" \
        --table-input file:///tmp/table-input.json \
        --region "$AWS_REGION"
    
    # Delete old table
    aws glue delete-table \
        --database-name "$AWS_CUR_DATABASE" \
        --name "$CREATED_TABLE" \
        --region "$AWS_REGION"
    
    log_success "Table renamed to: $AWS_CUR_TABLE"
fi

# ============================================================================
# Step 6: Validate
# ============================================================================

log_info "Validating CUR data access..."

VALIDATION_SQL="SELECT 
  DATE(line_item_usage_start_date) as usage_date,
  line_item_product_code,
  CAST(SUM(line_item_unblended_cost) AS DECIMAL(10,2)) as total_cost,
  COUNT(*) as line_items
FROM $AWS_CUR_DATABASE.$AWS_CUR_TABLE
WHERE line_item_usage_start_date >= DATE '2024-10-01'
  AND line_item_usage_start_date < DATE '2024-12-01'
  AND line_item_line_item_type = 'Usage'
  AND line_item_unblended_cost > 0
GROUP BY DATE(line_item_usage_start_date), line_item_product_code
ORDER BY total_cost DESC
LIMIT 10"

QUERY_ID=$(aws athena start-query-execution \
    --query-string "$VALIDATION_SQL" \
    --query-execution-context "Database=$AWS_CUR_DATABASE" \
    --result-configuration "OutputLocation=${ATHENA_OUTPUT_LOCATION}" \
    --work-group "${ATHENA_WORKGROUP:-finops-workgroup}" \
    --region "$AWS_REGION" \
    --query 'QueryExecutionId' \
    --output text)

log_info "Running validation query... ($QUERY_ID)"

for i in {1..60}; do
    STATUS=$(aws athena get-query-execution \
        --query-execution-id "$QUERY_ID" \
        --region "$AWS_REGION" \
        --query 'QueryExecution.Status.State' \
        --output text)
    
    if [ "$STATUS" = "SUCCEEDED" ]; then
        RESULT_COUNT=$(aws athena get-query-results \
            --query-execution-id "$QUERY_ID" \
            --region "$AWS_REGION" \
            --query 'length(ResultSet.Rows)' \
            --output text)
        
        if [ "$RESULT_COUNT" -gt 1 ]; then
            log_success "✅ CUR data accessible! Found $((RESULT_COUNT - 1)) cost records"
            
            log_info "Top services by cost:"
            aws athena get-query-results \
                --query-execution-id "$QUERY_ID" \
                --region "$AWS_REGION" \
                --query 'ResultSet.Rows[1:6]' \
                --output table
        else
            log_warning "Table created but no data returned"
        fi
        break
    elif [ "$STATUS" = "FAILED" ]; then
        ERROR=$(aws athena get-query-execution \
            --query-execution-id "$QUERY_ID" \
            --region "$AWS_REGION" \
            --query 'QueryExecution.Status.StateChangeReason' \
            --output text)
        log_error "Query failed: $ERROR"
        exit 1
    fi
    
    sleep 1
done

# ============================================================================
# Success!
# ============================================================================

echo ""
log_success "==========================================="
log_success "✅ CUR Schema Auto-Discovery Complete!"
log_success "==========================================="
log_success "Database: $AWS_CUR_DATABASE"
log_success "Table: $AWS_CUR_TABLE"
log_success "Columns: Auto-detected from Parquet schema"
log_success "==========================================="
echo ""
log_info "Next: Restart backend ECS service to use CUR data"
echo ""
