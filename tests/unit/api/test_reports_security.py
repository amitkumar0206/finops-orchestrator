"""
Security tests for Reports API — CRIT-11 vulnerability fix (2026-03-05)

The reports endpoints were previously unauthenticated mock stubs with zero
tenant isolation. These tests enforce the security contract so that when
real report generation lands, the guardrails are already locked in:

1. GET /reports requires authentication (Depends(get_request_context))
2. POST /reports/generate requires authentication
3. Responses include tenant scope (organization_id) — contract for future impl
4. Audit events logged with user_id + organization_id (no user_email — MED-28)
5. Regression tripwires: endpoints must not regress to anonymous access
"""

import inspect
import pytest
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi import HTTPException

from backend.api.reports import (
    get_reports,
    generate_report,
    get_request_context,
)
from backend.services.request_context import RequestContext


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def tenant_context():
    """Authenticated user with full tenant scope (org + AWS accounts)."""
    return RequestContext(
        user_id=uuid4(),
        user_email="finops@tenant.example",
        organization_id=uuid4(),
        is_admin=False,
        org_role="member",
        allowed_account_ids=["111122223333", "444455556666"],
    )


@pytest.fixture
def tenant_context_no_org():
    """Authenticated user without an organization (edge case)."""
    return RequestContext(
        user_id=uuid4(),
        user_email="solo@example.com",
        organization_id=None,
        is_admin=False,
        allowed_account_ids=[],
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /reports — Authentication enforcement
# ─────────────────────────────────────────────────────────────────────────────

class TestGetReportsAuthentication:
    """CRIT-11: GET /reports must require authentication."""

    def test_signature_requires_context_dependency(self):
        """
        get_reports must declare `context` bound to Depends(get_request_context).
        Regression guard — the vulnerable version had no parameters at all.
        """
        sig = inspect.signature(get_reports)
        assert "context" in sig.parameters, (
            "get_reports must declare a `context` parameter — CRIT-11 regression"
        )
        default = sig.parameters["context"].default
        assert default is not inspect.Parameter.empty, (
            "`context` must be bound to Depends(get_request_context)"
        )
        assert getattr(default, "dependency", None) is get_request_context, (
            "`context` must use Depends(get_request_context) — enforces 401 on unauth"
        )

    @pytest.mark.asyncio
    async def test_get_request_context_raises_401_without_auth(self):
        """The dependency raises 401 when no context is attached to the request."""
        mock_request = Mock()
        mock_request.state = Mock(spec=[])  # no .context attribute

        with pytest.raises(HTTPException) as exc:
            await get_request_context(mock_request)
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_allows_authenticated_access(self, tenant_context):
        """Authenticated users get a response."""
        result = await get_reports(tenant_context)
        assert "reports" in result
        assert "timestamp" in result
        assert result["reports"] == []  # mock impl — contract only


# ─────────────────────────────────────────────────────────────────────────────
# GET /reports — Tenant isolation contract
# ─────────────────────────────────────────────────────────────────────────────

class TestGetReportsTenantIsolation:
    """
    CRIT-11: response must carry the caller's organization_id.

    Even though the current impl is a mock, the response shape establishes
    the tenant-scoping contract for when real data lands. A future
    implementation that removes organization_id from the response will
    break this test — by design.
    """

    @pytest.mark.asyncio
    async def test_response_includes_organization_id(self, tenant_context):
        result = await get_reports(tenant_context)
        assert result["organization_id"] == str(tenant_context.organization_id)

    @pytest.mark.asyncio
    async def test_response_handles_no_org_gracefully(self, tenant_context_no_org):
        """Users without an org get organization_id=None, not a crash."""
        result = await get_reports(tenant_context_no_org)
        assert result["organization_id"] is None

    @pytest.mark.asyncio
    async def test_audit_log_includes_tenant_context(self, tenant_context):
        with patch("backend.api.reports.logger") as mock_logger:
            await get_reports(tenant_context)

        mock_logger.info.assert_called_once()
        evt_name = mock_logger.info.call_args[0][0]
        evt_kwargs = mock_logger.info.call_args[1]
        assert evt_name == "reports_listed"
        assert evt_kwargs["user_id"] == str(tenant_context.user_id)
        assert evt_kwargs["organization_id"] == str(tenant_context.organization_id)
        # MED-28: no user_email in audit logs
        assert "user_email" not in evt_kwargs


# ─────────────────────────────────────────────────────────────────────────────
# POST /reports/generate — Authentication enforcement
# ─────────────────────────────────────────────────────────────────────────────

class TestGenerateReportAuthentication:
    """CRIT-11: POST /reports/generate must require authentication."""

    def test_signature_requires_context_dependency(self):
        sig = inspect.signature(generate_report)
        assert "context" in sig.parameters, (
            "generate_report must declare a `context` parameter — CRIT-11 regression"
        )
        default = sig.parameters["context"].default
        assert getattr(default, "dependency", None) is get_request_context, (
            "`context` must use Depends(get_request_context) — enforces 401 on unauth"
        )

    @pytest.mark.asyncio
    async def test_allows_authenticated_access(self, tenant_context):
        result = await generate_report(tenant_context)
        assert "report_id" in result
        assert result["status"] == "generated"


# ─────────────────────────────────────────────────────────────────────────────
# POST /reports/generate — Tenant isolation contract
# ─────────────────────────────────────────────────────────────────────────────

class TestGenerateReportTenantIsolation:
    """
    CRIT-11: generated reports must carry the full tenant scope.

    When real generation lands, the implementation MUST filter all underlying
    queries by organization_id + allowed_account_ids. This test enforces
    that both values are present in the response contract.
    """

    @pytest.mark.asyncio
    async def test_response_includes_organization_id(self, tenant_context):
        result = await generate_report(tenant_context)
        assert result["organization_id"] == str(tenant_context.organization_id)

    @pytest.mark.asyncio
    async def test_response_includes_account_ids(self, tenant_context):
        """
        The caller's allowed_account_ids must appear in the response.
        This is the contract that any future impl must filter CUR data by.
        """
        result = await generate_report(tenant_context)
        assert result["account_ids"] == tenant_context.allowed_account_ids
        assert result["account_ids"] == ["111122223333", "444455556666"]

    @pytest.mark.asyncio
    async def test_response_empty_accounts_preserved(self, tenant_context_no_org):
        """
        Empty account_ids means "no accounts accessible" — the response
        must carry [] (not None, not omitted).
        """
        result = await generate_report(tenant_context_no_org)
        assert result["account_ids"] == []

    @pytest.mark.asyncio
    async def test_audit_log_includes_tenant_context(self, tenant_context):
        with patch("backend.api.reports.logger") as mock_logger:
            await generate_report(tenant_context)

        mock_logger.info.assert_called_once()
        evt_name = mock_logger.info.call_args[0][0]
        evt_kwargs = mock_logger.info.call_args[1]
        assert evt_name == "report_generation_requested"
        assert evt_kwargs["user_id"] == str(tenant_context.user_id)
        assert evt_kwargs["organization_id"] == str(tenant_context.organization_id)
        assert evt_kwargs["account_count"] == 2
        # MED-28: no user_email in audit logs
        assert "user_email" not in evt_kwargs


# ─────────────────────────────────────────────────────────────────────────────
# Module-level regression tripwires
# ─────────────────────────────────────────────────────────────────────────────

class TestReportsModuleUsesFailClosedAuth:
    """
    The reports module must import require_context (fail-closed 401) and NOT
    the Optional-returning get_context_from_request variant.
    """

    def test_module_imports_require_context(self):
        import backend.api.reports as reports_module
        assert hasattr(reports_module, "require_context"), (
            "reports.py must import require_context (the fail-closed 401 variant)"
        )

    def test_module_does_not_import_get_context_from_request(self):
        import backend.api.reports as reports_module
        assert not hasattr(reports_module, "get_context_from_request"), (
            "reports.py must not import get_context_from_request — it returns None "
            "on missing auth instead of raising 401 (CRIT-11 regression vector)"
        )

    def test_all_routes_have_context_dependency(self):
        """
        Every route handler registered on the reports router must take a
        `context` parameter. Adding a new endpoint without auth will break
        this test — by design.
        """
        import backend.api.reports as reports_module

        for route in reports_module.router.routes:
            handler = route.endpoint
            sig = inspect.signature(handler)
            assert "context" in sig.parameters, (
                f"Route {route.path} handler {handler.__name__} has no `context` "
                f"parameter — every reports endpoint must enforce auth (CRIT-11)"
            )
            default = sig.parameters["context"].default
            assert getattr(default, "dependency", None) is get_request_context, (
                f"Route {route.path} handler {handler.__name__} `context` is not "
                f"bound to Depends(get_request_context)"
            )
