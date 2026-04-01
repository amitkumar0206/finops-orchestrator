#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONFIG_FILE="${UPDATE_TARGETS_CONFIG:-$ROOT_DIR/config/deploy/update-targets.env}"

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "[prod-update] Missing config file: $CONFIG_FILE" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$CONFIG_FILE"

DRY_RUN=false
BUILD_IMAGES=true
RUN_MIGRATIONS=true
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --skip-build) BUILD_IMAGES=false ;;
    --skip-migrations) RUN_MIGRATIONS=false ;;
    *) echo "[prod-update] Unknown argument: $arg" >&2; exit 1 ;;
  esac
done

run_cmd() {
  if $DRY_RUN; then
    echo "[dry-run] $*"
  else
    "$@"
  fi
}

run_shell() {
  if $DRY_RUN; then
    echo "[dry-run] $*"
  else
    bash -lc "$*"
  fi
}

log() {
  echo "[prod-update] $1"
}

clean_value() {
  local v="$1"
  if [[ "$v" == "None" || "$v" == "null" || -z "$v" ]]; then
    echo ""
  else
    echo "$v"
  fi
}

BACKEND_IMAGE_URI="${BACKEND_IMAGE_URI:-$ECR_REGISTRY/aasmaa-backend:latest}"
FRONTEND_IMAGE_URI="${FRONTEND_IMAGE_URI:-$ECR_REGISTRY/aasmaa-frontend:latest}"

log "Target main stack: $PROD_STACK_NAME"
log "Target services stack: $PROD_SERVICES_STACK_NAME"
log "Target cluster: $PROD_CLUSTER_NAME"

# ── Preflight: verify both CFN stacks exist ───────────────────────────────────
log "Preflight: checking CloudFormation stacks..."
STACK_JSON="$(aws cloudformation describe-stacks --stack-name "$PROD_STACK_NAME" --region "$AWS_REGION" --output json 2>/dev/null)" || {
  echo "[prod-update] Stack '$PROD_STACK_NAME' not found or inaccessible." >&2; exit 1
}
aws cloudformation describe-stacks --stack-name "$PROD_SERVICES_STACK_NAME" --region "$AWS_REGION" >/dev/null 2>&1 || {
  echo "[prod-update] Services stack '$PROD_SERVICES_STACK_NAME' not found or inaccessible." >&2; exit 1
}

# Parse all params + outputs from the single describe-stacks response
parse_param() {
  echo "$STACK_JSON" | python3 -c "
import sys,json
data=json.load(sys.stdin)
params={p['ParameterKey']:p['ParameterValue'] for p in data['Stacks'][0].get('Parameters',[])}
print(params.get('$1',''))
" 2>/dev/null || true
}
parse_output() {
  echo "$STACK_JSON" | python3 -c "
import sys,json
data=json.load(sys.stdin)
outputs={o['OutputKey']:o['OutputValue'] for o in data['Stacks'][0].get('Outputs',[])}
print(outputs.get('$1',''))
" 2>/dev/null || true
}

ENVIRONMENT="${ENVIRONMENT:-$(clean_value "$(parse_param Environment)")}"
S3_BUCKET="${S3_BUCKET:-$(clean_value "$(parse_param S3BucketName)")}"
DOMAIN_NAME="${DOMAIN_NAME:-$(clean_value "$(parse_param DomainName)")}"
HOSTED_ZONE_ID="${HOSTED_ZONE_ID:-$(clean_value "$(parse_param HostedZoneId)")}"
CREATE_ACM_CERTIFICATE="${CREATE_ACM_CERTIFICATE:-$(clean_value "$(parse_param CreateACMCertificate)")}"
CUR_BUCKET="${CUR_BUCKET:-$(clean_value "$(parse_param CurReportBucketName)")}"
CUR_PREFIX="${CUR_PREFIX:-$(clean_value "$(parse_param CurReportPrefix)")}"
CUR_DATABASE="${CUR_DATABASE:-$(clean_value "$(parse_param CurDatabaseName)")}"
BEDROCK_MODEL="${BEDROCK_MODEL:-$(clean_value "$(parse_param BedrockModelId)")}"

ENVIRONMENT="${ENVIRONMENT:-production}"
CREATE_ACM_CERTIFICATE="${CREATE_ACM_CERTIFICATE:-true}"
CUR_PREFIX="${CUR_PREFIX:-cost-exports/aasmaa-cost-export}"
CUR_DATABASE="${CUR_DATABASE:-cost_usage_db}"
BEDROCK_MODEL="${BEDROCK_MODEL:-us.amazon.nova-pro-v1:0}"

