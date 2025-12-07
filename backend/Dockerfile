# Backend Dockerfile - Optimized for faster builds
FROM python:3.11-slim AS base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=0 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

# Set work directory
WORKDIR /app

# Install system dependencies (cached layer)
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Builder stage for dependencies
FROM base AS builder

# Set PATH early to avoid warnings during pip install
ENV PATH=/root/.local/bin:$PATH

# Copy and install Python dependencies
COPY backend/requirements.txt .

# Use pip cache mount for faster rebuilds
# Install with extra index for torch CPU-only version
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --user --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

# Final stage
FROM base

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local

# Make sure scripts in .local are usable
ENV PATH=/root/.local/bin:$PATH

# Build argument for cache busting - placed here to only invalidate code layers
ARG BUILD_TIMESTAMP=unknown
ENV BUILD_TIMESTAMP=$BUILD_TIMESTAMP

# Copy backend code to /app/backend to match import structure
COPY backend/ /app/backend/

# Create data directory for Chroma
RUN mkdir -p /app/data/chroma

# Make entrypoint script executable
RUN chmod +x /app/backend/docker-entrypoint.sh

# Add build timestamp label for tracking
LABEL build.timestamp="${BUILD_TIMESTAMP}"

# Expose port
EXPOSE 8000

# Health check with longer start-period to allow for DB migrations
HEALTHCHECK --interval=30s --timeout=10s --start-period=300s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Set entrypoint to run migrations before starting app
ENTRYPOINT ["/app/backend/docker-entrypoint.sh"]

# Default command to start the application (run from backend directory)
WORKDIR /app/backend
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]