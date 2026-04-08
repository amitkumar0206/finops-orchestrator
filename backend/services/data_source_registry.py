"""Service layer for F-001 multi-cloud data source registry and ingestion runs."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple
from uuid import UUID, uuid4

import structlog
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy import text

from backend.config.settings import get_settings
from backend.models.data_sources import (
    DataSourceCapabilitiesResponse,
    DataSourceCreateRequest,
    DataSourceIngestResponse,
    DataSourceIngestRequest,
    DataSourceProvider,
    DataSourceResponse,
    DataSourceMode,
    DataSourceRunResponse,
    DataSourceRunStatus,
    DataSourceStatus,
    DataSourceTestResponse,
    DataSourceUploadResponse,
    NormalizedCostRecord,
)
from backend.services.database import DatabaseService
from backend.services.focus_normalizer import FocusNormalizer
from backend.services.provider_connectors import (
    AWSCURConnector,
    AzureExportConnector,
    GCPBillingConnector,
    GenericCostConnector,
)

logger = structlog.get_logger(__name__)
settings = get_settings()


class ProviderConnector(Protocol):
    def validate_credentials(self, credentials: Dict[str, Any]) -> Dict[str, Any]: ...
    def load_dataframe(self, content: bytes, filename: str, max_rows: int) -> pd.DataFrame: ...


class DataSourceRegistryService:
    def __init__(self, organization_id: UUID):
        self.organization_id = organization_id
        self.db = DatabaseService()
        self._schema_checked = False
        self.normalizer = FocusNormalizer()
        self.connectors: Dict[DataSourceProvider, ProviderConnector] = {
            DataSourceProvider.AWS_CUR: AWSCURConnector(),
            DataSourceProvider.AZURE_EXPORT: AzureExportConnector(),
            DataSourceProvider.GCP_BILLING: GCPBillingConnector(),
            DataSourceProvider.GENERIC_COST: GenericCostConnector(),
        }

    async def _ensure_db(self) -> None:
        if not settings.database_enabled:
            raise RuntimeError("DATABASE_ENABLED must be true for data source ingestion")
        if not self.db.engine:
            await self.db.initialize()
        await self._ensure_schema()

    async def _ensure_schema(self) -> None:
        if self._schema_checked:
            return
        if not self.db.engine:
            return

        statements = [
            """
            CREATE TABLE IF NOT EXISTS data_sources (
                id UUID PRIMARY KEY,
                organization_id UUID NOT NULL,
                name VARCHAR(120) NOT NULL,
                provider_type TEXT NOT NULL,
                connection_mode TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                credentials JSONB NOT NULL DEFAULT '{}'::jsonb,
                scope JSONB NOT NULL DEFAULT '{}'::jsonb,
                retention_months INTEGER NOT NULL DEFAULT 24,
                schema_version VARCHAR(40) NOT NULL DEFAULT 'focus-v1',
                currency VARCHAR(8),
                timezone VARCHAR(64),
                is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
                version INTEGER NOT NULL DEFAULT 1,
                created_by UUID,
                updated_by UUID,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS source_file_registry (
                id UUID PRIMARY KEY,
                organization_id UUID NOT NULL,
                data_source_id UUID NOT NULL,
                file_name VARCHAR(255) NOT NULL,
                file_size_bytes BIGINT NOT NULL,
                file_checksum VARCHAR(64) NOT NULL,
                created_by UUID,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(organization_id, data_source_id, file_checksum)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS data_source_runs (
                id UUID PRIMARY KEY,
                organization_id UUID NOT NULL,
                data_source_id UUID NOT NULL,
                status TEXT NOT NULL,
                trigger_type VARCHAR(40) NOT NULL,
                source_file_id UUID,
                records_read INTEGER NOT NULL DEFAULT 0,
                records_normalized INTEGER NOT NULL DEFAULT 0,
                validation_errors JSONB NOT NULL DEFAULT '[]'::jsonb,
                run_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ,
                created_by UUID,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS normalized_cost_partitions (
                id UUID PRIMARY KEY,
                organization_id UUID NOT NULL,
                data_source_id UUID NOT NULL,
                run_id UUID NOT NULL,
                provider_type TEXT NOT NULL,
                partition_month DATE NOT NULL,
                billing_period_start DATE NOT NULL,
                billing_period_end DATE NOT NULL,
                account_or_project_id VARCHAR(128),
                service_name VARCHAR(255) NOT NULL,
                region VARCHAR(64),
                usage_quantity NUMERIC(20, 6) NOT NULL DEFAULT 0,
                usage_unit VARCHAR(64),
                cost_amount NUMERIC(20, 6) NOT NULL,
                currency VARCHAR(8) NOT NULL DEFAULT 'USD',
                tags JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_data_sources_org ON data_sources (organization_id, provider_type)",
            "CREATE INDEX IF NOT EXISTS idx_data_source_runs_org ON data_source_runs (organization_id, data_source_id, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_normalized_cost_org_month ON normalized_cost_partitions (organization_id, partition_month)",
            "CREATE INDEX IF NOT EXISTS idx_normalized_cost_provider ON normalized_cost_partitions (organization_id, provider_type, service_name)",
        ]

        engine = self.db.engine
        if not engine:
            return

        async with engine.begin() as conn:
            for sql in statements:
                await conn.execute(text(sql))

        self._schema_checked = True

    async def _engine(self) -> AsyncEngine:
        await self._ensure_db()
        if not self.db.engine:
            raise RuntimeError("Database engine is not initialized")
        return self.db.engine

    async def capabilities(self) -> DataSourceCapabilitiesResponse:
        return DataSourceCapabilitiesResponse(
            enabled=settings.f001_data_sources_enabled,
            providers=[
                DataSourceProvider.AWS_CUR,
                DataSourceProvider.AZURE_EXPORT,
                DataSourceProvider.GCP_BILLING,
                DataSourceProvider.GENERIC_COST,
            ],
            modes=[
                DataSourceMode.CONNECTED,
                DataSourceMode.ADVISORY_UPLOAD,
            ],
            max_upload_size_mb=settings.f001_upload_max_size_mb,
            max_upload_rows=settings.f001_upload_max_rows,
            supports_async_ingest=False,
        )

    async def create_data_source(self, payload: DataSourceCreateRequest, actor_id: UUID) -> DataSourceResponse:
        await self._ensure_db()
        now = datetime.now(timezone.utc)
        data_source_id = uuid4()

        engine = await self._engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    """
                    INSERT INTO data_sources (
                        id, organization_id, name, provider_type, connection_mode,
                        status, credentials, scope, retention_months,
                        schema_version, currency, timezone,
                        created_by, updated_by, created_at, updated_at
                    ) VALUES (
                        :id, :organization_id, :name, :provider_type, :connection_mode,
                        :status, :credentials::jsonb, :scope::jsonb, :retention_months,
                        :schema_version, :currency, :timezone,
                        :created_by, :updated_by, :created_at, :updated_at
                    )
                    RETURNING id, organization_id, name, provider_type, connection_mode,
                        status, schema_version, currency, timezone, created_at, updated_at
                    """
                ),
                {
                    "id": data_source_id,
                    "organization_id": self.organization_id,
                    "name": payload.name,
                    "provider_type": payload.provider_type.value,
                    "connection_mode": payload.connection_mode.value,
                    "status": payload.status.value,
                    "credentials": self._redact_credentials(payload.credentials),
                    "scope": payload.scope,
                    "retention_months": payload.retention_months,
                    "schema_version": "focus-v1",
                    "currency": "USD",
                    "timezone": "UTC",
                    "created_by": actor_id,
                    "updated_by": actor_id,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            row = result.mappings().first()

        if not row:
            raise RuntimeError("Failed to create data source")

        await self._audit(actor_id, "data_source_created", "data_source", row["id"], {
            "provider": row["provider_type"],
            "connection_mode": row["connection_mode"],
        })
        return self._to_data_source(row)

    async def list_data_sources(self) -> List[DataSourceResponse]:
        await self._ensure_db()
        query = text(
            """
            SELECT
                ds.id, ds.organization_id, ds.name, ds.provider_type, ds.connection_mode,
                ds.status, ds.schema_version, ds.currency, ds.timezone,
                ds.created_at, ds.updated_at,
                dr.status AS latest_run_status,
                dr.created_at AS latest_run_at
            FROM data_sources ds
            LEFT JOIN LATERAL (
                SELECT status, created_at
                FROM data_source_runs
                WHERE data_source_id = ds.id
                ORDER BY created_at DESC
                LIMIT 1
            ) dr ON TRUE
            WHERE ds.organization_id = :organization_id AND ds.is_deleted = FALSE
            ORDER BY ds.created_at DESC
            """
        )
        engine = await self._engine()
        async with engine.begin() as conn:
            result = await conn.execute(query, {"organization_id": self.organization_id})
            rows = result.mappings().all()
        return [self._to_data_source(r) for r in rows]

    async def get_data_source(self, data_source_id: UUID) -> Optional[DataSourceResponse]:
        await self._ensure_db()
        query = text(
            """
            SELECT
                ds.id, ds.organization_id, ds.name, ds.provider_type, ds.connection_mode,
                ds.status, ds.schema_version, ds.currency, ds.timezone,
                ds.created_at, ds.updated_at,
                dr.status AS latest_run_status,
                dr.created_at AS latest_run_at
            FROM data_sources ds
            LEFT JOIN LATERAL (
                SELECT status, created_at
                FROM data_source_runs
                WHERE data_source_id = ds.id
                ORDER BY created_at DESC
                LIMIT 1
            ) dr ON TRUE
            WHERE ds.organization_id = :organization_id
                AND ds.id = :data_source_id
                AND ds.is_deleted = FALSE
            """
        )
        engine = await self._engine()
        async with engine.begin() as conn:
            result = await conn.execute(query, {"organization_id": self.organization_id, "data_source_id": data_source_id})
            row = result.mappings().first()
        return self._to_data_source(row) if row else None

    async def get_runs(self, data_source_id: UUID) -> List[DataSourceRunResponse]:
        await self._ensure_db()
        query = text(
            """
            SELECT id, data_source_id, organization_id, status, trigger_type, source_file_id,
                records_read, records_normalized, validation_errors, run_metadata,
                started_at, completed_at, created_at
            FROM data_source_runs
            WHERE organization_id = :organization_id AND data_source_id = :data_source_id
            ORDER BY created_at DESC
            LIMIT 100
            """
        )
        engine = await self._engine()
        async with engine.begin() as conn:
            result = await conn.execute(query, {"organization_id": self.organization_id, "data_source_id": data_source_id})
            rows = result.mappings().all()
        return [self._to_run(r) for r in rows]

    async def test_connection(self, data_source_id: UUID) -> DataSourceTestResponse:
        source = await self._get_source_row(data_source_id)
        if source is None:
            raise KeyError("Data source not found")

        connector = self.connectors[DataSourceProvider(source["provider_type"])]
        details = connector.validate_credentials(source.get("credentials") or {})
        return DataSourceTestResponse(
            success=bool(details.get("valid", False)),
            provider_type=DataSourceProvider(source["provider_type"]),
            checked_at=datetime.now(timezone.utc),
            details=details,
        )

    async def ingest(self, data_source_id: UUID, payload: DataSourceIngestRequest, actor_id: UUID) -> DataSourceIngestResponse:
        # Connected-mode stub entrypoint; keeps API shape complete while advisory
        # uploads are the primary path for now.
        source = await self._get_source_row(data_source_id)
        if source is None:
            raise KeyError("Data source not found")

        run_id = await self._create_run(
            data_source_id=data_source_id,
            trigger_type="manual",
            actor_id=actor_id,
            status=DataSourceRunStatus.FAILED,
            validation_errors=["Connected-mode ingestion is not yet enabled for this provider in this deployment"],
            run_metadata={"label": payload.run_label or "manual"},
        )
        await self._audit(actor_id, "data_source_ingest_requested", "data_source", data_source_id, {
            "run_id": str(run_id),
            "result": "not_enabled",
        })
        return DataSourceIngestResponse(
            run_id=run_id,
            status=DataSourceRunStatus.FAILED,
            records_read=0,
            records_normalized=0,
            validation_errors=["Connected-mode ingestion is not yet enabled for this provider in this deployment"],
        )

    async def upload_and_ingest(
        self,
        data_source_id: UUID,
        actor_id: UUID,
        filename: str,
        content: bytes,
    ) -> DataSourceUploadResponse:
        source = await self._get_source_row(data_source_id)
        if source is None:
            raise KeyError("Data source not found")

        provider = DataSourceProvider(source["provider_type"])
        connector = self.connectors[provider]

        checksum = hashlib.sha256(content).hexdigest()
        max_bytes = settings.f001_upload_max_size_mb * 1024 * 1024
        if len(content) > max_bytes:
            raise ValueError(f"File exceeds {settings.f001_upload_max_size_mb} MB limit")

        await self._ensure_db()
        source_file_id, duplicate = await self._register_source_file(
            data_source_id=data_source_id,
            actor_id=actor_id,
            filename=filename,
            file_size=len(content),
            checksum=checksum,
        )

        if duplicate:
            run_id = await self._create_run(
                data_source_id=data_source_id,
                trigger_type="upload",
                actor_id=actor_id,
                status=DataSourceRunStatus.SKIPPED_DUPLICATE,
                source_file_id=source_file_id,
                validation_errors=["Duplicate file checksum already ingested"],
            )
            return DataSourceUploadResponse(
                data_source_id=data_source_id,
                run_id=run_id,
                status=DataSourceRunStatus.SKIPPED_DUPLICATE,
                file_name=filename,
                file_checksum=checksum,
                records_read=0,
                records_normalized=0,
                validation_errors=["Duplicate file checksum already ingested"],
            )

        run_id = await self._create_run(
            data_source_id=data_source_id,
            trigger_type="upload",
            actor_id=actor_id,
            status=DataSourceRunStatus.RUNNING,
            source_file_id=source_file_id,
        )

        df = connector.load_dataframe(content=content, filename=filename, max_rows=settings.f001_upload_max_rows)
        records, validation_errors = self.normalizer.normalize(provider=provider, df=df)

        await self._store_normalized_records(data_source_id=data_source_id, run_id=run_id, records=records)
        final_status = DataSourceRunStatus.COMPLETED if records else DataSourceRunStatus.FAILED

        await self._finish_run(
            run_id=run_id,
            status=final_status,
            records_read=int(len(df.index)),
            records_normalized=len(records),
            validation_errors=validation_errors,
            run_metadata={
                "filename": filename,
                "provider": provider.value,
            },
        )

        await self._audit(actor_id, "data_source_upload_ingested", "data_source", data_source_id, {
            "run_id": str(run_id),
            "records_read": int(len(df.index)),
            "records_normalized": len(records),
            "status": final_status.value,
        })

        return DataSourceUploadResponse(
            data_source_id=data_source_id,
            run_id=run_id,
            status=final_status,
            file_name=filename,
            file_checksum=checksum,
            records_read=int(len(df.index)),
            records_normalized=len(records),
            validation_errors=validation_errors,
        )

    async def unified_spend(self) -> List[Dict[str, Any]]:
        """Convenience output proving unified provider/service/month query support."""
        await self._ensure_db()
        query = text(
            """
            SELECT provider_type, partition_month AS month, service_name,
                   SUM(cost_amount) AS cost_amount
            FROM normalized_cost_partitions
            WHERE organization_id = :organization_id
            GROUP BY provider_type, partition_month, service_name
            ORDER BY partition_month DESC, provider_type, service_name
            """
        )
        engine = await self._engine()
        async with engine.begin() as conn:
            result = await conn.execute(query, {"organization_id": self.organization_id})
            rows = result.mappings().all()
        return [
            {
                "provider_type": r["provider_type"],
                "month": r["month"].isoformat() if r["month"] else None,
                "service_name": r["service_name"],
                "cost_amount": float(r["cost_amount"] or 0.0),
            }
            for r in rows
        ]

    async def _register_source_file(
        self,
        data_source_id: UUID,
        actor_id: UUID,
        filename: str,
        file_size: int,
        checksum: str,
    ) -> Tuple[UUID, bool]:
        query_select = text(
            """
            SELECT id
            FROM source_file_registry
            WHERE organization_id = :organization_id
                AND data_source_id = :data_source_id
                AND file_checksum = :file_checksum
            LIMIT 1
            """
        )
        query_insert = text(
            """
            INSERT INTO source_file_registry (
                id, organization_id, data_source_id, file_name, file_size_bytes,
                file_checksum, created_by, created_at
            ) VALUES (
                :id, :organization_id, :data_source_id, :file_name, :file_size_bytes,
                :file_checksum, :created_by, :created_at
            )
            RETURNING id
            """
        )
        engine = await self._engine()
        async with engine.begin() as conn:
            existing = await conn.execute(
                query_select,
                {
                    "id": uuid4(),
                    "organization_id": self.organization_id,
                    "data_source_id": data_source_id,
                    "file_checksum": checksum,
                },
            )
            row = existing.mappings().first()
            if row:
                return row["id"], True

            inserted = await conn.execute(
                query_insert,
                {
                    "organization_id": self.organization_id,
                    "data_source_id": data_source_id,
                    "file_name": filename,
                    "file_size_bytes": file_size,
                    "file_checksum": checksum,
                    "created_by": actor_id,
                    "created_at": datetime.now(timezone.utc),
                },
            )
            inserted_row = inserted.mappings().first()
            if not inserted_row:
                raise RuntimeError("Failed to register source file")
            return inserted_row["id"], False

    async def _create_run(
        self,
        data_source_id: UUID,
        trigger_type: str,
        actor_id: UUID,
        status: DataSourceRunStatus,
        source_file_id: Optional[UUID] = None,
        validation_errors: Optional[List[str]] = None,
        run_metadata: Optional[Dict[str, Any]] = None,
    ) -> UUID:
        await self._ensure_db()
        now = datetime.now(timezone.utc)
        query = text(
            """
            INSERT INTO data_source_runs (
                id, organization_id, data_source_id, status, trigger_type,
                source_file_id, records_read, records_normalized,
                validation_errors, run_metadata,
                started_at, completed_at,
                created_by, created_at
            ) VALUES (
                :id, :organization_id, :data_source_id, :status, :trigger_type,
                :source_file_id, :records_read, :records_normalized,
                :validation_errors::jsonb, :run_metadata::jsonb,
                :started_at, :completed_at,
                :created_by, :created_at
            )
            RETURNING id
            """
        )
        engine = await self._engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                query,
                {
                    "id": uuid4(),
                    "organization_id": self.organization_id,
                    "data_source_id": data_source_id,
                    "status": status.value,
                    "trigger_type": trigger_type,
                    "source_file_id": source_file_id,
                    "records_read": 0,
                    "records_normalized": 0,
                    "validation_errors": validation_errors or [],
                    "run_metadata": run_metadata or {},
                    "started_at": now if status in {DataSourceRunStatus.RUNNING, DataSourceRunStatus.COMPLETED, DataSourceRunStatus.FAILED} else None,
                    "completed_at": now if status in {DataSourceRunStatus.COMPLETED, DataSourceRunStatus.FAILED, DataSourceRunStatus.SKIPPED_DUPLICATE} else None,
                    "created_by": actor_id,
                    "created_at": now,
                },
            )
            run_row = result.mappings().first()
            if not run_row:
                raise RuntimeError("Failed to create data source run")
            return run_row["id"]

    async def _finish_run(
        self,
        run_id: UUID,
        status: DataSourceRunStatus,
        records_read: int,
        records_normalized: int,
        validation_errors: List[str],
        run_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        await self._ensure_db()
        query = text(
            """
            UPDATE data_source_runs
            SET status = :status,
                records_read = :records_read,
                records_normalized = :records_normalized,
                validation_errors = :validation_errors::jsonb,
                run_metadata = COALESCE(run_metadata, '{}'::jsonb) || :run_metadata::jsonb,
                completed_at = :completed_at
            WHERE id = :run_id AND organization_id = :organization_id
            """
        )
        engine = await self._engine()
        async with engine.begin() as conn:
            await conn.execute(
                query,
                {
                    "status": status.value,
                    "records_read": records_read,
                    "records_normalized": records_normalized,
                    "validation_errors": validation_errors,
                    "run_metadata": run_metadata or {},
                    "completed_at": datetime.now(timezone.utc),
                    "run_id": run_id,
                    "organization_id": self.organization_id,
                },
            )

    async def _store_normalized_records(
        self,
        data_source_id: UUID,
        run_id: UUID,
        records: Sequence[NormalizedCostRecord],
    ) -> None:
        if not records:
            return

        query = text(
            """
            INSERT INTO normalized_cost_partitions (
                id, organization_id, data_source_id, run_id, provider_type,
                partition_month, billing_period_start, billing_period_end,
                account_or_project_id, service_name, region,
                usage_quantity, usage_unit, cost_amount, currency, tags,
                created_at
            ) VALUES (
                :id, :organization_id, :data_source_id, :run_id, :provider_type,
                :partition_month, :billing_period_start, :billing_period_end,
                :account_or_project_id, :service_name, :region,
                :usage_quantity, :usage_unit, :cost_amount, :currency, :tags::jsonb,
                :created_at
            )
            """
        )
        now = datetime.now(timezone.utc)
        engine = await self._engine()
        async with engine.begin() as conn:
            for rec in records:
                await conn.execute(
                    query,
                    {
                        "id": uuid4(),
                        "organization_id": self.organization_id,
                        "data_source_id": data_source_id,
                        "run_id": run_id,
                        "provider_type": rec.provider_type.value,
                        "partition_month": rec.partition_month,
                        "billing_period_start": rec.billing_period_start,
                        "billing_period_end": rec.billing_period_end,
                        "account_or_project_id": rec.account_or_project_id,
                        "service_name": rec.service_name,
                        "region": rec.region,
                        "usage_quantity": rec.usage_quantity,
                        "usage_unit": rec.usage_unit,
                        "cost_amount": rec.cost_amount,
                        "currency": rec.currency,
                        "tags": rec.tags,
                        "created_at": now,
                    },
                )

    async def _get_source_row(self, data_source_id: UUID) -> Optional[Dict[str, Any]]:
        await self._ensure_db()
        query = text(
            """
            SELECT id, organization_id, name, provider_type, connection_mode,
                   status, credentials, scope
            FROM data_sources
            WHERE id = :data_source_id AND organization_id = :organization_id AND is_deleted = FALSE
            """
        )
        engine = await self._engine()
        async with engine.begin() as conn:
            result = await conn.execute(query, {"data_source_id": data_source_id, "organization_id": self.organization_id})
            row = result.mappings().first()
        return dict(row) if row else None

    async def _audit(
        self,
        actor_id: UUID,
        action: str,
        resource_type: str,
        resource_id: UUID,
        details: Dict[str, Any],
    ) -> None:
        """Best-effort audit log write without failing request paths."""
        try:
            await self._ensure_db()
            query = text(
                """
                INSERT INTO audit_logs (
                    user_id, user_email, action, resource_type, resource_id,
                    status, details, created_at
                ) VALUES (
                    :user_id, :user_email, :action, :resource_type, :resource_id,
                    :status, :details::jsonb, :created_at
                )
                """
            )
            engine = await self._engine()
            async with engine.begin() as conn:
                await conn.execute(
                    query,
                    {
                        "user_id": actor_id,
                        "user_email": "system@aasmaa.local",
                        "action": action,
                        "resource_type": resource_type,
                        "resource_id": resource_id,
                        "status": "success",
                        "details": details,
                        "created_at": datetime.now(timezone.utc),
                    },
                )
        except Exception as exc:  # pragma: no cover
            logger.warning("data_source_audit_failed", action=action, error=str(exc))

    @staticmethod
    def _redact_credentials(raw: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for k, v in raw.items():
            if any(t in k.lower() for t in ["secret", "token", "key", "password"]):
                out[k] = "***"
            else:
                out[k] = v
        return out

    @staticmethod
    def _to_data_source(row: Any) -> DataSourceResponse:
        return DataSourceResponse(
            id=row["id"],
            organization_id=row["organization_id"],
            name=row["name"],
            provider_type=DataSourceProvider(row["provider_type"]),
            connection_mode=DataSourceMode(row["connection_mode"]),
            status=DataSourceStatus(row["status"]),
            schema_version=row["schema_version"],
            currency=row["currency"],
            timezone=row["timezone"],
            latest_run_status=DataSourceRunStatus(row["latest_run_status"]) if row.get("latest_run_status") else None,
            latest_run_at=row.get("latest_run_at"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _to_run(row: Any) -> DataSourceRunResponse:
        return DataSourceRunResponse(
            id=row["id"],
            data_source_id=row["data_source_id"],
            organization_id=row["organization_id"],
            status=DataSourceRunStatus(row["status"]),
            trigger_type=row["trigger_type"],
            source_file_id=row["source_file_id"],
            records_read=int(row["records_read"] or 0),
            records_normalized=int(row["records_normalized"] or 0),
            validation_errors=row.get("validation_errors") or [],
            run_metadata=row.get("run_metadata") or {},
            started_at=row.get("started_at"),
            completed_at=row.get("completed_at"),
            created_at=row["created_at"],
        )


def get_data_source_registry_service(organization_id: UUID) -> DataSourceRegistryService:
    return DataSourceRegistryService(organization_id=organization_id)
