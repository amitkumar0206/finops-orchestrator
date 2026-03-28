# Deployment Scripts Verification & Status

## Scripts Verification ✓

All deployment scripts pass bash syntax validation:
- ✅ `deploy.sh` - main production deployment
- ✅ `scripts/deployment/deploy-demo-barebones.sh` - demo-only infrastructure
- ✅ `scripts/deployment/deploy-demo-only.sh` - alternative demo deployment

## Latest Changes (Commit 1cc0edf)

### Time Range Bug Fix
- **File**: `backend/aasmaa/time_range.py`, `backend/finops/time_range.py`
- **Issue**: "for 60 days" was not recognized as explicit time override, causing costs for 60 days to appear lower than 30 days
- **Fix**: Added missing regex patterns for `for N days/months/weeks/years` to TIME_PATTERNS
- **Impact**: Follow-up messages with explicit time ranges are now correctly parsed as overrides

### Deployment Script Hardening
- **File**: `scripts/deployment/deploy-demo-barebones.sh`
- **Changes**:
  1. Default stack name: `aasmaa-demo` → `aasmaa-demo-barebones` (avoids ghost stack state)
  2. Added `cleanup_stuck_stacks()` function to auto-delete stacks in terminal failure states
  3. Added `--no-fail-on-empty-changeset` for idempotent re-runs
  4. Added CloudFormation event dump for faster failure diagnosis

### CloudFormation Templates
- `infrastructure/cloudformation/main-stack-demo.yaml`: Secret name scoped to stack name
- `infrastructure/cloudformation/ecs-services.yaml`: Use `Fn::ImportValue` for secret ARN reference

## Deployment Status

### Recent Deployment Attempt
**Date**: 2026-03-28  
**Stack**: `aasmaa-demo-1774657014` (timestamp-based to avoid collisions)  
**Result**: ⚠️ Infrastructure deployment failed due to IAM permission restrictions

### IAM Permission Issues
The `amitadmin` user is missing the following permissions:
1. `ec2:RevokeSecurityGroupEgress` - Required to manage ALB security groups
2. `secretsmanager:GetRandomPassword` - Required to create Secrets Manager secrets

### Workaround
To deploy successfully, use either:
1. A user with `AdministratorAccess` policy, or
2. The `aiverse-deployer` user profile:
   ```bash
   export AWS_PROFILE=aiverse-deployer
   export STACK_NAME=aasmaa-demo-barebones
   export BUILD_IMAGES=false
   ./scripts/deployment/deploy-demo-barebones.sh
   ```

## Git Commits
- **1cc0edf**: Fix time range parsing for "for N days" queries; harden demo deploy script
  - 5 files changed, 245 insertions(+), 2 deletions(-)
  - Pushed to origin/DemoOnly

## Next Steps
1. Grant `ec2:*` and `secretsmanager:*` permissions to `amitadmin` user, or
2. Use `aiverse-deployer` profile which has broader permissions
3. Re-run deployment with appropriate credentials
