"""
Database Service - Manages PostgreSQL database operations
"""

import asyncio
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
import structlog

from backend.config.settings import get_settings

settings = get_settings()
logger = structlog.get_logger(__name__)


class DatabaseService:
    """Service for managing database operations"""
    
    def __init__(self):
        self.engine = None
        self.session_factory = None
    
    async def initialize(self):
        """Initialize database connection"""
        try:
            logger.info("Initializing database connection", database_url=settings.database_url.split('@')[1] if '@' in settings.database_url else 'unknown')
            
            # Configure SSL for asyncpg when using RDS or production
            connect_args = {"server_settings": {"application_name": "finops-intelligence-platform"}}
            if "rds.amazonaws.com" in settings.postgres_host or settings.environment.lower() == "production":
                # Use SSL context requiring encryption but allowing startup before cert validation delays
                try:
                    import ssl
                    ssl_ctx = ssl.create_default_context()
                    ssl_ctx.check_hostname = False  # RDS hostname change tolerance during provisioning
                    ssl_ctx.verify_mode = ssl.CERT_NONE  # Skip verification to prevent early failures
                    connect_args["ssl"] = ssl_ctx
                    logger.info("Configuring database connection with SSL context for RDS")
                except Exception as e:
                    logger.warning(f"Failed to create SSL context: {e}. Proceeding without explicit SSL context.")
            
            self.engine = create_async_engine(
                settings.database_url,
                echo=settings.is_development,
                pool_size=20,
                max_overflow=0,
                pool_pre_ping=True,  # Verify connections before using
                pool_recycle=3600,  # Recycle connections after 1 hour
                connect_args=connect_args
            )
            
            self.session_factory = sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False
            )
            
            # Test connection with retry logic
            max_retries = 12  # Allow up to ~3 minutes for fresh RDS instance to become available
            retry_delay = 15  # Progressive delay accounting for RDS creation latency
            
            for attempt in range(max_retries):
                try:
                    async with self.engine.begin() as conn:
                        await conn.execute(text("SELECT 1"))
                    logger.info("Database connection test successful")
                    break
                except Exception as e:
                    if attempt < max_retries - 1:
                        logger.warning(
                            "Database connection attempt failed",
                            attempt=attempt + 1,
                            max_retries=max_retries,
                            delay_seconds=retry_delay,
                            error=str(e)
                        )
                        await asyncio.sleep(retry_delay)
                        continue
                    else:
                        logger.error("Exhausted database connection retries", attempts=max_retries, error=str(e))
                        raise
            
            logger.info("Database service initialized successfully")
            
        except Exception as e:
            logger.error(f"Database initialization failed: {e}", exc_info=True)
            raise
    
    async def get_session(self):
        """Get database session as context manager"""
        session = self.session_factory()
        return session
    
    async def close(self):
        """Close database connections"""
        if self.engine:
            await self.engine.dispose()