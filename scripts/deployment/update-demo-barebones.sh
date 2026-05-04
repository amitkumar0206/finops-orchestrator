#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONFIG_FILE="${UPDATE_TARGETS_CONFIG:-$ROOT_DIR/config/deploy/update-targets.env}"

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "[demo-update] Missing config file: $CONFIG_FILE" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$CONFIG_FILE"

DRY_RUN=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    *) echo "[demo-update] Unknown argument: $arg" >&2; exit 1 ;;
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
  echo "[demo-update] $1"
}

resolve_stack_output() {
  local stack_name="$1"
  local output_key="$2"
  aws cloudformation describe-stacks \
    --stack-name "$stack_name" \
    --region "$AWS_REGION" \
    --query "Stacks[0].Outputs[?OutputKey==\`${output_key}\`].OutputValue | [0]" \
    --output text 2>/dev/null || true
}

stack_exists() {
  local stack_name="$1"
  aws cloudformation describe-stacks \
    --stack-name "$stack_name" \
    --region "$AWS_REGION" >/dev/null 2>&1
}

resolve_service_image_uri() {
  local cluster_name="$1"
  local service_name="$2"
  local container_name="$3"
  local fallback_image="$4"
  local task_definition
  local service_image

  task_definition="$(aws ecs describe-services \
    --cluster "$cluster_name" \
    --services "$service_name" \
    --region "$AWS_REGION" \
    --query 'services[0].taskDefinition' \
    --output text 2>/dev/null || true)"

  if [[ -z "$task_definition" || "$task_definition" == "None" ]]; then
    echo "$fallback_image"
    return 0
  fi

  service_image="$(aws ecs describe-task-definition \
    --task-definition "$task_definition" \
    --region "$AWS_REGION" \
    --query "taskDefinition.containerDefinitions[?name==\`${container_name}\`].image | [0]" \
    --output text 2>/dev/null || true)"

  if [[ -z "$service_image" || "$service_image" == "None" ]]; then
    echo "$fallback_image"
    return 0
  fi

  echo "$service_image"
}

image_registry_from_uri() {
  local image_uri="$1"
  echo "$image_uri" | cut -d'/' -f1
}

image_region_from_uri() {
  local image_uri="$1"
  image_registry_from_uri "$image_uri" | awk -F'.' '{print $4}'
}

ecr_login_for_image() {
  local image_uri="$1"
  local registry
  local registry_region

  registry="$(image_registry_from_uri "$image_uri")"
  registry_region="$(image_region_from_uri "$image_uri")"

  if [[ -z "$registry" || -z "$registry_region" ]]; then
    echo "[demo-update] Unable to parse registry/region from image URI: $image_uri" >&2
    exit 1
  fi

  if [[ "${LOGGED_ECR_REGISTRIES:-}" == *"|${registry}|"* ]]; then
    return 0
  fi

  run_shell "aws ecr get-login-password --region \"$registry_region\" | docker login --username AWS --password-stdin \"$registry\""
  LOGGED_ECR_REGISTRIES="${LOGGED_ECR_REGISTRIES:-}|${registry}|"
}

BACKEND_IMAGE_URI="${BACKEND_IMAGE_URI:-$ECR_REGISTRY/aasmaa-backend:latest}"
FRONTEND_IMAGE_URI="${FRONTEND_IMAGE_URI:-$ECR_REGISTRY/aasmaa-frontend:latest}"

log "Target stack: $DEMO_STACK_NAME"
log "Target cluster: $DEMO_CLUSTER_NAME"
log "Target services: $DEMO_BACKEND_SERVICE, $DEMO_FRONTEND_SERVICE"
log "Target URL: $DEMO_URL"

run_cmd aws cloudformation describe-stacks --stack-name "$DEMO_STACK_NAME" --region "$AWS_REGION" >/dev/null

DEMO_SERVICES_STACK_NAME="${DEMO_SERVICES_STACK_NAME:-${DEMO_STACK_NAME}-services}"

# Resolve canonical ECS names from CloudFormation outputs when available.
STACK_CLUSTER_NAME="$(resolve_stack_output "$DEMO_STACK_NAME" "ECSClusterName")"
STACK_BACKEND_SERVICE="$(resolve_stack_output "$DEMO_SERVICES_STACK_NAME" "BackendServiceName")"
STACK_FRONTEND_SERVICE="$(resolve_stack_output "$DEMO_SERVICES_STACK_NAME" "FrontendServiceName")"

if [[ -n "$STACK_CLUSTER_NAME" && "$STACK_CLUSTER_NAME" != "None" ]]; then
  DEMO_CLUSTER_NAME="$STACK_CLUSTER_NAME"
fi
if [[ -n "$STACK_BACKEND_SERVICE" && "$STACK_BACKEND_SERVICE" != "None" ]]; then
  DEMO_BACKEND_SERVICE="$STACK_BACKEND_SERVICE"
fi
if [[ -n "$STACK_FRONTEND_SERVICE" && "$STACK_FRONTEND_SERVICE" != "None" ]]; then
  DEMO_FRONTEND_SERVICE="$STACK_FRONTEND_SERVICE"
fi

log "Resolved cluster: $DEMO_CLUSTER_NAME"
log "Resolved services: $DEMO_BACKEND_SERVICE, $DEMO_FRONTEND_SERVICE"

EXISTING_SERVICE_COUNT="$(aws ecs list-services \
  --cluster "$DEMO_CLUSTER_NAME" \
  --region "$AWS_REGION" \
  --query 'length(serviceArns)' \
  --output text 2>/dev/null || echo "0")"

if [[ "$EXISTING_SERVICE_COUNT" == "0" ]]; then
  echo "[demo-update] ECS preflight failed: cluster $DEMO_CLUSTER_NAME has no services" >&2
  if stack_exists "$DEMO_SERVICES_STACK_NAME"; then
    SERVICES_STACK_STATUS="$(aws cloudformation describe-stacks \
      --stack-name "$DEMO_SERVICES_STACK_NAME" \
      --region "$AWS_REGION" \
      --query 'Stacks[0].StackStatus' \
      --output text 2>/dev/null || true)"
    echo "[demo-update] Services stack status: ${SERVICES_STACK_STATUS:-unknown}" >&2
  else
    echo "[demo-update] Services stack not found: $DEMO_SERVICES_STACK_NAME" >&2
  fi
  echo "[demo-update] Run ./scripts/deployment/deploy-demo-barebones.sh first to create the demo ECS services." >&2
  exit 1
fi

if [[ -z "${DEMO_ALB_DNS:-}" ]]; then
  DEMO_ALB_DNS="$(aws cloudformation describe-stacks \
    --stack-name "$DEMO_STACK_NAME" \
    --region "$AWS_REGION" \
    --query 'Stacks[0].Outputs[?OutputKey==`LoadBalancerDNS`].OutputValue' \
    --output text 2>/dev/null || true)"
fi

ECS_FAILURES_JSON="$(aws ecs describe-services \
  --cluster "$DEMO_CLUSTER_NAME" \
  --services "$DEMO_BACKEND_SERVICE" "$DEMO_FRONTEND_SERVICE" \
  --region "$AWS_REGION" \
  --query 'failures[].{arn:arn,reason:reason,detail:detail}' \
  --output json 2>/dev/null || true)"

if [[ "$ECS_FAILURES_JSON" != "[]" ]]; then
  echo "[demo-update] ECS preflight failed for cluster $DEMO_CLUSTER_NAME" >&2
  echo "[demo-update] Requested services: $DEMO_BACKEND_SERVICE, $DEMO_FRONTEND_SERVICE" >&2
  echo "[demo-update] AWS failures: $ECS_FAILURES_JSON" >&2
  exit 1
fi

BACKEND_IMAGE_URI="$(resolve_service_image_uri "$DEMO_CLUSTER_NAME" "$DEMO_BACKEND_SERVICE" "backend" "$BACKEND_IMAGE_URI")"
FRONTEND_IMAGE_URI="$(resolve_service_image_uri "$DEMO_CLUSTER_NAME" "$DEMO_FRONTEND_SERVICE" "frontend" "$FRONTEND_IMAGE_URI")"

log "Using backend image URI: $BACKEND_IMAGE_URI"
log "Using frontend image URI: $FRONTEND_IMAGE_URI"

if command -v dig >/dev/null 2>&1; then
  LIVE_IPS="$(dig +short "$DEMO_URL" | tr '\n' ' ' | xargs || true)"
  ALB_IPS="${DEMO_ALB_DNS:+$(dig +short "$DEMO_ALB_DNS" | tr '\n' ' ' | xargs || true)}"
  log "DNS check $DEMO_URL -> ${LIVE_IPS:-n/a}"
  if [[ -n "${DEMO_ALB_DNS:-}" ]]; then
    log "DNS check $DEMO_ALB_DNS -> ${ALB_IPS:-n/a}"
  fi
fi

log "Syntax-checking backend Python files before build"
if ! find "$ROOT_DIR/backend" -name '*.py' -print0 | xargs -0 python3 -m py_compile 2>&1; then
  echo "[demo-update] Python syntax check failed — aborting deployment." >&2
  exit 1
fi
log "Python syntax check passed"

log "Building and pushing latest backend/frontend images"
ecr_login_for_image "$BACKEND_IMAGE_URI"
if [[ "$FRONTEND_IMAGE_URI" != "$BACKEND_IMAGE_URI" ]]; then
  ecr_login_for_image "$FRONTEND_IMAGE_URI"
fi
run_shell "DOCKER_BUILDKIT=1 docker build --platform linux/amd64 -f \"$ROOT_DIR/backend/Dockerfile\" -t aasmaa-backend:latest \"$ROOT_DIR\""
run_cmd docker tag aasmaa-backend:latest "$BACKEND_IMAGE_URI"
run_cmd docker push "$BACKEND_IMAGE_URI"
run_shell "DOCKER_BUILDKIT=1 docker build --platform linux/amd64 -f \"$ROOT_DIR/frontend/Dockerfile\" -t aasmaa-frontend:latest \"$ROOT_DIR\""
run_cmd docker tag aasmaa-frontend:latest "$FRONTEND_IMAGE_URI"
run_cmd docker push "$FRONTEND_IMAGE_URI"

log "Forcing in-place ECS rollout on existing services"
run_cmd aws ecs update-service --cluster "$DEMO_CLUSTER_NAME" --service "$DEMO_BACKEND_SERVICE" --force-new-deployment --region "$AWS_REGION" >/dev/null
run_cmd aws ecs update-service --cluster "$DEMO_CLUSTER_NAME" --service "$DEMO_FRONTEND_SERVICE" --force-new-deployment --region "$AWS_REGION" >/dev/null
run_cmd aws ecs wait services-stable --cluster "$DEMO_CLUSTER_NAME" --services "$DEMO_BACKEND_SERVICE" "$DEMO_FRONTEND_SERVICE" --region "$AWS_REGION"

run_cmd aws ecs describe-services --cluster "$DEMO_CLUSTER_NAME" --services "$DEMO_BACKEND_SERVICE" "$DEMO_FRONTEND_SERVICE" --region "$AWS_REGION" --query "services[].[serviceName,desiredCount,runningCount,deployments[0].rolloutState]" --output table
run_cmd curl -I --max-time 20 "https://$DEMO_URL"

log "Demo barebones update completed"
