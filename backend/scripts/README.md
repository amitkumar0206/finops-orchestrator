# Database Scripts Directory

This directory contains database initialization and migration scripts.

## Directory Structure

```
scripts/
├── init_database.sh              # Main initialization orchestrator
├── seed_all_32_recommendations.sql  # One-time seed for optimization recommendations
├── migrations/                    # One-time data migrations
│   └── (future migration scripts)
└── completed/                     # Tracking directory (git-ignored)
    └── *.completed               # Completion markers
```

## Script Types

### 1. Seed Scripts (One-Time)
**Location**: `scripts/seed_*.sql`

These scripts populate initial reference data and should only run once.

**Behavior**:
- Runs on first deployment (fresh install)
- Checks for completion marker in `completed/` folder
- If data exists in table, marks as completed without re-running
- Safe to run multiple times (idempotent)

**Examples**:
- `seed_all_32_recommendations.sql` - Populates optimization_recommendations table

### 2. Migration Scripts (One-Time)
**Location**: `scripts/migrations/*.sql`

These scripts handle one-time data transformations or fixes.

**Behavior**:
- Runs sequentially in alphabetical order
- Each script runs only once (completion tracked)
- Use naming convention: `YYYYMMDD_description.sql`
- Example: `20251121_fix_column_names.sql`

**When to Create**:
- Data transformation needed after schema change
- Backfilling missing data
- Fixing data inconsistencies

### 3. Initialization Script
**Location**: `scripts/init_database.sh`

Orchestrates all database initialization logic.

**Responsibilities**:
- Detects fresh install vs update
- Runs seed scripts (if not completed)
- Runs pending migrations
- Provides clear status messages
- Tracks completion state

## Adding New Scripts

### Adding a Seed Script

1. Create the SQL file:
   ```bash
   backend/scripts/seed_something.sql
   ```

2. Add to `init_database.sh`:
   ```bash
   # In PHASE 2 section
   SEED_SCRIPT="$SCRIPT_DIR/seed_something.sql"
   SEED_NAME="seed_something"
   
   if [ -f "$SEED_SCRIPT" ]; then
       if has_been_run "$SEED_NAME"; then
           echo "⏭️  Skipping: $SEED_NAME (already completed)"
       else
           run_sql_file "$SEED_SCRIPT"
       fi
   fi
   ```

### Adding a Migration Script

1. Create SQL file in migrations folder:
   ```bash
   backend/scripts/migrations/20251122_add_missing_tags.sql
   ```

2. No code changes needed - `init_database.sh` auto-discovers migrations

## Completion Tracking

Each script creates a completion marker:
```
backend/scripts/completed/seed_all_32_recommendations.completed
```

File contains timestamp of completion:
```
2025-11-21T14:30:00Z
```

**Important**: The `completed/` directory is git-ignored and instance-specific.

## Deployment Scenarios

### Fresh Install (No Infrastructure)
```
1. CloudFormation creates infrastructure
2. RDS database created (empty)
3. Alembic runs schema migrations
4. init_database.sh runs:
   - Detects fresh install (< 5 tables)
   - Runs ALL seed scripts
   - Runs ALL migration scripts
   - Creates completion markers
   - Shows "FRESH INSTALL COMPLETE" message
```

### Update (Infrastructure Exists)
```
1. New Docker image deployed
2. Existing RDS database
3. Alembic runs new schema migrations (if any)
4. init_database.sh runs:
   - Detects update (>= 5 tables)
   - Skips completed seed scripts
   - Runs only NEW migration scripts
   - Verifies existing data
   - Shows "UPDATE COMPLETE" message
```

### Re-deployment (No Changes)
```
1. Same Docker image redeployed
2. Existing RDS database
3. Alembic: "Already at latest version"
4. init_database.sh runs:
   - Skips ALL completed scripts
   - Verifies data exists
   - Shows "UPDATE COMPLETE" (all skipped)
```

## Best Practices

1. **Idempotent Scripts**: Design SQL scripts to be safe if run multiple times
   ```sql
   -- Good
   INSERT INTO table (id, name) VALUES (1, 'test')
   ON CONFLICT (id) DO NOTHING;
   
   -- Bad
   INSERT INTO table (id, name) VALUES (1, 'test');
   -- Would fail on second run
   ```

2. **Check Before Action**:
   ```sql
   -- Only insert if not exists
   INSERT INTO table (id, name)
   SELECT 1, 'test'
   WHERE NOT EXISTS (SELECT 1 FROM table WHERE id = 1);
   ```

3. **Migration Naming**: Use dates for ordering
   - `20251121_initial_seed.sql`
   - `20251122_fix_metadata.sql`
   - `20251123_backfill_tags.sql`

4. **Test Locally**: Always test scripts locally before deploying

5. **Rollback Plan**: For destructive changes, create backup first
   ```sql
   -- Create backup table
   CREATE TABLE old_data_backup AS SELECT * FROM old_data;
   
   -- Perform migration
   UPDATE old_data SET ...;
   ```

## Troubleshooting

### Script Not Running
1. Check if completion marker exists: `ls -la backend/scripts/completed/`
2. Delete marker to re-run: `rm backend/scripts/completed/script_name.completed`
3. Redeploy application

### Script Failed
1. Check logs: `aws logs tail /ecs/finops-intelligence-platform/backend --since 10m`
2. Look for error in `/tmp/script_name.log` inside container
3. Fix SQL syntax/logic
4. Delete completion marker if created
5. Redeploy

### Data Missing After Deployment
1. Check if seed ran: Look for "Running One-Time Seed Scripts" in logs
2. Verify completion: `ls backend/scripts/completed/`
3. Manual verification:
   ```bash
   # Connect to ECS container
   PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -U $POSTGRES_USER -d $POSTGRES_DB
   
   # Check table
   SELECT COUNT(*) FROM optimization_recommendations;
   ```

## Version Control

**Commit**:
- All `.sql` scripts
- `init_database.sh`
- This README.md

**Git-Ignore**:
- `completed/` directory
- `*.completed` files
- Temporary logs

This ensures each deployment environment tracks its own completion state.
