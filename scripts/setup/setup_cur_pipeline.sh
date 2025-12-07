#!/usr/bin/env bash
set -euo pipefail

# Setup CUR 2.0 data pipeline for Athena without a Glue crawler by default.
# - Archives all Manifest.json files to keep Athena reads clean
# - Optionally creates a lightweight Glue Crawler targeting the cleaned prefix
# - Creates/updates Athena external table cost_usage_db.cur_data from manifest schema
#
# Requirements:
# - AWS CLI configured
# - Python 3 available

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log() { echo -e "${BLUE}[CUR-SETUP]${NC} $*"; }
ok()  { echo -e "${GREEN}[OK]${NC} $*"; }
warn(){ echo -e "${YELLOW}[WARN]${NC} $*"; }
err() { echo -e "${RED}[ERR]${NC} $*"; }

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/../.. && pwd)"

# Load deployment.env if present (provides AWS_ACCOUNT_ID, etc.)
if [ -f "$ROOT_DIR/deployment.env" ]; then
  # shellcheck disable=SC1090
  source "$ROOT_DIR/deployment.env"
fi

AWS_REGION="${AWS_REGION:-us-east-1}"
ATHENA_DB="${AWS_CUR_DATABASE:-cost_usage_db}"
ATHENA_TABLE="${AWS_CUR_TABLE:-cur_data}"
CUR_BUCKET_DEFAULT="finops-intelligence-platform-data-${AWS_ACCOUNT_ID:-XXXX}"
CUR_BUCKET="${CUR_S3_BUCKET:-$CUR_BUCKET_DEFAULT}"
# Raw CUR 2.0 delivery prefix
CUR_PREFIX="${CUR_S3_PREFIX:-cost-exports/finops-cost-export}"
# Archive location for manifests
ARCHIVE_PREFIX="_archived-manifests"

log "Using bucket=$CUR_BUCKET, prefix=$CUR_PREFIX, region=$AWS_REGION"

ensure_bucket_exists() {
  if ! aws s3 ls "s3://$CUR_BUCKET" --region "$AWS_REGION" >/dev/null 2>&1; then
    err "Bucket s3://$CUR_BUCKET not found. Export CUR_S3_BUCKET or create the bucket."
    return 1
  fi
}

