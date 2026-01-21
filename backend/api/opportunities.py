"""
Opportunities API Endpoints

Provides REST API for managing optimization opportunities:
- List/search opportunities with filtering and pagination
- Get opportunity details with evidence
- Update opportunity status
- Export opportunities
- Ingest signals from AWS
"""

from typing import Optional, List
from uuid import UUID
from datetime import datetime
import csv
import io

from fastapi import APIRouter, HTTPException, Depends, Query, BackgroundTasks, Response, Request, status
from fastapi.responses import StreamingResponse
import structlog

from backend.models.opportunities import (
    OpportunityStatus,
    OpportunitySource,
    OpportunityCategory,
    EffortLevel,
    RiskLevel,
    OpportunityCreate,
    OpportunityUpdate,
    OpportunityStatusUpdate,
    OpportunityFilter,
    OpportunitySort,
    OpportunityListRequest,
    OpportunityListResponse,
    OpportunityDetail,
    OpportunitiesStats,
    OpportunityIngestResult,
    OpportunityExportRequest,
    BulkStatusUpdateRequest,
    BulkStatusUpdateResponse,
)
from backend.services.opportunities_service import (
    OpportunitiesService,
    get_opportunities_service,
)
from backend.services.aws_optimization_signals import (
    AWSOptimizationSignalsService,
    get_optimization_signals_service,
)
from backend.services.request_context import get_context_from_request
from backend.middleware.rate_limiting import check_ingest_rate_limit
from backend.utils.errors import (
    raise_not_found,
    raise_internal_error,
    raise_validation_error,
    raise_aws_error,
    handle_opportunity_error,
    create_error_response,
    ErrorCode,
)
from backend.utils.pii_masking import mask_email, hash_identifier

router = APIRouter(prefix="/opportunities", tags=["opportunities"])
logger = structlog.get_logger(__name__)


def get_service(request: Request) -> OpportunitiesService:
    """Get opportunities service with organization scoping from request context"""
    context = get_context_from_request(request)
    org_id = context.organization_id if context else None
    return get_opportunities_service(org_id)


@router.get("", response_model=OpportunityListResponse)
async def list_opportunities(
    request: Request,
    # Pagination
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    # Sorting
    sort: OpportunitySort = Query(OpportunitySort.SAVINGS_DESC, description="Sort order"),
    # Filters
    account_id: Optional[List[str]] = Query(None, description="Filter by account IDs"),
    status: Optional[List[OpportunityStatus]] = Query(None, description="Filter by status"),
    category: Optional[List[OpportunityCategory]] = Query(None, description="Filter by category"),
    source: Optional[List[OpportunitySource]] = Query(None, description="Filter by source"),
    service: Optional[List[str]] = Query(None, description="Filter by AWS service"),
    region: Optional[List[str]] = Query(None, description="Filter by region"),
    min_savings: Optional[float] = Query(None, ge=0, description="Minimum monthly savings"),
    max_savings: Optional[float] = Query(None, ge=0, description="Maximum monthly savings"),
    effort_level: Optional[List[EffortLevel]] = Query(None, description="Filter by effort level"),
    risk_level: Optional[List[RiskLevel]] = Query(None, description="Filter by risk level"),
    tag: Optional[List[str]] = Query(None, description="Filter by tags"),
    search: Optional[str] = Query(None, max_length=500, description="Full-text search"),
    first_detected_after: Optional[datetime] = Query(None, description="Filter by detection date"),
    first_detected_before: Optional[datetime] = Query(None, description="Filter by detection date"),
):
    """
    List optimization opportunities with filtering, sorting, and pagination.

    Returns a paginated list with aggregations for filtering UI.
    """
    try:
        svc = get_service(request)

        # Build filter from query params
        filter_obj = OpportunityFilter(
            account_ids=account_id,
            statuses=status,
            categories=category,
            sources=source,
            services=service,
            regions=region,
            min_savings=min_savings,
            max_savings=max_savings,
            effort_levels=effort_level,
            risk_levels=risk_level,
            tags=tag,
            search=search,
            first_detected_after=first_detected_after,
            first_detected_before=first_detected_before,
        )

        result = svc.list_opportunities(
            filter=filter_obj,
            sort=sort,
            page=page,
            page_size=page_size,
            include_aggregations=True
        )

        logger.info(
            "Listed opportunities",
            total=result.total,
            page=page,
            has_filters=any([
                account_id, status, category, source, service, region,
                min_savings, max_savings, effort_level, risk_level, tag, search
            ])
        )

        return result

    except Exception as e:
        raise_internal_error(
            "Error listing opportunities",
            exception=e,
            user_message="Unable to retrieve optimization opportunities. Please try again later.",
        )


