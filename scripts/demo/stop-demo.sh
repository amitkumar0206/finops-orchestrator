#!/usr/bin/env bash
# stop-demo.sh — Scale all demo.aasmaa.ai ECS services to 0 to save cost.
# Usage: ./scripts/demo/stop-demo.sh [--region us-east-1]
# Safe to run at any time; services can be restarted with start-demo.sh

set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER="aasmaa-cluster"
SERVICES=("aasmaa-backend" "aasmaa-frontend")

# Allow region override via flag
while [[ $# -gt 0 ]]; do
  case "$1" in
    --region) AWS_REGION="$2"; shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

echo "==> Stopping demo.aasmaa.ai services in ${AWS_REGION}..."
echo "    Cluster : ${CLUSTER}"

for svc in "${SERVICES[@]}"; do
  current=$(aws ecs describe-services \
    --cluster "$CLUSTER" \
    --services "$svc" \
    --region "$AWS_REGION" \
    --query 'services[0].desiredCount' \
    --output text 2>/dev/null || echo "0")

  if [[ "$current" == "0" ]]; then
    echo "    [SKIP] ${svc} is already stopped (desiredCount=0)"
  else
    aws ecs update-service \
      --cluster "$CLUSTER" \
      --service "$svc" \
      --desired-count 0 \
      --region "$AWS_REGION" \
      --query 'service.desiredCount' \
      --output text > /dev/null
    echo "    [STOPPED] ${svc}  (was ${current} → now 0 tasks)"
  fi
done

echo ""
echo "✓ All services stopped. The ALB and other infrastructure remain running."
echo "  To restart: ./scripts/demo/start-demo.sh"
echo ""
echo "  Note: The ALB, RDS, and ElastiCache instances still accrue costs while stopped."
echo "  To stop those too, scale down manually or use aws rds/elasticache stop commands."
