# Demo-Only Deployment (Lowest-Cost Path)

This deployment mode is intended for client demos, not multi-tenant SaaS production.

## What this mode changes

- Uses `DEMO_MODE=true` in backend
- Disables PostgreSQL-backed features (`DATABASE_ENABLED=false`, `CHAT_HISTORY_ENABLED=false`)
- Removes expensive core infrastructure from the main stack:
  - No RDS
  - No Valkey
  - No NAT gateway
- Runs ECS tasks in public subnets with public IP assignment
- Keeps ALB + ECS + Bedrock + S3/Athena for NLP + cost recommendations

## Intended use case

- Show NLP-driven cloud cost analysis and optimization recommendations
- Use static demo data in S3 that you refresh daily
- Single environment at `demo.aasmaa.ai`

## Prerequisites

- AWS CLI configured
- Docker running
- Route53 hosted zone ID for `aasmaa.ai` (if using custom domain)
- Bedrock model access enabled

## One-command demo deploy

Run from repo root:

```bash
AWS_REGION=us-east-1 \
DOMAIN_NAME=demo.aasmaa.ai \
HOSTED_ZONE_ID=<your_hosted_zone_id> \
CREATE_ACM_CERTIFICATE=true \
DEMO_ALLOWED_ACCOUNT_IDS=123456789012,210987654321 \
BEDROCK_MODEL=us.amazon.nova-lite-v1:0 \
bash scripts/deployment/deploy-demo-only.sh
```

## Recommended low-cost settings

- `BEDROCK_MODEL=us.amazon.nova-lite-v1:0` (or `us.amazon.nova-micro-v1:0`)
- Keep ECS desired count at 1 for both backend and frontend
- Limit demo account scope with `DEMO_ALLOWED_ACCOUNT_IDS`
- Use compressed Parquet demo datasets in S3

## Data refresh strategy

- Upload fresh static demo files into the S3 demo bucket daily
- Keep schema stable to avoid demo-time query errors
- Reuse curated prompts/queries for predictable outputs

## Notes

- This mode intentionally bypasses JWT login/database-backed user context and injects a synthetic demo identity.
- Do not use this mode for real customer production workloads.
