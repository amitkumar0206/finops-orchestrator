"""Analytics API endpoints"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from datetime import datetime, timedelta, date
from typing import Optional
from pydantic import BaseModel
from botocore.exceptions import ClientError
import structlog

from backend.config.settings import get_settings
from backend.utils.aws_session import create_aws_session, create_aws_client
from backend.utils.aws_constants import AwsService, COST_EXPLORER_REGION

router = APIRouter()
settings = get_settings()
logger = structlog.get_logger(__name__)


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
async def get_analytics():
    """Get analytics data"""
    return {"analytics": {}, "timestamp": datetime.utcnow().isoformat()}


@router.get("/historical-availability")
async def check_historical_data_availability():
    """
    Check how many months of historical cost data are available
    via Cost Explorer API
    """
    try:
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
            Metrics=['BlendedCost']
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
        logger.error(f"AWS Cost Explorer error: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"Cannot access Cost Explorer API: {str(e)}. Ensure Cost Explorer is enabled in your AWS account."
        )
    except Exception as e:
        logger.error(f"Error checking historical data: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to check historical data availability: {str(e)}"
        )


async def _load_historical_data_to_cache(months: int):
    """
    Background task to load historical data into cache/database
    This preloads commonly accessed data for better performance
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
            GroupBy=[{'Type': 'DIMENSION', 'Key': 'SERVICE'}]
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
            GroupBy=[{'Type': 'DIMENSION', 'Key': 'SERVICE'}]
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
                f"analytics:monthly:{start_date}:{end_date}",
                str(monthly_data)
            )
            valkey_client.set(
                f"analytics:daily:{recent_start}:{end_date}",
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
    request: CacheInitRequest,
    background_tasks: BackgroundTasks
):
    """
    Initialize cache with historical cost data for better performance.
    This endpoint loads commonly accessed historical data into cache.
    """
    try:
        # Validate months parameter
        if request.months < 1 or request.months > 13:
            raise HTTPException(
                status_code=400,
                detail="Months must be between 1 and 13"
            )
        
        # Start background task to load data
        background_tasks.add_task(_load_historical_data_to_cache, request.months)
        
        return {
            "success": True,
            "message": f"Cache initialization started for {request.months} months of historical data",
            "status": "processing",
            "estimated_time": "1-2 minutes"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error initializing cache: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to initialize cache: {str(e)}"
        )


@router.get("/data-sources")
async def get_data_sources_info():
    """
    Get information about available cost data sources and their capabilities
    """
    try:
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
                Metrics=['BlendedCost']
            )
            ce_available = True
            logger.info("Cost Explorer check: Available")
        except Exception as ce_error:
            logger.error(f"Cost Explorer check failed: {ce_error}")
            pass

        # Check CUR
        cur_available = False
        cur_reports = []
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
        
        return {
            "cost_explorer": {
                "available": ce_available,
                "historical_months": 13,
                "granularity": ["HOURLY", "DAILY", "MONTHLY"],
                "description": "AWS Cost Explorer API - Immediate access to recent cost data"
            },
            "cur": {
                "available": cur_available,
                "report_count": len(cur_reports),
                "reports": [
                    {
                        "name": r.get('ReportName'),
                        "bucket": r.get('S3Bucket'),
                        "format": r.get('Format')
                    }
                    for r in cur_reports
                ],
                "description": "Cost and Usage Reports - Detailed historical data for long-term analysis"
            },
            "recommendation": (
                "Cost Explorer is available for immediate use. "
                if ce_available else
                "Set up Cost Explorer in AWS Console. "
            ) + (
                f"CUR configured with {len(cur_reports)} report(s)."
                if cur_available else
                "Consider setting up CUR for extended historical analysis."
            )
        }
        
    except Exception as e:
        logger.error(f"Error getting data sources info: {e}")
        return {
            "error": str(e),
            "cost_explorer": {"available": False},
            "cur": {"available": False}
        }
