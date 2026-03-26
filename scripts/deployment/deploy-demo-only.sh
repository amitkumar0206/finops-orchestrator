#!/bin/bash

set -euo pipefail

STACK_NAME="aasmaa-demo"
AWS_REGION="${AWS_REGION:-us-east-1}"
ENVIRONMENT="${ENVIRONMENT:-production}"
DOMAIN_NAME="${DOMAIN_NAME:-demo.aasmaa.ai}"
HOSTED_ZONE_ID="${HOSTED_ZONE_ID:-}"
CREATE_ACM_CERTIFICATE="${CREATE_ACM_CERTIFICATE:-true}"
DEMO_ALLOWED_ACCOUNT_IDS="${DEMO_ALLOWED_ACCOUNT_IDS:-}"
DEMO_USER_EMAIL="${DEMO_USER_EMAIL:-demo@aasmaa.ai}"
DEMO_ORGANIZATION_NAME="${DEMO_ORGANIZATION_NAME:-Demo Organization}"
BEDROCK_MODEL="${BEDROCK_MODEL:-us.amazon.nova-lite-v1:0}"
# DEPLOYMENT_BACKEND: 'ec2' (ultra-lean, ~$12/month) or 'fargate' (ALB+ECS, ~$73/month)
# Default: ec2 for cost-optimized demo
DEPLOYMENT_BACKEND="${DEPLOYMENT_BACKEND:-ec2}"

log() {
  echo "[demo-deploy] $1"
}

normalize_zone_id() {
  local zone_id="$1"
  zone_id="${zone_id#/hostedzone/}"
  echo "$zone_id"
}

