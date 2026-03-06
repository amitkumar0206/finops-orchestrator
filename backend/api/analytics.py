"""Analytics API endpoints"""

from fastapi import APIRouter, HTTPException, BackgroundTasks, Request, Depends
from datetime import datetime, timedelta, date
from typing import Optional
from pydantic import BaseModel
from botocore.exceptions import ClientError
import hashlib
import structlog

from backend.config.settings import get_settings
from backend.utils.aws_session import create_aws_session, create_aws_client
from backend.utils.aws_constants import AwsService, COST_EXPLORER_REGION
from backend.services.request_context import require_context, RequestContext

router = APIRouter()
settings = get_settings()
logger = structlog.get_logger(__name__)


async def get_request_context(request: Request) -> RequestContext:
    """Dependency to get request context and enforce authentication"""
    return require_context(request)


# ──────────────────────────────────────────────────────────────────────────
# HIGH-15 — Tenant isolation for Cost Explorer
#
# Every get_cost_and_usage() call in this module MUST be filtered to the
# requester's allowed_account_ids. Without this, CE returns spend across
# ALL linked accounts under the management account — any authenticated user
# sees every tenant's costs.
#
# The filter is built once at the top of each handler (before any try/except
# that catches Exception) so that an empty scope fail-closes to 403 and
# propagates cleanly to FastAPI rather than being swallowed as 500/error-dict.
# ──────────────────────────────────────────────────────────────────────────

def _build_account_filter(allowed_account_ids: list[str]) -> dict:
    """
    Build a Cost Explorer Filter dict scoped to the caller's accounts.

    Fail-closed: an empty list means the caller's org has no accounts
    configured, the caller has no account permissions, or their active
    saved-view selection intersected to nothing. In all three cases they
    must see zero data — and since CE rejects an empty Values list anyway,
    we raise 403 here rather than let boto raise a confusing ClientError.
    """
    if not allowed_account_ids:
        raise HTTPException(
            status_code=403,
            detail="No AWS accounts in scope for this request",
        )
    return {
        "Dimensions": {
            "Key": "LINKED_ACCOUNT",
            "Values": list(allowed_account_ids),
        }
    }


def _scope_cache_key(allowed_account_ids: list[str]) -> str:
    """
    Stable tenant segment for Valkey keys. Sorted-then-hashed so the same
    set of accounts in a different order produces the same key, and the raw
    12-digit account IDs never appear in Valkey keyspace.
    """
    canonical = ",".join(sorted(allowed_account_ids))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


class CacheInitRequest(BaseModel):
    """Request model for cache initialization"""
    months: Optional[int] = 13
    force_refresh: Optional[bool] = False


class HistoricalDataResponse(BaseModel):
    """Response model for historical data info"""
    success: bool
    months_available: int
    date_range: dict
    total_records: int
    message: str


@router.get("/")
async def get_analytics(
    request: Request,
    context: RequestContext = Depends(get_request_context)
):
    """Get analytics data. Requires authentication."""
    logger.info(
        "analytics_accessed",
        user_id=str(context.user_id),
        user_email=context.user_email
    )
    return {"analytics": {}, "timestamp": datetime.utcnow().isoformat()}


