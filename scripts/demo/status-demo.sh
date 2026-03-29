#!/usr/bin/env bash
# status-demo.sh — Show the current running state of all demo.aasmaa.ai ECS services.
# Usage: ./scripts/demo/status-demo.sh [--region us-east-1]

set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER="aasmaa-cluster"
SERVICES=("aasmaa-backend" "aasmaa-frontend")

while [[ $# -gt 0 ]]; do
  case "$1" in
    --region) AWS_REGION="$2"; shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

echo "==> demo.aasmaa.ai service status (${AWS_REGION})"
echo ""
printf "  %-24s  %-8s  %-8s  %-14s  %s\n" "SERVICE" "DESIRED" "RUNNING" "ROLLOUT" "TASK DEF"
printf "  %-24s  %-8s  %-8s  %-14s  %s\n" "-------" "-------" "-------" "-------" "--------"

for svc in "${SERVICES[@]}"; do
  result=$(aws ecs describe-services \
    --cluster "$CLUSTER" \
    --services "$svc" \
    --region "$AWS_REGION" \
    --query 'services[0].{desired:desiredCount,running:runningCount,taskDef:taskDefinition,rollout:deployments[?status==`PRIMARY`]|[0].rolloutState}' \
    --output json 2>/dev/null || echo '{}')

  desired=$(echo "$result" | jq -r '.desired // "?"')
  running=$(echo "$result" | jq -r '.running // "?"')
  rollout=$(echo "$result" | jq -r '.rollout // "?"')
  taskdef=$(echo "$result" | jq -r '.taskDef // "?" | split("/") | last')

  printf "  %-24s  %-8s  %-8s  %-14s  %s\n" "$svc" "$desired" "$running" "$rollout" "$taskdef"
done

echo ""
echo "  URL: https://demo.aasmaa.ai"
