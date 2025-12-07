#!/usr/bin/env bash
# Create a unified cur_data view from timestamped Glue tables
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

ENV_FILE="${1:-deployment.env}"
source "$ENV_FILE"

AWS_CUR_DATABASE="${AWS_CUR_DATABASE:-cost_usage_db}"
AWS_CUR_TABLE="${AWS_CUR_TABLE:-cur_data}"
AWS_REGION="${AWS_REGION:-us-east-1}"
ATHENA_OUTPUT_LOCATION="${ATHENA_OUTPUT_LOCATION:-s3://finops-intelligence-platform-athena-results-515966519020/}"
ATHENA_WORKGROUP="${ATHENA_WORKGROUP:-finops-workgroup}"

log_info "Creating unified CUR view: $AWS_CUR_DATABASE.$AWS_CUR_TABLE"

# Get the latest timestamped table (highest timestamp)
LATEST_TABLE=$(aws glue get-tables --database-name "$AWS_CUR_DATABASE" --region "$AWS_REGION" \
  --query 'TableList[].Name' --output text | tr '\t' '\n' | grep '^202[45]' | sort -r | head -1)

if [ -z "$LATEST_TABLE" ]; then
  log_error "No timestamped tables found in database $AWS_CUR_DATABASE"
  exit 1
fi

log_info "Latest CUR table: $LATEST_TABLE"

# Get table location to verify it has Parquet files
TABLE_LOCATION=$(aws glue get-table --database-name "$AWS_CUR_DATABASE" --name "$LATEST_TABLE" \
  --region "$AWS_REGION" --query 'Table.StorageDescriptor.Location' --output text)

log_info "Table location: $TABLE_LOCATION"

# Create or replace view
VIEW_SQL="CREATE OR REPLACE VIEW ${AWS_CUR_DATABASE}.${AWS_CUR_TABLE} AS SELECT * FROM ${AWS_CUR_DATABASE}.\"${LATEST_TABLE}\""

log_info "Creating view with SQL:"
log_info "$VIEW_SQL"

QUERY_ID=$(aws athena start-query-execution \
  --query-string "$VIEW_SQL" \
  --query-execution-context "Database=$AWS_CUR_DATABASE" \
  --result-configuration "OutputLocation=$ATHENA_OUTPUT_LOCATION" \
  --work-group "$ATHENA_WORKGROUP" \
  --region "$AWS_REGION" \
  --query 'QueryExecutionId' \
  --output text)

log_info "Query ID: $QUERY_ID"
log_info "Waiting for view creation..."

for i in {1..30}; do
  STATUS=$(aws athena get-query-execution --query-execution-id "$QUERY_ID" --region "$AWS_REGION" \
    --query 'QueryExecution.Status.State' --output text)
  
  if [ "$STATUS" = "SUCCEEDED" ]; then
    log_success "✅ View created: $AWS_CUR_DATABASE.$AWS_CUR_TABLE"
    
    # Test the view
    log_info "Testing view with sample query..."
    TEST_QUERY="SELECT COUNT(*) as total_rows FROM ${AWS_CUR_DATABASE}.${AWS_CUR_TABLE} LIMIT 1"
    
    TEST_ID=$(aws athena start-query-execution \
      --query-string "$TEST_QUERY" \
      --query-execution-context "Database=$AWS_CUR_DATABASE" \
      --result-configuration "OutputLocation=$ATHENA_OUTPUT_LOCATION" \
      --work-group "$ATHENA_WORKGROUP" \
      --region "$AWS_REGION" \
      --query 'QueryExecutionId' \
      --output text)
    
    sleep 5
    
    TEST_STATUS=$(aws athena get-query-execution --query-execution-id "$TEST_ID" --region "$AWS_REGION" \
      --query 'QueryExecution.Status.State' --output text)
    
    if [ "$TEST_STATUS" = "SUCCEEDED" ]; then
      ROWS=$(aws athena get-query-results --query-execution-id "$TEST_ID" --region "$AWS_REGION" \
        --query 'ResultSet.Rows[1].Data[0].VarCharValue' --output text)
      log_success "✅ View is queryable! Total rows: $ROWS"
    else
      ERROR=$(aws athena get-query-execution --query-execution-id "$TEST_ID" --region "$AWS_REGION" \
        --query 'QueryExecution.Status.StateChangeReason' --output text)
      log_warning "View created but test query failed: $ERROR"
    fi
    
    exit 0
  elif [ "$STATUS" = "FAILED" ]; then
    ERROR=$(aws athena get-query-execution --query-execution-id "$QUERY_ID" --region "$AWS_REGION" \
      --query 'QueryExecution.Status.StateChangeReason' --output text)
    log_error "View creation failed: $ERROR"
    exit 1
  fi
  
  sleep 1
done

log_error "View creation timed out"
exit 1
