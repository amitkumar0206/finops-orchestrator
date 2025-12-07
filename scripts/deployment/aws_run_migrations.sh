#!/usr/bin/env bash
set -euo pipefail

# Run Alembic migrations on AWS by executing a command inside a running ECS task
# or by launching a one-off task with the backend image.
#
# Requirements:
# - AWS CLI v2 with permissions for ecs:ExecuteCommand, ecs:ListTasks, ecs:RunTask, iam:PassRole
# - ECS Exec must be enabled on the service if using EXEC mode
# - The backend image includes alembic and has DB env vars configured
#
# Usage examples:
# 1) Exec into a running task (recommended if service is healthy):
#    ./scripts/deployment/aws_run_migrations.sh exec \
#      --region us-east-1 \
#      --cluster my-ecs-cluster \
#      --service finops-backend-svc \
#      --container backend
#
# 2) Run a one-off task (if no tasks are running yet):
#    ./scripts/deployment/aws_run_migrations.sh run \
#      --region us-east-1 \
#      --cluster my-ecs-cluster \
#      --task-def arn:aws:ecs:us-east-1:123456789012:task-definition/finops-backend:42 \
#      --subnets subnet-abc123,subnet-def456 \
#      --security-groups sg-0123456789abcdef0
#
# Notes:
# - Command executed inside container: "alembic upgrade head"
# - Ensure container has POSTGRES_* env vars pointing to RDS endpoint.

MODE=${1:-}
shift || true

REGION=""
CLUSTER=""
SERVICE=""
TASK_ID=""
TASK_DEF=""
CONTAINER="backend"
SUBNETS=""
SGS=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --region) REGION="$2"; shift 2;;
    --cluster) CLUSTER="$2"; shift 2;;
    --service) SERVICE="$2"; shift 2;;
    --task-id) TASK_ID="$2"; shift 2;;
    --task-def) TASK_DEF="$2"; shift 2;;
    --container) CONTAINER="$2"; shift 2;;
    --subnets) SUBNETS="$2"; shift 2;;
    --security-groups) SGS="$2"; shift 2;;
    *) echo "Unknown arg: $1"; exit 2;;
  esac
done

if [[ -z "$REGION" || -z "$CLUSTER" ]]; then
  echo "Usage: $0 <exec|run> --region REGION --cluster CLUSTER [--service SERVICE|--task-id TASK_ID|--task-def TASK_DEF]" >&2
  exit 2
fi

set -x

if [[ "$MODE" == "exec" ]]; then
  if [[ -z "$TASK_ID" ]]; then
    if [[ -z "$SERVICE" ]]; then
      echo "For exec mode, provide --task-id or --service to auto-select a task" >&2
      exit 2
    fi
    TASK_ID=$(aws ecs list-tasks \
      --region "$REGION" \
      --cluster "$CLUSTER" \
      --service-name "$SERVICE" \
      --desired-status RUNNING \
      --query 'taskArns[0]' \
      --output text)
    if [[ "$TASK_ID" == "None" || -z "$TASK_ID" ]]; then
      echo "No running tasks found for service $SERVICE" >&2
      exit 1
    fi
  fi
  aws ecs execute-command \
    --region "$REGION" \
    --cluster "$CLUSTER" \
    --task "$TASK_ID" \
    --container "$CONTAINER" \
    --interactive \
    --command "alembic -c /app/alembic.ini upgrade head"
  exit $?
fi

if [[ "$MODE" == "run" ]]; then
  if [[ -z "$TASK_DEF" || -z "$SUBNETS" || -z "$SGS" ]]; then
    echo "For run mode, provide --task-def, --subnets (csv), and --security-groups (csv)" >&2
    exit 2
  fi
  aws ecs run-task \
    --region "$REGION" \
    --cluster "$CLUSTER" \
    --launch-type FARGATE \
    --task-definition "$TASK_DEF" \
    --count 1 \
    --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SGS],assignPublicIp=ENABLED}" \
    --overrides "{\"containerOverrides\":[{\"name\":\"$CONTAINER\",\"command\":[\"alembic\",\"-c\",\"/app/alembic.ini\",\"upgrade\",\"head\"]}]}"
  exit $?
fi

echo "Unknown mode: $MODE (use exec or run)" >&2
exit 2
