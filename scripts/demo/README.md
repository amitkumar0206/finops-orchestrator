# demo.aasmaa.ai — Start / Stop Scripts

Located in `scripts/demo/`. These scripts scale the ECS tasks to 0 (stop) or 1 (start) to save compute cost without tearing down any infrastructure.

## Scripts

| Script | Purpose |
|--------|---------|
| `start-demo.sh` | Scale services back up to 1 task each |
| `stop-demo.sh` | Scale services down to 0 tasks (saves ~$X/day on Fargate) |
| `status-demo.sh` | Show current desired/running counts and rollout state |

## Prerequisites

- AWS CLI configured with credentials that have `ecs:UpdateService` and `ecs:DescribeServices` permissions
- `jq` installed (`brew install jq`)

## Usage

```bash
# Make scripts executable (one-time)
chmod +x scripts/demo/start-demo.sh scripts/demo/stop-demo.sh scripts/demo/status-demo.sh

# Check current status
./scripts/demo/status-demo.sh

# Stop all services (saves Fargate task cost)
./scripts/demo/stop-demo.sh

# Start all services
./scripts/demo/start-demo.sh

# Start and wait until healthy (~2-3 min)
./scripts/demo/start-demo.sh --wait

# Override region if needed
AWS_REGION=us-east-1 ./scripts/demo/start-demo.sh --wait
```

## What is stopped vs. what keeps running

| Resource | Stop command effect | Monthly cost impact |
|----------|--------------------|--------------------|
| ECS tasks (backend + frontend) | ✅ Scaled to 0 — **no cost** | Saves ~$30–60/mo depending on task size |
| ALB (Application Load Balancer) | ❌ Still running | ~$16/mo fixed |
| RDS (PostgreSQL) | ❌ Still running | ~$15–50/mo |
| ElastiCache / Valkey | ❌ Still running | ~$12–25/mo |
| ECR images | ❌ Stored (read-only) | ~$0.10/GB/mo |

To also stop RDS and ElastiCache, use the AWS Console or add `aws rds stop-db-instance` / `aws elasticache` commands.

## Notes

- Stopping tasks does **not** affect the CloudFormation stacks or any infrastructure.
- The ALB stays up so DNS (`demo.aasmaa.ai`) keeps resolving, but will return 503 while tasks are stopped.
- Services start fresh and pick up the latest task definition revision when started again.
