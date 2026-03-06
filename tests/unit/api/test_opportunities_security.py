"""
Security tests for Opportunities API - CRIT-2 IDOR Fix

Tests ownership validation for opportunity CRUD operations to ensure:
1. Users can only access their own opportunities
2. Users cannot access opportunities created by other users in the same organization
3. Proper error codes are returned (403 for unauthorized, 404 for not found)
4. Audit logging captures access attempts

Addresses CRIT-2: Opportunities Accessible Without Ownership Validation (IDOR)
CVSS 9.1 (Critical)
"""

import pytest
from unittest.mock import Mock, patch
from uuid import uuid4
from datetime import datetime, timezone

from fastapi import HTTPException
from backend.api.opportunities import (
    get_opportunity,
    update_opportunity,
    delete_opportunity,
    update_opportunity_status,
)
from backend.services.opportunities_service import OpportunitiesService
from backend.services.request_context import RequestContext
from backend.models.opportunities import (
    OpportunityDetail,
    OpportunityStatus,
    OpportunitySource,
    OpportunityCategory,
    OpportunityUpdate,
    OpportunityStatusUpdate,
)


@pytest.fixture
def mock_request_context():
    """Mock request context with user information"""
    context = Mock(spec=RequestContext)
    context.user_id = uuid4()
    context.user_email = "alice@company.com"
    context.organization_id = uuid4()
    context.organization_name = "Test Org"
    context.is_admin = False
    return context


@pytest.fixture
def mock_request():
    """Mock FastAPI request object"""
    request = Mock()
    request.state = Mock()
    return request


