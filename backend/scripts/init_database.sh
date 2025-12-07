#!/bin/bash
# Database Initialization and Migration Manager
# Handles one-time seeds, migrations, and tracks completion status

set -e

SCRIPT_DIR="/app/backend/scripts"
COMPLETED_DIR="/app/backend/scripts/completed"
MIGRATIONS_DIR="/app/backend/scripts/migrations"

echo "=================================================="
echo "Database Initialization Manager"
echo "=================================================="

# Ensure directories exist
mkdir -p "$COMPLETED_DIR"
mkdir -p "$MIGRATIONS_DIR"

# Function to check if a script has been run
has_been_run() {
    local script_name="$1"
    [ -f "$COMPLETED_DIR/${script_name}.completed" ]
}

# Function to mark script as completed
mark_completed() {
    local script_name="$1"
    local timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    echo "$timestamp" > "$COMPLETED_DIR/${script_name}.completed"
    echo "✅ Marked $script_name as completed"
}

# Function to check if table exists and has data
check_table_data() {
    local table_name="$1"
    local min_rows="${2:-1}"
    
    local count=$(PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c \
        "SELECT COUNT(*) FROM $table_name;" 2>/dev/null | xargs || echo "0")
    
    [ "$count" -ge "$min_rows" ]
}

# Function to run SQL file
run_sql_file() {
    local sql_file="$1"
    local script_name=$(basename "$sql_file" .sql)
    
    echo ""
    echo "📝 Running: $script_name"
    
    if PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -f "$sql_file" > "/tmp/${script_name}.log" 2>&1; then
        echo "✅ Success: $script_name"
        mark_completed "$script_name"
        return 0
    else
        echo "❌ Failed: $script_name"
        echo "   Log output:"
        tail -20 "/tmp/${script_name}.log" | sed 's/^/   /'
        return 1
    fi
}

# ============================================================
# PHASE 1: Check Database State
# ============================================================

echo ""
echo "🔍 Checking database state..."

# Check if this is a fresh install (no tables) or an update
FRESH_INSTALL=false
TABLE_COUNT=$(PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c \
    "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';" 2>/dev/null | xargs || echo "0")

if [ "$TABLE_COUNT" -lt 5 ]; then
    FRESH_INSTALL=true
    echo "📦 FRESH INSTALL detected (found $TABLE_COUNT tables)"
else
    echo "🔄 UPDATE detected (found $TABLE_COUNT tables)"
fi

# ============================================================
# PHASE 2: Run One-Time Seed Scripts
# ============================================================

echo ""
echo "=================================================="
echo "Running One-Time Seed Scripts"
echo "=================================================="

# Seed 1: Optimization Recommendations
SEED_SCRIPT="$SCRIPT_DIR/seed_all_32_recommendations.sql"
SEED_NAME="seed_all_32_recommendations"

if [ -f "$SEED_SCRIPT" ]; then
    if has_been_run "$SEED_NAME"; then
        echo "⏭️  Skipping: $SEED_NAME (already completed)"
        
        # Verify data is still there
        if check_table_data "optimization_recommendations" 30; then
            local count=$(PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c \
                "SELECT COUNT(*) FROM optimization_recommendations;" 2>/dev/null | xargs)
            echo "   ✅ Verified: $count recommendations exist"
        else
            echo "   ⚠️  Warning: Recommendations table has fewer than expected rows"
            echo "   Re-running seed script..."
            run_sql_file "$SEED_SCRIPT" || echo "   ⚠️  Re-seed failed, continuing..."
        fi
    else
        # Check if table has data (maybe seeded manually)
        if check_table_data "optimization_recommendations" 30; then
            local count=$(PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c \
                "SELECT COUNT(*) FROM optimization_recommendations;" 2>/dev/null | xargs)
            echo "✅ Found existing data: $count recommendations"
            mark_completed "$SEED_NAME"
        else
            # Need to seed
            run_sql_file "$SEED_SCRIPT"
        fi
    fi
else
    echo "⚠️  Seed script not found: $SEED_SCRIPT"
fi

# ============================================================
# PHASE 3: Run One-Time Migration Scripts (if any)
# ============================================================

echo ""
echo "=================================================="
echo "Running One-Time Migrations"
echo "=================================================="

if [ -d "$MIGRATIONS_DIR" ] && [ "$(ls -A $MIGRATIONS_DIR/*.sql 2>/dev/null)" ]; then
    for migration_file in "$MIGRATIONS_DIR"/*.sql; do
        migration_name=$(basename "$migration_file" .sql)
        
        if has_been_run "$migration_name"; then
            echo "⏭️  Skipping: $migration_name (already completed)"
        else
            run_sql_file "$migration_file" || echo "⚠️  Migration failed: $migration_name"
        fi
    done
else
    echo "ℹ️  No migration scripts found in $MIGRATIONS_DIR"
fi

# ============================================================
# PHASE 4: Summary Report
# ============================================================

echo ""
echo "=================================================="
echo "Database Initialization Summary"
echo "=================================================="

# Count recommendations
REC_COUNT=$(PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c \
    "SELECT COUNT(*) FROM optimization_recommendations;" 2>/dev/null | xargs || echo "0")

# Count completed scripts
COMPLETED_COUNT=$(ls -1 "$COMPLETED_DIR"/*.completed 2>/dev/null | wc -l | xargs)

echo ""
echo "📊 Database Status:"
echo "   Tables: $TABLE_COUNT"
echo "   Optimization Recommendations: $REC_COUNT"
echo "   Completed Scripts: $COMPLETED_COUNT"
echo ""

if [ "$FRESH_INSTALL" = true ]; then
    echo "✨ FRESH INSTALL COMPLETE"
    echo ""
    echo "Next steps:"
    echo "  1. Access the application at your ALB URL"
    echo "  2. Test query: 'Generate a cost optimization report'"
    echo "  3. Verify recommendations are displayed"
else
    echo "🔄 UPDATE COMPLETE"
    echo ""
    echo "What was updated:"
    echo "  - Application code deployed"
    echo "  - Database schema migrated (if needed)"
    echo "  - Seed data verified/updated"
    echo ""
    echo "Next steps:"
    echo "  1. Test the application for new features"
    echo "  2. Check CloudWatch logs for any issues"
fi

echo "=================================================="
echo ""

exit 0
