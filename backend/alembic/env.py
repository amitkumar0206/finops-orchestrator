"""Alembic environment configuration for FinOps conversation threading system."""

from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
import os
import sys

# Add the backend directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Import your models here
from backend.models.database_models import Base
try:
    # Prefer using application settings for DB URL if available
    from backend.config.settings import get_settings
    _settings = get_settings()
    _pg_user = _settings.postgres_user
    _pg_pass = _settings.postgres_password
    _pg_host = _settings.postgres_host
    _pg_port = _settings.postgres_port
    _pg_db = _settings.postgres_db
    # Use psycopg2 sync driver for Alembic
    _sqlalchemy_url = f"postgresql+psycopg2://{_pg_user}:{_pg_pass}@{_pg_host}:{_pg_port}/{_pg_db}"
except Exception:
    _sqlalchemy_url = None

# this is the Alembic Config object
config = context.config

# If DATABASE_URL env-var provided, prefer it; else use settings; else keep ini
_env_url = os.getenv("DATABASE_URL")
if _env_url:
    config.set_main_option("sqlalchemy.url", _env_url)
elif _sqlalchemy_url:
    config.set_main_option("sqlalchemy.url", _sqlalchemy_url)

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target metadata for 'autogenerate' support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
