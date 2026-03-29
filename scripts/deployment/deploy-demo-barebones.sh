#!/bin/bash

set -euo pipefail

# Standalone bare-bones demo deployment:
# - no RDS deployment
# - no custom domain/ACM deployment
# - optional cleanup of existing RDS instances created by aasmaa stacks
# NOTE: Default stack name is 'aasmaa-demo-barebones' — the old 'aasmaa-demo'
#       name may be stuck in a CloudFormation ghost/terminal state.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/../setup/load_deploy_config.sh" ]; then
  # shellcheck disable=SC1091
  source "$SCRIPT_DIR/../setup/load_deploy_config.sh"
  # Force demo profile unless explicitly overridden by DEPLOY_CONFIG/DEPLOY_CONFIG_FILE
  export DEPLOY_CONFIG="${DEPLOY_CONFIG:-demo}"
  load_deploy_config
fi

STACK_NAME="${STACK_NAME:-aasmaa-demo-barebones}"
AWS_REGION="${AWS_REGION:-us-east-1}"
ENVIRONMENT="${ENVIRONMENT:-development}"
BEDROCK_MODEL="${BEDROCK_MODEL:-us.amazon.nova-lite-v1:0}"
DEMO_ALLOWED_ACCOUNT_IDS="${DEMO_ALLOWED_ACCOUNT_IDS:-123456789012}"
DEMO_USER_EMAIL="${DEMO_USER_EMAIL:-demo@aasmaa.ai}"
DEMO_ORGANIZATION_NAME="${DEMO_ORGANIZATION_NAME:-Demo Organization}"
CLEANUP_EXISTING_RDS="${CLEANUP_EXISTING_RDS:-true}"
BUILD_IMAGES="${BUILD_IMAGES:-true}"
DISABLE_ROLLBACK="${DISABLE_ROLLBACK:-true}"
DEMO_DOMAIN_NAME="${DEMO_DOMAIN_NAME:-demo.aasmaa.ai}"
DEMO_HOSTED_ZONE_ID="${DEMO_HOSTED_ZONE_ID:-}"

log() {
  echo "[demo-barebones] $1"
}

require_tool() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required tool: $1" >&2
    exit 1
  fi
}

cleanup_stuck_stacks() {
  # Delete any stacks that are stuck in terminal failure states that prevent
  # a fresh deploy. CloudFormation does not allow updating stacks in these states.
  local bad_statuses="ROLLBACK_COMPLETE ROLLBACK_FAILED UPDATE_ROLLBACK_FAILED CREATE_FAILED DELETE_FAILED"
  for status in $bad_statuses; do
    local matching
    matching="$(aws cloudformation list-stacks \
      --region "$AWS_REGION" \
      --stack-status-filter "$status" \
      --query "StackSummaries[?StackName=='${STACK_NAME}' || StackName=='${STACK_NAME}-services'].StackName" \
      --output text 2>/dev/null || true)"
    for s in $matching; do
      [[ -z "$s" || "$s" == "None" ]] && continue
      log "Stack '$s' is in status $status — deleting so we can redeploy"
      aws cloudformation delete-stack --stack-name "$s" --region "$AWS_REGION"
      aws cloudformation wait stack-delete-complete --stack-name "$s" --region "$AWS_REGION" || true
      log "Deleted stuck stack: $s"
    done
  done
}

cleanup_rds_from_stack() {
  local stack="$1"
  local db_ids

  db_ids="$(aws cloudformation list-stack-resources \
    --stack-name "$stack" \
    --region "$AWS_REGION" \
    --query 'StackResourceSummaries[?ResourceType==`AWS::RDS::DBInstance`].PhysicalResourceId' \
    --output text 2>/dev/null || true)"

  if [[ -z "$db_ids" || "$db_ids" == "None" ]]; then
    return 0
  fi

  for db_id in $db_ids; do
    [[ -z "$db_id" || "$db_id" == "None" ]] && continue

    log "Found RDS instance in stack '$stack': $db_id"

    local delete_protection
    delete_protection="$(aws rds describe-db-instances \
      --db-instance-identifier "$db_id" \
      --region "$AWS_REGION" \
      --query 'DBInstances[0].DeletionProtection' \
      --output text 2>/dev/null || echo "false")"

    if [[ "$delete_protection" == "True" || "$delete_protection" == "true" ]]; then
      log "Disabling delete protection for $db_id"
      aws rds modify-db-instance \
        --db-instance-identifier "$db_id" \
        --no-deletion-protection \
        --apply-immediately \
        --region "$AWS_REGION" >/dev/null
      aws rds wait db-instance-available --db-instance-identifier "$db_id" --region "$AWS_REGION"
    fi

    log "Deleting RDS instance $db_id"
    aws rds delete-db-instance \
      --db-instance-identifier "$db_id" \
      --skip-final-snapshot \
      --delete-automated-backups \
      --region "$AWS_REGION" >/dev/null
    aws rds wait db-instance-deleted --db-instance-identifier "$db_id" --region "$AWS_REGION"
    log "Deleted RDS instance: $db_id"
  done
}

