"""Add user-specific rate limits for fine-grained control

Revision ID: 015
Revises: 014
Create Date: 2026-02-08 18:00:00.000000

This migration adds support for per-user rate limit overrides,
allowing organization admins to set custom limits for specific users.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = '015'
down_revision = '014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Create user_rate_limits table for per-user rate limit overrides.

    Priority hierarchy:
    1. User-specific override (user_rate_limits) - highest priority
    2. Organization role default (organization_rate_limits)
    3. System default (settings.py) - lowest priority

    Example use case:
    - Organization has default admin limit of 100/hour
    - Give John Smith (admin) custom limit of 200/hour
    - Other admins still have 100/hour
    """
    op.create_table(
        'user_rate_limits',
        sa.Column('id', UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', UUID, sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('organization_id', UUID, sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('endpoint', sa.String(100), nullable=False),  # e.g., "athena_export"
        sa.Column('requests_per_hour', sa.Integer, nullable=False),  # Custom limit for this user
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('created_by', UUID, sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('notes', sa.Text, nullable=True),  # Optional note explaining why custom limit

        # Unique constraint: One limit per (user, org, endpoint) combination
        sa.UniqueConstraint('user_id', 'organization_id', 'endpoint', name='uq_user_org_endpoint_limit')
    )

    # Indexes for efficient lookups
    op.create_index('idx_user_rate_limits_user', 'user_rate_limits', ['user_id'])
    op.create_index('idx_user_rate_limits_org', 'user_rate_limits', ['organization_id'])
    op.create_index('idx_user_rate_limits_endpoint', 'user_rate_limits', ['endpoint'])
    op.create_index('idx_user_rate_limits_lookup', 'user_rate_limits',
                    ['user_id', 'organization_id', 'endpoint'])


def downgrade() -> None:
    """Remove user rate limits table"""
    op.drop_index('idx_user_rate_limits_lookup', table_name='user_rate_limits')
    op.drop_index('idx_user_rate_limits_endpoint', table_name='user_rate_limits')
    op.drop_index('idx_user_rate_limits_org', table_name='user_rate_limits')
    op.drop_index('idx_user_rate_limits_user', table_name='user_rate_limits')
    op.drop_table('user_rate_limits')
