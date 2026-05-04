"""
Athena Query API endpoints
Handles Athena SQL query generation, execution, and result export
"""

import re
from typing import Optional
from datetime import timedelta, date

from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
import structlog

from backend.services.athena_query_service import athena_service
from backend.services.chart_recommendation import chart_engine
from backend.services.chart_data_builder import chart_data_builder
from backend.aasmaa.time_range import TimeRangeParser
from backend.config.settings import get_settings
from backend.services.request_context import require_context, RequestContext
from backend.middleware.rate_limiting import check_athena_export_rate_limit

router = APIRouter()
logger = structlog.get_logger(__name__)
settings = get_settings()


async def get_request_context(request: Request) -> RequestContext:
    """Dependency to get request context and enforce authentication"""
    return require_context(request)


class AthenaQueryRequest(BaseModel):
    """Request model for Athena query generation"""
    user_query: str = Field(..., description="Natural language query from user")
    start_date: Optional[str] = Field(None, description="Start date (YYYY-MM-DD)")
    end_date: Optional[str] = Field(None, description="End date (YYYY-MM-DD)")
    services: Optional[list[str]] = Field(None, description="AWS services to filter")
    context: Optional[dict] = Field(None, description="Conversation context for fallback resolution")
    execute_query: bool = Field(default=False, description="Execute query immediately")
    export_format: Optional[str] = Field(None, description="Export format: csv or json")


class AthenaQueryResponse(BaseModel):
    """Response model for Athena query"""
    sql_query: str
    description: str
    query_execution_id: Optional[str] = None
    status: Optional[str] = None
    results: Optional[list[dict]] = None
    charts: Optional[list[dict]] = None
    row_count: Optional[int] = None
    error: Optional[str] = None


def _extract_services_from_text(text: str) -> list[str]:
    """Extract known AWS CUR service codes from free text."""
    if not text:
        return []

    normalized = text.lower()
    service_map = {
        "cloudwatch": "AmazonCloudWatch",
        "ec2": "AmazonEC2",
        "rds": "AmazonRDS",
        "eks": "AmazonEKS",
        "elb": "AWSELB",
        "vpc": "AmazonVPC",
        "s3": "AmazonS3",
        "lambda": "AWSLambda",
        "kinesis": "AmazonKinesis",
        "elasticache": "AmazonElastiCache",
    }

    found = []
    for token, service_name in service_map.items():
        if re.search(rf"\b{re.escape(token)}\b", normalized):
            found.append(service_name)
    return found


def _resolve_fallback_services(request: AthenaQueryRequest) -> Optional[list[str]]:
    """Resolve service filter from explicit request or contextual references like "this"."""
    if request.services:
        return request.services

    direct = _extract_services_from_text(request.user_query)
    if direct:
        return direct

    ctx = request.context or {}
    follow_up_reference = bool(re.search(r"\b(this|that|same)\b", request.user_query.lower()))
    if follow_up_reference:
        top_service = ctx.get("last_assistant_top_service")
        if isinstance(top_service, str) and top_service.strip():
            return [top_service.strip()]

    prior_query = ctx.get("last_query")
    if isinstance(prior_query, str) and prior_query.strip():
        prior_services = _extract_services_from_text(prior_query)
        if prior_services:
            return prior_services

    return None


def _resolve_effective_query(request: AthenaQueryRequest) -> str:
    """Augment follow-up fallback queries with contextual intent hints."""
    user_query = request.user_query or ""
    q_lower = user_query.lower()
    ctx = request.context or {}
    last_query = str(ctx.get("last_query") or "").lower()

    follow_up_reference = bool(re.search(r"\b(this|that|same)\b", q_lower))
    asks_region_breakdown = "region" in q_lower
    prior_was_trend = any(token in last_query for token in ["trend", "over time", "timeline", "time series"])

    time_hint = None
    if last_query:
        hint_match = re.search(
            r"(last\s+\d+\s+(?:days?|weeks?|months?|years?)|this\s+month|last\s+month|this\s+year|last\s+year|ytd|mtd|wtd)",
            last_query,
            re.IGNORECASE,
        )
        if hint_match:
            time_hint = hint_match.group(1)

    # Example: "break this cost down by region" after a trend request should
    # preserve trend semantics and render multi-line trend-by-region.
    if asks_region_breakdown and follow_up_reference and prior_was_trend:
        if time_hint:
            return f"{user_query} as trend over time for {time_hint}"
        return f"{user_query} as trend over time"

    return user_query


