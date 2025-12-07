"""fix expiring recommendations index predicate

Revision ID: 006
Revises: 005
Create Date: 2025-11-17 00:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Drop the old index if it exists
    op.execute("DROP INDEX IF EXISTS idx_optimization_recommendations_expiring;")
    # Create the new index with a valid predicate
    op.execute("""
        CREATE INDEX idx_optimization_recommendations_expiring 
        ON optimization_recommendations (expires_at) 
        WHERE status IN ('pending', 'in_progress') AND expires_at IS NOT NULL;
    """)

def downgrade() -> None:
    # Drop the fixed index
    op.execute("DROP INDEX IF EXISTS idx_optimization_recommendations_expiring;")
    # Optionally, you could recreate the old (invalid) index, but it's not recommended
