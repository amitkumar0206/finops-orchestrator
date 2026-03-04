"""Add encrypted columns for sensitive credentials

Adds *_encrypted columns to aws_accounts and ticketing_integrations tables
so that role_arn, external_id, and ticketing credentials can be stored
encrypted at rest.  The original plaintext columns are kept temporarily
for backward compatibility; a later migration will drop them.

Revision ID: 016
Revises: 015
Create Date: 2026-03-04 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '016'
down_revision = '015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # aws_accounts — encrypted versions of role_arn and external_id
    op.add_column('aws_accounts', sa.Column('role_arn_encrypted', sa.Text, nullable=True))
    op.add_column('aws_accounts', sa.Column('external_id_encrypted', sa.Text, nullable=True))

    # Make role_arn nullable so future rows can use encrypted-only storage
    op.alter_column('aws_accounts', 'role_arn', nullable=True)

    # ticketing_integrations — encrypted version of credentials JSONB
    op.add_column('ticketing_integrations', sa.Column('credentials_encrypted', sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column('ticketing_integrations', 'credentials_encrypted')
    op.alter_column('aws_accounts', 'role_arn', nullable=False)
    op.drop_column('aws_accounts', 'external_id_encrypted')
    op.drop_column('aws_accounts', 'role_arn_encrypted')
