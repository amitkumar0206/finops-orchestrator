#!/bin/bash
# Backend startup script with diagnostics
# This can be used as an alternative CMD in Dockerfile for debugging

set -e

echo "=================================================="
echo "FinOps Backend - Startup"
echo "=================================================="
echo ""

# Print environment info (without sensitive data)
echo "Environment: ${ENVIRONMENT:-development}"
echo "Python version: $(python --version)"
echo "Working directory: $(pwd)"
echo ""

# Check if we should run diagnostics
if [ "${RUN_DIAGNOSTICS}" = "true" ]; then
    echo "Running diagnostics..."
    python diagnose.py || true
    echo ""
fi

# Print configuration (masked)
echo "Configuration:"
echo "  - Postgres Host: ${POSTGRES_HOST:-localhost}"
echo "  - Postgres Port: ${POSTGRES_PORT:-5432}"
echo "  - Postgres DB: ${POSTGRES_DB:-finops}"
echo "  - AWS Region: ${AWS_REGION:-us-east-1}"
echo "  - ChromaDB Path: ${CHROMA_DB_PATH:-./data/chroma}"
echo ""

# Start the application
echo "Starting FastAPI application..."
echo "=================================================="
echo ""

exec uvicorn main:app \
    --host "${HOST:-0.0.0.0}" \
    --port "${PORT:-8000}" \
    --log-level "${LOG_LEVEL:-info}" \
    ${RELOAD:+--reload}
