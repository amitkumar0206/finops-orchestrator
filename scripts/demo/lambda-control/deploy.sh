#!/usr/bin/env bash
# deploy.sh — Deploy (or re-deploy) the aasmaa demo control panel Lambda.
#
# What it creates:
#   • IAM role  aasmaa-demo-control-role   (scoped to your ECS cluster only)
#   • Lambda    aasmaa-demo-control         (Python 3.12, 128 MB, 30 s timeout)
#   • Function URL (HTTPS, public, token-protected)
#
# Usage:
#   ./deploy.sh                         # first deploy or re-deploy after code changes
#   AWS_REGION=eu-west-1 ./deploy.sh    # different region
#   ECS_CLUSTER=my-cluster ./deploy.sh  # different cluster
#
# After deploy the script prints the shareable URL (with token).
# The token is saved in .control-token — guard it like a password.

set -euo pipefail

REGION="${AWS_REGION:-ap-south-1}"
CLUSTER="${ECS_CLUSTER:-aasmaa-demo-barebones-cluster}"
ECS_REGION="${ECS_REGION:-$REGION}"
ECS_SERVICES="${ECS_SERVICES:-aasmaa-demo-barebones-backend|aasmaa-demo-barebones-frontend}"
DEMO_URL="${DEMO_URL:-https://demo.aasmaa.ai}"
LAMBDA_NAME="aasmaa-demo-control"
ROLE_NAME="aasmaa-demo-control-role"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TOKEN_FILE="$SCRIPT_DIR/.control-token"

# ── Token ────────────────────────────────────────────────────────────────────
if [[ -f "$TOKEN_FILE" ]]; then
  TOKEN=$(cat "$TOKEN_FILE")
  echo "  Reusing token from $TOKEN_FILE"
else
  TOKEN=$(openssl rand -hex 16)
  printf '%s' "$TOKEN" > "$TOKEN_FILE"
  chmod 600 "$TOKEN_FILE"
  echo "  Generated new token (saved to $TOKEN_FILE)"
fi

# ── AWS identity ──────────────────────────────────────────────────────────────
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo ""
echo "==> Deploying $LAMBDA_NAME"
echo "    Account : $ACCOUNT_ID"
echo "    Region  : $REGION"
echo "    Cluster : $CLUSTER"
echo "    ECS API : $ECS_REGION"
echo ""

# ── IAM Role ──────────────────────────────────────────────────────────────────
if aws iam get-role --role-name "$ROLE_NAME" &>/dev/null; then
  echo "  [OK]      IAM role $ROLE_NAME already exists"
  ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --query Role.Arn --output text)
else
  echo "  [CREATE]  IAM role $ROLE_NAME..."
  ROLE_ARN=$(aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document '{
      "Version":"2012-10-17",
      "Statement":[{
        "Effect":"Allow",
        "Principal":{"Service":"lambda.amazonaws.com"},
        "Action":"sts:AssumeRole"
      }]
    }' \
    --query Role.Arn --output text)

  aws iam attach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"

  echo "  [WAIT]    IAM propagation (12 s)..."
  sleep 12
fi

# ── Inline ECS policy (idempotent) ────────────────────────────────────────────
# Scoped to this cluster only — cannot touch other clusters or services.
aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "ecs-demo-control" \
  --policy-document "{
    \"Version\":\"2012-10-17\",
    \"Statement\":[{
      \"Effect\":\"Allow\",
      \"Action\":[\"ecs:DescribeServices\",\"ecs:UpdateService\"],
      \"Resource\":[
        \"arn:aws:ecs:${ECS_REGION}:${ACCOUNT_ID}:cluster/${CLUSTER}\",
        \"arn:aws:ecs:${ECS_REGION}:${ACCOUNT_ID}:service/${CLUSTER}/*\"
      ]
    }]
  }"
echo "  [OK]      ECS inline policy applied (cluster-scoped)"

