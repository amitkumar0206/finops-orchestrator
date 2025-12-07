# Database Migration Setup

## Overview

The backend container now **automatically runs database migrations on startup** before the FastAPI application starts.

## How It Works

1. **Entrypoint Script** (`docker-entrypoint.sh`):
   - Waits for the database to be ready (max 60 seconds)
   - Converts `DATABASE_URL` from asyncpg to psycopg2 format for Alembic
   - Runs `alembic upgrade head` to apply pending migrations
   - Shows migration status before and after
   - Starts the FastAPI application

2. **Migration Location**: `backend/alembic/versions/`

3. **Current Migrations**:
   - `001_create_conversation_threads.py` - Conversation threading
   - `002_create_conversation_messages.py` - Message storage
   - `003_create_query_intents.py` - Query classification
   - `004_create_agent_executions.py` - Agent execution tracking
   - `005_create_optimization_recommendations.py` - Cost optimization recommendations

## Verifying Migrations

### Check Migration Status in Container

```bash
# Get the running task
aws ecs list-tasks --cluster finops-intelligence-platform-cluster --query 'taskArns[0]' --output text

# View the startup logs (migrations run during startup)
aws logs tail /ecs/finops-intelligence-platform/backend --since 10m --format short
```

### Check Database Directly

```bash
# Connect to RDS (requires network access or bastion)
psql -h <RDS_ENDPOINT> -U postgres -d finops

# Check current migration version
SELECT * FROM alembic_version;

# List all tables
\dt
```

## Manual Migration Commands

If you need to run migrations manually:

```bash
# Inside the container
docker exec -it <container_id> bash
alembic current          # Show current version
alembic history          # Show all migrations
alembic upgrade head     # Apply all pending migrations
alembic downgrade -1     # Rollback one migration
```

## Creating New Migrations

```bash
cd backend

# Auto-generate migration from model changes
alembic revision --autogenerate -m "description of changes"

# Create blank migration
alembic revision -m "description of changes"

# Edit the generated file in alembic/versions/
# Then commit to git
```

## Troubleshooting

### Migrations Fail on Startup

Check the logs:
```bash
aws logs tail /ecs/finops-intelligence-platform/backend --since 30m
```

Common issues:
- Database not ready: The script waits 60s, but you can increase this
- Migration syntax error: Check the migration file
- Concurrent migrations: Only one container should run migrations at a time

### Skip Migrations Temporarily

Set environment variable in the task definition:
```bash
SKIP_MIGRATIONS=true
```

### Check Health After Migration

```bash
curl https://finops.cape.dazn-dev.com/health
```

The health endpoint will show:
- Database connectivity
- Migration status (indirectly - if tables exist)

## Configuration

### Environment Variables

- `DATABASE_URL`: Full database connection string (uses asyncpg for app, converted to psycopg2 for migrations)
- `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`: Alternative way to specify database
- `SKIP_MIGRATIONS`: Set to `true` to skip automatic migrations on startup

### Docker Configuration

- **Entrypoint**: `/app/docker-entrypoint.sh`
- **CMD**: `["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]`
- **Health Check**: Increased `start-period` to 40s to allow time for migrations

## Deployment

When deploying changes:

1. Commit migration files to git
2. Push to repository
3. Deploy using `./deploy.sh`
4. The new task will automatically run migrations on startup
5. Check logs to verify migration success

## Safety Features

- Database connection retry with timeout
- Non-blocking: If migrations fail, the app still starts (with warnings)
- Logging: All migration steps are logged
- Health check: Adjusted to wait for migrations to complete
