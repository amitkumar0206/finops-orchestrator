"""
Tests for HIGH-3: Internal Exception Details Exposed in API Responses

Verifies two things across every API file that was patched:

1. **Static (AST)** — No exception handler in any of the six target files
   passes ``str(e)`` or an f-string containing ``{str(e)}`` into
   ``HTTPException(detail=...)``.  The only allowed ``str(e)`` usage inside
   an except block is as an argument to a logger call.

2. **Runtime** — Representative handlers from each file actually produce
   the expected generic detail string and log the real error, without
   leaking any secret present in the original exception.
"""

import ast
import inspect
import os
import json

import sys
import types

import pytest
from unittest.mock import AsyncMock, Mock, patch, MagicMock
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Stub backend.services.scheduled_report_service so phase3_enterprise can be
# imported without pulling in croniter / email_service / s3_service.
# This only needs to happen once per interpreter; subsequent imports use the
# cached module from sys.modules.
# ---------------------------------------------------------------------------
if 'backend.services.scheduled_report_service' not in sys.modules:
    _srs_stub = types.ModuleType('backend.services.scheduled_report_service')
    _srs_stub.scheduled_report_service = Mock()
    sys.modules['backend.services.scheduled_report_service'] = _srs_stub

import backend.api.phase3_enterprise  # noqa: E402, F401
import backend.api.auth  # noqa: E402, F401


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BACKEND_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..', 'backend')
)


def _read_source(relative_path: str) -> str:
    with open(os.path.join(_BACKEND_ROOT, relative_path)) as f:
        return f.read()


# Generic messages that are acceptable in HTTPException detail
_ALLOWED_DETAILS = {
    "Invalid request. Please check your input.",
    "An internal error occurred. Please try again later.",
    "Service temporarily unavailable.",
    "Authentication failed",
}


def _find_str_e_in_http_exception(source: str) -> list:
    """
    AST-walk and return (lineno, snippet) for every HTTPException whose
    ``detail`` keyword argument contains ``str(e)`` or an f-string with
    ``{str(e)}``.

    We look for:
      - Call nodes to HTTPException
      - keyword arg named 'detail'
      - whose value is either:
          * a Call to str() whose first arg is a Name 'e'
          * an f-string (JoinedStr) containing a FormattedValue that wraps
            a Call to str() on Name 'e'
          * an f-string containing any FormattedValue whose value is a
            Call to str() on any Name node (covers ``str(e)``, ``str(exc)``, etc.)
    """
    tree = ast.parse(source)
    hits = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Is this a call to HTTPException (possibly via fastapi.HTTPException)?
        func = node.func
        is_http_exc = False
        if isinstance(func, ast.Name) and func.id == 'HTTPException':
            is_http_exc = True
        elif isinstance(func, ast.Attribute) and func.attr == 'HTTPException':
            is_http_exc = True
        if not is_http_exc:
            continue

        # Find 'detail' keyword
        for kw in node.keywords:
            if kw.arg != 'detail':
                continue
            if _detail_contains_str_e(kw.value):
                hits.append((node.lineno, "HTTPException detail contains str(e)"))
    return hits


def _detail_contains_str_e(node) -> bool:
    """Return True if the AST node is or contains a str(e) call."""
    # Direct str(e) call
    if _is_str_e_call(node):
        return True
    # f-string (JoinedStr)
    if isinstance(node, ast.JoinedStr):
        for value in node.values:
            if isinstance(value, ast.FormattedValue):
                if _is_str_e_call(value.value):
                    return True
    return False