archive_existing_manifests() {
  log "Archiving any existing Manifest.json files to s3://$CUR_BUCKET/$ARCHIVE_PREFIX/"
  # Move both top-level and nested manifests
  mapfile -t manifest_keys < <(aws s3 ls "s3://$CUR_BUCKET/$CUR_PREFIX/" --recursive --region "$AWS_REGION" | awk '/Manifest.json$/ {print $4}')
  if [ ${#manifest_keys[@]} -eq 0 ]; then
    ok "No Manifest.json files to archive."
    return 0
  fi
  for key in "${manifest_keys[@]}"; do
    dest_key="$ARCHIVE_PREFIX/$(echo "$key" | tr '/' '_')"
    aws s3 mv "s3://$CUR_BUCKET/$key" "s3://$CUR_BUCKET/$dest_key" --region "$AWS_REGION" >/dev/null
    echo "Archived: $key -> $dest_key"
  done
  ok "Archived ${#manifest_keys[@]} manifest files."
}

generate_table_from_manifest() {
  # Pick the newest manifest to read schema from (works even after archiving, so grab before archiving next time)
  local tmp_manifest="/tmp/cur_manifest.json"
  local latest_manifest
  latest_manifest=$(aws s3 ls "s3://$CUR_BUCKET/$ARCHIVE_PREFIX/" --region "$AWS_REGION" 2>/dev/null | awk '{print $4}' | sort | tail -1)
  if [ -z "$latest_manifest" ]; then
    warn "No archived manifest found; attempting to read one from CUR prefix (if present)."
    latest_manifest=$(aws s3 ls "s3://$CUR_BUCKET/$CUR_PREFIX/" --recursive --region "$AWS_REGION" | awk '/Manifest.json$/ {print $4}' | sort | tail -1 || true)
  fi
  if [ -z "$latest_manifest" ]; then
    err "Unable to locate any Manifest.json to derive schema. Ensure at least one CUR delivery exists."
    return 1
  fi
  aws s3 cp "s3://$CUR_BUCKET/$latest_manifest" "$tmp_manifest" --region "$AWS_REGION" >/dev/null

  python3 "$ROOT_DIR/scripts/generate_cur_table_ddl.py" > /tmp/create_cur_from_manifest.sql
  # Replace LOCATION to target the raw CUR prefix (manifests were archived)
  sed -i '' "s|LOCATION 's3://.*/'|LOCATION 's3://$CUR_BUCKET/$CUR_PREFIX/'|" /tmp/create_cur_from_manifest.sql || true

  # Execute DROP + CREATE separately via Athena
  aws athena start-query-execution \
    --query-string "DROP TABLE IF EXISTS $ATHENA_DB.$ATHENA_TABLE" \
    --work-group "${ATHENA_WORKGROUP:-finops-workgroup}" \
    --result-configuration OutputLocation="s3://$CUR_BUCKET/athena-results/" \
    --region "$AWS_REGION" >/dev/null

  # Send only the CREATE statement
  grep -v "^DROP" /tmp/create_cur_from_manifest.sql > /tmp/_create_only.sql
  aws athena start-query-execution \
    --query-string "$(cat /tmp/_create_only.sql)" \
    --work-group "${ATHENA_WORKGROUP:-finops-workgroup}" \
    --result-configuration OutputLocation="s3://$CUR_BUCKET/athena-results/" \
    --region "$AWS_REGION" >/dev/null
  ok "Created/updated Athena table $ATHENA_DB.$ATHENA_TABLE"
}

create_lambda_archiver() {
  local role_name="finops-cur-lambda-role"
  local fn_name="finops-cur-manifest-archiver"

  log "Ensuring Lambda IAM role $role_name"
  if ! aws iam get-role --role-name "$role_name" --region "$AWS_REGION" >/dev/null 2>&1; then
    cat > /tmp/lambda-trust.json <<EOF
{ "Version":"2012-10-17", "Statement":[{ "Effect":"Allow", "Principal":{"Service":"lambda.amazonaws.com"}, "Action":"sts:AssumeRole" }] }
EOF
    aws iam create-role --role-name "$role_name" \
      --assume-role-policy-document file:///tmp/lambda-trust.json \
      --region "$AWS_REGION" >/dev/null
    aws iam attach-role-policy --role-name "$role_name" \
      --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole \
      --region "$AWS_REGION" >/dev/null
    aws iam put-role-policy --role-name "$role_name" --policy-name CurBucketAccess \
      --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"s3:GetObject\",\"s3:PutObject\",\"s3:ListBucket\",\"s3:CopyObject\"],\"Resource\":[\"arn:aws:s3:::$CUR_BUCKET\",\"arn:aws:s3:::$CUR_BUCKET/*\"]}]}" \
      --region "$AWS_REGION" >/dev/null
    ok "Created role $role_name"
  fi

  log "Packaging and creating Lambda $fn_name"
  local zip_path="/tmp/cur-archiver.zip"
  pushd "$ROOT_DIR/scripts/lambda" >/dev/null
  zip -q -r "$zip_path" cur_manifest_archiver.py
  popd >/dev/null

  local role_arn
  role_arn=$(aws iam get-role --role-name "$role_name" --region "$AWS_REGION" --query 'Role.Arn' --output text)
  if ! aws lambda get-function --function-name "$fn_name" --region "$AWS_REGION" >/dev/null 2>&1; then
    aws lambda create-function \
      --function-name "$fn_name" \
      --runtime python3.11 \
      --handler cur_manifest_archiver.handler \
      --timeout 120 \
      --memory-size 256 \
      --role "$role_arn" \
      --environment "Variables={BUCKET=$CUR_BUCKET,SOURCE_PREFIX=$CUR_PREFIX,ARCHIVE_PREFIX=$ARCHIVE_PREFIX}" \
      --zip-file fileb://"$zip_path" \
      --region "$AWS_REGION" >/dev/null
    ok "Created Lambda $fn_name"
  else
    aws lambda update-function-code --function-name "$fn_name" --zip-file fileb://"$zip_path" --region "$AWS_REGION" >/dev/null
    ok "Updated Lambda code for $fn_name"
  fi

  # Allow S3 to invoke Lambda and set bucket notification
  aws lambda add-permission \
    --function-name "$fn_name" \
    --statement-id curS3Invoke \
    --action lambda:InvokeFunction \
    --principal s3.amazonaws.com \
    --source-arn "arn:aws:s3:::$CUR_BUCKET" \
    --region "$AWS_REGION" >/dev/null 2>&1 || true

  log "Configuring S3 bucket notification to trigger Lambda for new CUR objects"
  cat > /tmp/s3-notify.json <<EOF
{ "LambdaFunctionConfigurations": [
  { "LambdaFunctionArn": "$(aws lambda get-function --function-name "$fn_name" --region "$AWS_REGION" --query 'Configuration.FunctionArn' --output text)",
    "Events": ["s3:ObjectCreated:*"],
    "Filter": { "Key": { "FilterRules": [ {"Name": "prefix", "Value": "$CUR_PREFIX/"} ] } }
  }
] }
EOF
  aws s3api put-bucket-notification-configuration \
    --bucket "$CUR_BUCKET" \
    --notification-configuration file:///tmp/s3-notify.json \
    --region "$AWS_REGION"
  ok "S3 -> Lambda notification configured"
}

validate_query() {
  log "Validating Athena table $ATHENA_DB.$ATHENA_TABLE"
  qid=$(aws athena start-query-execution \
    --query-string "SELECT COUNT(*) AS total FROM $ATHENA_DB.$ATHENA_TABLE" \
    --work-group "${ATHENA_WORKGROUP:-finops-workgroup}" \
    --result-configuration OutputLocation="s3://$CUR_BUCKET/athena-results/" \
    --region "$AWS_REGION" --query 'QueryExecutionId' --output text)
  sleep 10
  state=$(aws athena get-query-execution --query-execution-id "$qid" --region "$AWS_REGION" --query 'QueryExecution.Status.State' --output text)
  if [ "$state" != "SUCCEEDED" ]; then
    err "Athena validation failed. Check query execution $qid"
    return 1
  fi
  ok "Athena validation SUCCEEDED (query: $qid)"
}

main() {
  ensure_bucket_exists
  archive_existing_manifests
  create_lambda_archiver
  generate_table_from_manifest
  validate_query
  ok "CUR pipeline setup complete."
}

main "$@"
