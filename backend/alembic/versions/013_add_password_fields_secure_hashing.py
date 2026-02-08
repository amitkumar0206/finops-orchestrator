"""Add password fields with secure hashing support

Revision ID: 013
Revises: 012
Create Date: 2026-02-08 14:00:00.000000

This migration adds password-related columns to the users table
and includes support for tracking password hash versions for future migrations.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '013'
down_revision = '012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Add password authentication fields to users table.

    Fields added:
    - password_hash: Stores the PBKDF2-HMAC-SHA256 hash
    - password_salt: Stores the random salt (64-char hex)
    - password_hash_version: Tracks which hashing parameters were used
      - Version 1: 100,000 iterations (legacy, insecure)
      - Version 2: 600,000 iterations (OWASP 2023+ recommendation)
    - password_updated_at: Timestamp of last password change
    """
    # Add password authentication fields
    op.add_column('users', sa.Column('password_hash', sa.String(128), nullable=True))
    op.add_column('users', sa.Column('password_salt', sa.String(64), nullable=True))
    op.add_column('users', sa.Column('password_hash_version', sa.Integer, server_default='2', nullable=False))
    op.add_column('users', sa.Column('password_updated_at', sa.DateTime(timezone=True), nullable=True))

    # Create index for password lookup optimization
    op.create_index('idx_users_password_hash', 'users', ['password_hash'], unique=False)

    # Create index for password version tracking (for future migrations)
    op.create_index('idx_users_password_version', 'users', ['password_hash_version'], unique=False)

    # Note: password_hash and password_salt are nullable to support:
    # 1. Users who haven't set passwords yet (SSO-only accounts in future)
    # 2. Gradual rollout - existing users without passwords
    #
    # In production, enforce password requirements at application layer


def downgrade() -> None:
    """Remove password fields"""
    # Drop indexes
    op.drop_index('idx_users_password_version', table_name='users')
    op.drop_index('idx_users_password_hash', table_name='users')

    # Drop columns
    op.drop_column('users', 'password_updated_at')
    op.drop_column('users', 'password_hash_version')
    op.drop_column('users', 'password_salt')
    op.drop_column('users', 'password_hash')
