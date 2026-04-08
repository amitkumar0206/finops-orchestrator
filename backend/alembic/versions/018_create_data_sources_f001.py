"""Create F-001 data source ingestion tables.

Revision ID: 018
Revises: 017
Create Date: 2026-04-08 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


# revision identifiers, used by Alembic.
revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE data_source_provider AS ENUM (
                'aws_cur',
                'azure_export',
                'gcp_billing',
                'generic_cost'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
        """
    )

    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE data_source_mode AS ENUM (
                'connected',
                'advisory_upload'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
        """
    )

    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE data_source_status AS ENUM (
                'draft',
                'active',
                'disabled'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
        """
    )

    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE data_source_run_status AS ENUM (
                'pending',
                'running',
                'completed',
                'failed',
                'skipped_duplicate'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
        """
    )

    op.create_table(
        "data_sources",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("provider_type", sa.Text(), nullable=False),
        sa.Column("connection_mode", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("credentials", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("scope", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("retention_months", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("schema_version", sa.String(40), nullable=False, server_default="focus-v1"),
        sa.Column("currency", sa.String(8), nullable=True),
        sa.Column("timezone", sa.String(64), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "source_file_registry",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("data_source_id", UUID(as_uuid=True), sa.ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("file_checksum", sa.String(64), nullable=False),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "data_source_id", "file_checksum", name="uq_source_file_checksum"),
    )

    op.create_table(
        "data_source_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("data_source_id", UUID(as_uuid=True), sa.ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("trigger_type", sa.String(40), nullable=False),
        sa.Column("source_file_id", UUID(as_uuid=True), sa.ForeignKey("source_file_registry.id", ondelete="SET NULL"), nullable=True),
        sa.Column("records_read", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_normalized", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("validation_errors", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("run_metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "normalized_cost_partitions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("data_source_id", UUID(as_uuid=True), sa.ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", UUID(as_uuid=True), sa.ForeignKey("data_source_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_type", sa.Text(), nullable=False),
        sa.Column("partition_month", sa.Date(), nullable=False),
        sa.Column("billing_period_start", sa.Date(), nullable=False),
        sa.Column("billing_period_end", sa.Date(), nullable=False),
        sa.Column("account_or_project_id", sa.String(128), nullable=True),
        sa.Column("service_name", sa.String(255), nullable=False),
        sa.Column("region", sa.String(64), nullable=True),
        sa.Column("usage_quantity", sa.Numeric(20, 6), nullable=False, server_default="0"),
        sa.Column("usage_unit", sa.String(64), nullable=True),
        sa.Column("cost_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("tags", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_index("idx_data_sources_org", "data_sources", ["organization_id", "provider_type"])
    op.create_index("idx_data_source_runs_org", "data_source_runs", ["organization_id", "data_source_id", "created_at"])
    op.create_index("idx_normalized_cost_org_month", "normalized_cost_partitions", ["organization_id", "partition_month"])
    op.create_index("idx_normalized_cost_provider", "normalized_cost_partitions", ["organization_id", "provider_type", "service_name"])


def downgrade() -> None:
    op.drop_index("idx_normalized_cost_provider", table_name="normalized_cost_partitions")
    op.drop_index("idx_normalized_cost_org_month", table_name="normalized_cost_partitions")
    op.drop_index("idx_data_source_runs_org", table_name="data_source_runs")
    op.drop_index("idx_data_sources_org", table_name="data_sources")

    op.drop_table("normalized_cost_partitions")
    op.drop_table("data_source_runs")
    op.drop_table("source_file_registry")
    op.drop_table("data_sources")

    op.execute("DROP TYPE IF EXISTS data_source_run_status")
    op.execute("DROP TYPE IF EXISTS data_source_status")
    op.execute("DROP TYPE IF EXISTS data_source_mode")
    op.execute("DROP TYPE IF EXISTS data_source_provider")