def _infer_chart_intent(request_query: str, results: list[dict]) -> str:
    """Infer a chart intent for Athena fallback responses."""
    q = (request_query or "").lower()
    if any(token in q for token in ["compare", "comparison", "vs", "versus", "mom", "yoy", "qoq"]):
        return "comparison"

    if any(token in q for token in ["trend", "over time", "timeline", "time series"]):
        return "cost_trend"

    if not results:
        return "cost_breakdown"

    sample = results[0]
    keys = {str(k).lower() for k in sample.keys()}

    if "current_period_cost" in keys and "previous_period_cost" in keys:
        return "comparison"

    # If date buckets are present, this is likely a trend/time-series response.
    if any(k in keys for k in ["usage_date", "date", "month", "week", "day", "year", "period"]):
        return "cost_trend"

    # Default to breakdown so service/region totals render as bars.
    return "cost_breakdown"


@router.post("/generate", response_model=AthenaQueryResponse)
async def generate_athena_query(
    request: AthenaQueryRequest,
    context: RequestContext = Depends(get_request_context)
):
    """
    Generate Athena SQL query based on user's natural language request.
    Optionally execute the query and return results.

    Requires authentication.
    """

    logger.info(
        "Generating Athena query",
        user_query=request.user_query,
        execute=request.execute_query,
        user_id=str(context.user_id),
        user_email=context.user_email
    )
    
    try:
        effective_query = _resolve_effective_query(request)

        # Parse time range
        if request.start_date and request.end_date:
            start_date = date.fromisoformat(request.start_date)
            end_date = date.fromisoformat(request.end_date)
        else:
            # Parse time from natural language query for fallback requests.
            parsed = TimeRangeParser("UTC").parse(effective_query)
            if parsed.source != "default":
                start_date = parsed.start.date()
                end_date = parsed.end.date()
            else:
                end_date = date.today()
                start_date = end_date - timedelta(days=30)
        
        time_range = {
            "start_date": start_date,
            "end_date": end_date
        }
        
        resolved_services = _resolve_fallback_services(request)

        # Generate SQL query
        sql_query, description = await athena_service.generate_query_for_user_request(
            user_query=effective_query,
            time_range=time_range,
            services=resolved_services
        )
        
        response_data = {
            "sql_query": sql_query,
            "description": description
        }
        
        # Execute query if requested
        if request.execute_query:
            execution_result = await athena_service.execute_query(sql_query)

            if execution_result.get("error"):
                logger.error("athena_inline_execution_error", error=execution_result.get("error"))

            results = execution_result.get("results") or []
            charts = []
            if results:
                chart_intent = _infer_chart_intent(effective_query, results)
                chart_specs = chart_engine.recommend_charts(
                    intent=chart_intent,
                    data_results=results,
                    extracted_params={},
                    query=effective_query,
                )
                charts = chart_data_builder.build_chart_data(
                    chart_specs=chart_specs,
                    data_results=results,
                    conv_context=None,
                )

            response_data.update({
                "query_execution_id": execution_result.get("query_execution_id"),
                "status": execution_result.get("status"),
                "results": results,
                "charts": charts,
                "row_count": execution_result.get("row_count"),
                "error": "Query execution failed." if execution_result.get("error") else None
            })
        
        return AthenaQueryResponse(**response_data)
        
    except Exception as e:
        logger.error("athena_query_generation_failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An internal error occurred. Please try again later."
        )


@router.get("/execute/{query_execution_id}")
async def get_query_results(
    query_execution_id: str,
    context: RequestContext = Depends(get_request_context)
):
    """
    Get results from a previously executed Athena query.

    Requires authentication.
    """

    logger.info(
        "Fetching query results",
        query_execution_id=query_execution_id,
        user_id=str(context.user_id),
        user_email=context.user_email
    )

    try:
        results = await athena_service._get_query_results(query_execution_id)
        
        return {
            "query_execution_id": query_execution_id,
            "results": results,
            "row_count": len(results)
        }
        
    except Exception as e:
        logger.error("athena_query_results_failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An internal error occurred. Please try again later."
        )