@router.get("/historical-availability")
async def check_historical_data_availability(
    request: Request,
    context: RequestContext = Depends(get_request_context)
):
    """
    Check how many months of historical cost data are available
    via Cost Explorer API. Requires authentication.
    """
    # HIGH-15: build the tenant filter BEFORE the try block. The except
    # clauses below catch broad Exception → 500; an empty-scope 403 must
    # propagate directly to FastAPI, not be downgraded.
    account_filter = _build_account_filter(context.allowed_account_ids)

    try:
        logger.info(
            "historical_availability_checked",
            user_id=str(context.user_id),
            user_email=context.user_email
        )
        # Initialize Cost Explorer client using IAM role credentials
        # Cost Explorer API is only available in us-east-1
        ce_client = create_aws_client(AwsService.COST_EXPLORER, region_name=COST_EXPLORER_REGION)

        # Query for maximum available historical data (13 months)
        end_date = date.today()
        start_date = end_date - timedelta(days=395)  # ~13 months

        response = ce_client.get_cost_and_usage(
            TimePeriod={
                'Start': start_date.strftime('%Y-%m-%d'),
                'End': end_date.strftime('%Y-%m-%d')
            },
            Granularity='MONTHLY',
            Metrics=['BlendedCost'],
            Filter=account_filter,
        )
        
        months_available = len(response.get('ResultsByTime', []))
        total_cost = sum(
            float(item['Total']['BlendedCost']['Amount'])
            for item in response.get('ResultsByTime', [])
        )
        
        return HistoricalDataResponse(
            success=True,
            months_available=months_available,
            date_range={
                'start': start_date.strftime('%Y-%m-%d'),
                'end': end_date.strftime('%Y-%m-%d')
            },
            total_records=len(response.get('ResultsByTime', [])),
            message=f"Successfully retrieved {months_available} months of historical data. Total cost: ${total_cost:,.2f}"
        )
        
    except ClientError as e:
        logger.error("cost_explorer_access_failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=503,
            detail="Service temporarily unavailable."
        )
    except Exception as e:
        logger.error("historical_data_check_failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An internal error occurred. Please try again later."
        )


async def _load_historical_data_to_cache(
    months: int,
    account_filter: dict,
    scope_key: str,
):
    """
    Background task to load historical data into cache/database
    This preloads commonly accessed data for better performance

    HIGH-15: This runs via BackgroundTasks AFTER the response is sent, so
    RequestContext is not in scope. The handler validates and passes:
      - account_filter: the already-validated CE Filter dict (empty-scope
        has already raised 403 in the handler; this task is never scheduled
        for a zero-scope caller)
      - scope_key: tenant segment for the Valkey keys. Without this,
        scoping the CE calls but NOT the cache keys means tenant A's
        filtered data overwrites tenant B's entry under the same date key.
    """
    try:
        logger.info(f"Starting historical data cache initialization for {months} months")

        # Use IAM role credentials via default credential chain
        ce_client = create_aws_client(AwsService.COST_EXPLORER, region_name=COST_EXPLORER_REGION)

        end_date = date.today()
        start_date = end_date - timedelta(days=months * 30)

        # Load monthly aggregates
        monthly_data = ce_client.get_cost_and_usage(
            TimePeriod={
                'Start': start_date.strftime('%Y-%m-%d'),
                'End': end_date.strftime('%Y-%m-%d')
            },
            Granularity='MONTHLY',
            Metrics=['BlendedCost', 'UsageQuantity'],
            GroupBy=[{'Type': 'DIMENSION', 'Key': 'SERVICE'}],
            Filter=account_filter,
        )

        # Load daily data for recent period (last 90 days)
        recent_start = end_date - timedelta(days=90)
        daily_data = ce_client.get_cost_and_usage(
            TimePeriod={
                'Start': recent_start.strftime('%Y-%m-%d'),
                'End': end_date.strftime('%Y-%m-%d')
            },
            Granularity='DAILY',
            Metrics=['BlendedCost'],
            GroupBy=[{'Type': 'DIMENSION', 'Key': 'SERVICE'}],
            Filter=account_filter,
        )

        # Store this data in Valkey cache (if available)
        try:
            import valkey
            valkey_client = valkey.Valkey(
                host=getattr(settings, 'valkey_host', 'localhost'),
                port=getattr(settings, 'valkey_port', 6379),
                db=getattr(settings, 'valkey_db', 0),
                socket_timeout=2
            )
            valkey_client.set(
                f"analytics:monthly:{scope_key}:{start_date}:{end_date}",
                str(monthly_data)
            )
            valkey_client.set(
                f"analytics:daily:{scope_key}:{recent_start}:{end_date}",
                str(daily_data)
            )
            logger.info("Analytics data persisted to Valkey cache.")
        except Exception as cache_exc:
            logger.warning(f"Valkey not available, skipping cache: {cache_exc}")
        
        monthly_records = sum(
            len(item.get('Groups', [])) 
            for item in monthly_data.get('ResultsByTime', [])
        )
        daily_records = sum(
            len(item.get('Groups', [])) 
            for item in daily_data.get('ResultsByTime', [])
        )
        
        logger.info(
            f"Historical data cache initialized: {monthly_records} monthly records, "
            f"{daily_records} daily records"
        )
        
    except Exception as e:
        logger.error(f"Error loading historical data to cache: {e}")