if [[ -z "$S3_BUCKET" ]]; then
  echo "[prod-update] Missing S3 bucket value. Set S3_BUCKET in env or config." >&2
  exit 1
fi
if [[ -z "$CUR_BUCKET" ]]; then
  CUR_BUCKET="$S3_BUCKET"
fi

# ── Preflight: verify current stack has a real DB endpoint ────────────────────
DB_ENDPOINT="$(clean_value "$(parse_output DatabaseEndpoint)")"
VALKEY_ENDPOINT="$(clean_value "$(parse_output ValkeyEndpoint)")"
CERT_ARN="$(clean_value "$(parse_output CertificateArn)")"
ALB_ARN="$(clean_value "$(parse_output ALBArn)")"

if [[ -z "$DB_ENDPOINT" || "$DB_ENDPOINT" == "localhost" ]]; then
  echo "[prod-update] Refusing to continue: target stack '$PROD_STACK_NAME' does not expose a DB-backed endpoint (got '${DB_ENDPOINT:-empty}')." >&2
  exit 1
fi
if [[ -z "$VALKEY_ENDPOINT" || "$VALKEY_ENDPOINT" == "localhost" ]]; then
  echo "[prod-update] Refusing to continue: target stack '$PROD_STACK_NAME' does not expose a Valkey endpoint (got '${VALKEY_ENDPOINT:-empty}')." >&2
  exit 1
fi
log "DB endpoint: $DB_ENDPOINT"
log "Valkey endpoint: $VALKEY_ENDPOINT"

EXISTING_HTTPS_LISTENER_ARN=""
if [[ -n "$ALB_ARN" ]]; then
  EXISTING_HTTPS_LISTENER_ARN="$(aws elbv2 describe-listeners --load-balancer-arn "$ALB_ARN" --region "$AWS_REGION" \
    --query 'Listeners[?Port==`443`].ListenerArn | [0]' --output text 2>/dev/null || true)"
  EXISTING_HTTPS_LISTENER_ARN="$(clean_value "$EXISTING_HTTPS_LISTENER_ARN")"
fi

# ── ECS preflight ─────────────────────────────────────────────────────────────
if ! aws ecs describe-services --cluster "$PROD_CLUSTER_NAME" --services "$PROD_BACKEND_SERVICE" "$PROD_FRONTEND_SERVICE" --region "$AWS_REGION" --query 'length(failures)' --output text | grep -q '^0$'; then
  echo "[prod-update] ECS preflight failed: one or more services not found in cluster $PROD_CLUSTER_NAME" >&2
  exit 1
fi

# ── Resolve DB password ───────────────────────────────────────────────────────
if [[ -z "${DB_PASSWORD:-}" ]] && ! $DRY_RUN; then
  DB_PASSWORD="$(aws ssm get-parameter --name "/${PROD_STACK_NAME}/database/password" --with-decryption \
    --region "$AWS_REGION" --cli-connect-timeout 10 --cli-read-timeout 10 \
    --query 'Parameter.Value' --output text 2>/dev/null || true)"
fi
if [[ -z "${DB_PASSWORD:-}" && -f "$ROOT_DIR/$PROD_ENV_FILE" ]]; then
  DB_PASSWORD="$(grep '^DB_PASSWORD=' "$ROOT_DIR/$PROD_ENV_FILE" | tail -n1 | cut -d'=' -f2- || true)"
fi
if [[ -z "${DB_PASSWORD:-}" ]]; then
  if $DRY_RUN; then
    DB_PASSWORD="<DB_PASSWORD>"
    log "Dry-run: DB_PASSWORD not resolved — will use placeholder in command output"
  else
    echo "[prod-update] Could not resolve DB_PASSWORD (set env DB_PASSWORD or ensure SSM /${PROD_STACK_NAME}/database/password)." >&2
    exit 1
  fi
fi