@router.post("/export/csv")
async def export_results_csv(
    request: AthenaQueryRequest,
    context: RequestContext = Depends(get_request_context),
    rate_limit_info: dict = Depends(check_athena_export_rate_limit)
):
    """
    Execute query and export results as CSV file.

    Requires authentication.
    Rate limited per organization based on subscription tier:
    - Free: 10 exports/hour
    - Standard: 50 exports/hour
    - Enterprise: 200 exports/hour
    """

    logger.info(
        "Exporting query results to CSV",
        user_query=request.user_query,
        user_id=str(context.user_id),
        user_email=context.user_email
    )

    try:
        # Parse time range
        if request.start_date and request.end_date:
            start_date = date.fromisoformat(request.start_date)
            end_date = date.fromisoformat(request.end_date)
        else:
            end_date = date.today()
            start_date = end_date - timedelta(days=30)
        
        time_range = {
            "start_date": start_date,
            "end_date": end_date
        }
        
        # Generate and execute query
        sql_query, description = await athena_service.generate_query_for_user_request(
            user_query=request.user_query,
            time_range=time_range,
            services=request.services
        )
        
        execution_result = await athena_service.execute_query(sql_query)
        
        if execution_result.get("status") != "success":
            logger.error("athena_query_execution_failed", error=execution_result.get('error', 'Unknown error'))
            raise HTTPException(
                status_code=500,
                detail="An internal error occurred. Please try again later."
            )

        results = execution_result.get("results", [])

        # Export to CSV
        csv_content, filename = await athena_service.export_results_to_csv(results)
        
        # Return as downloadable file
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("athena_csv_export_failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An internal error occurred. Please try again later."
        )


@router.post("/export/json")
async def export_results_json(
    request: AthenaQueryRequest,
    context: RequestContext = Depends(get_request_context),
    rate_limit_info: dict = Depends(check_athena_export_rate_limit)
):
    """
    Execute query and export results as JSON file.

    Requires authentication.
    Rate limited per organization based on subscription tier:
    - Free: 10 exports/hour
    - Standard: 50 exports/hour
    - Enterprise: 200 exports/hour
    """

    logger.info(
        "Exporting query results to JSON",
        user_query=request.user_query,
        user_id=str(context.user_id),
        user_email=context.user_email
    )

    try:
        # Parse time range
        if request.start_date and request.end_date:
            start_date = date.fromisoformat(request.start_date)
            end_date = date.fromisoformat(request.end_date)
        else:
            end_date = date.today()
            start_date = end_date - timedelta(days=30)
        
        time_range = {
            "start_date": start_date,
            "end_date": end_date
        }
        
        # Generate and execute query
        sql_query, description = await athena_service.generate_query_for_user_request(
            user_query=request.user_query,
            time_range=time_range,
            services=request.services
        )
        
        execution_result = await athena_service.execute_query(sql_query)
        
        if execution_result.get("status") != "success":
            logger.error("athena_query_execution_failed", error=execution_result.get('error', 'Unknown error'))
            raise HTTPException(
                status_code=500,
                detail="An internal error occurred. Please try again later."
            )

        results = execution_result.get("results", [])

        # Export to JSON
        json_content, filename = await athena_service.export_results_to_json(results)
        
        # Return as downloadable file
        return Response(
            content=json_content,
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("athena_json_export_failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An internal error occurred. Please try again later."
        )


@router.get("/sample-queries")
async def get_sample_queries():
    """Get sample Athena queries that users can try"""
    
    return {
        "samples": [
            {
                "title": "Top 10 Most Expensive Services",
                "query": "Show me my top 10 most expensive AWS services",
                "description": "Returns the top 10 services by total cost"
            },
            {
                "title": "Daily Cost Breakdown",
                "query": "Show me daily costs for EC2 and S3",
                "description": "Returns daily cost breakdown for specified services"
            },
            {
                "title": "Cost by Region",
                "query": "Show me costs broken down by AWS region",
                "description": "Returns cost distribution across AWS regions"
            },
            {
                "title": "Cost by Account",
                "query": "Show me costs by AWS account",
                "description": "Returns cost breakdown across different AWS accounts"
            },
            {
                "title": "Service Cost Details",
                "query": "Show me detailed breakdown of S3 costs",
                "description": "Returns detailed usage and cost information for a specific service"
            }
        ]
    }
