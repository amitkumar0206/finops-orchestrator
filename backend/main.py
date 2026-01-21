"""
FastAPI backend for FinOps AI Cost Intelligence Platform
Main application entry point with middleware, routes, and startup configuration
"""

from contextlib import asynccontextmanager
import asyncio
from typing import Any, Dict

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST, Counter, Histogram

from config.settings import get_settings
from api import chat, health, reports, analytics, athena_queries
from api import saved_views, organizations, scope
from services.vector_store import VectorStoreService
from services.database import DatabaseService
from middleware.account_scoping import AccountScopingMiddleware
from utils.logging import setup_logging

# Setup structured logging
logger = structlog.get_logger(__name__)
settings = get_settings()

# Prometheus metrics
request_count = Counter('http_requests_total', 'Total HTTP requests', ['method', 'endpoint', 'status'])
request_duration = Histogram('http_request_duration_seconds', 'HTTP request duration')


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown events"""
    # Startup
    setup_logging(settings.log_level)
    logger.info("Starting FinOps AI Cost Intelligence Platform", environment=settings.environment)
    
    # Initialize services
    db_service = None
    vector_service = None
    
    try:
        # Initialize database connection in the background to avoid blocking startup
        logger.info("Scheduling database service initialization (non-blocking)...")
        db_service = DatabaseService()

        async def init_db_background():
            try:
                await db_service.initialize()
                app.state.db = db_service
                logger.info("Database service initialized successfully (background)")
            except Exception as e:
                logger.error(f"Database service initialization failed: {e}", exc_info=True)
                logger.warning("Running without database - some features may be limited")

        # Fire-and-forget task; app starts serving immediately
        asyncio.create_task(init_db_background())
        
    except Exception as e:
        logger.error(f"Failed to schedule database service initialization: {e}", exc_info=True)
        logger.warning("Continuing without database - some features may be limited")
    
    try:
        # Initialize vector store (local disk; should be quick). Don't block for too long.
        logger.info("Initializing vector store service...")
        vector_service = VectorStoreService()
        # Bound the time to avoid long startup in rare cases
        await asyncio.wait_for(vector_service.initialize(), timeout=10)
        app.state.vector_store = vector_service
        logger.info("Vector store service initialized successfully")
        
    except asyncio.TimeoutError:
        logger.warning("Vector store initialization timed out (>10s); continuing without it")
    except Exception as e:
        logger.error(f"Failed to initialize vector store service: {e}", exc_info=True)
        logger.warning("Continuing without vector store - some features may be limited")
    
    logger.info("FinOps AI Platform startup complete", 
                database_available=hasattr(app.state, 'db'),
                vector_store_available=hasattr(app.state, 'vector_store'))
    
    yield
    
    # Shutdown
    logger.info("Shutting down FinOps AI Cost Intelligence Platform")
    if hasattr(app.state, 'db') and app.state.db:
        try:
            await app.state.db.close()
            logger.info("Database connection closed")
        except Exception as e:
            logger.error(f"Error closing database: {e}")
    
    if hasattr(app.state, 'vector_store') and app.state.vector_store:
        try:
            await app.state.vector_store.close()
            logger.info("Vector store connection closed")
        except Exception as e:
            logger.error(f"Error closing vector store: {e}")


# Create FastAPI application
app = FastAPI(
    title="FinOps AI Cost Intelligence Platform",
    description="AI-powered AWS cost analysis platform for DAZN with multi-agent architecture",
    version="1.0.0",
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url="/redoc" if settings.environment != "production" else None,
    lifespan=lifespan
)

# Add middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)

# Add account scoping middleware for multi-tenant support
app.add_middleware(AccountScopingMiddleware)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """Prometheus metrics collection middleware"""
    with request_duration.time():
        response = await call_next(request)
        
    request_count.labels(
        method=request.method,
        endpoint=request.url.path,
        status=response.status_code
    ).inc()
    
    return response


@app.middleware("http") 
async def logging_middleware(request: Request, call_next):
    """Request logging middleware"""
    logger.info(
        "HTTP request",
        method=request.method,
        path=request.url.path,
        client=request.client.host if request.client else None
    )
    
    response = await call_next(request)
    
    logger.info(
        "HTTP response",
        status_code=response.status_code,
        method=request.method,
        path=request.url.path
    )
    
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Global exception handler"""
    logger.error(
        "Unhandled exception",
        exc_info=exc,
        path=request.url.path,
        method=request.method
    )
    
    if settings.environment == "production":
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"}
        )
    else:
        return JSONResponse(
            status_code=500,
            content={
                "detail": f"Internal server error: {str(exc)}",
                "type": exc.__class__.__name__
            }
        )


# Include routers
app.include_router(health.router, prefix="/health", tags=["Health"])
app.include_router(chat.router, prefix="/api/v1", tags=["Chat"])
app.include_router(reports.router, prefix="/api/v1/reports", tags=["Reports"])
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["Analytics"])
app.include_router(athena_queries.router, prefix="/api/v1/athena", tags=["Athena Queries"])

# Multi-tenant support routers
app.include_router(saved_views.router, prefix="/api/v1", tags=["Saved Views"])
app.include_router(organizations.router, prefix="/api/v1", tags=["Organizations"])
app.include_router(scope.router, prefix="/api/v1", tags=["Scope"])


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return generate_latest().decode('utf-8')


@app.get("/")
async def root() -> Dict[str, Any]:
    """Root endpoint with API information"""
    return {
        "message": "FinOps AI Cost Intelligence Platform",
        "version": "1.0.0",
        "description": "AI-powered AWS cost analysis platform for DAZN",
        "docs_url": "/docs" if settings.environment != "production" else "Contact admin for API documentation",
        "health_check": "/health",
        "metrics": "/metrics"
    }


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.environment == "development",
        workers=1 if settings.environment == "development" else 4,
        log_level=settings.log_level.lower()
    )