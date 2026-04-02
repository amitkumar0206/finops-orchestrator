#!/usr/bin/env bash
# deploy.sh — Deploy aasmaa demo control panel using API Gateway HTTP API.
# 
# This is an alternative to Lambda Function URLs that works in all AWS accounts.
# Cost: ~$0.50/month + minimal Lambda costs (within free tier).
# 
# Usage:
#   ./deploy.sh
#
# Setup: Requires same IAM permissions (Lambda, API Gateway, IAM).

set -euo pipefail

REGION="${AWS_REGION:-ap-south-1}"
CLUSTER="${ECS_CLUSTER:-aasmaa-demo-barebones-cluster}"
ECS_REGION="${ECS_REGION:-$REGION}"
ECS_SERVICES="${ECS_SERVICES:-aasmaa-demo-barebones-backend|aasmaa-demo-barebones-frontend}"
DEMO_URL="${DEMO_URL:-https://demo.aasmaa.ai}"
LAMBDA_NAME="aasmaa-demo-control"
API_NAME="aasmaa-demo-control-api"
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
echo "==> Deploying $LAMBDA_NAME with API Gateway HTTP API"
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

  echo "  [WAIT]    IAM propagation (12 s)…"
  sleep 12
fi

# ── Inline ECS policy (idempotent) ────────────────────────────────────────────
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
import zipfile
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

# ── API Gateway HTTP API ──────────────────────────────────────────────────────
echo "  [CREATE]  API Gateway HTTP API..."

# Create API if it doesn't exist
API_ID=$(aws apigatewayv2 get-apis \
  --region "$REGION" \
  --query "Items[?Name=='$API_NAME'].ApiId" \
  --output text 2>/dev/null || true)

if [[ -z "$API_ID" ]]; then
  API_ID=$(aws apigatewayv2 create-api \
    --name "$API_NAME" \
    --protocol-type HTTP \
    --region "$REGION" \
    --query ApiId --output text)
fi

# Create/update integration to the Lambda target.
INT_ID=$(aws apigatewayv2 get-integrations \
  --api-id "$API_ID" \
  --region "$REGION" \
  --query "Items[0].IntegrationId" \
  --output text 2>/dev/null || true)

if [[ -z "$INT_ID" || "$INT_ID" == "None" ]]; then
  INT_ID=$(aws apigatewayv2 create-integration \
    --api-id "$API_ID" \
    --integration-type AWS_PROXY \
    --integration-uri "arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${LAMBDA_NAME}" \
    --payload-format-version "2.0" \
    --region "$REGION" \
    --query IntegrationId --output text)
else
  aws apigatewayv2 update-integration \
    --api-id "$API_ID" \
    --integration-id "$INT_ID" \
    --integration-uri "arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${LAMBDA_NAME}" \
    --payload-format-version "2.0" \
    --region "$REGION" > /dev/null
fi

# Grant API Gateway permission to invoke Lambda
aws lambda add-permission \
  --function-name "$LAMBDA_NAME" \
  --statement-id AllowAPIGateway \
  --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com \
  --region "$REGION" 2>/dev/null || true

# Create or update route
ROUTE_ID=$(aws apigatewayv2 get-routes \
  --api-id "$API_ID" \
  --region "$REGION" \
  --query "Items[?RouteKey=='\$default'].RouteId" \
  --output text 2>/dev/null || true)

if [[ -z "$ROUTE_ID" ]]; then
  aws apigatewayv2 create-route \
    --api-id "$API_ID" \
    --route-key '$default' \
    --target "integrations/$INT_ID" \
    --region "$REGION" > /dev/null
fi

# Create stage if it doesn't exist
STAGE_ID=$(aws apigatewayv2 get-stages \
  --api-id "$API_ID" \
  --region "$REGION" \
  --query "Items[?StageName=='demo'].StageName" \
  --output text 2>/dev/null || true)

if [[ -z "$STAGE_ID" ]]; then
  aws apigatewayv2 create-stage \
    --api-id "$API_ID" \
    --stage-name demo \
    --auto-deploy \
    --region "$REGION" > /dev/null
fi

# Get the API endpoint
API_ENDPOINT=$(aws apigatewayv2 get-api \
  --api-id "$API_ID" \
  --region "$REGION" \
  --query ApiEndpoint \
  --output text)

echo "  [OK]      API Gateway HTTP API deployed"

SHARE_URL="${API_ENDPOINT}/index.html?token=${TOKEN}"

rm -f "$ZIP_FILE"

echo ""
echo "================================================================"
echo "  Demo Control Panel is live!"
echo "================================================================"
echo ""
echo "  Share this URL with your team:"
echo ""
echo "  ${API_ENDPOINT}?token=${TOKEN}"
echo ""
echo "  Token file : $TOKEN_FILE"
echo "  (Do not commit the token file to git)"
echo ""
echo "================================================================"
echo "  To redeploy after code changes : ./deploy.sh"
echo "  To rotate the token            : rm $TOKEN_FILE && ./deploy.sh"
echo "  To remove everything           : ./teardown.sh"
echo "================================================================"