def _is_str_e_call(node) -> bool:
    """Return True if node is ``str(<Name>)`` — i.e. str() called on any name."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == 'str'
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Name)
    )


def _find_execution_result_error_in_detail(source: str) -> list:
    """
    Find any HTTPException detail that contains execution_result.get('error').
    This catches the pattern:  detail=f"...{execution_result.get('error'...)}..."
    """
    tree = ast.parse(source)
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_http_exc = (
            (isinstance(func, ast.Name) and func.id == 'HTTPException')
            or (isinstance(func, ast.Attribute) and func.attr == 'HTTPException')
        )
        if not is_http_exc:
            continue
        for kw in node.keywords:
            if kw.arg != 'detail':
                continue
            # Walk the detail value looking for execution_result.get(...)
            for child in ast.walk(kw.value):
                if (isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Attribute)
                        and child.func.attr == 'get'
                        and isinstance(child.func.value, ast.Name)
                        and child.func.value.id == 'execution_result'):
                    hits.append((node.lineno, "HTTPException detail contains execution_result.get()"))
    return hits


# Files to verify — all six from the HIGH-3 finding
_TARGET_FILES = [
    "api/analytics.py",
    "api/athena_queries.py",
    "api/saved_views.py",
    "api/organizations.py",
    "api/phase3_enterprise.py",
    "api/auth.py",
]


# ---------------------------------------------------------------------------
# Static analysis
# ---------------------------------------------------------------------------


class TestStaticAnalysis:
    """AST verification that no str(e) remains in HTTPException detail."""

    @pytest.mark.parametrize("source_file", _TARGET_FILES)
    def test_no_str_e_in_http_exception_detail(self, source_file):
        violations = _find_str_e_in_http_exception(_read_source(source_file))
        assert violations == [], (
            f"{source_file} still leaks str(e) in HTTPException detail:\n"
            + "\n".join(f"  line {ln}: {desc}" for ln, desc in violations)
        )

    @pytest.mark.parametrize("source_file", _TARGET_FILES)
    def test_no_execution_result_error_in_http_exception_detail(self, source_file):
        violations = _find_execution_result_error_in_detail(_read_source(source_file))
        assert violations == [], (
            f"{source_file} still leaks execution_result error in HTTPException detail:\n"
            + "\n".join(f"  line {ln}: {desc}" for ln, desc in violations)
        )

    def test_phase3_enterprise_has_structlog_logger(self):
        """phase3_enterprise.py must have a structlog logger for its new error calls."""
        source = _read_source("api/phase3_enterprise.py")
        assert "import structlog" in source
        assert "logger = structlog.get_logger(__name__)" in source

    def test_analytics_response_body_no_str_e(self):
        """The get_data_sources_info fallback response must not contain str(e)."""
        source = _read_source("api/analytics.py")
        # The old pattern was: "error": str(e),
        # Verify it's gone by checking that no line has both "error" key and str(e)
        for i, line in enumerate(source.splitlines(), 1):
            if '"error"' in line and 'str(e)' in line:
                pytest.fail(
                    f"analytics.py line {i} still exposes str(e) in response body: {line.strip()}"
                )

    def test_athena_inline_error_sanitised(self):
        """The inline execution_result error in generate_athena_query must be generic."""
        source = _read_source("api/athena_queries.py")
        # Find the response_data.update block — the "error" value must be a generic string
        assert '"error": "Query execution failed."' in source
        # The raw execution_result.get("error") must only appear in logger calls
        for i, line in enumerate(source.splitlines(), 1):
            stripped = line.strip()
            if "execution_result.get" in stripped and '"error"' in stripped:
                # Allowed only inside a logger.error call or as the conditional check
                assert (
                    "logger.error" in stripped
                    or "if execution_result.get" in stripped
                ), f"athena_queries.py line {i} leaks raw error: {stripped}"


# ---------------------------------------------------------------------------
# Runtime — analytics.py
# ---------------------------------------------------------------------------


class TestAnalyticsExceptionSanitisation:
    """Runtime checks for analytics.py handlers."""

    @pytest.mark.asyncio
    async def test_client_error_returns_generic_503(self):
        """ClientError in check_historical_data_availability → generic 503."""
        from botocore.exceptions import ClientError
        secret = "AccessDeniedException: User arn:aws:iam::111111111111:role/finops not authorized"
        error = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": secret}},
            "GetCostAndUsage",
        )
        mock_client = Mock()
        mock_client.get_cost_and_usage = Mock(side_effect=error)

        with patch('backend.api.analytics.create_aws_client', return_value=mock_client):
            with patch('backend.api.analytics.logger') as mock_log:
                from backend.api.analytics import check_historical_data_availability
                with pytest.raises(HTTPException) as exc_info:
                    await check_historical_data_availability()

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail == "Service temporarily unavailable."
        assert secret not in str(exc_info.value.detail)
        mock_log.error.assert_called_once()
        assert secret in str(mock_log.error.call_args)

    @pytest.mark.asyncio
    async def test_generic_exception_returns_500(self):
        """Generic Exception in check_historical_data_availability → generic 500."""
        secret = "psycopg2.OperationalError: connection to 10.0.0.5:5432 refused"
        mock_client = Mock()
        mock_client.get_cost_and_usage = Mock(side_effect=Exception(secret))

        with patch('backend.api.analytics.create_aws_client', return_value=mock_client):
            with patch('backend.api.analytics.logger') as mock_log:
                from backend.api.analytics import check_historical_data_availability
                with pytest.raises(HTTPException) as exc_info:
                    await check_historical_data_availability()

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "An internal error occurred. Please try again later."
        assert secret not in str(exc_info.value.detail)
        mock_log.error.assert_called_once()
        assert secret in str(mock_log.error.call_args)

    @pytest.mark.asyncio
    async def test_data_sources_info_error_is_generic(self):
        """get_data_sources_info fallback must not expose str(e)."""
        secret = "NoCredentialsError: Unable to locate credentials in /home/deploy/.aws"

        with patch('backend.api.analytics.create_aws_session', side_effect=Exception(secret)):
            with patch('backend.api.analytics.logger') as mock_log:
                from backend.api.analytics import get_data_sources_info
                result = await get_data_sources_info()

        assert secret not in json.dumps(result)
        assert "/home/deploy" not in json.dumps(result)
        assert result["error"] == "Unable to retrieve data source information."
        mock_log.error.assert_called_once()
        assert secret in str(mock_log.error.call_args)

    @pytest.mark.asyncio
    async def test_cache_init_error_is_generic(self):
        """initialize_historical_cache generic Exception → generic 500."""
        from backend.api.analytics import initialize_historical_cache, CacheInitRequest
        secret = "Redis connection error: ECONNREFUSED 172.16.0.10:6379"

        mock_bg = Mock()
        # Force the HTTPException path by making months validation pass but
        # having the background task addition raise
        mock_bg.add_task = Mock(side_effect=Exception(secret))

        with patch('backend.api.analytics.logger') as mock_log:
            request = CacheInitRequest(months=3)
            with pytest.raises(HTTPException) as exc_info:
                await initialize_historical_cache(request, mock_bg)

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "An internal error occurred. Please try again later."
        assert secret not in str(exc_info.value.detail)
        mock_log.error.assert_called_once()
        assert secret in str(mock_log.error.call_args)


# ---------------------------------------------------------------------------
# Runtime — athena_queries.py
# ---------------------------------------------------------------------------


class TestAthenaQueriesExceptionSanitisation:
    """Runtime checks for athena_queries.py handlers."""

    @pytest.mark.asyncio
    async def test_generate_query_exception_is_generic(self):
        """Exception in generate_athena_query → generic 500."""
        secret = "Table finops_cur.aws_cur_table not found in database finops_prod"
        mock_service = Mock()
        mock_service.generate_query_for_user_request = AsyncMock(side_effect=Exception(secret))

        with patch('backend.api.athena_queries.athena_service', mock_service):
            with patch('backend.api.athena_queries.logger') as mock_log:
                from backend.api.athena_queries import generate_athena_query, AthenaQueryRequest
                request = AthenaQueryRequest(user_query="show costs")
                with pytest.raises(HTTPException) as exc_info:
                    await generate_athena_query(request)

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "An internal error occurred. Please try again later."
        assert secret not in str(exc_info.value.detail)
        mock_log.error.assert_called_once()
        assert secret in str(mock_log.error.call_args)

    @pytest.mark.asyncio
    async def test_get_query_results_exception_is_generic(self):
        """Exception in get_query_results → generic 500."""
        secret = "athena.AmazonAthena: Access Denied on arn:aws:athena:us-east-1:123456789012"
        mock_service = Mock()
        mock_service._get_query_results = AsyncMock(side_effect=Exception(secret))

        with patch('backend.api.athena_queries.athena_service', mock_service):
            with patch('backend.api.athena_queries.logger') as mock_log:
                from backend.api.athena_queries import get_query_results
                with pytest.raises(HTTPException) as exc_info:
                    await get_query_results("test-query-id")

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "An internal error occurred. Please try again later."
        assert "123456789012" not in str(exc_info.value.detail)
        mock_log.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_execution_result_error_sanitised_in_csv_export(self):
        """Failed execution_result in CSV export → generic 500, error logged."""
        secret_error = "SYNTAX_ERROR: Line 3: col 15: table secret_cur_table not found"
        mock_service = Mock()
        mock_service.generate_query_for_user_request = AsyncMock(return_value=("SELECT 1", "test"))
        mock_service.execute_query = AsyncMock(return_value={
            "status": "failed",
            "error": secret_error,
        })

        with patch('backend.api.athena_queries.athena_service', mock_service):
            with patch('backend.api.athena_queries.logger') as mock_log:
                from backend.api.athena_queries import export_results_csv, AthenaQueryRequest
                request = AthenaQueryRequest(user_query="show costs")
                with pytest.raises(HTTPException) as exc_info:
                    await export_results_csv(request)

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "An internal error occurred. Please try again later."
        assert "secret_cur_table" not in str(exc_info.value.detail)
        mock_log.error.assert_called()
        # The real error must appear in logs
        assert secret_error in str(mock_log.error.call_args_list)

    @pytest.mark.asyncio
    async def test_inline_execution_error_sanitised_in_generate(self):
        """Inline execution error in generate_athena_query response is generic."""
        secret_error = "SYNTAX_ERROR: column secret_column not found in secret_db.secret_table"
        mock_service = Mock()
        mock_service.generate_query_for_user_request = AsyncMock(return_value=("SELECT 1", "test"))
        mock_service.execute_query = AsyncMock(return_value={
            "status": "failed",
            "error": secret_error,
            "query_execution_id": "qid-123",
            "results": [],
            "row_count": 0,
        })

        with patch('backend.api.athena_queries.athena_service', mock_service):
            with patch('backend.api.athena_queries.logger') as mock_log:
                from backend.api.athena_queries import generate_athena_query, AthenaQueryRequest
                request = AthenaQueryRequest(user_query="show costs", execute_query=True)
                result = await generate_athena_query(request)

        # The response error field must be generic
        assert result.error == "Query execution failed."
        assert secret_error not in str(result.error)
        assert "secret_db" not in str(result.error)
        # Real error must be logged
        mock_log.error.assert_called()
        assert secret_error in str(mock_log.error.call_args_list)


# ---------------------------------------------------------------------------
# Runtime — saved_views.py
# ---------------------------------------------------------------------------


class TestSavedViewsExceptionSanitisation:
    """Runtime checks for saved_views.py ValueError handlers."""

    @pytest.mark.asyncio
    async def test_create_saved_view_value_error_is_generic(self):
        """ValueError in create_saved_view → generic 400, error logged."""
        secret = "Database constraint: unique violation on (org_id, name) at table saved_views"
        mock_service = Mock()
        mock_service.create_saved_view = AsyncMock(side_effect=ValueError(secret))

        mock_context = Mock()
        mock_request = Mock()

        with patch('backend.api.saved_views.saved_views_service', mock_service):
            with patch('backend.api.saved_views.logger') as mock_log:
                from backend.api.saved_views import create_saved_view, CreateSavedViewRequest
                from uuid import uuid4
                payload = CreateSavedViewRequest(
                    name="Test View",
                    account_ids=[uuid4()],
                )
                with pytest.raises(HTTPException) as exc_info:
                    await create_saved_view(payload, mock_request, mock_context)

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Invalid request. Please check your input."
        assert secret not in str(exc_info.value.detail)
        mock_log.error.assert_called_once()
        assert secret in str(mock_log.error.call_args)

    @pytest.mark.asyncio
    async def test_update_saved_view_value_error_is_generic(self):
        """ValueError in update_saved_view → generic 400, error logged."""
        secret = "SQL injection attempt detected in field 'name'; value contains DROP TABLE"
        mock_service = Mock()
        mock_service.update_saved_view = AsyncMock(side_effect=ValueError(secret))

        mock_context = Mock()
        mock_request = Mock()

        with patch('backend.api.saved_views.saved_views_service', mock_service):
            with patch('backend.api.saved_views.logger') as mock_log:
                from backend.api.saved_views import update_saved_view, UpdateSavedViewRequest
                from uuid import uuid4
                payload = UpdateSavedViewRequest(name="Updated")
                with pytest.raises(HTTPException) as exc_info:
                    await update_saved_view(uuid4(), payload, mock_request, mock_context)

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Invalid request. Please check your input."
        assert "DROP TABLE" not in str(exc_info.value.detail)
        mock_log.error.assert_called_once()
        assert secret in str(mock_log.error.call_args)


# ---------------------------------------------------------------------------
# Runtime — organizations.py
# ---------------------------------------------------------------------------


class TestOrganizationsExceptionSanitisation:
    """Runtime checks for organizations.py ValueError handlers."""

    @pytest.mark.asyncio
    async def test_switch_organization_value_error_is_generic(self):
        """ValueError in switch_organization → generic 400, error logged."""
        secret = "User finops@company.com is not a member of org uuid-abc-123 (table: org_memberships)"
        mock_service = Mock()
        mock_service.switch_organization = AsyncMock(side_effect=ValueError(secret))

        mock_context = Mock(user_id="user-1")
        mock_request = Mock()

        with patch('backend.api.organizations.organization_service', mock_service):
            with patch('backend.api.organizations.logger') as mock_log:
                from backend.api.organizations import switch_organization
                from uuid import uuid4
                with pytest.raises(HTTPException) as exc_info:
                    await switch_organization(uuid4(), mock_request, mock_context)

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Invalid request. Please check your input."
        assert "org_memberships" not in str(exc_info.value.detail)
        assert "finops@company.com" not in str(exc_info.value.detail)
        mock_log.error.assert_called_once()
        assert secret in str(mock_log.error.call_args)

    @pytest.mark.asyncio
    async def test_add_member_value_error_is_generic(self):
        """ValueError in add_organization_member → generic 400, error logged."""
        secret = "IntegrityError: duplicate key (email=admin@internal.corp) in users table"
        mock_service = Mock()
        mock_service.add_member = AsyncMock(side_effect=ValueError(secret))

        mock_context = Mock(organization_id="org-1", user_email="me@test.com")
        mock_request = Mock()

        with patch('backend.api.organizations.organization_service', mock_service):
            with patch('backend.api.organizations.logger') as mock_log:
                from backend.api.organizations import add_organization_member, AddMemberRequest
                payload = AddMemberRequest(email="admin@internal.corp")
                with pytest.raises(HTTPException) as exc_info:
                    await add_organization_member(payload, mock_request, mock_context)

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Invalid request. Please check your input."
        assert "admin@internal.corp" not in str(exc_info.value.detail)
        assert "users table" not in str(exc_info.value.detail)
        mock_log.error.assert_called_once()
        assert secret in str(mock_log.error.call_args)


# ---------------------------------------------------------------------------
# Runtime — phase3_enterprise.py
# ---------------------------------------------------------------------------


class TestPhase3EnterpriseExceptionSanitisation:
    """Runtime checks for phase3_enterprise.py bare Exception handlers.

    Each handler is decorated with @require_permission, which extracts
    ``request`` as a keyword argument and checks ``request.state.auth_user``.
    We must therefore:
      1. Pass ``request`` as a keyword argument.
      2. Attach a mock auth_user to ``request.state``.
      3. Patch ``backend.services.rbac_service.rbac_service`` so the decorator's
         permission check succeeds.
    """

    def _auth_request(self):
        """Return a mock Request with auth_user set for @require_permission."""
        req = Mock()
        req.state = Mock()
        req.state.auth_user = Mock(is_authenticated=True, email="test@test.com")
        return req

    def _rbac_permit(self):
        """Return a mock rbac_service that always permits, for the decorator."""
        rbac = Mock()
        rbac.get_user_by_email = AsyncMock(return_value={"id": "user-1"})
        rbac.check_permission = AsyncMock(return_value=True)
        return rbac

    @pytest.mark.asyncio
    async def test_create_scheduled_report_exception_is_generic(self):
        """Exception in create_scheduled_report → generic 400, error logged."""
        secret = "sqlalchemy.exc.OperationalError: (psycopg2.OperationalError) connection refused to 10.0.0.5"
        mock_srs = Mock()
        mock_srs.create_scheduled_report = AsyncMock(side_effect=Exception(secret))
        mock_audit = Mock()
        mock_audit.log_report_creation = AsyncMock()
        mock_user = {"id": "user-1", "email": "test@test.com"}

        with patch('backend.services.rbac_service.rbac_service', self._rbac_permit()):
            with patch('backend.api.phase3_enterprise.scheduled_report_service', mock_srs):
                with patch('backend.api.phase3_enterprise.audit_log_service', mock_audit):
                    with patch('backend.api.phase3_enterprise.logger') as mock_log:
                        from backend.api.phase3_enterprise import create_scheduled_report, ScheduledReportCreate
                        report = ScheduledReportCreate(
                            name="Test Report",
                            report_type="cost_breakdown",
                            query_params={},
                            frequency="DAILY",
                            format="CSV",
                            delivery_methods=["EMAIL"],
                            recipients={"emails": ["user@test.com"]},
                        )
                        with pytest.raises(HTTPException) as exc_info:
                            await create_scheduled_report(
                                report,
                                request=self._auth_request(),
                                current_user=mock_user,
                            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Invalid request. Please check your input."
        assert "10.0.0.5" not in str(exc_info.value.detail)
        assert "psycopg2" not in str(exc_info.value.detail)
        mock_log.error.assert_called_once()
        assert secret in str(mock_log.error.call_args)

    @pytest.mark.asyncio
    async def test_register_aws_account_exception_is_generic(self):
        """Exception in register_aws_account → generic 400, error logged."""
        secret = "boto3.exceptions.Botocore ClientError: arn:aws:iam::222222222222:role/secret-role"
        mock_mas = Mock()
        mock_mas.register_account = AsyncMock(side_effect=Exception(secret))
        mock_audit = Mock()
        mock_audit.log_action = AsyncMock()
        mock_user = {"id": "user-1", "email": "test@test.com"}

        with patch('backend.services.rbac_service.rbac_service', self._rbac_permit()):
            with patch('backend.api.phase3_enterprise.multi_account_service', mock_mas):
                with patch('backend.api.phase3_enterprise.audit_log_service', mock_audit):
                    with patch('backend.api.phase3_enterprise.logger') as mock_log:
                        from backend.api.phase3_enterprise import register_aws_account, AWSAccountCreate
                        account = AWSAccountCreate(
                            account_id="123456789012",
                            account_name="Test Account",
                            role_arn="arn:aws:iam::123456789012:role/test",
                        )
                        with pytest.raises(HTTPException) as exc_info:
                            await register_aws_account(
                                account,
                                request=self._auth_request(),
                                current_user=mock_user,
                            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Invalid request. Please check your input."
        assert "222222222222" not in str(exc_info.value.detail)
        assert "secret-role" not in str(exc_info.value.detail)
        mock_log.error.assert_called_once()
        assert secret in str(mock_log.error.call_args)

    @pytest.mark.asyncio
    async def test_grant_account_permission_exception_is_generic(self):
        """Exception in grant_account_permission → generic 400, error logged."""
        secret = "Foreign key constraint: account 999999999999 does not exist in accounts table"
        mock_mas = Mock()
        mock_mas.grant_account_access = AsyncMock(side_effect=Exception(secret))
        mock_audit = Mock()
        mock_audit.log_action = AsyncMock()
        mock_user = {"id": "user-1", "email": "test@test.com"}

        with patch('backend.services.rbac_service.rbac_service', self._rbac_permit()):
            with patch('backend.api.phase3_enterprise.multi_account_service', mock_mas):
                with patch('backend.api.phase3_enterprise.audit_log_service', mock_audit):
                    with patch('backend.api.phase3_enterprise.logger') as mock_log:
                        from backend.api.phase3_enterprise import grant_account_permission, AccountPermissionGrant
                        permission = AccountPermissionGrant(
                            account_id="999999999999",
                            user_email="target@test.com",
                            access_level="read",
                        )
                        with pytest.raises(HTTPException) as exc_info:
                            await grant_account_permission(
                                "999999999999",
                                permission,
                                request=self._auth_request(),
                                current_user=mock_user,
                            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Invalid request. Please check your input."
        assert "999999999999" not in str(exc_info.value.detail)
        assert "accounts table" not in str(exc_info.value.detail)
        mock_log.error.assert_called_once()
        assert secret in str(mock_log.error.call_args)

    @pytest.mark.asyncio
    async def test_create_role_exception_is_generic(self):
        """Exception in create_role → generic 400, error logged."""
        secret = "UniqueViolation: role 'secret_admin_role' already exists (constraint: roles_name_key)"
        # The decorator and the handler body both use rbac_service.
        # Decorator needs get_user_by_email + check_permission to succeed;
        # handler body needs create_role to raise.
        mock_rbac = Mock()
        mock_rbac.get_user_by_email = AsyncMock(return_value={"id": "user-1"})
        mock_rbac.check_permission = AsyncMock(return_value=True)
        mock_rbac.create_role = AsyncMock(side_effect=Exception(secret))
        mock_audit = Mock()
        mock_audit.log_action = AsyncMock()
        mock_user = {"id": "user-1", "email": "test@test.com"}

        with patch('backend.services.rbac_service.rbac_service', mock_rbac):
            with patch('backend.api.phase3_enterprise.rbac_service', mock_rbac):
                with patch('backend.api.phase3_enterprise.audit_log_service', mock_audit):
                    with patch('backend.api.phase3_enterprise.logger') as mock_log:
                        from backend.api.phase3_enterprise import create_role, RoleCreate
                        role = RoleCreate(
                            name="secret_admin_role",
                            permissions=["read"],
                        )
                        with pytest.raises(HTTPException) as exc_info:
                            await create_role(
                                role,
                                request=self._auth_request(),
                                current_user=mock_user,
                            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Invalid request. Please check your input."
        assert "secret_admin_role" not in str(exc_info.value.detail)
        assert "roles_name_key" not in str(exc_info.value.detail)
        mock_log.error.assert_called_once()
        assert secret in str(mock_log.error.call_args)

    @pytest.mark.asyncio
    async def test_assign_role_exception_is_generic(self):
        """Exception in assign_role → generic 400, error logged."""
        secret = "ForeignKeyError: user secret@internal.corp not found in users table at /data/db"
        # Decorator calls get_user_by_email("test@test.com") → success.
        # Handler body calls get_user_by_email("secret@internal.corp") → raise.
        mock_rbac = Mock()
        mock_rbac.check_permission = AsyncMock(return_value=True)

        async def _get_user(email):
            if email == "test@test.com":
                return {"id": "user-1"}
            raise Exception(secret)

        mock_rbac.get_user_by_email = AsyncMock(side_effect=_get_user)
        mock_audit = Mock()
        mock_audit.log_role_assignment = AsyncMock()
        mock_user = {"id": "user-1", "email": "test@test.com"}

        with patch('backend.services.rbac_service.rbac_service', mock_rbac):
            with patch('backend.api.phase3_enterprise.rbac_service', mock_rbac):
                with patch('backend.api.phase3_enterprise.audit_log_service', mock_audit):
                    with patch('backend.api.phase3_enterprise.logger') as mock_log:
                        from backend.api.phase3_enterprise import assign_role, RoleAssignment
                        assignment = RoleAssignment(
                            user_email="secret@internal.corp",
                            role_name="admin",
                        )
                        with pytest.raises(HTTPException) as exc_info:
                            await assign_role(
                                assignment,
                                request=self._auth_request(),
                                current_user=mock_user,
                            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Invalid request. Please check your input."
        assert "secret@internal.corp" not in str(exc_info.value.detail)
        assert "/data/db" not in str(exc_info.value.detail)
        mock_log.error.assert_called_once()
        assert secret in str(mock_log.error.call_args)


# ---------------------------------------------------------------------------
# Runtime — auth.py
# ---------------------------------------------------------------------------


class TestAuthExceptionSanitisation:
    """Runtime check for auth.py TokenInvalidError handler."""

    @pytest.mark.asyncio
    async def test_invalid_token_detail_is_generic(self):
        """TokenInvalidError in validate_token → 'Authentication failed', error logged."""
        from backend.utils.auth import TokenInvalidError
        secret = "Signature verification failed: expected HS256 with key at /secrets/jwt_key"

        mock_request = Mock()
        mock_request.headers = {"Authorization": "Bearer fake.token.here"}
        mock_authenticator = Mock()
        mock_authenticator.validate_access_token = Mock(side_effect=TokenInvalidError(secret))

        with patch('backend.api.auth.extract_token_from_header', return_value="fake.token.here"):
            with patch('backend.api.auth.get_authenticator', return_value=mock_authenticator):
                with patch('backend.api.auth.logger') as mock_log:
                    from backend.api.auth import validate_token
                    with pytest.raises(HTTPException) as exc_info:
                        await validate_token(mock_request)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Authentication failed"
        assert "/secrets/jwt_key" not in str(exc_info.value.detail)
        assert "Signature verification" not in str(exc_info.value.detail)
        mock_log.warning.assert_called_once()
        assert secret in str(mock_log.warning.call_args)