resolve_hosted_zone_id() {

if [[ "$DEPLOYMENT_BACKEND" != "ec2" && "$DEPLOYMENT_BACKEND" != "fargate" ]]; then
  log "ERROR: DEPLOYMENT_BACKEND must be 'ec2' or 'fargate', got '${DEPLOYMENT_BACKEND}'"
  exit 1
fi

log "Resolving hosted zone for custom domain (backend: ${DEPLOYMENT_BACKEND})"
  local labels=()
  local candidate
  local zone_id

  IFS='.' read -r -a labels <<< "$domain"
  if [[ ${#labels[@]} -lt 2 ]]; then
    return 1
  fi

  for ((i=0; i<${#labels[@]}-1; i++)); do
    candidate="${labels[i]}"
    for ((j=i+1; j<${#labels[@]}; j++)); do
      candidate+=".${labels[j]}"
    done

    zone_id="$(aws route53 list-hosted-zones-by-name \
      --dns-name "$candidate" \
      --max-items 1 \
      --query "HostedZones[?Name=='${candidate}.']|[0].Id" \
      --output text 2>/dev/null || true)"

    if [[ -n "$zone_id" && "$zone_id" != "None" ]]; then
      normalize_zone_id "$zone_id"
      return 0
    fi
  done

  return 1
}

require_tool() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required tool: $1" >&2
    exit 1
  fi
}

require_tool aws
require_tool docker

AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
S3_BUCKET="${S3_BUCKET:-aasmaa-demo-data-${AWS_ACCOUNT_ID}}"
CUR_BUCKET="${CUR_BUCKET:-$S3_BUCKET}"
CUR_PREFIX="${CUR_PREFIX:-demo-cur/}"
ATHENA_DB="${ATHENA_DB:-cost_usage_db}"
ATHENA_TABLE="${ATHENA_TABLE:-cur_data}"
DB_PASSWORD_PLACEHOLDER="demo-disabled-db-password"

BACKEND_IMAGE_URI="${BACKEND_IMAGE_URI:-${ECR_REGISTRY}/aasmaa-backend:demo}"
FRONTEND_IMAGE_URI="${FRONTEND_IMAGE_URI:-${ECR_REGISTRY}/aasmaa-frontend:demo}"

log "Ensuring S3 bucket exists: ${S3_BUCKET}"
aws s3api head-bucket --bucket "$S3_BUCKET" >/dev/null 2>&1 || aws s3 mb "s3://${S3_BUCKET}" --region "$AWS_REGION"

log "Ensuring ECR repositories exist"
aws ecr create-repository --repository-name aasmaa-backend --region "$AWS_REGION" >/dev/null 2>&1 || true
aws ecr create-repository --repository-name aasmaa-frontend --region "$AWS_REGION" >/dev/null 2>&1 || true

log "Logging into ECR"
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_REGISTRY"

log "Building and pushing backend image"
docker build --platform linux/amd64 -f backend/Dockerfile -t aasmaa-backend:demo .
docker tag aasmaa-backend:demo "$BACKEND_IMAGE_URI"
docker push "$BACKEND_IMAGE_URI"

log "Building and pushing frontend image"
docker build --platform linux/amd64 -f frontend/Dockerfile -t aasmaa-frontend:demo .
docker tag aasmaa-frontend:demo "$FRONTEND_IMAGE_URI"
docker push "$FRONTEND_IMAGE_URI"

if [[ -z "$HOSTED_ZONE_ID" && -n "$DOMAIN_NAME" ]]; then
  log "HOSTED_ZONE_ID not provided, attempting auto-discovery for ${DOMAIN_NAME}"
  HOSTED_ZONE_ID="$(resolve_hosted_zone_id "$DOMAIN_NAME" || true)"
fi

if [[ -z "$HOSTED_ZONE_ID" ]]; then
  log "Hosted zone auto-discovery failed; deploying without Route53/ACM custom domain"
  DOMAIN_NAME=""
  CREATE_ACM_CERTIFICATE="false"
else
  log "Using hosted zone ID: ${HOSTED_ZONE_ID}"
fi


if [[ "$DEPLOYMENT_BACKEND" == "ec2" ]]; then
  log "=== ULTRA-LEAN EC2 DEPLOYMENT (t3.small, ~$12-13/month) ==="
  log "Deploying EC2-based infrastructure stack (${STACK_NAME}-ec2)"
  
  EC2_PARAMS=(
    DomainName="$DOMAIN_NAME"
    HostedZoneId="$HOSTED_ZONE_ID"
    CreateACMCertificate="$CREATE_ACM_CERTIFICATE"
    BackendImageUri="$BACKEND_IMAGE_URI"
    FrontendImageUri="$FRONTEND_IMAGE_URI"
    BedrockModelId="$BEDROCK_MODEL"
    S3BucketName="$S3_BUCKET"
    CurReportBucketName="$CUR_BUCKET"
    DemoUserEmail="$DEMO_USER_EMAIL"
    DemoOrganizationName="$DEMO_ORGANIZATION_NAME"
    DemoAllowedAccountIds="$DEMO_ALLOWED_ACCOUNT_IDS"
  )
  
  aws cloudformation deploy \
    --template-file infrastructure/cloudformation/main-stack-demo-ec2.yaml \
    --stack-name "$STACK_NAME" \
    --capabilities CAPABILITY_NAMED_IAM,CAPABILITY_IAM \
    --region "$AWS_REGION" \
    --parameter-overrides "${EC2_PARAMS[@]}"
  
  INSTANCE_ID="$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$AWS_REGION" --query 'Stacks[0].Outputs[?OutputKey==`EC2InstanceId`].OutputValue' --output text 2>/dev/null || true)"
  PUBLIC_IP="$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$AWS_REGION" --query 'Stacks[0].Outputs[?OutputKey==`EC2PublicIP`].OutputValue' --output text 2>/dev/null || true)"
  APP_URL="$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$AWS_REGION" --query 'Stacks[0].Outputs[?OutputKey==`ApplicationURL`].OutputValue' --output text 2>/dev/null || true)"
  
  log "EC2 deployment complete!"
  log "Instance ID: ${INSTANCE_ID}"
  log "Public IP: ${PUBLIC_IP}"
  log "Application URL: ${APP_URL}"
  log "Note: Docker Compose services are starting on the instance. Allow 2-3 minutes for full startup."
  log ""
  log "To SSH into instance (if you set KeyPairName parameter):"
  log "  ssh -i <your-key.pem> ec2-user@${PUBLIC_IP}"

else
  log "=== FARGATE-BASED DEPLOYMENT (ALB + ECS, ~$73/month) ==="
  log "Deploying Fargate infrastructure stack (${STACK_NAME})"
  
  aws cloudformation deploy \
    --template-file infrastructure/cloudformation/main-stack-demo.yaml \
    --stack-name "$STACK_NAME" \
    --capabilities CAPABILITY_NAMED_IAM \
    --region "$AWS_REGION" \
    --parameter-overrides \
      Environment="$ENVIRONMENT" \
      S3BucketName="$S3_BUCKET" \
      CurReportBucketName="$CUR_BUCKET" \
      DomainName="$DOMAIN_NAME" \
      HostedZoneId="$HOSTED_ZONE_ID" \
      CreateACMCertificate="$CREATE_ACM_CERTIFICATE"
  
  CERT_ARN="$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$AWS_REGION" --query 'Stacks[0].Outputs[?OutputKey==`CertificateArn`].OutputValue' --output text 2>/dev/null || true)"
  
  SERVICE_PARAMS=(
    ParentStackName="$STACK_NAME"
    DeploymentMode="demo"
    BackendImageUri="$BACKEND_IMAGE_URI"
    FrontendImageUri="$FRONTEND_IMAGE_URI"
    DatabaseEndpoint="localhost"
    ValkeyEndpoint="localhost"
    DatabasePassword="$DB_PASSWORD_PLACEHOLDER"
    BedrockModelId="$BEDROCK_MODEL"
    S3BucketName="$S3_BUCKET"
    CurBucketName="$CUR_BUCKET"
    CurDatabase="$ATHENA_DB"
    CurTable="$ATHENA_TABLE"
    CurS3Prefix="$CUR_PREFIX"
    DemoUserEmail="$DEMO_USER_EMAIL"
    DemoOrganizationName="$DEMO_ORGANIZATION_NAME"
    DemoAllowedAccountIds="$DEMO_ALLOWED_ACCOUNT_IDS"
  )
  
  if [[ -n "$CERT_ARN" && "$CERT_ARN" != "None" ]]; then
    SERVICE_PARAMS+=(CertificateArn="$CERT_ARN")
  fi
  
  log "Deploying Fargate ECS services stack (${STACK_NAME}-services)"
  aws cloudformation deploy \
    --template-file infrastructure/cloudformation/ecs-services.yaml \
    --stack-name "${STACK_NAME}-services" \
    --capabilities CAPABILITY_IAM \
    --region "$AWS_REGION" \
    --parameter-overrides "${SERVICE_PARAMS[@]}"
  
  ALB_DNS="$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$AWS_REGION" --query 'Stacks[0].Outputs[?OutputKey==`LoadBalancerDNS`].OutputValue' --output text 2>/dev/null || true)"
  APP_URL="$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$AWS_REGION" --query 'Stacks[0].Outputs[?OutputKey==`ApplicationURL`].OutputValue' --output text 2>/dev/null || true)"
  
  log "Fargate deployment complete"
  log "Application URL: ${APP_URL}"
  log "ALB DNS: ${ALB_DNS}"
fi

APP_URL="$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$AWS_REGION" --query 'Stacks[0].Outputs[?OutputKey==`ApplicationURL`].OutputValue' --output text)"
ALB_DNS="$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$AWS_REGION" --query 'Stacks[0].Outputs[?OutputKey==`LoadBalancerDNS`].OutputValue' --output text)"

log "Demo deployment complete"
