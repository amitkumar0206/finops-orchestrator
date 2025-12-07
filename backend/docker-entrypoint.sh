#!/bin/bash
set -e

echo "=================================================="
echo "FinOps Backend - Container Startup"
echo "=================================================="

# Convert DATABASE_URL from asyncpg to psycopg2 for Alembic if needed
if [ ! -z "$DATABASE_URL" ]; then
    # Alembic needs psycopg2, but app uses asyncpg
    # Convert postgresql+asyncpg:// to postgresql+psycopg2://
    export ALEMBIC_DATABASE_URL="${DATABASE_URL//postgresql+asyncpg:\/\//postgresql+psycopg2:\/\/}"
    export ALEMBIC_DATABASE_URL="${ALEMBIC_DATABASE_URL//postgresql:\/\//postgresql+psycopg2:\/\/}"
fi

# Function to wait for database to be ready
wait_for_db() {
    echo "Waiting for database to be ready..."
    max_attempts=30
    attempt=0
    
    # Convert DATABASE_URL to async format for SQLAlchemy check
    ASYNC_DB_URL=$(echo "$DATABASE_URL" | sed 's|^postgresql://|postgresql+asyncpg://|')
    
    while [ $attempt -lt $max_attempts ]; do
        if python3 -c "
import sys
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def check():
    try:
        engine = create_async_engine('${ASYNC_DB_URL}', echo=False)
        async with engine.begin() as conn:
            await conn.execute(text('SELECT 1'))
        await engine.dispose()
        return True
    except Exception as e:
        print(f'Database not ready: {e}', file=sys.stderr)
        return False

result = asyncio.run(check())
sys.exit(0 if result else 1)
" 2>/dev/null; then
            echo "✅ Database is ready"
            return 0
        fi
        
        attempt=$((attempt + 1))
        echo "⏳ Database not ready yet (attempt $attempt/$max_attempts), waiting 2 seconds..."
        sleep 2
    done
    
    echo "❌ Database failed to become ready after $max_attempts attempts"
    return 1
}

# Function to run database migrations
run_migrations() {
    echo ""
    echo "=================================================="
    echo "Running Database Migrations"
    echo "=================================================="
    
    # Check if alembic is installed
    if ! command -v alembic &> /dev/null; then
        echo "⚠️  Alembic not found, skipping migrations"
        return 0
    fi
    
    # Check if alembic.ini exists
    if [ ! -f "alembic.ini" ]; then
        echo "⚠️  alembic.ini not found, skipping migrations"
        return 0
    fi
    
    # Show current migration status
    echo "📍 Current migration status:"
    if [ ! -z "$ALEMBIC_DATABASE_URL" ]; then
        DATABASE_URL="$ALEMBIC_DATABASE_URL" alembic current 2>/dev/null || echo "No migrations applied yet"
    else
        alembic current 2>/dev/null || echo "No migrations applied yet"
    fi
    
    # Run migrations
    echo ""
    echo "⬆️  Upgrading database to latest version..."
    # Use ALEMBIC_DATABASE_URL if set, otherwise let alembic/env.py handle it
    if [ ! -z "$ALEMBIC_DATABASE_URL" ]; then
        if DATABASE_URL="$ALEMBIC_DATABASE_URL" alembic upgrade head; then
            echo "✅ Migrations completed successfully"
            
            # Show new status
            echo ""
            echo "📍 New migration status:"
            DATABASE_URL="$ALEMBIC_DATABASE_URL" alembic current
        else
            echo "❌ Migration failed!"
            return 1
        fi
    else
        if alembic upgrade head; then
            echo "✅ Migrations completed successfully"
            
            # Show new status
            echo ""
            echo "📍 New migration status:"
            alembic current
        else
            echo "❌ Migration failed!"
            return 1
        fi
    fi
    
    echo "=================================================="
    echo ""
}

# Function to run database initialization scripts
run_database_init() {
    echo ""
    echo "=================================================="
    echo "Database Initialization"
    echo "=================================================="
    
    # Check if init script exists
    if [ ! -f "/app/backend/scripts/init_database.sh" ]; then
        echo "⚠️  Database init script not found, skipping"
        echo "=================================================="
        echo ""
        return 0
    fi
    
    # Make script executable
    chmod +x /app/backend/scripts/init_database.sh
    
    # Run the initialization script
    if /app/backend/scripts/init_database.sh; then
        echo "✅ Database initialization completed"
    else
        echo "⚠️  Database initialization had issues (check logs above)"
        echo "⚠️  Continuing anyway..."
    fi
    
    echo ""
}

# Main execution
echo "Environment: ${ENVIRONMENT:-production}"
echo "Database: ${POSTGRES_HOST:-unknown}:${POSTGRES_PORT:-5432}/${POSTGRES_DB:-unknown}"
echo ""

# Wait for database
if ! wait_for_db; then
    echo "⚠️  Could not connect to database, starting anyway..."
    echo "⚠️  Database-dependent features may not work properly"
else
    # Run migrations if database is available
    if ! run_migrations; then
        echo "⚠️  Migration failed, but continuing to start application..."
        echo "⚠️  Database may not be in the correct state"
    else
        # Run database initialization (seeds, one-time scripts) after successful migrations
        run_database_init
    fi
fi

echo ""
echo "=================================================="
echo "Starting FastAPI Application"
echo "=================================================="
echo ""

# Start the application with provided command or default
exec "$@"