if $BUILD_IMAGES; then
  log "Building and pushing latest backend/frontend images"
  run_shell "aws ecr get-login-password --region \"$AWS_REGION\" | docker login --username AWS --password-stdin \"$ECR_REGISTRY\""
  run_shell "DOCKER_BUILDKIT=1 docker build --platform linux/amd64 -f \"$ROOT_DIR/backend/Dockerfile\" -t aasmaa-backend:latest \"$ROOT_DIR\""
  run_cmd docker tag aasmaa-backend:latest "$BACKEND_IMAGE_URI"
  run_cmd docker push "$BACKEND_IMAGE_URI"
  run_shell "DOCKER_BUILDKIT=1 docker build --platform linux/amd64 -f \"$ROOT_DIR/frontend/Dockerfile\" -t aasmaa-frontend:latest \"$ROOT_DIR\""
  run_cmd docker tag aasmaa-frontend:latest "$FRONTEND_IMAGE_URI"
  run_cmd docker push "$FRONTEND_IMAGE_URI"
else
  log "Skipping image build/push (--skip-build)"
fi

log "Updating production main infrastructure stack"
run_cmd aws cloudformation deploy --template-file "$ROOT_DIR/$PROD_MAIN_TEMPLATE" --stack-name "$PROD_STACK_NAME" --capabilities CAPABILITY_NAMED_IAM --region "$AWS_REGION" --parameter-overrides "Environment=$ENVIRONMENT" "DatabasePassword=$DB_PASSWORD" "BedrockModelId=$BEDROCK_MODEL" "S3BucketName=$S3_BUCKET" "DomainName=$DOMAIN_NAME" "HostedZoneId=$HOSTED_ZONE_ID" "CreateACMCertificate=$CREATE_ACM_CERTIFICATE" "CurReportBucketName=$CUR_BUCKET" "CurReportPrefix=$CUR_PREFIX" "CurDatabaseName=$CUR_DATABASE" "CreateCurDatabase=false"

SERVICE_PARAMS=(
  "ParentStackName=$PROD_STACK_NAME"
  "DeploymentMode=full"
  "BackendImageUri=$BACKEND_IMAGE_URI"
  "FrontendImageUri=$FRONTEND_IMAGE_URI"
  "DatabaseEndpoint=$DB_ENDPOINT"
  "ValkeyEndpoint=$VALKEY_ENDPOINT"
  "DatabasePassword=$DB_PASSWORD"
  "BedrockModelId=$BEDROCK_MODEL"
  "S3BucketName=$S3_BUCKET"
  "CurBucketName=$CUR_BUCKET"
  "CurDatabase=$CUR_DATABASE"
  "CurTable=${AWS_CUR_TABLE:-cur_data}"
  "CurS3Prefix=$CUR_PREFIX"
)
if [[ -n "$CERT_ARN" && "$CERT_ARN" != "None" ]]; then
  SERVICE_PARAMS+=("CertificateArn=$CERT_ARN")
fi
if [[ -n "$EXISTING_HTTPS_LISTENER_ARN" && "$EXISTING_HTTPS_LISTENER_ARN" != "None" ]]; then
  SERVICE_PARAMS+=("ExistingHttpsListenerArn=$EXISTING_HTTPS_LISTENER_ARN")
fi

log "Updating production services stack"
run_cmd aws cloudformation deploy --template-file "$ROOT_DIR/$PROD_SERVICES_TEMPLATE" --stack-name "$PROD_SERVICES_STACK_NAME" --capabilities CAPABILITY_IAM --region "$AWS_REGION" --parameter-overrides "${SERVICE_PARAMS[@]}"

log "Forcing ECS rollout"
run_cmd aws ecs update-service --cluster "$PROD_CLUSTER_NAME" --service "$PROD_BACKEND_SERVICE" --force-new-deployment --region "$AWS_REGION" >/dev/null
run_cmd aws ecs update-service --cluster "$PROD_CLUSTER_NAME" --service "$PROD_FRONTEND_SERVICE" --force-new-deployment --region "$AWS_REGION" >/dev/null
run_cmd aws ecs wait services-stable --cluster "$PROD_CLUSTER_NAME" --services "$PROD_BACKEND_SERVICE" "$PROD_FRONTEND_SERVICE" --region "$AWS_REGION"

if $RUN_MIGRATIONS; then
  log "Running ECS migration helper"
  run_shell "cd \"$ROOT_DIR\" && ./scripts/deployment/aws_run_migrations.sh run --region \"$AWS_REGION\" --stack-name \"$PROD_STACK_NAME\""
fi

run_cmd aws ecs describe-services --cluster "$PROD_CLUSTER_NAME" --services "$PROD_BACKEND_SERVICE" "$PROD_FRONTEND_SERVICE" --region "$AWS_REGION" --query "services[].[serviceName,desiredCount,runningCount,deployments[0].rolloutState]" --output table

log "Production full update completed"
