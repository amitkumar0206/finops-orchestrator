# Demo-Only Deployment (Lowest-Cost Path)
# aasmaa Demo Deployment Guide

**UPDATED**: Now supports EC2 t3.small ($12-13/month, RECOMMENDED) and Fargate ($73/month)

Choose EC2 for cost-optimized demo (default), or Fargate for HA. Intended for client demos only.

## What this mode changes

Both EC2 and Fargate modes share these changes:

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

- AWS CLI configured with working `aiverse-deployer` profile
- Docker running locally
- Bedrock model access enabled in AWS account 152924644003
- Route53 hosted zone for `aasmaa.ai` (auto-discovered automatically)

---

## OPTION A: EC2 Deployment (RECOMMENDED, $12-13/month)

**Smallest, cheapest option. Perfect for demo.**

### Deploy with pre-configured environment:

```bash
cd /path/to/repo
source scripts/deployment/demo.aasmaa.ai.env
bash scripts/deployment/deploy-demo-only.sh
```

### Or manually:

```bash
export DEPLOYMENT_BACKEND=ec2
export AWS_PROFILE=aiverse-deployer
export AWS_REGION=us-east-1
export DOMAIN_NAME=demo.aasmaa.ai
export HOSTED_ZONE_ID=Z00723291RSJHAKVIGJBI
export CREATE_ACM_CERTIFICATE=true
bash scripts/deployment/deploy-demo-only.sh
```

**What deploys:**
- CloudFormation stack `aasmaa-demo` (main-stack-demo-ec2.yaml)
- EC2 t3.small instance (2 vCPU, 2GB RAM) in public subnet
- Docker Compose with backend (port 8000) + frontend (port 80)
- Security group: HTTP/HTTPS/SSH open
- ACM certificate for HTTPS (optional, DNS-validated)
- Route53 A record pointing EC2 public IP to `demo.aasmaa.ai`

**Cost: ~$8 (compute) + $2 (storage) + $2 (data xfer + Route53) = $12-13/month**

**Timeline: 5-10 minutes for stack creation + 2-3 min for Docker startup = ~8-13 minutes total**

**Post-deploy**, wait ~5 minutes then visit:
- `https://demo.aasmaa.ai` (if custom domain)
- Or the EC2 public IP from CloudFormation outputs

**To SSH into instance:**
```bash
INSTANCE_IP=$(aws ec2 describe-instances --filters "Name=tag:Name,Values=aasmaa-demo-instance" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
ssh -i /path/to/keypair.pem ec2-user@$INSTANCE_IP
cd /opt/aasmaa-demo && docker-compose logs backend
```

---

## OPTION B: Fargate Deployment (Original, ~$73/month)

**Higher-cost option. Use only if you need multi-AZ HA for demo.**

```bash
export DEPLOYMENT_BACKEND=fargate
bash scripts/deployment/deploy-demo-only.sh
```

**What differs from EC2:**
- Application Load Balancer (always-on): $18/month
- ECS Fargate tasks (1.25 vCPU total): $45/month
- Multi-AZ by default
- Total: ~$73/month (6x more expensive)

**Not recommended for demo unless you specifically need HA.**

## One-command demo deploy


```bash
# DEPRECATED: This command defaults to Fargate now
# Use OPTION A (EC2) instructions above instead for cost-optimized demo
```
### To use the old command with proper settings:
- If your default AWS profile is expired, run with the working profile explicitly, for example:

```bash
# Old Fargate command (not recommended, expensive):
DEPLOYMENT_BACKEND=fargate \\
AWS_PROFILE=aiverse-deployer \\
AWS_REGION=us-east-1 \\
DOMAIN_NAME=demo.aasmaa.ai \\
CREATE_ACM_CERTIFICATE=true \\
DEMO_ALLOWED_ACCOUNT_IDS=123456789012,210987654321 \\
BEDROCK_MODEL=us.amazon.nova-lite-v1:0 \\
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
