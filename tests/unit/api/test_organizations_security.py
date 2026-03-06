"""
HIGH-17 — Missing Membership Verification on Organization Switch (API Layer)

Pre-fix state: PUT /organizations/current/{org_id} delegated straight to
organization_service.switch_organization() with no API-layer membership check.
The service layer DOES check (organization_service.py:258-266 raises ValueError)
— but that check is now the SECOND line of defense, not the only one.

Defense in depth: a future service refactor, a new service method, or any
caller that bypasses switch_organization() shouldn't silently drop the guard.
The API layer owns authorization semantics (403); the service owns data
integrity (ValueError → 400).

Tests exercise the handler directly (not via TestClient) so we control the
organization_service mock precisely and assert short-circuit ordering.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException


# ── fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def target_org_id():
    """The org the attacker/user is attempting to switch into."""
    return uuid4()


@pytest.fixture
def member_org_id():
    """A different org the user legitimately belongs to."""
    return uuid4()


@pytest.fixture
def ctx():
    """RequestContext — only user_id is read by the handler pre-delegation."""
    return Mock(user_id=uuid4())


@pytest.fixture
def http_req():
    return Mock()


# ═══════════════════════════════════════════════════════════════════════════
# Non-member → 403 (the fix)
# ═══════════════════════════════════════════════════════════════════════════


class TestSwitchOrganizationMembershipGuard:
    """HIGH-17 regression — API layer denies non-members with 403."""

    @pytest.mark.asyncio
    async def test_non_member_receives_403(
        self, target_org_id, member_org_id, ctx, http_req
    ):
        """
        HIGH-17 PRIMARY REGRESSION.

        User belongs to member_org_id only. Attempts switch to target_org_id.
        Pre-fix: request delegated to service → ValueError → 400 (wrong
        semantics — 400 means "malformed", not "forbidden").
        Post-fix: API layer checks membership → 403, service never called.
        """
        svc = Mock()
        svc.get_user_organizations = AsyncMock(
            return_value=[{"id": str(member_org_id), "name": "My Org"}]
        )
        svc.switch_organization = AsyncMock()  # sentinel — must NOT be reached

        with patch("backend.api.organizations.organization_service", svc):
            from backend.api.organizations import switch_organization
            with pytest.raises(HTTPException) as exc:
                await switch_organization(target_org_id, http_req, ctx)

        assert exc.value.status_code == 403
        # Load-bearing: service is NOT reached. The API layer stops it.
        svc.switch_organization.assert_not_called()
        svc.get_user_organizations.assert_awaited_once_with(user_id=ctx.user_id)

    @pytest.mark.asyncio
    async def test_user_with_zero_orgs_receives_403(
        self, target_org_id, ctx, http_req
    ):
        """Empty membership list — every org_id is foreign. Still 403,
        not 400/404/500."""
        svc = Mock()
        svc.get_user_organizations = AsyncMock(return_value=[])
        svc.switch_organization = AsyncMock()

        with patch("backend.api.organizations.organization_service", svc):
            from backend.api.organizations import switch_organization
            with pytest.raises(HTTPException) as exc:
                await switch_organization(target_org_id, http_req, ctx)

        assert exc.value.status_code == 403
        svc.switch_organization.assert_not_called()

    @pytest.mark.asyncio
    async def test_403_is_not_swallowed_by_generic_500_handler(
        self, target_org_id, ctx, http_req
    ):
        """
        The handler's final `except Exception` would eat our HTTPException(403)
        and re-raise as 500 if there's no `except HTTPException: raise` before
        it. This test is the reason that clause exists.
        """
        svc = Mock()
        svc.get_user_organizations = AsyncMock(return_value=[])

        with patch("backend.api.organizations.organization_service", svc):
            from backend.api.organizations import switch_organization
            with pytest.raises(HTTPException) as exc:
                await switch_organization(target_org_id, http_req, ctx)

        # NOT 500 — if this fails, the `except HTTPException: raise` was
        # removed and the generic handler downgraded our 403 to a 500.
        assert exc.value.status_code == 403
        assert exc.value.status_code != 500
        assert "not a member" in exc.value.detail.lower()

    @pytest.mark.asyncio
    async def test_denial_is_audit_logged(
        self, target_org_id, ctx, http_req
    ):
        """Failed-authorization events are audit signals. Verify the denial
        logs a warning with user_id + org_id for SOC correlation."""
        svc = Mock()
        svc.get_user_organizations = AsyncMock(return_value=[])

        with patch("backend.api.organizations.organization_service", svc), \
             patch("backend.api.organizations.logger") as log:
            from backend.api.organizations import switch_organization
            with pytest.raises(HTTPException):
                await switch_organization(target_org_id, http_req, ctx)

        log.warning.assert_called_once()
        event_name = log.warning.call_args.args[0]
        kwargs = log.warning.call_args.kwargs
        assert event_name == "organization_switch_denied_not_member"
        assert kwargs.get("user_id") == str(ctx.user_id)
        assert kwargs.get("org_id") == str(target_org_id)


# ═══════════════════════════════════════════════════════════════════════════
# Member → passes through (fix doesn't over-block)
# ═══════════════════════════════════════════════════════════════════════════


class TestSwitchOrganizationMemberPassesThrough:
    """Members still reach the service layer. No over-blocking."""

    @pytest.mark.asyncio
    async def test_member_reaches_service_layer(
        self, target_org_id, member_org_id, ctx, http_req
    ):
        """
        User IS a member of target_org_id → guard passes → service called.

        get_user_organizations returns ids as str(UUID) (see
        organization_service.py:175). The handler compares str(org_id) against
        that set — this test confirms the string-comparison works for a real
        UUID path param.
        """
        svc = Mock()
        svc.get_user_organizations = AsyncMock(return_value=[
            {"id": str(member_org_id), "name": "Other Org"},
            {"id": str(target_org_id), "name": "Target Org"},  # ← member
        ])
        svc.switch_organization = AsyncMock(return_value=True)
        svc.get_organization = AsyncMock(return_value={
            "id": str(target_org_id), "name": "Target Org", "slug": "target",
            "subscription_tier": "pro", "max_users": 10, "max_accounts": 5,
            "saved_view_default_expiration_days": 30, "created_at": "2026-01-01",
        })

        with patch("backend.api.organizations.organization_service", svc):
            from backend.api.organizations import switch_organization
            resp = await switch_organization(target_org_id, http_req, ctx)

        assert resp["success"] is True
        svc.switch_organization.assert_awaited_once_with(
            user_id=ctx.user_id, org_id=target_org_id
        )

    @pytest.mark.asyncio
    async def test_member_with_service_layer_value_error_still_400(
        self, target_org_id, ctx, http_req
    ):
        """
        Defense-in-depth verified end-to-end. API check passes (member), but
        the service layer's OWN check fires — e.g. membership was revoked
        between the two checks (TOCTOU window). The service's ValueError must
        still map to 400 with a generic message.

        This is why BOTH layers check: the API layer gives correct authz
        semantics in the common case, the service layer is the transactional
        floor for the race.
        """
        svc = Mock()
        svc.get_user_organizations = AsyncMock(
            return_value=[{"id": str(target_org_id), "name": "T"}]
        )
        svc.switch_organization = AsyncMock(
            side_effect=ValueError("internal: not a member")
        )

        with patch("backend.api.organizations.organization_service", svc):
            from backend.api.organizations import switch_organization
            with pytest.raises(HTTPException) as exc:
                await switch_organization(target_org_id, http_req, ctx)

        assert exc.value.status_code == 400
        # Service-layer detail NOT leaked
        assert "internal" not in str(exc.value.detail)


# ═══════════════════════════════════════════════════════════════════════════
# Source tripwire
# ═══════════════════════════════════════════════════════════════════════════


class TestSwitchOrganizationSourceTripwire:
    """
    AST-level guard. The behavioural tests above would still pass if someone
    replaced the membership check with a different implementation — which is
    fine. What's NOT fine is removing the check entirely because the service
    "already checks". That's the exact state the audit found.
    """

    def test_get_user_organizations_called_before_switch(self):
        """
        get_user_organizations must be called (line-number) before
        switch_organization in the handler body. Ordering = the membership
        check gates the delegation.
        """
        import ast
        import inspect
        from backend.api import organizations

        src = inspect.getsource(organizations)
        tree = ast.parse(src)

        handler = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef)
            and n.name == "switch_organization"
        )

        def _find_service_call(method_name: str) -> int | None:
            """Line number of organization_service.<method_name>(...) call."""
            for node in ast.walk(handler):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == method_name
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "organization_service"
                ):
                    return node.lineno
            return None

        member_check_line = _find_service_call("get_user_organizations")
        delegate_line = _find_service_call("switch_organization")

        assert member_check_line is not None, (
            "HIGH-17 REGRESSION: switch_organization handler no longer calls "
            "organization_service.get_user_organizations(). The API-layer "
            "membership guard has been removed. Even if the service layer "
            "checks, defense-in-depth requires BOTH layers — see HIGH-17."
        )
        assert delegate_line is not None, (
            "switch_organization handler no longer delegates to the service "
            "— unexpected, check if the endpoint was rewritten."
        )
        assert member_check_line < delegate_line, (
            f"HIGH-17 REGRESSION: membership check (line {member_check_line}) "
            f"must precede service delegation (line {delegate_line}). If the "
            f"order is inverted, the check is dead code."
        )

    def test_http_exception_reraise_before_generic_handler(self):
        """
        The handler must re-raise HTTPException before `except Exception`.
        Without this, the 403 is swallowed → 500.
        """
        import ast
        import inspect
        from backend.api import organizations

        tree = ast.parse(inspect.getsource(organizations))
        handler = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef)
            and n.name == "switch_organization"
        )

        # Find the Try node and its handlers in declaration order
        try_node = next(n for n in ast.walk(handler) if isinstance(n, ast.Try))
        handler_types = [
            h.type.id if isinstance(h.type, ast.Name) else None
            for h in try_node.handlers
        ]

        assert "HTTPException" in handler_types, (
            "switch_organization has no `except HTTPException` clause — the "
            "403 membership denial will be swallowed by `except Exception` "
            "and re-raised as 500."
        )
        http_idx = handler_types.index("HTTPException")
        exc_idx = handler_types.index("Exception")
        assert http_idx < exc_idx, (
            "`except HTTPException` must precede `except Exception` — Python "
            "tries handlers in order, so reversed order = 403 still swallowed."
        )

        # And the HTTPException handler must actually re-raise (bare `raise`)
        http_handler = try_node.handlers[http_idx]
        has_bare_raise = any(
            isinstance(stmt, ast.Raise) and stmt.exc is None
            for stmt in ast.walk(http_handler)
        )
        assert has_bare_raise, (
            "`except HTTPException` clause must contain a bare `raise` — "
            "otherwise the 403 is caught and silently dropped."
        )
