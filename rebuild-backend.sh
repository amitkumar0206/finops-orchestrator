#!/bin/bash
set -euo pipefail

cd /Users/Amit.Kumar2/Documents/private/finops-orchestrator

AWS_REGION=us-east-1
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

# Generate unique tag to force image pull
IMAGE_TAG="$(date +%Y%m%d-%H%M%S)-$(git rev-parse --short HEAD 2>/dev/null || echo 'local')"

echo "=== Logging in to ECR ==="
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_REGISTRY"

echo "=== Building backend image (with fixed code) ==="
DOCKER_BUILDKIT=1 docker build --platform linux/amd64 -f backend/Dockerfile -t finops-backend .

echo "=== Tagging image with unique tag: ${IMAGE_TAG} ==="
docker tag finops-backend:latest "${ECR_REGISTRY}/finops-backend:${IMAGE_TAG}"
docker tag finops-backend:latest "${ECR_REGISTRY}/finops-backend:latest"

echo "=== Pushing to ECR ==="
docker push "${ECR_REGISTRY}/finops-backend:${IMAGE_TAG}"
docker push "${ECR_REGISTRY}/finops-backend:latest"

echo "=== Forcing ECS to redeploy with new image ==="
# Stop existing tasks to force new image pull
TASK_ARNS=$(aws ecs list-tasks --cluster finops-intelligence-platform-cluster --service-name finops-intelligence-platform-backend --region "$AWS_REGION" --query 'taskArns' --output text)
if [ -n "$TASK_ARNS" ]; then
  echo "Stopping existing tasks to force image pull..."
  for TASK_ARN in $TASK_ARNS; do
    aws ecs stop-task --cluster finops-intelligence-platform-cluster --task "$TASK_ARN" --region "$AWS_REGION" --query 'task.taskArn' --output text
  done
fi

aws ecs update-service \
  --cluster finops-intelligence-platform-cluster \
  --service finops-intelligence-platform-backend \
  --force-new-deployment \
  --region "$AWS_REGION"

echo "=== Waiting for deployment to complete ==="
aws ecs wait services-stable \
  --cluster finops-intelligence-platform-cluster \
  --services finops-intelligence-platform-backend \
  --region "$AWS_REGION"

echo "✅ SUCCESS: Backend rebuilt and deployed!"
echo "Image: ${ECR_REGISTRY}/finops-backend:${IMAGE_TAG} (also tagged as :latest)"
echo "New code is now running in ECS"