# ── Package Lambda ────────────────────────────────────────────────────────────
echo "  [PACKAGE] Zipping handler.py..."
ZIP_FILE="/tmp/demo-control-$$.zip"
rm -f "$ZIP_FILE"
python3 - <<PYEOF
import zipfile, os
with zipfile.ZipFile("$ZIP_FILE", "w", zipfile.ZIP_DEFLATED) as z:
    z.write("$SCRIPT_DIR/handler.py", "handler.py")
PYEOF
echo "  [OK]      $(du -h "$ZIP_FILE" | cut -f1) zip created"

# ── Create or Update Lambda ───────────────────────────────────────────────────
ENV_VARS="Variables={CONTROL_TOKEN=${TOKEN},ECS_CLUSTER=${CLUSTER},ECS_REGION=${ECS_REGION},ECS_SERVICES=${ECS_SERVICES},DEMO_URL=${DEMO_URL}}"

if aws lambda get-function --function-name "$LAMBDA_NAME" --region "$REGION" &>/dev/null; then
  echo "  [UPDATE]  Lambda code..."
  aws lambda update-function-code \
    --function-name "$LAMBDA_NAME" \
    --zip-file "fileb://$ZIP_FILE" \
    --region "$REGION" > /dev/null

  aws lambda wait function-updated \
    --function-name "$LAMBDA_NAME" --region "$REGION"

  echo "  [UPDATE]  Lambda configuration..."
  aws lambda update-function-configuration \
    --function-name "$LAMBDA_NAME" \
    --environment "$ENV_VARS" \
    --region "$REGION" > /dev/null
else
  echo "  [CREATE]  Lambda function $LAMBDA_NAME..."
  aws lambda create-function \
    --function-name  "$LAMBDA_NAME" \
    --runtime        python3.12 \
    --role           "$ROLE_ARN" \
    --handler        handler.lambda_handler \
    --zip-file       "fileb://$ZIP_FILE" \
    --timeout        30 \
    --memory-size    128 \
    --environment    "$ENV_VARS" \
    --region         "$REGION" > /dev/null

  echo "  [WAIT]    Lambda activation..."
  aws lambda wait function-active \
    --function-name "$LAMBDA_NAME" --region "$REGION"
fi

rm -f "$ZIP_FILE"
echo "  [OK]      Lambda deployed"

# ── Function URL ──────────────────────────────────────────────────────────────
# Delete and recreate to ensure clean state (AWS sometimes caches config)
aws lambda delete-function-url-config \
  --function-name "$LAMBDA_NAME" \
  --region "$REGION" 2>/dev/null || true

echo "  [CREATE]  Lambda Function URL..."
sleep 2  # Give AWS time to fully delete

FUNCTION_URL=$(aws lambda create-function-url-config \
  --function-name "$LAMBDA_NAME" \
  --auth-type NONE \
  --region "$REGION" \
  --query FunctionUrl --output text)

# Remove old permission if it exists, then add new one
aws lambda remove-permission \
  --function-name "$LAMBDA_NAME" \
  --statement-id FunctionURLPublic \
  --region "$REGION" 2>/dev/null || true

sleep 1

# Add permission with explicit NONE auth type
aws lambda add-permission \
  --function-name "$LAMBDA_NAME" \
  --statement-id FunctionURLPublic \
  --action lambda:InvokeFunctionUrl \
  --principal "*" \
  --function-url-auth-type NONE \
  --region "$REGION" > /dev/null

echo "  [OK]      Function URL created and permissions set"

SHARE_URL="${FUNCTION_URL}?token=${TOKEN}"

echo ""
echo "================================================================"
echo "  Demo Control Panel is live!"
echo "================================================================"
echo ""
echo "  Share this URL with your team:"
echo ""
echo "  $SHARE_URL"
echo ""
echo "  Token file : $TOKEN_FILE"
echo "  (Do not commit the token file to git)"
echo ""
echo "================================================================"
echo "  To redeploy after code changes : ./deploy.sh"
echo "  To rotate the token            : rm $TOKEN_FILE && ./deploy.sh"
echo "  To remove everything           : ./teardown.sh"
echo "================================================================"