cleanup_existing_rds() {
  local stacks
  stacks="$(aws cloudformation list-stacks \
    --region "$AWS_REGION" \
    --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE UPDATE_ROLLBACK_COMPLETE ROLLBACK_COMPLETE \
    --query 'StackSummaries[?contains(StackName, `aasmaa`)].StackName' \
    --output text 2>/dev/null || true)"

  if [[ -z "$stacks" || "$stacks" == "None" ]]; then
    log "No aasmaa stacks found for RDS cleanup"
    return 0
  fi

  for stack in $stacks; do
    cleanup_rds_from_stack "$stack"
  done
}

require_tool aws
require_tool docker

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
ECR_REGISTRY="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
S3_BUCKET="${S3_BUCKET:-aasmaa-demo-data-${ACCOUNT_ID}}"
CUR_BUCKET="${CUR_BUCKET:-$S3_BUCKET}"
CUR_PREFIX="${CUR_PREFIX:-demo-cur/}"
ATHENA_DB="${ATHENA_DB:-cost_and_usage_db}"
ATHENA_TABLE="${ATHENA_TABLE:-costandusagereport}"
DB_PASSWORD_PLACEHOLDER="demo-disabled-db-password"
BACKEND_IMAGE_URI="${BACKEND_IMAGE_URI:-${ECR_REGISTRY}/aasmaa-backend:demo}"
FRONTEND_IMAGE_URI="${FRONTEND_IMAGE_URI:-${ECR_REGISTRY}/aasmaa-frontend:demo}"

log "Authenticated as: $(aws sts get-caller-identity --query Arn --output text)"
log "Using stack: $STACK_NAME"
log "Using region: $AWS_REGION"

if [[ "$CLEANUP_EXISTING_RDS" == "true" ]]; then
  log "Checking for existing RDS resources in aasmaa stacks"
  cleanup_existing_rds
fi

log "Checking for stuck CloudFormation stacks that would block deployment"
cleanup_stuck_stacks

log "Ensuring S3 bucket exists: $S3_BUCKET"
aws s3api head-bucket --bucket "$S3_BUCKET" >/dev/null 2>&1 || aws s3 mb "s3://${S3_BUCKET}" --region "$AWS_REGION"

log "Ensuring ECR repositories exist"
aws ecr create-repository --repository-name aasmaa-backend --region "$AWS_REGION" >/dev/null 2>&1 || true
aws ecr create-repository --repository-name aasmaa-frontend --region "$AWS_REGION" >/dev/null 2>&1 || true

if [[ "$BUILD_IMAGES" == "true" ]]; then
  log "Logging into ECR"
  aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_REGISTRY"

  log "Building and pushing backend image"
  docker build --platform linux/amd64 -f backend/Dockerfile -t aasmaa-backend:demo .
  docker tag aasmaa-backend:demo "$BACKEND_IMAGE_URI"
  docker push "$BACKEND_IMAGE_URI"

  log "Building and pushing frontend image"
  docker build --platform linux/amd64 -f frontend/Dockerfile -t aasmaa-frontend:demo .
  docker tag aasmaa-frontend:demo "$FRONTEND_IMAGE_URI"
  docker push "$FRONTEND_IMAGE_URI"
fi

DISABLE_ROLLBACK_FLAG=()
if [[ "$DISABLE_ROLLBACK" == "true" ]]; then
  DISABLE_ROLLBACK_FLAG+=(--disable-rollback)
fi

