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
BUILD_IMAGES=true
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --skip-build) BUILD_IMAGES=false ;;
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

BACKEND_IMAGE_URI="${BACKEND_IMAGE_URI:-$ECR_REGISTRY/aasmaa-backend:latest}"
FRONTEND_IMAGE_URI="${FRONTEND_IMAGE_URI:-$ECR_REGISTRY/aasmaa-frontend:latest}"

log "Target stack: $DEMO_STACK_NAME"
log "Target cluster: $DEMO_CLUSTER_NAME"
log "Target services: $DEMO_BACKEND_SERVICE, $DEMO_FRONTEND_SERVICE"
log "Target URL: $DEMO_URL"

run_cmd aws cloudformation describe-stacks --stack-name "$DEMO_STACK_NAME" --region "$AWS_REGION" >/dev/null
if ! aws ecs describe-services --cluster "$DEMO_CLUSTER_NAME" --services "$DEMO_BACKEND_SERVICE" "$DEMO_FRONTEND_SERVICE" --region "$AWS_REGION" --query 'length(failures)' --output text | grep -q '^0$'; then
  echo "[demo-update] ECS preflight failed: one or more demo services not found in cluster $DEMO_CLUSTER_NAME" >&2
  exit 1
fi

if command -v dig >/dev/null 2>&1; then
  LIVE_IPS="$(dig +short "$DEMO_URL" | tr '\n' ' ' | xargs || true)"
  ALB_IPS="$(dig +short "$DEMO_ALB_DNS" | tr '\n' ' ' | xargs || true)"
  log "DNS check $DEMO_URL -> ${LIVE_IPS:-n/a}"
  log "DNS check $DEMO_ALB_DNS -> ${ALB_IPS:-n/a}"
fi

if $BUILD_IMAGES; then
  log "Building and pushing latest backend/frontend images"
  run_shell "aws ecr get-login-password --region \"$AWS_REGION\" | docker login --username AWS --password-stdin \"$ECR_REGISTRY\""
  run_shell "DOCKER_BUILDKIT=1 docker build --platform linux/amd64 -f backend/Dockerfile -t aasmaa-backend:latest \"$ROOT_DIR\""
  run_cmd docker tag aasmaa-backend:latest "$BACKEND_IMAGE_URI"
  run_cmd docker push "$BACKEND_IMAGE_URI"
  run_shell "DOCKER_BUILDKIT=1 docker build --platform linux/amd64 -f frontend/Dockerfile -t aasmaa-frontend:latest \"$ROOT_DIR\""
  run_cmd docker tag aasmaa-frontend:latest "$FRONTEND_IMAGE_URI"
  run_cmd docker push "$FRONTEND_IMAGE_URI"
else
  log "Skipping image build/push (--skip-build)"
fi

log "Forcing in-place ECS rollout on existing services"
run_cmd aws ecs update-service --cluster "$DEMO_CLUSTER_NAME" --service "$DEMO_BACKEND_SERVICE" --force-new-deployment --region "$AWS_REGION" >/dev/null
run_cmd aws ecs update-service --cluster "$DEMO_CLUSTER_NAME" --service "$DEMO_FRONTEND_SERVICE" --force-new-deployment --region "$AWS_REGION" >/dev/null
run_cmd aws ecs wait services-stable --cluster "$DEMO_CLUSTER_NAME" --services "$DEMO_BACKEND_SERVICE" "$DEMO_FRONTEND_SERVICE" --region "$AWS_REGION"

run_cmd aws ecs describe-services --cluster "$DEMO_CLUSTER_NAME" --services "$DEMO_BACKEND_SERVICE" "$DEMO_FRONTEND_SERVICE" --region "$AWS_REGION" --query "services[].[serviceName,desiredCount,runningCount,deployments[0].rolloutState]" --output table
run_cmd curl -I --max-time 20 "https://$DEMO_URL"

log "Demo barebones update completed"
