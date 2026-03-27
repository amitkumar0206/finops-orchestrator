"""Add cloudwatch_analysis to opportunity_source enum

Extends the opportunity_source PostgreSQL ENUM to include the new
'cloudwatch_analysis' source value used by the CloudWatch idle resource
detection, RI/SP analysis, and storage optimization signal services.

Revision ID: 017
Revises: 016
Create Date: 2026-03-28 00:00:00.000000
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '017'
down_revision = '016'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL ALTER TYPE ... ADD VALUE cannot run inside a transaction block.
    # We use op.execute with IF NOT EXISTS to make it idempotent.
    op.execute("""
        DO $$
        BEGIN
            ALTER TYPE opportunity_source ADD VALUE IF NOT EXISTS 'cloudwatch_analysis';
        EXCEPTION
            WHEN others THEN null;
        END $$;
    """)


def downgrade() -> None:
    # PostgreSQL does not support removing enum values directly.
    # The safest downgrade is to leave the value in place (no-op).
    # If a full rollback is needed, recreate the type without the value.
    pass