@router.post("/search", response_model=OpportunityListResponse)
async def search_opportunities(
    request: Request,
    body: OpportunityListRequest,
):
    """
    Search opportunities with complex filter criteria.

    Accepts filter object in request body for complex queries.
    """
    try:
        svc = get_service(request)

        result = svc.list_opportunities(
            filter=body.filter,
            sort=body.sort,
            page=body.page,
            page_size=body.page_size,
            include_aggregations=True
        )

        return result

    except Exception as e:
        raise_internal_error(
            "Error searching opportunities",
            exception=e,
            user_message="Unable to search optimization opportunities. Please try again later.",
        )


@router.get("/stats", response_model=OpportunitiesStats)
async def get_stats(request: Request):
    """
    Get statistics summary for opportunities dashboard.

    Returns counts, savings totals, and top opportunities.
    """
    try:
        svc = get_service(request)
        stats = svc.get_stats()

        logger.info(
            "Retrieved opportunity stats",
            total=stats.total_opportunities,
            open=stats.open_opportunities,
            potential_savings=stats.total_potential_monthly_savings
        )

        return stats

    except Exception as e:
        raise_internal_error(
            "Error getting opportunity stats",
            exception=e,
            user_message="Unable to retrieve opportunity statistics. Please try again later.",
        )


@router.get("/{opportunity_id}", response_model=OpportunityDetail)
async def get_opportunity(
    request: Request,
    opportunity_id: UUID,
):
    """
    Get full details of a single opportunity including evidence.
    """
    try:
        svc = get_service(request)
        opportunity = svc.get_opportunity(opportunity_id)

        if not opportunity:
            raise_not_found("optimization opportunity", str(opportunity_id))

        logger.info(f"Retrieved opportunity: {opportunity_id}")
        return opportunity

    except HTTPException:
        raise
    except Exception as e:
        handle_opportunity_error("retrieving", str(opportunity_id), e)


@router.post("", response_model=OpportunityDetail, status_code=201)
async def create_opportunity(
    request: Request,
    body: OpportunityCreate,
):
    """
    Create a manual opportunity.

    For creating opportunities not detected automatically by AWS signals.
    """
    try:
        svc = get_service(request)

        # Get user from context
        context = get_context_from_request(request)
        user_email = context.user_email if context else None

        data = body.model_dump(exclude_none=True)
        data['source'] = OpportunitySource.MANUAL.value
        data['status'] = OpportunityStatus.OPEN.value

        if body.implementation_steps:
            data['implementation_steps'] = [s.model_dump() for s in body.implementation_steps]

        # Calculate annual savings
        if body.estimated_monthly_savings:
            data['estimated_annual_savings'] = body.estimated_monthly_savings * 12

        opportunity = svc.create_opportunity(data)

        logger.info(
            "Created manual opportunity",
            id=str(opportunity.id),
            title=opportunity.title,
            created_by=hash_identifier(user_email, "user")
        )

        return opportunity

    except Exception as e:
        handle_opportunity_error("creating", None, e)


@router.patch("/{opportunity_id}", response_model=OpportunityDetail)
async def update_opportunity(
    request: Request,
    opportunity_id: UUID,
    body: OpportunityUpdate,
):
    """
    Update an opportunity's details.
    """
    try:
        svc = get_service(request)

        data = body.model_dump(exclude_none=True)

        if body.implementation_steps:
            data['implementation_steps'] = [s.model_dump() for s in body.implementation_steps]

        opportunity = svc.update_opportunity(opportunity_id, data)

        if not opportunity:
            raise_not_found("optimization opportunity", str(opportunity_id))

        logger.info(f"Updated opportunity: {opportunity_id}")
        return opportunity

    except HTTPException:
        raise
    except Exception as e:
        handle_opportunity_error("updating", str(opportunity_id), e)