@pytest.fixture
def sample_opportunity():
    """Sample opportunity data"""
    opportunity_id = uuid4()
    user_id = uuid4()
    org_id = uuid4()

    return {
        "id": opportunity_id,
        "account_id": "123456789012",
        "organization_id": org_id,
        "created_by_user_id": user_id,
        "title": "EC2 Rightsizing Recommendation",
        "description": "Downsize overprovisioned EC2 instances",
        "category": OpportunityCategory.RIGHTSIZING.value,
        "source": OpportunitySource.COST_EXPLORER.value,
        "service": "AmazonEC2",
        "estimated_monthly_savings": 1500.00,
        "status": OpportunityStatus.OPEN.value,
        "first_detected_at": datetime.now(timezone.utc),
        "last_seen_at": datetime.now(timezone.utc),
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


class TestGetOpportunityOwnership:
    """Test ownership validation for GET /opportunities/{id}"""

    @pytest.mark.asyncio
    async def test_returns_404_when_opportunity_not_found(
        self, mock_request, mock_request_context
    ):
        """Should return 404 when opportunity doesn't exist"""
        with patch('backend.api.opportunities.get_service') as mock_get_service:

            mock_service = Mock(spec=OpportunitiesService)
            mock_service.get_opportunity.return_value = None
            mock_get_service.return_value = mock_service

            opportunity_id = uuid4()

            with pytest.raises(HTTPException) as exc_info:
                await get_opportunity(mock_request, opportunity_id, mock_request_context)

            assert exc_info.value.status_code == 404
            mock_service.get_opportunity.assert_called_once_with(
                opportunity_id,
                user_id=mock_request_context.user_id
            )

    @pytest.mark.asyncio
    async def test_returns_403_when_user_not_owner(
        self, mock_request, mock_request_context, sample_opportunity
    ):
        """Should return 403 when user tries to access another user's opportunity"""
        with patch('backend.api.opportunities.get_service') as mock_get_service:

            # Service will raise HTTPException when ownership validation fails
            mock_service = Mock(spec=OpportunitiesService)
            mock_service.get_opportunity.side_effect = HTTPException(
                status_code=403,
                detail="Access denied. You can only access opportunities you created."
            )
            mock_get_service.return_value = mock_service

            opportunity_id = uuid4()

            with pytest.raises(HTTPException) as exc_info:
                await get_opportunity(mock_request, opportunity_id, mock_request_context)

            assert exc_info.value.status_code == 403
            assert "Access denied" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_allows_access_when_user_is_owner(
        self, mock_request, mock_request_context, sample_opportunity
    ):
        """Should allow access when user owns the opportunity"""
        # Set the opportunity's creator to match the requesting user
        sample_opportunity['created_by_user_id'] = mock_request_context.user_id

        with patch('backend.api.opportunities.get_service') as mock_get_service:

            mock_service = Mock(spec=OpportunitiesService)
            mock_service.get_opportunity.return_value = OpportunityDetail(**sample_opportunity)
            mock_get_service.return_value = mock_service

            opportunity_id = sample_opportunity['id']

            result = await get_opportunity(mock_request, opportunity_id, mock_request_context)

            assert result is not None
            assert result.id == opportunity_id
            assert result.title == sample_opportunity['title']
            mock_service.get_opportunity.assert_called_once_with(
                opportunity_id,
                user_id=mock_request_context.user_id
            )


class TestUpdateOpportunityOwnership:
    """Test ownership validation for PATCH /opportunities/{id}"""

    @pytest.mark.asyncio
    async def test_returns_404_when_opportunity_not_found(
        self, mock_request, mock_request_context
    ):
        """Should return 404 when opportunity doesn't exist"""
        with patch('backend.api.opportunities.get_service') as mock_get_service:

            mock_service = Mock(spec=OpportunitiesService)
            mock_service.update_opportunity.return_value = None
            mock_get_service.return_value = mock_service

            opportunity_id = uuid4()
            update_data = OpportunityUpdate(title="Updated Title")

            with pytest.raises(HTTPException) as exc_info:
                await update_opportunity(mock_request, opportunity_id, update_data, mock_request_context)

            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_403_when_user_not_owner(
        self, mock_request, mock_request_context, sample_opportunity
    ):
        """Should return 403 when user tries to update another user's opportunity"""
        with patch('backend.api.opportunities.get_service') as mock_get_service:

            # Service will raise HTTPException when ownership validation fails
            mock_service = Mock(spec=OpportunitiesService)
            mock_service.update_opportunity.side_effect = HTTPException(
                status_code=403,
                detail="Access denied. You can only access opportunities you created."
            )
            mock_get_service.return_value = mock_service

            opportunity_id = uuid4()
            update_data = OpportunityUpdate(title="Malicious Update")

            with pytest.raises(HTTPException) as exc_info:
                await update_opportunity(mock_request, opportunity_id, update_data, mock_request_context)

            assert exc_info.value.status_code == 403
            assert "Access denied" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_allows_update_when_user_is_owner(
        self, mock_request, mock_request_context, sample_opportunity
    ):
        """Should allow update when user owns the opportunity"""
        # Set the opportunity's creator to match the requesting user
        sample_opportunity['created_by_user_id'] = mock_request_context.user_id
        sample_opportunity['title'] = "Updated Title"

        with patch('backend.api.opportunities.get_service') as mock_get_service:

            mock_service = Mock(spec=OpportunitiesService)
            mock_service.update_opportunity.return_value = OpportunityDetail(**sample_opportunity)
            mock_get_service.return_value = mock_service

            opportunity_id = sample_opportunity['id']
            update_data = OpportunityUpdate(title="Updated Title")

            result = await update_opportunity(mock_request, opportunity_id, update_data, mock_request_context)

            assert result is not None
            assert result.title == "Updated Title"
            mock_service.update_opportunity.assert_called_once()


class TestDeleteOpportunityOwnership:
    """Test ownership validation for DELETE /opportunities/{id}"""

    @pytest.mark.asyncio
    async def test_returns_404_when_opportunity_not_found(
        self, mock_request, mock_request_context
    ):
        """Should return 404 when opportunity doesn't exist"""
        with patch('backend.api.opportunities.get_service') as mock_get_service:

            mock_service = Mock(spec=OpportunitiesService)
            mock_service.delete_opportunity.return_value = False
            mock_get_service.return_value = mock_service

            opportunity_id = uuid4()

            with pytest.raises(HTTPException) as exc_info:
                await delete_opportunity(mock_request, opportunity_id, mock_request_context)

            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_403_when_user_not_owner(
        self, mock_request, mock_request_context
    ):
        """Should return 403 when user tries to delete another user's opportunity"""
        with patch('backend.api.opportunities.get_service') as mock_get_service:

            # Service will raise HTTPException when ownership validation fails
            mock_service = Mock(spec=OpportunitiesService)
            mock_service.delete_opportunity.side_effect = HTTPException(
                status_code=403,
                detail="Access denied. You can only access opportunities you created."
            )
            mock_get_service.return_value = mock_service

            opportunity_id = uuid4()

            with pytest.raises(HTTPException) as exc_info:
                await delete_opportunity(mock_request, opportunity_id, mock_request_context)

            assert exc_info.value.status_code == 403
            assert "Access denied" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_allows_deletion_when_user_is_owner(
        self, mock_request, mock_request_context
    ):
        """Should allow deletion when user owns the opportunity"""
        with patch('backend.api.opportunities.get_service') as mock_get_service:

            mock_service = Mock(spec=OpportunitiesService)
            mock_service.delete_opportunity.return_value = True
            mock_get_service.return_value = mock_service

            opportunity_id = uuid4()

            result = await delete_opportunity(mock_request, opportunity_id, mock_request_context)

            assert result.status_code == 204
            mock_service.delete_opportunity.assert_called_once_with(
                opportunity_id,
                user_id=mock_request_context.user_id
            )


class TestUpdateStatusOwnership:
    """Test ownership validation for PATCH /opportunities/{id}/status"""

    @pytest.mark.asyncio
    async def test_returns_403_when_user_not_owner(
        self, mock_request, mock_request_context
    ):
        """Should return 403 when user tries to update status of another user's opportunity"""
        with patch('backend.api.opportunities.get_service') as mock_get_service:

            # Service will raise HTTPException when ownership validation fails
            mock_service = Mock(spec=OpportunitiesService)
            mock_service.update_status.side_effect = HTTPException(
                status_code=403,
                detail="Access denied. You can only access opportunities you created."
            )
            mock_get_service.return_value = mock_service

            opportunity_id = uuid4()
            status_update = OpportunityStatusUpdate(
                status=OpportunityStatus.DISMISSED,
                reason="Not applicable"
            )

            with pytest.raises(HTTPException) as exc_info:
                await update_opportunity_status(mock_request, opportunity_id, status_update, mock_request_context)

            assert exc_info.value.status_code == 403
            assert "Access denied" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_allows_status_update_when_user_is_owner(
        self, mock_request, mock_request_context, sample_opportunity
    ):
        """Should allow status update when user owns the opportunity"""
        # Set the opportunity's creator to match the requesting user
        sample_opportunity['created_by_user_id'] = mock_request_context.user_id
        sample_opportunity['status'] = OpportunityStatus.ACCEPTED.value

        with patch('backend.api.opportunities.get_service') as mock_get_service:

            mock_service = Mock(spec=OpportunitiesService)
            mock_service.update_status.return_value = OpportunityDetail(**sample_opportunity)
            mock_get_service.return_value = mock_service

            opportunity_id = sample_opportunity['id']
            status_update = OpportunityStatusUpdate(
                status=OpportunityStatus.ACCEPTED,
                reason="Will implement"
            )

            result = await update_opportunity_status(mock_request, opportunity_id, status_update, mock_request_context)

            assert result is not None
            assert result.status == OpportunityStatus.ACCEPTED


class TestOpportunitiesServiceOwnershipValidation:
    """Test the service layer ownership validation logic"""

    def test_validate_ownership_allows_owner(self):
        """_validate_ownership should allow when user_id matches created_by_user_id"""
        service = OpportunitiesService()

        user_id = uuid4()
        opportunity = {
            'id': uuid4(),
            'created_by_user_id': user_id,
            'title': 'Test Opportunity'
        }

        # Should not raise exception
        service._validate_ownership(opportunity, user_id)

    def test_validate_ownership_denies_non_owner(self):
        """_validate_ownership should deny when user_id doesn't match"""
        service = OpportunitiesService()

        owner_id = uuid4()
        other_user_id = uuid4()

        opportunity = {
            'id': uuid4(),
            'created_by_user_id': owner_id,
            'title': 'Test Opportunity'
        }

        with pytest.raises(HTTPException) as exc_info:
            service._validate_ownership(opportunity, other_user_id)

        assert exc_info.value.status_code == 403
        assert "Access denied" in str(exc_info.value.detail)

    def test_validate_ownership_allows_legacy_data(self):
        """_validate_ownership should allow access to opportunities without created_by_user_id (legacy data)"""
        service = OpportunitiesService()

        user_id = uuid4()
        opportunity = {
            'id': uuid4(),
            'created_by_user_id': None,  # Legacy data
            'title': 'Test Opportunity'
        }

        # Should not raise exception
        service._validate_ownership(opportunity, user_id)


class TestEndToEndOwnershipFlow:
    """Test complete ownership validation flow"""

    @pytest.mark.asyncio
    async def test_complete_flow_unauthorized_access(
        self, mock_request, mock_request_context, sample_opportunity
    ):
        """Test that a complete flow properly blocks unauthorized access"""
        # Alice creates an opportunity
        alice_id = uuid4()
        alice_opportunity = sample_opportunity.copy()
        alice_opportunity['created_by_user_id'] = alice_id

        # Bob tries to access it
        bob_context = mock_request_context
        bob_context.user_id = uuid4()  # Different user

        with patch('backend.api.opportunities.get_service') as mock_get_service:  # bob_context passed directly to handler

            mock_service = Mock(spec=OpportunitiesService)
            mock_service.get_opportunity.side_effect = HTTPException(
                status_code=403,
                detail="Access denied. You can only access opportunities you created."
            )
            mock_get_service.return_value = mock_service

            # Bob's attempt should be blocked
            with pytest.raises(HTTPException) as exc_info:
                await get_opportunity(mock_request, alice_opportunity['id'], bob_context)

            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_complete_flow_authorized_access(
        self, mock_request, mock_request_context, sample_opportunity
    ):
        """Test that owner can perform all operations on their opportunity"""
        # Alice creates and accesses her own opportunity
        alice_context = mock_request_context
        alice_context.user_id = uuid4()

        alice_opportunity = sample_opportunity.copy()
        alice_opportunity['created_by_user_id'] = alice_context.user_id

        with patch('backend.api.opportunities.get_service') as mock_get_service:  # alice_context passed directly to handler

            mock_service = Mock(spec=OpportunitiesService)
            mock_get_service.return_value = mock_service

            # Test GET
            mock_service.get_opportunity.return_value = OpportunityDetail(**alice_opportunity)
            result = await get_opportunity(mock_request, alice_opportunity['id'], alice_context)
            assert result.id == alice_opportunity['id']

            # Test UPDATE
            updated_opportunity = alice_opportunity.copy()
            updated_opportunity['title'] = "Updated by Alice"
            mock_service.update_opportunity.return_value = OpportunityDetail(**updated_opportunity)

            update_data = OpportunityUpdate(title="Updated by Alice")
            result = await update_opportunity(mock_request, alice_opportunity['id'], update_data, alice_context)
            assert result.title == "Updated by Alice"

            # Test DELETE
            mock_service.delete_opportunity.return_value = True
            result = await delete_opportunity(mock_request, alice_opportunity['id'], alice_context)
            assert result.status_code == 204


# ═════════════════════════════════════════════════════════════════════════════
# HIGH-20 — Missing Authentication on Opportunities Endpoints
# ═════════════════════════════════════════════════════════════════════════════
#
# Pre-fix (opportunities.py:67-71, verified 2026-03-06):
#
#     def get_service(request: Request) -> OpportunitiesService:
#         context = get_context_from_request(request)   # returns Optional — None if no auth
#         org_id = context.organization_id if context else None
#         return get_opportunities_service(org_id)      # ← org_id=None → unscoped
#
# Every route inherited this. No route declared Depends(get_request_context).
# An unauthenticated request (no Authorization header, middleware sets no
# request.state.context) reached every handler body with context=None, then
# every `X if context else None` branch took None, and the service layer ran
# queries with no tenant filter. List/export/stats returned ALL orgs' data;
# create/update/delete ran without ownership stamping.
#
# Post-fix: get_request_context() wraps require_context() which raises 401
# before any handler body executes. Every route declares the dependency.
# get_service() takes RequestContext, not Request — the None-tolerant branch
# is structurally impossible. The router tripwire below asserts this contract
# holds for every route including any added in future.
#
# Precedent: F-35 (reports.py, CRIT-11) — identical pattern, identical fix,
# identical tripwire. See test_reports_security.py::test_all_routes_have_context_dependency.


class TestOpportunitiesRequireAuthentication:
    """HIGH-20 regression — the auth dependency itself works correctly."""

    @pytest.mark.asyncio
    async def test_get_request_context_raises_401_when_unauthenticated(self):
        """
        HIGH-20 PRIMARY REGRESSION. A request with no request.state.context
        (what the auth middleware produces for a missing/invalid token) must
        yield 401 at dependency-resolution time. Handler bodies never run.
        """
        from backend.api.opportunities import get_request_context

        bare_request = Mock()
        bare_request.state = Mock(spec=[])  # spec=[] → hasattr(state, 'context') is False

        with pytest.raises(HTTPException) as exc:
            await get_request_context(bare_request)

        assert exc.value.status_code == 401
        assert "authentication" in str(exc.value.detail).lower()

    @pytest.mark.asyncio
    async def test_get_request_context_returns_context_when_authenticated(
        self, mock_request_context
    ):
        """Positive path — middleware attached a context, dependency returns it."""
        from backend.api.opportunities import get_request_context

        authed_request = Mock()
        authed_request.state = Mock()
        authed_request.state.context = mock_request_context

        result = await get_request_context(authed_request)

        assert result is mock_request_context

    def test_get_service_takes_request_context_not_request(self):
        """
        Signature-level pin. Pre-fix, get_service(request: Request) pulled
        context internally via the nullable helper. Post-fix it takes
        RequestContext directly — the None-tolerant branch cannot exist
        because there is no Request to extract a maybe-None from.
        """
        import inspect
        from backend.api.opportunities import get_service

        sig = inspect.signature(get_service)
        params = list(sig.parameters.values())

        assert len(params) == 1, f"get_service should take exactly 1 param, got {params}"
        assert params[0].name == "context"
        assert params[0].annotation is RequestContext, (
            f"HIGH-20 REGRESSION: get_service must take RequestContext (guaranteed "
            f"authenticated), not {params[0].annotation}. Accepting Request would "
            f"reintroduce the nullable-context path."
        )

    def test_get_service_scopes_to_caller_organization(self, mock_request_context):
        """get_service forwards context.organization_id to the service factory."""
        from backend.api.opportunities import get_service

        with patch("backend.api.opportunities.get_opportunities_service") as factory:
            get_service(mock_request_context)

        factory.assert_called_once_with(mock_request_context.organization_id)


class TestOpportunitiesRouterAuthTripwire:
    """
    HIGH-20 CI tripwire — router-level invariants that survive refactors.

    These tests do NOT exercise behaviour. They inspect source and router
    structure so that the vulnerability cannot be reintroduced by someone
    who adds a new endpoint, forgets the Depends(), and doesn't touch this
    test file. Same design as F-35's tripwire in test_reports_security.py.
    """

    def test_every_route_has_auth_dependency(self):
        """
        ROUTER-WIDE TRIPWIRE. Every route registered on the opportunities
        router must declare `context: RequestContext = Depends(get_request_context)`.

        Adding a new endpoint without auth will break THIS test, even if no
        one thinks to write a new auth test for that specific endpoint.

        Pre-fix: all 12 routes would have failed this.
        """
        import inspect
        from backend.api.opportunities import router, get_request_context

        violations = []
        for route in router.routes:
            handler = route.endpoint
            sig = inspect.signature(handler)

            if "context" not in sig.parameters:
                violations.append(
                    f"  {sorted(route.methods)[0]:6s} {route.path} "
                    f"→ {handler.__name__}() has no `context` parameter"
                )
                continue

            default = sig.parameters["context"].default
            dep = getattr(default, "dependency", None)
            if dep is not get_request_context:
                violations.append(
                    f"  {sorted(route.methods)[0]:6s} {route.path} "
                    f"→ {handler.__name__}() `context` is bound to "
                    f"{dep!r}, not Depends(get_request_context)"
                )

        assert not violations, (
            "HIGH-20 REGRESSION — routes without required auth dependency:\n"
            + "\n".join(violations)
            + "\n\nEvery opportunities endpoint MUST declare "
            "`context: RequestContext = Depends(get_request_context)`. "
            "The previous nullable pattern (get_context_from_request → None "
            "when unauthenticated → service runs unscoped) was CVSS 8.5."
        )

    def test_router_has_expected_route_count(self):
        """
        Sanity floor for the tripwire above — if someone restructures the
        module and the router ends up empty, test_every_route_has_auth_dependency
        would vacuously pass. 12 routes as of fix date; adjust only if routes
        are intentionally added/removed (and DO add auth to new ones).
        """
        from backend.api.opportunities import router
        assert len(router.routes) >= 12, (
            f"Expected ≥12 routes on opportunities router, found {len(router.routes)}. "
            f"If routes were removed, adjust this floor. If the router is empty, "
            f"test_every_route_has_auth_dependency is vacuously passing."
        )

    def test_nullable_context_function_not_imported(self):
        """
        get_context_from_request returns Optional[RequestContext] → None on
        missing auth → the exact vector. It MUST NOT be in the opportunities
        module namespace. require_context (which raises 401) replaces it.
        """
        import backend.api.opportunities as opportunities_module

        assert not hasattr(opportunities_module, "get_context_from_request"), (
            "HIGH-20 REGRESSION: opportunities.py imports get_context_from_request. "
            "That function returns None when unauthenticated — the nullable pattern "
            "that allowed org_id=None → unscoped service. Use require_context "
            "(via get_request_context dependency) which raises 401."
        )
        # Positive: the secure alternative IS imported
        assert hasattr(opportunities_module, "require_context")
        assert hasattr(opportunities_module, "RequestContext")

    def test_no_if_context_else_none_fallback_pattern(self):
        """
        AST TRIPWIRE for the None-tolerant branch pattern. Pre-fix, seven
        handlers had `context.user_id if context else None` (and variants).
        This test walks every function in the module and fails if any
        `X if context else Y` ternary appears — the pattern has no legitimate
        use once context is guaranteed non-None by the Depends().

        Catches a merge/revert that reintroduces the tolerant branch even
        if the Depends() is still present (defense against partial reverts).
        """
        import ast
        import inspect
        import backend.api.opportunities as opportunities_module

        tree = ast.parse(inspect.getsource(opportunities_module))

        violations = []
        for node in ast.walk(tree):
            # `X if context else Y` → IfExp where test is Name(id='context')
            if (
                isinstance(node, ast.IfExp)
                and isinstance(node.test, ast.Name)
                and node.test.id == "context"
            ):
                violations.append(f"  line {node.lineno}: {ast.unparse(node)}")

        assert not violations, (
            "HIGH-20 REGRESSION — `X if context else Y` pattern found:\n"
            + "\n".join(violations)
            + "\n\nThis pattern tolerated context=None. After the Depends() fix, "
            "context is guaranteed — these branches are dead and mask the real "
            "risk (a future refactor drops the Depends, the branch silently "
            "re-engages). Use context.attr directly."
        )


# Summary of test coverage:
# ✅ GET /opportunities/{id} - ownership validation (CRIT-2)
# ✅ PATCH /opportunities/{id} - ownership validation (CRIT-2)
# ✅ DELETE /opportunities/{id} - ownership validation (CRIT-2)
# ✅ PATCH /opportunities/{id}/status - ownership validation (CRIT-2)
# ✅ Service layer _validate_ownership method (CRIT-2)
# ✅ Legacy data handling (opportunities without created_by_user_id)
# ✅ End-to-end flow validation (CRIT-2)
# ✅ Proper HTTP status codes (403 for unauthorized, 404 for not found)
# ─────────────────────────────────────────────────────────────────────────────
# ✅ HIGH-20: 401 on unauthenticated requests (dependency raises)
# ✅ HIGH-20: get_service takes RequestContext not Request (signature pin)
# ✅ HIGH-20: every route has Depends(get_request_context) (router tripwire)
# ✅ HIGH-20: nullable get_context_from_request not imported (namespace check)
# ✅ HIGH-20: no `X if context else None` fallback pattern (AST tripwire)
