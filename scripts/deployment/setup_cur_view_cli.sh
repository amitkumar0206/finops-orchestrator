#!/usr/bin/env bash
set -euo pipefail

# Unified CUR view creation using AWS CLI + jq (no boto3 required)
# - Discovers Glue tables and picks latest per billing period
# - Computes common columns across tables
# - Creates/updates Athena view cost_usage_db.cur_data
#
# Usage: bash scripts/deployment/setup_cur_view_cli.sh [deployment.env]

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info(){ echo -e "${BLUE}[INFO]${NC} $1"; }
log_success(){ echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning(){ echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error(){ echo -e "${RED}[ERROR]${NC} $1"; }

ENV_FILE="${1:-deployment.env}"
if [[ ! -f "$ENV_FILE" ]]; then
  log_error "Env file not found: $ENV_FILE"; exit 1
fi

# shellcheck disable=SC1090
source "$ENV_FILE"

AWS_REGION="${AWS_REGION:-us-east-1}"
DB_NAME="${AWS_CUR_DATABASE:-cost_usage_db}"
VIEW_NAME="${AWS_CUR_TABLE:-cur_data}"
WG="${ATHENA_WORKGROUP:-finops-workgroup}"
OUTPUT_LOC="${ATHENA_OUTPUT_LOCATION:-s3://finops-intelligence-platform-athena-results-$(aws sts get-caller-identity --query Account --output text)/}"

log_info "Region: $AWS_REGION"
log_info "Database: $DB_NAME"
log_info "View: $VIEW_NAME"
log_info "Workgroup: $WG"
log_info "Results: $OUTPUT_LOC"

require(){ command -v "$1" >/dev/null 2>&1 || { log_error "Missing dependency: $1"; exit 1; }; }
require aws
require jq

# Paginate Glue get-tables
log_info "Listing Glue tables..."
TABLES_JSON='[]'
NEXT_TOKEN=""
while :; do
  if [[ -n "$NEXT_TOKEN" ]]; then
    PAGE=$(aws glue get-tables --database-name "$DB_NAME" --region "$AWS_REGION" --next-token "$NEXT_TOKEN")
  else
    PAGE=$(aws glue get-tables --database-name "$DB_NAME" --region "$AWS_REGION")
  fi
  TABLES_JSON=$(jq -c --argjson a "$TABLES_JSON" --argjson b "$(echo "$PAGE" | jq -c '.TableList')" '$a + $b')
  NEXT_TOKEN=$(echo "$PAGE" | jq -r '.NextToken // ""')
  [[ -z "$NEXT_TOKEN" ]] && break
done

COUNT=$(echo "$TABLES_JSON" | jq 'length')
log_info "Found $COUNT tables in Glue"

if [[ "$COUNT" -eq 0 ]]; then
  log_error "No tables found. Ensure crawler ran."; exit 1
fi

# Build a map of latest table per billing period from S3 location path
# Location pattern contains /YYYYMMDD-YYYYMMDD/ and /YYYYMMDDT...Z/
LATEST_MAP=$(echo "$TABLES_JSON" | jq -r --arg view "$VIEW_NAME" '
  map(select(.Name != $view))
  | map({name:.Name, loc:(.StorageDescriptor.Location // "")})
  | map(select(.loc != ""))
  | map(. + {
      period: (.loc | capture("/(?<p>\\d{8}-\\d{8})/").p // null),
      ts: (.loc | capture("/(?<t>\\d{8}T\\d{6}Z)/i").t // .name)
    })
  | map(select(.period != null))
  | reduce .[] as $t ({ };
      .[$t.period] = (if (.[$t.period] // null) then
         (if ($t.ts > .[$t.period].ts) then $t else .[$t.period] end)
       else $t end))
')

PERIODS=$(echo "$LATEST_MAP" | jq -r 'keys | length')
log_info "Billing periods discovered: $PERIODS"
if [[ "$PERIODS" -eq 0 ]]; then
  log_error "Could not detect billing periods from table locations."; exit 1
fi

# Selected tables list
SELECTED_TABLES=$(echo "$LATEST_MAP" | jq -r 'to_entries | map(.value.name)')
log_info "Selected latest tables per period: $(echo "$SELECTED_TABLES" | jq -r 'join(", ")')"

# Compute common columns across selected tables using Glue column metadata
log_info "Computing common columns across tables..."
COMMON_COLS=$(echo "$TABLES_JSON" | jq -r --argjson sel "$SELECTED_TABLES" '
  map(select([.Name] | inside($sel)))
  | map({name:.Name, cols:(.StorageDescriptor.Columns // [])})
  | map({name, cols: [ .cols[].Name ]})
  | (if length == 0 then [] else
      reduce .[1:][] as $t (.[0].cols; . as $all | map(select(. as $i | $t.cols | index($i))) )
    end)
')

COL_COUNT=$(echo "$COMMON_COLS" | jq 'length')
if [[ "$COL_COUNT" -eq 0 ]]; then
  log_error "No common columns found across tables; cannot build a stable view."; exit 1
fi
log_info "Common column count: $COL_COUNT"

# Build SQL
COL_LIST=$(echo "$COMMON_COLS" | jq -r 'map("\"" + . + "\"") | join(", ")')
UNION_PARTS=$(echo "$SELECTED_TABLES" | jq -r --arg db "$DB_NAME" --arg cols "$COL_LIST" '
  map("SELECT " + $cols + " FROM " + $db + ".\"" + . + "\"") | join("\nUNION ALL\n")
')
SQL=$(cat <<EOF
CREATE OR REPLACE VIEW $DB_NAME.$VIEW_NAME AS
$UNION_PARTS
EOF
)

log_info "Creating/Updating view in Athena..."
QID=$(aws athena start-query-execution \
  --query-string "$SQL" \
  --query-execution-context Database="$DB_NAME" \
  --work-group "$WG" \
  --result-configuration OutputLocation="$OUTPUT_LOC" \
  --region "$AWS_REGION" \
  --output text --query 'QueryExecutionId')

for i in {1..90}; do
  STATE=$(aws athena get-query-execution --query-execution-id "$QID" --region "$AWS_REGION" --output text --query 'QueryExecution.Status.State')
  [[ "$STATE" == "SUCCEEDED" ]] && break
  [[ "$STATE" == "FAILED" || "$STATE" == "CANCELLED" ]] && {
    ERR=$(aws athena get-query-execution --query-execution-id "$QID" --region "$AWS_REGION" --output text --query 'QueryExecution.Status.StateChangeReason')
    log_error "Create view failed: $ERR"; exit 1; }
  sleep 1
done

if [[ "$STATE" != "SUCCEEDED" ]]; then
  log_error "Timed out waiting for view creation"; exit 1
fi
log_success "View created: $DB_NAME.$VIEW_NAME"

# Quick validation
log_info "Validating view returns data (last 60 days)..."
START=$(date -v-60d +%F 2>/dev/null || date -d '60 days ago' +%F)
END=$(date +%F)
VAL_SQL=$(cat <<EOF
SELECT DATE(line_item_usage_start_date) d, count(*) c
FROM $DB_NAME.$VIEW_NAME
WHERE line_item_usage_start_date >= TIMESTAMP '$START' AND line_item_usage_start_date < TIMESTAMP '$END'
LIMIT 1
EOF
)
VQ=$(aws athena start-query-execution \
  --query-string "$VAL_SQL" \
  --query-execution-context Database="$DB_NAME" \
  --work-group "$WG" \
  --result-configuration OutputLocation="$OUTPUT_LOC" \
  --region "$AWS_REGION" \
  --output text --query 'QueryExecutionId')

for i in {1..60}; do
  S=$(aws athena get-query-execution --query-execution-id "$VQ" --region "$AWS_REGION" --output text --query 'QueryExecution.Status.State')
  [[ "$S" == "SUCCEEDED" ]] && break
  [[ "$S" == "FAILED" || "$S" == "CANCELLED" ]] && break
  sleep 1
done

if [[ "$S" == "SUCCEEDED" ]]; then
  ROWS=$(aws athena get-query-results --query-execution-id "$VQ" --region "$AWS_REGION" --output text --query 'length(ResultSet.Rows)')
  if [[ "$ROWS" -gt 1 ]]; then
    log_success "Validation OK: view returned data"
  else
    log_warning "View created but returned 0 rows in the last 60 days"
  fi
else
  ERR=$(aws athena get-query-execution --query-execution-id "$VQ" --region "$AWS_REGION" --output text --query 'QueryExecution.Status.StateChangeReason')
  log_warning "Validation query failed: $ERR"
fi
