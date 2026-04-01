#!/usr/bin/env bash
# teardown.sh — Remove the aasmaa demo control panel Lambda and its IAM role.
# Does NOT touch your ECS cluster, services, or any other resources.

set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
LAMBDA_NAME="aasmaa-demo-control"
ROLE_NAME="aasmaa-demo-control-role"

echo "==> Removing $LAMBDA_NAME resources in $REGION"
echo ""

# Lambda (also deletes Function URL automatically)
if aws lambda get-function --function-name "$LAMBDA_NAME" --region "$REGION" &>/dev/null; then
  aws lambda delete-function --function-name "$LAMBDA_NAME" --region "$REGION"
  echo "  [DELETED] Lambda: $LAMBDA_NAME"
else
  echo "  [SKIP]    Lambda not found"
fi

# Inline policy
aws iam delete-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "ecs-demo-control" 2>/dev/null \
  && echo "  [DELETED] Inline policy: ecs-demo-control" \
  || echo "  [SKIP]    Inline policy not found"

# Managed policy attachment
aws iam detach-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" 2>/dev/null \
  || true

# IAM role
if aws iam get-role --role-name "$ROLE_NAME" &>/dev/null; then
  aws iam delete-role --role-name "$ROLE_NAME"
  echo "  [DELETED] IAM role: $ROLE_NAME"
else
  echo "  [SKIP]    IAM role not found"
fi

echo ""
echo "Done. ECS services and other resources are untouched."
echo "The .control-token file was NOT deleted — remove it manually if desired."
