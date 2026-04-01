#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

AWS_REGION=us-east-1
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

# Generate unique tag to force image pull
IMAGE_TAG="$(date +%Y%m%d-%H%M%S)-$(git rev-parse --short HEAD 2>/dev/null || echo 'local')"

echo "=== Logging in to ECR ==="
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_REGISTRY"

echo "=== Building frontend image ==="
DOCKER_BUILDKIT=1 docker build --platform linux/amd64 -f frontend/Dockerfile -t aasmaa-frontend .

echo "=== Tagging image with unique tag: ${IMAGE_TAG} ==="
docker tag aasmaa-frontend:latest "${ECR_REGISTRY}/aasmaa-frontend:${IMAGE_TAG}"
docker tag aasmaa-frontend:latest "${ECR_REGISTRY}/aasmaa-frontend:latest"

echo "=== Pushing to ECR ==="
docker push "${ECR_REGISTRY}/aasmaa-frontend:${IMAGE_TAG}"
docker push "${ECR_REGISTRY}/aasmaa-frontend:latest"

echo "=== Forcing ECS to redeploy with new image ==="
TASK_ARNS=$(aws ecs list-tasks --cluster aasmaa-cluster --service-name aasmaa-frontend --region "$AWS_REGION" --query 'taskArns' --output text 2>/dev/null || true)
if [ -n "$TASK_ARNS" ]; then
  echo "Stopping existing tasks to force image pull..."
  for TASK_ARN in $TASK_ARNS; do
    aws ecs stop-task --cluster aasmaa-cluster --task "$TASK_ARN" --region "$AWS_REGION" --query 'task.taskArn' --output text
  done
fi

aws ecs update-service \
  --cluster aasmaa-cluster \
  --service aasmaa-frontend \
  --force-new-deployment \
  --region "$AWS_REGION"

echo "=== Waiting for deployment to complete ==="
aws ecs wait services-stable \
  --cluster aasmaa-cluster \
  --services aasmaa-frontend \
  --region "$AWS_REGION"

echo "✅ SUCCESS: Frontend rebuilt and deployed!"
echo "Image: ${ECR_REGISTRY}/aasmaa-frontend:${IMAGE_TAG} (also tagged as :latest)"
echo "New code is now running in ECS"
