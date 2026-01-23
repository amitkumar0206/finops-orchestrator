"""
Database Service - Manages PostgreSQL database operations

SECURITY: This module implements proper SSL/TLS certificate validation
for database connections to prevent man-in-the-middle attacks.

SSL Modes:
- disable: No SSL (NOT recommended for production)
- allow: Try SSL first, fall back to non-SSL
- prefer: Prefer SSL, fall back to non-SSL (default)
- require: Require SSL, but don't verify certificates
- verify-ca: Require SSL and verify CA certificate
- verify-full: Require SSL, verify CA and hostname (RECOMMENDED for production)

For AWS RDS, download the CA bundle from:
https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
"""

import asyncio
import ssl
import os
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
import structlog

from backend.config.settings import get_settings

settings = get_settings()
logger = structlog.get_logger(__name__)


def create_ssl_context(
    ssl_mode: str,
    ca_cert_path: Optional[str] = None,
    client_cert_path: Optional[str] = None,
    client_key_path: Optional[str] = None,
) -> Optional[ssl.SSLContext]:
    """
    Create an SSL context based on the specified SSL mode.

    SECURITY: This function properly configures SSL certificate validation
    to prevent man-in-the-middle attacks on database connections.

    Args:
        ssl_mode: One of disable, allow, prefer, require, verify-ca, verify-full
        ca_cert_path: Path to CA certificate bundle (required for verify-ca/verify-full)
        client_cert_path: Path to client certificate (optional, for mutual TLS)
        client_key_path: Path to client private key (optional, for mutual TLS)

    Returns:
        Configured SSLContext or None if SSL is disabled
    """
    ssl_mode = ssl_mode.lower()

    if ssl_mode == "disable":
        logger.warning(
            "ssl_disabled",
            message="SSL is disabled for database connection. NOT recommended for production."
        )
        return None

    # Create SSL context with secure defaults
    ssl_ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)

    if ssl_mode in ("allow", "prefer", "require"):
        # These modes don't verify certificates (legacy behavior)
        # SECURITY WARNING: This is vulnerable to MITM attacks
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        logger.warning(
            "ssl_no_verification",
            ssl_mode=ssl_mode,
            message=f"SSL mode '{ssl_mode}' does not verify certificates. "
                    f"Consider 'verify-full' for production security."
        )

    elif ssl_mode == "verify-ca":
        # Verify the server certificate is signed by a trusted CA
        # but don't verify the hostname matches
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_REQUIRED

        if ca_cert_path:
            if not os.path.isfile(ca_cert_path):
                raise ValueError(f"CA certificate file not found: {ca_cert_path}")
            ssl_ctx.load_verify_locations(cafile=ca_cert_path)
            logger.info("ssl_ca_loaded", ca_cert_path=ca_cert_path)
        else:
            # Use system CA certificates
            ssl_ctx.load_default_certs()
            logger.info("ssl_using_system_ca", message="Using system CA certificates")

        logger.info(
            "ssl_verify_ca_enabled",
            message="SSL certificate verification enabled (CA only, no hostname check)"
        )

    elif ssl_mode == "verify-full":
        # Full verification: verify CA certificate AND hostname
        # SECURITY: This is the recommended mode for production
        ssl_ctx.check_hostname = True
        ssl_ctx.verify_mode = ssl.CERT_REQUIRED

        if ca_cert_path:
            if not os.path.isfile(ca_cert_path):
                raise ValueError(f"CA certificate file not found: {ca_cert_path}")
            ssl_ctx.load_verify_locations(cafile=ca_cert_path)
            logger.info("ssl_ca_loaded", ca_cert_path=ca_cert_path)
        else:
            # Use system CA certificates
            ssl_ctx.load_default_certs()
            logger.info("ssl_using_system_ca", message="Using system CA certificates")

        logger.info(
            "ssl_verify_full_enabled",
            message="Full SSL verification enabled (CA + hostname)"
        )

    else:
        raise ValueError(
            f"Invalid SSL mode: '{ssl_mode}'. "
            f"Must be one of: disable, allow, prefer, require, verify-ca, verify-full"
        )

    # Load client certificate for mutual TLS if provided
    if client_cert_path and client_key_path:
        if not os.path.isfile(client_cert_path):
            raise ValueError(f"Client certificate file not found: {client_cert_path}")
        if not os.path.isfile(client_key_path):
            raise ValueError(f"Client key file not found: {client_key_path}")

        ssl_ctx.load_cert_chain(certfile=client_cert_path, keyfile=client_key_path)
        logger.info(
            "ssl_client_cert_loaded",
            cert_path=client_cert_path,
            message="Client certificate loaded for mutual TLS"
        )

    return ssl_ctx


class DatabaseService:
    """Service for managing database operations"""

    def __init__(self):
        self.engine = None
        self.session_factory = None

    async def initialize(self):
        """Initialize database connection with secure SSL configuration"""
        try:
            # Log connection info (without password)
            logger.info(
                "initializing_database_connection",
                host=settings.postgres_host,
                port=settings.postgres_port,
                database=settings.postgres_db,
                ssl_mode=settings.postgres_ssl_mode,
            )

            # Configure connection arguments
            connect_args = {
                "server_settings": {"application_name": "finops-intelligence-platform"}
            }

            # Configure SSL based on settings
            ssl_mode = settings.postgres_ssl_mode.lower()

            if ssl_mode != "disable":
                try:
                    ssl_ctx = create_ssl_context(
                        ssl_mode=settings.postgres_ssl_mode,
                        ca_cert_path=settings.postgres_ssl_ca_cert_path,
                        client_cert_path=settings.postgres_ssl_cert_path,
                        client_key_path=settings.postgres_ssl_key_path,
                    )

                    if ssl_ctx:
                        connect_args["ssl"] = ssl_ctx
                        logger.info(
                            "ssl_context_configured",
                            ssl_mode=ssl_mode,
                            ca_cert=settings.postgres_ssl_ca_cert_path or "system default",
                        )

                except Exception as e:
                    # In production/RDS, SSL errors should fail hard
                    if settings.is_production or settings.is_rds_database:
                        logger.error(
                            "ssl_configuration_failed",
                            error=str(e),
                            message="SSL configuration failed. Cannot proceed without secure connection."
                        )
                        raise
                    else:
                        logger.warning(
                            "ssl_configuration_failed",
                            error=str(e),
                            message="SSL configuration failed. Proceeding without SSL in development."
                        )

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