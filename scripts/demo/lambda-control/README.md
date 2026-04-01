# Demo Control Panel

This control panel is designed to run as a public API Gateway endpoint backed by a Lambda function. The Lambda is hosted in one region and can control ECS services in another region.

## Status

| Component | Status | Notes |
|-----------|--------|-------|
| Lambda function | ✓ Supported | `aasmaa-demo-control` with handler code |
| IAM role | ✓ Supported | Scoped to your ECS cluster only |
| Auth token | ✓ Supported | Stored in `.control-token` (gitignored) |
| API Gateway | ✓ Supported | Created by `deploy-apigw.sh` |

## Quick Start

1. Deploy with `AWS_REGION=ap-south-1 ECS_REGION=us-east-1 ./deploy-apigw.sh`
2. Copy the printed API Gateway URL with the token
3. Share that URL with your team

## Files in this directory

- `handler.py` — Lambda function code (serves HTML + handles start/stop/status)
- `deploy.sh` — Legacy Function URL deploy script
- `deploy-apigw.sh` — API Gateway deploy script for the supported setup
- `.control-token` — Your secret token (**.gitignore'd**)
- `MANUAL_CONSOLE_SETUP.md` — Optional manual API Gateway fallback
- `teardown.sh` — Cleanup script

## What the control panel does

- **Shows status** of `aasmaa-backend` and `aasmaa-frontend` ECS services
- **Starts services** (scales desiredCount from 0 → 1)
- **Stops services** (scales desiredCount from 1 → 0)
- **Displays logs** of actions in real-time
- **Auto-refreshes** every 15 seconds
- **Token-protected** — only valid token can trigger start/stop

## Lambda permissions

The Lambda's IAM role can ONLY:
- ✓ `ecs:DescribeServices` on your cluster
- ✓ `ecs:UpdateService` on your cluster
- ✗ Cannot touch any other AWS resources

## Cost

**~$0.50/month** (free tier covers most of it)
- API Gateway: $0.50/month + free tier
- Lambda: free tier (~1M requests/month)

## Recommended Deploy Command

```bash
cd scripts/demo/lambda-control
AWS_REGION=ap-south-1 ECS_REGION=us-east-1 ./deploy-apigw.sh
```

This keeps the public API in `ap-south-1` while controlling the ECS cluster in `us-east-1`.

---

**Token location**:
```bash
cat .control-token
```

**Re-deploy after code changes**:
```bash
AWS_REGION=ap-south-1 ECS_REGION=us-east-1 ./deploy-apigw.sh
```

**Remove everything**:
```bash
./teardown.sh
# Then delete the API Gateway in the console
```
