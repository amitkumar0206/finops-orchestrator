"""
Reports API endpoints

Currently mock implementations. Authentication and tenant scoping are enforced
at the endpoint layer so that when real report generation lands, the security
contract is already in place (CRIT-11 remediation, 2026-03-05).
"""

from fastapi import APIRouter, Depends, Request
from datetime import datetime
import structlog

from backend.services.request_context import require_context, RequestContext

router = APIRouter()
logger = structlog.get_logger(__name__)


async def get_request_context(request: Request) -> RequestContext:
    """FastAPI dependency — enforces authentication. Raises 401 if no auth."""
    return require_context(request)


@router.get("/")
async def get_reports(
    context: RequestContext = Depends(get_request_context),
):
    """
    Get available reports for the caller's organization.

    Requires authentication. Results are scoped to the caller's
    organization_id — no cross-tenant report listing.
    """
    logger.info(
        "reports_listed",
        user_id=str(context.user_id),
        organization_id=str(context.organization_id) if context.organization_id else None,
    )
    return {
        "reports": [],
        "organization_id": str(context.organization_id) if context.organization_id else None,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.post("/generate")
async def generate_report(
    context: RequestContext = Depends(get_request_context),
):
    """
    Generate a new report scoped to the caller's organization and allowed accounts.

    Requires authentication. Report generation is bound to the caller's
    tenant scope (organization_id + allowed_account_ids) — any future
    implementation MUST filter underlying queries by these values.
    """
    logger.info(
        "report_generation_requested",
        user_id=str(context.user_id),
        organization_id=str(context.organization_id) if context.organization_id else None,
        account_count=len(context.allowed_account_ids),
    )
    return {
        "report_id": "mock-123",
        "status": "generated",
        "organization_id": str(context.organization_id) if context.organization_id else None,
        "account_ids": context.allowed_account_ids,
    }