log "Deploying demo infrastructure stack (no domain, no RDS)"
aws cloudformation deploy \
  --template-file infrastructure/cloudformation/main-stack-demo.yaml \
  --stack-name "$STACK_NAME" \
  --capabilities CAPABILITY_NAMED_IAM \
  --region "$AWS_REGION" \
  --no-fail-on-empty-changeset \
  "${DISABLE_ROLLBACK_FLAG[@]}" \
  --parameter-overrides \
    Environment="$ENVIRONMENT" \
    S3BucketName="$S3_BUCKET" \
    CurReportBucketName="$CUR_BUCKET" \
    DomainName="" \
    HostedZoneId="" \
    CreateACMCertificate="false" || {
  log "ERROR: Infrastructure stack deploy failed. Check CloudFormation events:"
  aws cloudformation describe-stack-events \
    --stack-name "$STACK_NAME" --region "$AWS_REGION" \
    --query 'StackEvents[?ResourceStatus==`CREATE_FAILED` || ResourceStatus==`UPDATE_FAILED`].[LogicalResourceId,ResourceStatusReason]' \
    --output table 2>/dev/null || true
  exit 1
}

log "Deploying demo ECS services stack"
aws cloudformation deploy \
  --template-file infrastructure/cloudformation/ecs-services.yaml \
  --stack-name "${STACK_NAME}-services" \
  --capabilities CAPABILITY_IAM \
  --region "$AWS_REGION" \
  --no-fail-on-empty-changeset \
  "${DISABLE_ROLLBACK_FLAG[@]}" \
  --parameter-overrides \
    ParentStackName="$STACK_NAME" \
    DeploymentMode="demo" \
    BackendImageUri="$BACKEND_IMAGE_URI" \
    FrontendImageUri="$FRONTEND_IMAGE_URI" \
    DatabaseEndpoint="localhost" \
    ValkeyEndpoint="localhost" \
    DatabasePassword="$DB_PASSWORD_PLACEHOLDER" \
    BedrockModelId="$BEDROCK_MODEL" \
    S3BucketName="$S3_BUCKET" \
    CurBucketName="$CUR_BUCKET" \
    CurDatabase="$ATHENA_DB" \
    CurTable="$ATHENA_TABLE" \
    CurS3Prefix="$CUR_PREFIX" \
    DemoUserEmail="$DEMO_USER_EMAIL" \
    DemoOrganizationName="$DEMO_ORGANIZATION_NAME" \
    DemoAllowedAccountIds="$DEMO_ALLOWED_ACCOUNT_IDS" || {
  log "ERROR: ECS services stack deploy failed. Check CloudFormation events:"
  aws cloudformation describe-stack-events \
    --stack-name "${STACK_NAME}-services" --region "$AWS_REGION" \
    --query 'StackEvents[?ResourceStatus==`CREATE_FAILED` || ResourceStatus==`UPDATE_FAILED`].[LogicalResourceId,ResourceStatusReason]' \
    --output table 2>/dev/null || true
  exit 1
}

APP_URL="$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$AWS_REGION" --query 'Stacks[0].Outputs[?OutputKey==`ApplicationURL`].OutputValue' --output text 2>/dev/null || true)"
ALB_DNS="$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$AWS_REGION" --query 'Stacks[0].Outputs[?OutputKey==`LoadBalancerDNS`].OutputValue' --output text 2>/dev/null || true)"

if [[ -n "$DEMO_HOSTED_ZONE_ID" && -n "$DEMO_DOMAIN_NAME" && -n "$ALB_DNS" ]]; then
  ALB_ZONE_ID="$(aws elbv2 describe-load-balancers --region "$AWS_REGION" --query "LoadBalancers[?DNSName=='${ALB_DNS}'].CanonicalHostedZoneId | [0]" --output text 2>/dev/null || true)"

  if [[ -n "$ALB_ZONE_ID" && "$ALB_ZONE_ID" != "None" ]]; then
    log "Upserting DNS alias ${DEMO_DOMAIN_NAME} -> ${ALB_DNS}"
    CHANGE_BATCH=$(cat <<JSON
{"Comment":"Auto-update demo domain alias","Changes":[{"Action":"UPSERT","ResourceRecordSet":{"Name":"${DEMO_DOMAIN_NAME}.","Type":"A","AliasTarget":{"HostedZoneId":"${ALB_ZONE_ID}","DNSName":"${ALB_DNS}.","EvaluateTargetHealth":false}}}]}
JSON
)

    aws route53 change-resource-record-sets \
      --hosted-zone-id "$DEMO_HOSTED_ZONE_ID" \
      --change-batch "$CHANGE_BATCH" >/dev/null 2>&1 || log "WARNING: failed to upsert demo domain alias"
  else
    log "WARNING: could not resolve ALB hosted zone id for DNS alias update"
  fi
fi

log "Demo deployment complete"
log "Application URL: $APP_URL"
log "ALB DNS: $ALB_DNS"
log "Demo URL: https://${DEMO_DOMAIN_NAME}"
