"""F-001 Data Sources API: registry, validation, ingestion, and run history."""

from __future__ import annotations

from typing import List
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from prometheus_client import Counter, Histogram
from sqlalchemy.exc import ProgrammingError

from backend.config.settings import get_settings
from backend.models.data_sources import (
    DataSourceCapabilitiesResponse,
    DataSourceCreateRequest,
    DataSourceIngestRequest,
    DataSourceIngestResponse,
    DataSourceResponse,
    DataSourceRunResponse,
    DataSourceTestResponse,
    DataSourceUploadResponse,
)
from backend.services.data_source_registry import get_data_source_registry_service
from backend.services.request_context import RequestContext, require_context

router = APIRouter(prefix="/data-sources", tags=["Data Sources"])
logger = structlog.get_logger(__name__)
settings = get_settings()

ingest_requests_total = Counter(
    "data_source_ingest_requests_total",
    "Total data-source ingest requests",
    ["provider", "result"],
)

ingest_duration_seconds = Histogram(
    "data_source_ingest_duration_seconds",
    "Time spent handling data-source uploads",
    ["provider"],
)


async def _get_context(request: Request) -> RequestContext:
    return require_context(request)


def _require_org_id(context: RequestContext) -> UUID:
    if context.organization_id is None:
        raise HTTPException(status_code=403, detail="Organization context is required")
    return context.organization_id


def _ensure_enabled() -> None:
    if not settings.f001_data_sources_enabled:
        raise HTTPException(status_code=403, detail="F-001 data source ingestion is disabled")


def _ensure_operational() -> None:
    _ensure_enabled()
    if not settings.database_enabled:
        raise HTTPException(
            status_code=503,
            detail="Data Sources requires PostgreSQL-backed mode and is unavailable in this deployment.",
        )


@router.get("/capabilities", response_model=DataSourceCapabilitiesResponse)
async def get_capabilities(
    request: Request,
    context: RequestContext = Depends(_get_context),
):
    _ensure_operational()
    svc = get_data_source_registry_service(_require_org_id(context))
    return await svc.capabilities()


@router.post("", response_model=DataSourceResponse)
async def create_data_source(
    request: Request,
    body: DataSourceCreateRequest,
    context: RequestContext = Depends(_get_context),
):
    _ensure_operational()
    svc = get_data_source_registry_service(_require_org_id(context))
    try:
        return await svc.create_data_source(body, actor_id=context.user_id)
    except Exception as exc:
        logger.error("data_source_create_failed", error=str(exc), org_id=str(context.organization_id))
        raise HTTPException(status_code=500, detail="Unable to create data source") from exc


@router.get("", response_model=List[DataSourceResponse])
async def list_data_sources(
    request: Request,
    context: RequestContext = Depends(_get_context),
):
    _ensure_operational()
    svc = get_data_source_registry_service(_require_org_id(context))
    try:
        return await svc.list_data_sources()
    except ProgrammingError as exc:
        logger.error("data_source_schema_not_ready", error=str(exc), org_id=str(context.organization_id))
        raise HTTPException(
            status_code=503,
            detail="Data Sources backend schema is not configured yet. Run backend migrations and reload the page.",
        ) from exc


@router.get("/{data_source_id}", response_model=DataSourceResponse)
async def get_data_source(
    request: Request,
    data_source_id: UUID,
    context: RequestContext = Depends(_get_context),
):
    _ensure_operational()
    svc = get_data_source_registry_service(_require_org_id(context))
    out = await svc.get_data_source(data_source_id)
    if not out:
        raise HTTPException(status_code=404, detail="Data source not found")
    return out


@router.get("/{data_source_id}/runs", response_model=List[DataSourceRunResponse])
async def get_data_source_runs(
    request: Request,
    data_source_id: UUID,
    context: RequestContext = Depends(_get_context),
):
    _ensure_operational()
    svc = get_data_source_registry_service(_require_org_id(context))
    try:
        return await svc.get_runs(data_source_id)
    except ProgrammingError as exc:
        logger.error("data_source_runs_schema_not_ready", error=str(exc), org_id=str(context.organization_id))
        raise HTTPException(
            status_code=503,
            detail="Data Sources run history is unavailable until backend migrations are applied.",
        ) from exc


@router.post("/{data_source_id}/test", response_model=DataSourceTestResponse)
async def test_data_source(
    request: Request,
    data_source_id: UUID,
    context: RequestContext = Depends(_get_context),
):
    _ensure_operational()
    svc = get_data_source_registry_service(_require_org_id(context))
    try:
        return await svc.test_connection(data_source_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Data source not found")


@router.post("/{data_source_id}/ingest", response_model=DataSourceIngestResponse)
async def ingest_data_source(
    request: Request,
    data_source_id: UUID,
    body: DataSourceIngestRequest,
    context: RequestContext = Depends(_get_context),
):
    _ensure_operational()
    svc = get_data_source_registry_service(_require_org_id(context))
    try:
        result = await svc.ingest(data_source_id, body, actor_id=context.user_id)
        source = await svc.get_data_source(data_source_id)
        provider = source.provider_type.value if source else "unknown"
        ingest_requests_total.labels(provider=provider, result=result.status.value).inc()
        return result
    except KeyError:
        raise HTTPException(status_code=404, detail="Data source not found")


@router.post("/upload", response_model=DataSourceUploadResponse)
async def upload_data_source_file(
    request: Request,
    data_source_id: UUID = Form(...),
    file: UploadFile = File(...),
    context: RequestContext = Depends(_get_context),
):
    _ensure_operational()
    if not file.filename:
        raise HTTPException(status_code=400, detail="file name is required")

    content = await file.read()
    svc = get_data_source_registry_service(_require_org_id(context))

    source = await svc.get_data_source(data_source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Data source not found")

    with ingest_duration_seconds.labels(provider=source.provider_type.value).time():
        try:
            result = await svc.upload_and_ingest(
                data_source_id=data_source_id,
                actor_id=context.user_id,
                filename=file.filename,
                content=content,
            )
            ingest_requests_total.labels(provider=source.provider_type.value, result=result.status.value).inc()
            return result
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            logger.error(
                "data_source_upload_failed",
                error=str(exc),
                data_source_id=str(data_source_id),
                org_id=str(context.organization_id),
            )
            raise HTTPException(status_code=500, detail="Unable to process uploaded file") from exc


@router.get("/preview/unified-spend")
async def preview_unified_spend(
    request: Request,
    context: RequestContext = Depends(_get_context),
):
    """Diagnostic endpoint used to verify unified provider/service/month query output."""
    _ensure_operational()
    svc = get_data_source_registry_service(_require_org_id(context))
    return {"rows": await svc.unified_spend()}
