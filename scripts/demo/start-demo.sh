#!/usr/bin/env bash
# start-demo.sh — Scale all demo.aasmaa.ai ECS services back to 1 task.
# Usage: ./scripts/demo/start-demo.sh [--region us-east-1] [--wait]
# Pass --wait to block until both services are COMPLETED/stable (~2-3 min)

set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER="aasmaa-cluster"
SERVICES=("aasmaa-backend" "aasmaa-frontend")
WAIT=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --region) AWS_REGION="$2"; shift 2 ;;
    --wait)   WAIT=true; shift ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

echo "==> Starting demo.aasmaa.ai services in ${AWS_REGION}..."
echo "    Cluster : ${CLUSTER}"

for svc in "${SERVICES[@]}"; do
  current=$(aws ecs describe-services \
    --cluster "$CLUSTER" \
    --services "$svc" \
    --region "$AWS_REGION" \
    --query 'services[0].desiredCount' \
    --output text 2>/dev/null || echo "0")

  if [[ "$current" -ge "1" ]]; then
    echo "    [SKIP] ${svc} is already running (desiredCount=${current})"
  else
    aws ecs update-service \
      --cluster "$CLUSTER" \
      --service "$svc" \
      --desired-count 1 \
      --region "$AWS_REGION" \
      --query 'service.desiredCount' \
      --output text > /dev/null
    echo "    [STARTED] ${svc}  (0 → 1 task)"
  fi
done

echo ""
echo "✓ Scale-up commands sent. Tasks are starting..."
echo "  URL : https://demo.aasmaa.ai"

if [[ "$WAIT" == "true" ]]; then
  echo ""
  echo "  Waiting for services to become stable (this takes ~2-3 minutes)..."
  for svc in "${SERVICES[@]}"; do
    echo -n "  Waiting for ${svc}..."
    for i in $(seq 1 36); do   # 36 × 5s = 3 minutes max
      state=$(aws ecs describe-services \
        --cluster "$CLUSTER" \
        --services "$svc" \
        --region "$AWS_REGION" \
        --query "services[0].deployments[?status=='PRIMARY']|[0].rolloutState" \
        --output text 2>/dev/null || echo "UNKNOWN")
      running=$(aws ecs describe-services \
        --cluster "$CLUSTER" \
        --services "$svc" \
        --region "$AWS_REGION" \
        --query 'services[0].runningCount' \
        --output text 2>/dev/null || echo "0")
      if [[ "$state" == "COMPLETED" && "$running" -ge "1" ]]; then
        echo " ready (${state})"
        break
      fi
      echo -n "."
      sleep 5
    done
  done
  echo ""
  echo "✓ All services are running. Visit https://demo.aasmaa.ai"
else
  echo "  Run with --wait to block until services are healthy."
fi
