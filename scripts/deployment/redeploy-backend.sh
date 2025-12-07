#!/bin/bash
# Quick redeploy script for backend with the fixes

set -euo pipefail

# Lock file to prevent multiple instances
LOCKFILE="/tmp/redeploy-backend.lock"

# Cleanup function
cleanup() {
    rm -f "$LOCKFILE"
}

# Set trap to cleanup on exit
trap cleanup EXIT INT TERM

echo "🔧 Redeploying Backend with Error Fixes"
echo "========================================"
echo ""

# 0. Check for and kill any existing redeploy scripts
echo "🔍 Checking for existing redeploy processes..."

# Check for lock file
if [ -f "$LOCKFILE" ]; then
    LOCK_PID=$(cat "$LOCKFILE")
    if ps -p "$LOCK_PID" > /dev/null 2>&1; then
        echo "⚠️  Another redeploy is already running (PID: $LOCK_PID)"
        echo "❌ Aborting to prevent conflicts"
        echo "   If you're sure no other redeploy is running, remove: $LOCKFILE"
        exit 1
    else
        echo "🧹 Cleaning up stale lock file"
        rm -f "$LOCKFILE"
    fi
fi

# Create lock file with current PID
echo $$ > "$LOCKFILE"

# Also check for any other redeploy scripts that might be running
EXISTING_PIDS=$(ps aux | grep -E "(redeploy-services\.sh|redeploy-backend\.sh)" | grep -v grep | grep -v $$ | awk '{print $2}')

if [ ! -z "$EXISTING_PIDS" ]; then
    echo "⚠️  Found running redeploy script(s) with PID(s): $EXISTING_PIDS"
    echo "🛑 Killing existing redeploy processes..."
    echo "$EXISTING_PIDS" | xargs kill -9 2>/dev/null || true
    sleep 2
    echo "✅ Cleaned up existing processes"
else
    echo "✅ No existing redeploy processes found"
fi
echo ""

# 1. Rebuild backend image
echo "📦 Building backend Docker image for linux/amd64..."
docker build --platform linux/amd64 -t finops-backend ./backend || docker-compose build --build-arg DOCKER_BUILDKIT=1 backend

# 2. Stop and remove old container
echo "🛑 Stopping old backend container..."
docker-compose stop backend
docker-compose rm -f backend

# 3. Start new container
echo "🚀 Starting new backend container..."
docker-compose up -d backend

# 4. Wait a bit for startup
echo "⏳ Waiting for startup (10 seconds)..."
sleep 10

# 5. Check logs
echo ""
echo "📋 Recent logs:"
echo "========================================"
docker-compose logs --tail=50 backend

echo ""
echo "========================================"
echo "✅ Redeploy complete!"
echo ""
echo "Commands to check status:"
echo "  - View logs:        docker-compose logs -f backend"
echo "  - Run diagnostics:  docker-compose exec backend python diagnose.py"
echo "  - Check health:     curl http://localhost:8000/health | jq"
echo "  - Check readiness:  curl http://localhost:8000/health/readiness | jq"
echo ""