@router.patch("/{opportunity_id}/status", response_model=OpportunityDetail)
async def update_opportunity_status(
    request: Request,
    opportunity_id: UUID,
    body: OpportunityStatusUpdate,
):
    """
    Update an opportunity's status.

    Common status transitions:
    - open -> accepted (user accepts recommendation)
    - open -> dismissed (user dismisses recommendation)
    - accepted -> in_progress (implementation started)
    - in_progress -> implemented (implementation complete)
    """
    try:
        svc = get_service(request)

        # Get user from context
        context = get_context_from_request(request)
        user_email = context.user_email if context else None

        opportunity = svc.update_status(
            opportunity_id,
            body.status,
            body.reason,
            user_email
        )

        if not opportunity:
            raise_not_found("optimization opportunity", str(opportunity_id))

        logger.info(
            "Updated opportunity status",
            id=str(opportunity_id),
            new_status=body.status.value,
            reason=body.reason,
            changed_by=hash_identifier(user_email, "user")
        )

        return opportunity

    except HTTPException:
        raise
    except Exception as e:
        handle_opportunity_error("updating status of", str(opportunity_id), e)


@router.post("/bulk-status", response_model=BulkStatusUpdateResponse)
async def bulk_update_status(
    request: Request,
    body: BulkStatusUpdateRequest,
):
    """
    Update status for multiple opportunities at once.
    """
    try:
        svc = get_service(request)

        # Get user from context
        context = get_context_from_request(request)
        user_email = context.user_email if context else None

        updated, failed, errors = svc.bulk_update_status(
            body.opportunity_ids,
            body.status,
            body.reason,
            user_email
        )

        logger.info(
            "Bulk status update",
            requested=len(body.opportunity_ids),
            updated=updated,
            failed=failed,
            status=body.status.value
        )

        # Return user-friendly error messages
        user_friendly_errors = None
        if errors:
            user_friendly_errors = [
                f"Opportunity {err.split(':')[0].strip()}: Unable to update status"
                if ':' in err else "Unable to update some opportunities"
                for err in errors
            ]

        return BulkStatusUpdateResponse(
            updated=updated,
            failed=failed,
            errors=user_friendly_errors
        )

    except Exception as e:
        raise_internal_error(
            "Error in bulk status update",
            exception=e,
            user_message="Unable to update opportunity statuses. Some updates may have succeeded.",
        )


@router.delete("/{opportunity_id}", status_code=204)
async def delete_opportunity(
    request: Request,
    opportunity_id: UUID,
):
    """
    Delete an opportunity.

    Typically used for manually created opportunities.
    """
    try:
        svc = get_service(request)

        deleted = svc.delete_opportunity(opportunity_id)

        if not deleted:
            raise_not_found("optimization opportunity", str(opportunity_id))

        logger.info(f"Deleted opportunity: {opportunity_id}")
        return Response(status_code=204)

    except HTTPException:
        raise
    except Exception as e:
        handle_opportunity_error("deleting", str(opportunity_id), e)