@router.post("/initialize-cache")
async def initialize_historical_cache(
    cache_request: CacheInitRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    context: RequestContext = Depends(get_request_context)
):
    """
    Initialize cache with historical cost data for better performance.
    This endpoint loads commonly accessed historical data into cache.
    Requires authentication.
    """
    # HIGH-15: validate scope before scheduling anything. A zero-scope caller
    # never reaches add_task, so the background task never runs unscoped.
    account_filter = _build_account_filter(context.allowed_account_ids)
    scope_key = _scope_cache_key(context.allowed_account_ids)

    try:
        logger.info(
            "cache_initialization_requested",
            user_id=str(context.user_id),
            user_email=context.user_email,
            months=cache_request.months
        )
        # Validate months parameter
        if cache_request.months < 1 or cache_request.months > 13:
            raise HTTPException(
                status_code=400,
                detail="Months must be between 1 and 13"
            )

        # Start background task to load data
        background_tasks.add_task(
            _load_historical_data_to_cache,
            cache_request.months,
            account_filter,
            scope_key,
        )

        return {
            "success": True,
            "message": f"Cache initialization started for {cache_request.months} months of historical data",
            "status": "processing",
            "estimated_time": "1-2 minutes"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("cache_initialization_failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An internal error occurred. Please try again later."
        )


@router.get("/data-sources")
async def get_data_sources_info(
    request: Request,
    context: RequestContext = Depends(get_request_context)
):
    """
    Get information about available cost data sources.
    Returns only availability status without exposing infrastructure details.
    Requires authentication.
    """
    # HIGH-15: scope check before the outer try. That try block's broad except
    # returns an error-dict instead of re-raising — a 403 raised inside it
    # would be silently swallowed as {"error": "Unable to retrieve..."}.
    account_filter = _build_account_filter(context.allowed_account_ids)

    try:
        logger.info(
            "data_sources_info_accessed",
            user_id=str(context.user_id),
            user_email=context.user_email
        )

        # Use IAM role credentials via default credential chain
        session = create_aws_session(region_name=COST_EXPLORER_REGION)

        # Check Cost Explorer
        ce_available = False
        try:
            ce_client = session.client(AwsService.COST_EXPLORER, region_name=COST_EXPLORER_REGION)
            ce_client.get_cost_and_usage(
                TimePeriod={
                    'Start': (date.today() - timedelta(days=7)).strftime('%Y-%m-%d'),
                    'End': date.today().strftime('%Y-%m-%d')
                },
                Granularity='DAILY',
                Metrics=['BlendedCost'],
                Filter=account_filter,
            )
            ce_available = True
            logger.info("Cost Explorer check: Available")
        except Exception as ce_error:
            logger.error(f"Cost Explorer check failed: {ce_error}")
            pass

        # Check CUR
        cur_available = False
        try:
            # CUR API only available in us-east-1
            cur_client = session.client(AwsService.COST_AND_USAGE_REPORTS, region_name=COST_EXPLORER_REGION)
            response = cur_client.describe_report_definitions()
            cur_reports = response.get('ReportDefinitions', [])
            cur_available = len(cur_reports) > 0
            logger.info(f"CUR check: Found {len(cur_reports)} report(s)")
        except Exception as cur_error:
            logger.error(f"CUR check failed: {cur_error}")
            pass

        # Return sanitized response - NO infrastructure details exposed
        return {
            "cost_explorer": {
                "available": ce_available,
                "description": "AWS Cost Explorer API - Access to recent cost data"
            },
            "cur": {
                "available": cur_available,
                "description": "Cost and Usage Reports - Detailed historical data"
            },
            "recommendation": (
                "Cost Explorer is available for use. "
                if ce_available else
                "Set up Cost Explorer in AWS Console. "
            ) + (
                "CUR is configured."
                if cur_available else
                "Consider setting up CUR for extended historical analysis."
            )
        }

    except Exception as e:
        logger.error("data_sources_info_failed", error=str(e), exc_info=True)
        return {
            "error": "Unable to retrieve data source information.",
            "cost_explorer": {"available": False},
            "cur": {"available": False}
        }
