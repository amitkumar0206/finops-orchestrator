"""
CUR Analysis API (Feature 2: CUR / Billing Export Deep Analysis)

Endpoints
---------
POST /api/v1/cur-analysis/upload
    Advisory Mode. Accepts a CUR CSV (or .csv.gz) export, runs the
    pandas-based :class:`CURCSVAnalyzer`, persists the resulting
    opportunities into the org-scoped Opportunities store, and returns the
    full findings list plus a summary.

POST /api/v1/cur-analysis/mine
    Connected Mode. Triggers :class:`CURPatternMiningSignalsService` to run
    the Athena + Cost Explorer detectors against the tenant's live CUR
    table and persists the resulting opportunities. Equivalent to calling
    ``POST /opportunities/ingest?source=cur_analysis`` but returns the raw
    findings as well.

GET /api/v1/cur-analysis/capabilities
    Returns which mode(s) are available and the active thresholds, so the
    frontend can render the right UI per tenant.

All routes require an authenticated :class:`RequestContext` (HIGH-20 tenant
isolation) and respect ``settings.cur_pattern_mining_enabled``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from backend.config.settings import get_settings
from backend.models.opportunities import OpportunityIngestResult
from backend.services.cur_csv_analyzer import CURCSVAnalyzer
from backend.services.cur_pattern_mining_signals import CURPatternMiningSignalsService
from backend.services.opportunities_service import get_opportunities_service
from backend.services.request_context import RequestContext, require_context

router = APIRouter(prefix="/cur-analysis", tags=["CUR Analysis"])
logger = structlog.get_logger(__name__)
settings = get_settings()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CURAnalysisSummary(BaseModel):
    rows_analyzed: int
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    period_days: int
    total_unblended_cost_usd: float
    total_opportunities: int
    estimated_monthly_savings_usd: float
    by_detector: Dict[str, int]


class CURAnalysisResponse(BaseModel):
    mode: str = Field(..., description="'advisory' (CSV upload) or 'connected' (Athena/CE)")
    account_id: Optional[str] = None
    summary: Optional[CURAnalysisSummary] = None
    opportunities: List[Dict[str, Any]] = Field(default_factory=list)
    ingest_result: Optional[OpportunityIngestResult] = None


class CURCapabilitiesResponse(BaseModel):
    enabled: bool
    advisory_mode_available: bool
    connected_mode_available: bool
    upload_max_size_mb: int
    upload_max_rows: int
    lookback_days: int
    thresholds: Dict[str, float]


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


async def _get_context(request: Request) -> RequestContext:
    """Same HIGH-20 guard as opportunities.py — never run without a tenant."""
    return require_context(request)


def _ensure_enabled() -> None:
    if not settings.cur_pattern_mining_enabled:
        raise HTTPException(
            status_code=403,
            detail="CUR pattern mining is disabled for this deployment "
            "(CUR_PATTERN_MINING_ENABLED=false).",
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/capabilities", response_model=CURCapabilitiesResponse)
async def get_capabilities(
    request: Request,
    context: RequestContext = Depends(_get_context),
):
    """Describe which CUR-analysis modes are available for this tenant."""
    cur_issues = settings.validate_cur_configuration()
    return CURCapabilitiesResponse(
        enabled=settings.cur_pattern_mining_enabled,
        advisory_mode_available=settings.cur_pattern_mining_enabled,
        connected_mode_available=settings.cur_pattern_mining_enabled and not cur_issues,
        upload_max_size_mb=settings.cur_upload_max_size_mb,
        upload_max_rows=settings.cur_upload_max_rows,
        lookback_days=settings.cur_mining_lookback_days,
        thresholds={
            "min_idle_cost_usd": settings.cur_mining_min_idle_cost_usd,
            "min_data_transfer_usd": settings.cur_mining_min_data_transfer_usd,
            "min_ri_unused_usd": settings.cur_mining_min_ri_unused_usd,
            "min_sp_unused_usd": settings.cur_mining_min_sp_unused_usd,
            "steady_state_hours_per_day": settings.cur_mining_steady_state_hours_per_day,
            "min_steady_state_cost_usd": settings.cur_mining_min_steady_state_cost_usd,
            "scheduling_off_hours_share": settings.cur_mining_scheduling_off_hours_share,
            "mom_increase_threshold_pct": settings.cur_mining_mom_increase_threshold_pct,
        },
    )


@router.post("/upload", response_model=CURAnalysisResponse)
async def upload_cur_csv(
    request: Request,
    file: UploadFile = File(..., description="AWS CUR export (.csv or .csv.gz)"),
    account_id: Optional[str] = Form(
        None,
        min_length=12,
        max_length=12,
        description="Override AWS account ID if the CUR file omits it",
    ),
    context: RequestContext = Depends(_get_context),
):
    """
    Advisory Mode: analyse an uploaded CUR CSV and persist findings.

    The file is parsed in memory (no disk write), columns are normalised to
    the canonical CUR schema, the seven detectors run, and resulting
    opportunities are ingested into the caller's organisation.
    """
    _ensure_enabled()

    if not file.filename:
        raise HTTPException(status_code=400, detail="filename is required")

    lowered = file.filename.lower()
    if not (lowered.endswith(".csv") or lowered.endswith(".csv.gz") or lowered.endswith(".gz")):
        raise HTTPException(
            status_code=400,
            detail="Only AWS CUR CSV exports (.csv or .csv.gz) are accepted.",
        )

    try:
        content = await file.read()
    except Exception as exc:  # pragma: no cover - FastAPI already guards most cases
        raise HTTPException(status_code=400, detail=f"Failed to read upload: {exc}") from exc

    max_bytes = settings.cur_upload_max_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds {settings.cur_upload_max_size_mb} MB limit.",
        )

    try:
        df = CURCSVAnalyzer.load_dataframe(
            content,
            filename=file.filename,
            max_rows=settings.cur_upload_max_rows,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("CUR CSV parse failed", error=str(exc), filename=file.filename)
        raise HTTPException(
            status_code=400,
            detail="Could not parse the file as a CUR CSV export. "
            "Ensure it was downloaded from the AWS Billing console or S3 CUR bucket.",
        ) from exc

    analyzer = CURCSVAnalyzer(
        account_id=account_id,
        organization_id=context.organization_id,
    )
    result = analyzer.analyze(df)

    ingest_result: Optional[OpportunityIngestResult] = None
    if result["opportunities"]:
        try:
            opp_svc = get_opportunities_service(context.organization_id)
            ingest_result = opp_svc.ingest_signals(result["opportunities"])
        except Exception as exc:
            # Persistence failure must not lose the analysis — return findings
            # anyway so the caller can still act on them.
            logger.warning(
                "CUR CSV opportunities could not be persisted; returning stateless results",
                error=str(exc),
                org_id=str(context.organization_id),
            )

    logger.info(
        "CUR CSV analysed",
        org_id=str(context.organization_id),
        filename=file.filename,
        rows=result["summary"]["rows_analyzed"],
        opportunities=result["summary"]["total_opportunities"],
        savings=result["summary"]["estimated_monthly_savings_usd"],
    )

    return CURAnalysisResponse(
        mode="advisory",
        account_id=analyzer.account_id,
        summary=CURAnalysisSummary(**result["summary"]),
        opportunities=result["opportunities"],
        ingest_result=ingest_result,
    )


@router.post("/mine", response_model=CURAnalysisResponse)
async def mine_cur_connected(
    request: Request,
    context: RequestContext = Depends(_get_context),
):
    """
    Connected Mode: run Athena + Cost Explorer detectors against the live
    CUR table and persist findings. Returns the raw findings list.
    """
    _ensure_enabled()

    cur_issues = settings.validate_cur_configuration()
    if cur_issues:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Athena/CUR is not configured for this deployment; "
                "use Advisory Mode (/cur-analysis/upload) instead.",
                "issues": cur_issues,
            },
        )

    svc = CURPatternMiningSignalsService(organization_id=context.organization_id)
    opportunities = await svc.fetch_all_cur_signals()

    ingest_result: Optional[OpportunityIngestResult] = None
    if opportunities:
        try:
            opp_svc = get_opportunities_service(context.organization_id)
            ingest_result = opp_svc.ingest_signals(opportunities)
        except Exception as exc:
            logger.warning(
                "CUR mining opportunities could not be persisted; returning stateless results",
                error=str(exc),
                org_id=str(context.organization_id),
            )

    by_detector: Dict[str, int] = {}
    for opp in opportunities:
        by_detector[opp.get("category", "other")] = by_detector.get(opp.get("category", "other"), 0) + 1

    logger.info(
        "CUR connected mining complete",
        org_id=str(context.organization_id),
        opportunities=len(opportunities),
    )

    return CURAnalysisResponse(
        mode="connected",
        account_id=svc.account_id,
        summary=CURAnalysisSummary(
            rows_analyzed=0,
            period_start=(datetime.now().date().isoformat()),
            period_end=(datetime.now().date().isoformat()),
            period_days=settings.cur_mining_lookback_days,
            total_unblended_cost_usd=0.0,
            total_opportunities=len(opportunities),
            estimated_monthly_savings_usd=round(
                sum(o.get("estimated_monthly_savings") or 0.0 for o in opportunities), 2
            ),
            by_detector=by_detector,
        ),
        opportunities=opportunities,
        ingest_result=ingest_result,
    )
