"""
Pydantic models for multi-cloud data source ingestion and FOCUS normalization.
"""

from __future__ import annotations

from datetime import datetime, date
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class DataSourceProvider(str, Enum):
    AWS_CUR = "aws_cur"
    AZURE_EXPORT = "azure_export"
    GCP_BILLING = "gcp_billing"
    GENERIC_COST = "generic_cost"


class DataSourceMode(str, Enum):
    CONNECTED = "connected"
    ADVISORY_UPLOAD = "advisory_upload"


class DataSourceStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    DISABLED = "disabled"


class DataSourceRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED_DUPLICATE = "skipped_duplicate"


class DataSourceCreateRequest(BaseModel):
    name: str = Field(..., min_length=3, max_length=120)
    provider_type: DataSourceProvider
    connection_mode: DataSourceMode
    credentials: Dict[str, Any] = Field(default_factory=dict)
    scope: Dict[str, Any] = Field(default_factory=dict)
    retention_months: int = Field(default=24, ge=1, le=120)
    status: DataSourceStatus = DataSourceStatus.DRAFT


class DataSourceUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=3, max_length=120)
    credentials: Optional[Dict[str, Any]] = None
    scope: Optional[Dict[str, Any]] = None
    retention_months: Optional[int] = Field(default=None, ge=1, le=120)
    status: Optional[DataSourceStatus] = None


class DataSourceResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    provider_type: DataSourceProvider
    connection_mode: DataSourceMode
    status: DataSourceStatus
    schema_version: str
    currency: Optional[str] = None
    timezone: Optional[str] = None
    latest_run_status: Optional[DataSourceRunStatus] = None
    latest_run_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class DataSourceRunResponse(BaseModel):
    id: UUID
    data_source_id: UUID
    organization_id: UUID
    status: DataSourceRunStatus
    trigger_type: str
    source_file_id: Optional[UUID] = None
    records_read: int = 0
    records_normalized: int = 0
    validation_errors: List[str] = Field(default_factory=list)
    run_metadata: Dict[str, Any] = Field(default_factory=dict)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime


class DataSourceRunSummary(BaseModel):
    total_runs: int
    completed_runs: int
    failed_runs: int
    last_success_at: Optional[datetime] = None


class DataSourceCapabilitiesResponse(BaseModel):
    enabled: bool
    providers: List[DataSourceProvider]
    modes: List[DataSourceMode]
    max_upload_size_mb: int
    max_upload_rows: int
    supports_async_ingest: bool


class DataSourceTestResponse(BaseModel):
    success: bool
    provider_type: DataSourceProvider
    checked_at: datetime
    details: Dict[str, Any] = Field(default_factory=dict)


class DataSourceIngestRequest(BaseModel):
    run_label: Optional[str] = Field(default=None, max_length=120)


class DataSourceIngestResponse(BaseModel):
    run_id: UUID
    status: DataSourceRunStatus
    records_read: int
    records_normalized: int
    validation_errors: List[str] = Field(default_factory=list)


class DataSourceUploadResponse(BaseModel):
    data_source_id: UUID
    run_id: UUID
    status: DataSourceRunStatus
    file_name: str
    file_checksum: str
    records_read: int
    records_normalized: int
    validation_errors: List[str] = Field(default_factory=list)


class NormalizedCostRecord(BaseModel):
    provider_type: DataSourceProvider
    billing_period_start: date
    billing_period_end: date
    partition_month: date
    account_or_project_id: Optional[str] = None
    service_name: str
    region: Optional[str] = None
    usage_quantity: float = 0.0
    usage_unit: Optional[str] = None
    cost_amount: float
    currency: str = "USD"
    tags: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("service_name")
    @classmethod
    def _service_required(cls, v: str) -> str:
        value = (v or "").strip()
        if not value:
            raise ValueError("service_name is required")
        return value


class UnifiedSpendRow(BaseModel):
    provider_type: DataSourceProvider
    month: date
    service_name: str
    cost_amount: float