@router.post("/ingest", response_model=OpportunityIngestResult)
async def ingest_signals(
    request: Request,
    background_tasks: BackgroundTasks,
    source: Optional[OpportunitySource] = Query(
        None,
        description="Specific source to ingest from (all sources if not specified)"
    ),
    rate_limit_info: dict = Depends(check_ingest_rate_limit),
):
    """
    Trigger ingestion of optimization signals from AWS APIs.

    This endpoint fetches recommendations from:
    - Cost Explorer (rightsizing recommendations)
    - Trusted Advisor (cost optimization checks)
    - Compute Optimizer (EC2 and Lambda recommendations)

    The ingestion runs in the background and returns immediately with a result summary.

    Rate Limited: 5 requests per hour per user/IP.
    """
    try:
        context = get_context_from_request(request)
        org_id = context.organization_id if context else None

        # Get AWS account info from context if available
        # For now, use settings default
        signals_svc = get_optimization_signals_service(
            organization_id=org_id
        )

        # Fetch signals based on source filter
        signals = []

        # Track ingestion errors for user feedback
        ingestion_errors = []

        if source is None or source == OpportunitySource.COST_EXPLORER:
            try:
                ce_signals = await signals_svc.fetch_cost_explorer_recommendations()
                signals.extend(ce_signals)
            except Exception as e:
                logger.warning(f"Failed to fetch Cost Explorer signals: {e}")
                ingestion_errors.append("Cost Explorer: Unable to fetch rightsizing recommendations")

        if source is None or source == OpportunitySource.TRUSTED_ADVISOR:
            try:
                ta_signals = await signals_svc.fetch_trusted_advisor_recommendations()
                signals.extend(ta_signals)
            except Exception as e:
                logger.warning(f"Failed to fetch Trusted Advisor signals: {e}")
                ingestion_errors.append("Trusted Advisor: Unable to fetch cost optimization checks")

        if source is None or source == OpportunitySource.COMPUTE_OPTIMIZER:
            try:
                co_signals = await signals_svc.fetch_compute_optimizer_recommendations()
                signals.extend(co_signals)
            except Exception as e:
                logger.warning(f"Failed to fetch Compute Optimizer signals: {e}")
                ingestion_errors.append("Compute Optimizer: Unable to fetch recommendations")

        # Deduplicate
        signals = signals_svc.deduplicate_opportunities(signals)

        # Ingest into database
        opp_svc = get_service(request)
        result = opp_svc.ingest_signals(signals)

        # Add any errors to result message
        if ingestion_errors:
            result.errors = ingestion_errors

        logger.info(
            "Ingested optimization signals",
            total=result.total_signals,
            new=result.new_opportunities,
            updated=result.updated_opportunities,
            errors=len(ingestion_errors)
        )

        return result

    except Exception as e:
        raise_internal_error(
            "Error ingesting optimization signals",
            exception=e,
            user_message="Unable to fetch optimization recommendations from AWS. Please check your AWS permissions and try again.",
        )


@router.post("/export")
async def export_opportunities(
    request: Request,
    body: OpportunityExportRequest,
):
    """
    Export opportunities to CSV, JSON, or Excel format.
    """
    try:
        svc = get_service(request)

        data = svc.export_opportunities(
            filter=body.filter,
            include_evidence=body.include_evidence,
            include_steps=body.include_steps
        )

        if body.format == "json":
            return data

        elif body.format == "csv":
            if not data:
                return Response(
                    content="No data",
                    media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=opportunities.csv"}
                )

            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=data[0].keys())
            writer.writeheader()

            for row in data:
                # Flatten complex fields
                flat_row = {}
                for k, v in row.items():
                    if isinstance(v, (dict, list)):
                        flat_row[k] = str(v)
                    elif isinstance(v, datetime):
                        flat_row[k] = v.isoformat()
                    else:
                        flat_row[k] = v
                writer.writerow(flat_row)

            output.seek(0)

            return StreamingResponse(
                iter([output.getvalue()]),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=opportunities.csv"}
            )

        elif body.format == "excel":
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail=create_error_response(
                    ErrorCode.EXPORT_FORMAT_NOT_SUPPORTED,
                    "Excel export is not yet available. Please use CSV or JSON format.",
                ),
            )

        else:
            raise_validation_error(
                f"Export format '{body.format}' is not supported. Use 'csv' or 'json'.",
                field="format",
            )

    except HTTPException:
        raise
    except Exception as e:
        raise_internal_error(
            "Error exporting opportunities",
            exception=e,
            user_message="Unable to export opportunities. Please try again later.",
        )


@router.get("/top", response_model=List[OpportunityDetail])
async def get_top_opportunities(
    request: Request,
    limit: int = Query(10, ge=1, le=50, description="Number of top opportunities"),
):
    """
    Get top opportunities by potential savings.

    Quick endpoint for dashboard widgets.
    """
    try:
        svc = get_service(request)

        filter_obj = OpportunityFilter(
            statuses=[OpportunityStatus.OPEN]
        )

        result = svc.list_opportunities(
            filter=filter_obj,
            sort=OpportunitySort.SAVINGS_DESC,
            page=1,
            page_size=limit,
            include_aggregations=False
        )

        # Fetch full details for each
        opportunities = []
        for summary in result.items:
            detail = svc.get_opportunity(summary.id)
            if detail:
                opportunities.append(detail)

        return opportunities

    except Exception as e:
        raise_internal_error(
            "Error getting top opportunities",
            exception=e,
            user_message="Unable to retrieve top optimization opportunities. Please try again later.",
        )
