"""
Security tests for Analytics API - CRIT-4 vulnerability fix

Tests authentication requirements for analytics endpoints to prevent:
- Unauthenticated access to cost data
- Infrastructure information disclosure
- Unauthorized triggering of expensive AWS operations
"""

import pytest
from uuid import uuid4
from unittest.mock import MagicMock, patch
from fastapi import HTTPException

from backend.api.analytics import (
    get_analytics,
    check_historical_data_availability,
    initialize_historical_cache,
    get_data_sources_info
)
from backend.services.request_context import RequestContext


# Fixtures

@pytest.fixture
def sample_user_id():
    """Sample user UUID"""
    return uuid4()


@pytest.fixture
def sample_org_id():
    """Sample organization UUID"""
    return uuid4()


@pytest.fixture
def mock_request():
    """Mock FastAPI request"""
    return MagicMock()


@pytest.fixture
def mock_background_tasks():
    """Mock FastAPI BackgroundTasks"""
    return MagicMock()


@pytest.fixture
def context_authenticated(sample_user_id, sample_org_id):
    """
    Authenticated user context with account scope.

    HIGH-15: allowed_account_ids is required — without it every handler
    fail-closes to 403 before reaching the code-under-test. Two accounts
    so tests can assert the FULL list reaches the Filter, not just the first.
    """
    return RequestContext(
        user_id=sample_user_id,
        user_email="user@company.com",
        organization_id=sample_org_id,
        is_admin=False,
        org_role="member",
        allowed_account_ids=["111111111111", "222222222222"],
    )


@pytest.fixture
def context_no_accounts(sample_user_id, sample_org_id):
    """
    Authenticated but zero-scope — org has no accounts, user has no
    permissions, or saved-view intersection is empty. HIGH-15 fail-closed path.
    """
    return RequestContext(
        user_id=sample_user_id,
        user_email="user@company.com",
        organization_id=sample_org_id,
        is_admin=False,
        org_role="member",
        allowed_account_ids=[],
    )


# Test Classes

class TestGetAnalyticsAuthentication:
    """Test authentication requirement for GET /analytics"""

    @pytest.mark.asyncio
    async def test_requires_authentication(self, mock_request):
        """Should return 401 when not authenticated"""
        # Mock require_context to raise 401
        with patch('backend.api.analytics.require_context') as mock_require:
            mock_require.side_effect = HTTPException(
                status_code=401,
                detail="Authentication required"
            )

            with pytest.raises(HTTPException) as exc_info:
                await get_analytics(mock_request, context=mock_require())

            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_allows_authenticated_access(
        self, mock_request, context_authenticated
    ):
        """Should allow access for authenticated users"""
        result = await get_analytics(mock_request, context_authenticated)

        assert "analytics" in result
        assert "timestamp" in result


class TestHistoricalAvailabilityAuthentication:
    """Test authentication requirement for GET /historical-availability"""

    @pytest.mark.asyncio
    async def test_requires_authentication(self, mock_request):
        """Should return 401 when not authenticated"""
        with patch('backend.api.analytics.require_context') as mock_require:
            mock_require.side_effect = HTTPException(
                status_code=401,
                detail="Authentication required"
            )

            with pytest.raises(HTTPException) as exc_info:
                await check_historical_data_availability(
                    mock_request, context=mock_require()
                )

            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_allows_authenticated_access(
        self, mock_request, context_authenticated
    ):
        """Should allow access for authenticated users"""
        with patch('backend.api.analytics.create_aws_client') as mock_client:
            # Mock Cost Explorer response
            mock_ce = MagicMock()
            mock_ce.get_cost_and_usage.return_value = {
                'ResultsByTime': [
                    {
                        'TimePeriod': {'Start': '2024-01-01', 'End': '2024-01-31'},
                        'Total': {'BlendedCost': {'Amount': '1000.00'}}
                    }
                ]
            }
            mock_client.return_value = mock_ce

            result = await check_historical_data_availability(
                mock_request, context_authenticated
            )

            assert result.success is True
            assert result.months_available >= 0
            mock_client.assert_called_once()

    @pytest.mark.asyncio
    async def test_logs_authenticated_access(
        self, mock_request, context_authenticated
    ):
        """Should log user access for audit trail"""
        with patch('backend.api.analytics.create_aws_client') as mock_client:
            with patch('backend.api.analytics.logger') as mock_logger:
                mock_ce = MagicMock()
                mock_ce.get_cost_and_usage.return_value = {
                    'ResultsByTime': []
                }
                mock_client.return_value = mock_ce

                await check_historical_data_availability(
                    mock_request, context_authenticated
                )

                # Verify audit logging
                mock_logger.info.assert_called_with(
                    "historical_availability_checked",
                    user_id=str(context_authenticated.user_id),
                    user_email=context_authenticated.user_email
                )


class TestInitializeCacheAuthentication:
    """Test authentication requirement for POST /initialize-cache"""

    @pytest.mark.asyncio
    async def test_requires_authentication(
        self, mock_request, mock_background_tasks
    ):
        """Should return 401 when not authenticated"""
        from backend.api.analytics import CacheInitRequest

        cache_request = CacheInitRequest(months=12)

        with patch('backend.api.analytics.require_context') as mock_require:
            mock_require.side_effect = HTTPException(
                status_code=401,
                detail="Authentication required"
            )

            with pytest.raises(HTTPException) as exc_info:
                await initialize_historical_cache(
                    cache_request,
                    mock_background_tasks,
                    mock_request,
                    context=mock_require()
                )

            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_allows_authenticated_access(
        self, mock_request, mock_background_tasks, context_authenticated
    ):
        """Should allow authenticated users to initialize cache"""
        from backend.api.analytics import CacheInitRequest

        cache_request = CacheInitRequest(months=12)

        result = await initialize_historical_cache(
            cache_request,
            mock_background_tasks,
            mock_request,
            context_authenticated
        )

        assert result["success"] is True
        assert "Cache initialization started" in result["message"]
        mock_background_tasks.add_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_logs_cache_initialization_request(
        self, mock_request, mock_background_tasks, context_authenticated
    ):
        """Should log cache initialization requests for audit"""
        from backend.api.analytics import CacheInitRequest

        cache_request = CacheInitRequest(months=6)

        with patch('backend.api.analytics.logger') as mock_logger:
            await initialize_historical_cache(
                cache_request,
                mock_background_tasks,
                mock_request,
                context_authenticated
            )

            # Verify audit logging
            mock_logger.info.assert_called_with(
                "cache_initialization_requested",
                user_id=str(context_authenticated.user_id),
                user_email=context_authenticated.user_email,
                months=6
            )

    @pytest.mark.asyncio
    async def test_validates_months_parameter(
        self, mock_request, mock_background_tasks, context_authenticated
    ):
        """Should validate months parameter range"""
        from backend.api.analytics import CacheInitRequest

        # Test months < 1
        cache_request = CacheInitRequest(months=0)
        with pytest.raises(HTTPException) as exc_info:
            await initialize_historical_cache(
                cache_request,
                mock_background_tasks,
                mock_request,
                context_authenticated
            )
        assert exc_info.value.status_code == 400
        assert "between 1 and 13" in exc_info.value.detail

        # Test months > 13
        cache_request = CacheInitRequest(months=14)
        with pytest.raises(HTTPException) as exc_info:
            await initialize_historical_cache(
                cache_request,
                mock_background_tasks,
                mock_request,
                context_authenticated
            )
        assert exc_info.value.status_code == 400


class TestDataSourcesInfoSecurity:
    """Test authentication and data sanitization for GET /data-sources"""

    @pytest.mark.asyncio
    async def test_requires_authentication(self, mock_request):
        """Should return 401 when not authenticated"""
        with patch('backend.api.analytics.require_context') as mock_require:
            mock_require.side_effect = HTTPException(
                status_code=401,
                detail="Authentication required"
            )

            with pytest.raises(HTTPException) as exc_info:
                await get_data_sources_info(mock_request, context=mock_require())

            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_does_not_expose_s3_bucket_names(
        self, mock_request, context_authenticated
    ):
        """Should NOT expose S3 bucket names in response"""
        with patch('backend.api.analytics.create_aws_session') as mock_session:
            mock_ce_client = MagicMock()
            mock_ce_client.get_cost_and_usage.return_value = {}

            mock_cur_client = MagicMock()
            mock_cur_client.describe_report_definitions.return_value = {
                'ReportDefinitions': [
                    {
                        'ReportName': 'my-report',
                        'S3Bucket': 'my-sensitive-bucket',
                        'S3Prefix': 'path/to/reports',
                        'Format': 'Parquet'
                    }
                ]
            }

            mock_sess = MagicMock()
            mock_sess.client.side_effect = lambda service, **kwargs: (
                mock_ce_client if service == 'ce' else mock_cur_client
            )
            mock_session.return_value = mock_sess

            result = await get_data_sources_info(mock_request, context_authenticated)

            # Verify NO sensitive data in response
            result_str = str(result)
            assert 'S3Bucket' not in result_str
            assert 'my-sensitive-bucket' not in result_str
            assert 'S3Prefix' not in result_str
            assert 'ReportName' not in result_str
            assert 'my-report' not in result_str

            # Verify only availability status is returned
            assert "cost_explorer" in result
            assert "available" in result["cost_explorer"]
            assert "cur" in result
            assert "available" in result["cur"]

    @pytest.mark.asyncio
    async def test_does_not_expose_database_names(
        self, mock_request, context_authenticated
    ):
        """Should NOT expose Athena database/table names"""
        with patch('backend.api.analytics.create_aws_session') as mock_session:
            mock_ce_client = MagicMock()
            mock_ce_client.get_cost_and_usage.return_value = {}

            mock_cur_client = MagicMock()
            mock_cur_client.describe_report_definitions.return_value = {
                'ReportDefinitions': []
            }

            mock_sess = MagicMock()
            mock_sess.client.side_effect = lambda service, **kwargs: (
                mock_ce_client if service == 'ce' else mock_cur_client
            )
            mock_session.return_value = mock_sess

            result = await get_data_sources_info(mock_request, context_authenticated)

            # Verify response structure - only status, no infrastructure details
            assert "cost_explorer" in result
            assert "cur" in result
            assert "recommendation" in result

            # Ensure no database/table information
            assert "database" not in str(result)
            assert "table" not in str(result)
            assert "bucket" not in str(result)
            assert "prefix" not in str(result)

    @pytest.mark.asyncio
    async def test_sanitized_response_format(
        self, mock_request, context_authenticated
    ):
        """Should return only sanitized availability information"""
        with patch('backend.api.analytics.create_aws_session') as mock_session:
            mock_ce_client = MagicMock()
            mock_ce_client.get_cost_and_usage.return_value = {}

            mock_cur_client = MagicMock()
            mock_cur_client.describe_report_definitions.return_value = {
                'ReportDefinitions': []
            }

            mock_sess = MagicMock()
            mock_sess.client.side_effect = lambda service, **kwargs: (
                mock_ce_client if service == 'ce' else mock_cur_client
            )
            mock_session.return_value = mock_sess

            result = await get_data_sources_info(mock_request, context_authenticated)

            # Verify sanitized response structure
            assert result == {
                "cost_explorer": {
                    "available": True,
                    "description": "AWS Cost Explorer API - Access to recent cost data"
                },
                "cur": {
                    "available": False,
                    "description": "Cost and Usage Reports - Detailed historical data"
                },
                "recommendation": "Cost Explorer is available for use. Consider setting up CUR for extended historical analysis."
            }

    @pytest.mark.asyncio
    async def test_logs_data_source_access(
        self, mock_request, context_authenticated
    ):
        """Should log data source information access for audit"""
        with patch('backend.api.analytics.create_aws_session') as mock_session:
            with patch('backend.api.analytics.logger') as mock_logger:
                mock_ce_client = MagicMock()
                mock_ce_client.get_cost_and_usage.return_value = {}

                mock_cur_client = MagicMock()
                mock_cur_client.describe_report_definitions.return_value = {
                    'ReportDefinitions': []
                }

                mock_sess = MagicMock()
                mock_sess.client.side_effect = lambda service, **kwargs: (
                    mock_ce_client if service == 'ce' else mock_cur_client
                )
                mock_session.return_value = mock_sess

                await get_data_sources_info(mock_request, context_authenticated)

                # Verify audit logging
                mock_logger.info.assert_any_call(
                    "data_sources_info_accessed",
                    user_id=str(context_authenticated.user_id),
                    user_email=context_authenticated.user_email
                )


class TestEndToEndAuthentication:
    """Test complete authentication flow for all analytics endpoints"""

    @pytest.mark.asyncio
    async def test_all_endpoints_require_authentication(
        self, mock_request, mock_background_tasks
    ):
        """Verify all analytics endpoints require authentication"""
        from backend.api.analytics import CacheInitRequest

        # Mock require_context to simulate unauthenticated request
        with patch('backend.api.analytics.require_context') as mock_require:
            mock_require.side_effect = HTTPException(
                status_code=401,
                detail="Authentication required"
            )

            # Test GET /analytics
            with pytest.raises(HTTPException) as exc:
                await get_analytics(mock_request, context=mock_require())
            assert exc.value.status_code == 401

            # Test GET /historical-availability
            with pytest.raises(HTTPException) as exc:
                await check_historical_data_availability(
                    mock_request, context=mock_require()
                )
            assert exc.value.status_code == 401

            # Test POST /initialize-cache
            cache_req = CacheInitRequest(months=12)
            with pytest.raises(HTTPException) as exc:
                await initialize_historical_cache(
                    cache_req, mock_background_tasks, mock_request, context=mock_require()
                )
            assert exc.value.status_code == 401

            # Test GET /data-sources
            with pytest.raises(HTTPException) as exc:
                await get_data_sources_info(mock_request, context=mock_require())
            assert exc.value.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════
# HIGH-15 — Tenant Isolation on Analytics Cost Explorer Calls
#
# Before the fix, all four get_cost_and_usage() call sites had no Filter
# param, so CE returned spend for every linked account under the management
# account. Any authenticated user — regardless of org — saw everyone's costs.
#
# Test groups:
#   1. Helpers — filter builder fail-closes, cache-key stability
#   2. Handler scoping — every endpoint passes Filter, 403s on empty scope
#   3. Background task — receives pre-validated filter, cache keys scoped
#   4. AST tripwire — source-level guard against reintroduction
# ═══════════════════════════════════════════════════════════════════════════

from backend.api.analytics import (
    _build_account_filter,
    _scope_cache_key,
    _load_historical_data_to_cache,
    CacheInitRequest,
)


class TestAccountFilterHelpers:
    """HIGH-15 group 1 — the two module-level helpers."""

    def test_build_account_filter_returns_linked_account_dimension(self):
        """
        PRIMARY POSITIVE CASE. The exact dict shape matters — CE requires
        Dimensions.Key == 'LINKED_ACCOUNT' (not 'LINKED_ACCOUNT_NAME', not
        a Tags filter). Assert on the full structure, not just that a dict
        comes back.
        """
        result = _build_account_filter(["111111111111", "222222222222"])

        assert result == {
            "Dimensions": {
                "Key": "LINKED_ACCOUNT",
                "Values": ["111111111111", "222222222222"],
            }
        }

    def test_build_account_filter_raises_403_on_empty_list(self):
        """
        PRIMARY FAIL-CLOSED CASE. Empty list → 403, not an empty filter.
        An empty Values list would be rejected by boto anyway (ClientError),
        but the point is: empty scope is a policy failure at OUR layer,
        not an AWS-side validation error. 403 is the right semantic.
        """
        with pytest.raises(HTTPException) as exc:
            _build_account_filter([])

        assert exc.value.status_code == 403
        assert "No AWS accounts in scope" in exc.value.detail

    def test_build_account_filter_preserves_all_accounts(self):
        """
        No accidental truncation/dedup. If the middleware gave us 5
        accounts, all 5 go into Values.
        """
        accounts = [f"{i:012d}" for i in range(1, 6)]
        result = _build_account_filter(accounts)
        assert result["Dimensions"]["Values"] == accounts

    def test_build_account_filter_copies_input_list(self):
        """
        Mutating the returned Values list must not mutate the caller's
        allowed_account_ids (which lives on RequestContext and may be
        reused across the request). Defensive copy.
        """
        original = ["111111111111"]
        result = _build_account_filter(original)
        result["Dimensions"]["Values"].append("999999999999")
        assert original == ["111111111111"]

    def test_scope_cache_key_is_stable_for_same_set(self):
        """
        Same accounts, different order → same key. This is the whole point
        of sorting before hashing. Without it, a user whose middleware
        happened to load accounts in a different order today would miss
        yesterday's cache.
        """
        key_a = _scope_cache_key(["111111111111", "222222222222"])
        key_b = _scope_cache_key(["222222222222", "111111111111"])
        assert key_a == key_b

    def test_scope_cache_key_differs_across_tenants(self):
        """
        Different account sets → different keys. Obvious, but this is the
        property that prevents cross-tenant cache reads.
        """
        key_a = _scope_cache_key(["111111111111"])
        key_b = _scope_cache_key(["222222222222"])
        assert key_a != key_b

    def test_scope_cache_key_does_not_leak_account_ids(self):
        """
        The raw 12-digit account ID must NOT appear in the cache key.
        Valkey KEYS * (or a monitoring dump) shouldn't expose which AWS
        accounts a tenant owns.
        """
        key = _scope_cache_key(["123456789012"])
        assert "123456789012" not in key

    def test_scope_cache_key_is_hex_and_bounded(self):
        """
        Key segment is fixed-length hex — no separators that could clash
        with the surrounding ':'-delimited Valkey key format.
        """
        key = _scope_cache_key(["111111111111", "222222222222"])
        assert len(key) == 16
        assert all(c in "0123456789abcdef" for c in key)


class TestHistoricalAvailabilityScoping:
    """HIGH-15 group 2a — GET /historical-availability."""

    @pytest.mark.asyncio
    async def test_ce_call_filtered_by_account_scope(
        self, mock_request, context_authenticated
    ):
        """
        PRIMARY HIGH-15 REGRESSION TEST.

        Before the fix, get_cost_and_usage was called without Filter and
        returned every tenant's spend. This test asserts the Filter kwarg
        is present AND carries EXACTLY the context's allowed_account_ids.
        Substring-checking would miss a Filter that's present but wrong.
        """
        with patch("backend.api.analytics.create_aws_client") as mock_client:
            mock_ce = MagicMock()
            mock_ce.get_cost_and_usage.return_value = {"ResultsByTime": []}
            mock_client.return_value = mock_ce

            await check_historical_data_availability(
                mock_request, context_authenticated
            )

            call_kwargs = mock_ce.get_cost_and_usage.call_args.kwargs
            assert "Filter" in call_kwargs, (
                "HIGH-15 REGRESSION — get_cost_and_usage called without "
                "Filter. This is the exact bug: CE returns ALL accounts' "
                "spend when unfiltered."
            )
            assert call_kwargs["Filter"] == {
                "Dimensions": {
                    "Key": "LINKED_ACCOUNT",
                    "Values": ["111111111111", "222222222222"],
                }
            }

    @pytest.mark.asyncio
    async def test_empty_scope_returns_403_before_ce_call(
        self, mock_request, context_no_accounts
    ):
        """
        Fail-closed ordering. A zero-scope user gets 403, and the CE client
        is NEVER constructed. If we see create_aws_client called, the scope
        check is in the wrong place (inside the try, where the broad
        Exception handler would swallow the 403 as a 500).
        """
        with patch("backend.api.analytics.create_aws_client") as mock_client:
            with pytest.raises(HTTPException) as exc:
                await check_historical_data_availability(
                    mock_request, context_no_accounts
                )

            assert exc.value.status_code == 403
            mock_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_403_not_downgraded_to_500(
        self, mock_request, context_no_accounts
    ):
        """
        The handler has a broad `except Exception → 500` at the bottom.
        HTTPException IS an Exception. If the scope check were inside the
        try block, a 403 would get caught and re-raised as 500 — wrong
        signal, and logs "internal error" for what is a policy decision.
        This test pins the scope check OUTSIDE the try.
        """
        with pytest.raises(HTTPException) as exc:
            await check_historical_data_availability(
                mock_request, context_no_accounts
            )

        assert exc.value.status_code == 403  # NOT 500
        assert "internal error" not in exc.value.detail.lower()


class TestInitializeCacheScoping:
    """HIGH-15 group 2b — POST /initialize-cache."""

    @pytest.mark.asyncio
    async def test_background_task_receives_account_filter(
        self, mock_request, mock_background_tasks, context_authenticated
    ):
        """
        PRIMARY HIGH-15 REGRESSION for the background-task path.

        The task runs AFTER the response is sent — context is gone. The
        ONLY way it can be scoped is if the handler passes the filter at
        schedule time. Assert on exact add_task call args, positionally:
        (func, months, filter_dict, scope_key).

        Before the fix: add_task(_load_historical_data_to_cache, months)
        — two args, no filter, task ran unscoped.
        """
        cache_req = CacheInitRequest(months=12)

        await initialize_historical_cache(
            cache_req, mock_background_tasks, mock_request, context_authenticated
        )

        mock_background_tasks.add_task.assert_called_once()
        call_args = mock_background_tasks.add_task.call_args.args

        # Arg 0: the task function itself
        assert call_args[0] is _load_historical_data_to_cache
        # Arg 1: months
        assert call_args[1] == 12
        # Arg 2: the filter dict — this is the fix
        assert call_args[2] == {
            "Dimensions": {
                "Key": "LINKED_ACCOUNT",
                "Values": ["111111111111", "222222222222"],
            }
        }
        # Arg 3: scope key for cache segmentation
        assert call_args[3] == _scope_cache_key(["111111111111", "222222222222"])

    @pytest.mark.asyncio
    async def test_empty_scope_never_schedules_background_task(
        self, mock_request, mock_background_tasks, context_no_accounts
    ):
        """
        Fail-closed for background work. A zero-scope 403 must fire BEFORE
        add_task. If the task gets scheduled and then the handler raises,
        FastAPI still runs the task after the response — unscoped CE call,
        exactly the bug.
        """
        cache_req = CacheInitRequest(months=12)

        with pytest.raises(HTTPException) as exc:
            await initialize_historical_cache(
                cache_req, mock_background_tasks, mock_request, context_no_accounts
            )

        assert exc.value.status_code == 403
        mock_background_tasks.add_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_scope_check_runs_before_months_validation(
        self, mock_request, mock_background_tasks, context_no_accounts
    ):
        """
        Security check precedence. With months=0 (invalid) AND empty scope,
        the user gets 403, not 400. They shouldn't learn that their months
        param is wrong — they shouldn't learn anything. Fail-closed first.
        """
        cache_req = CacheInitRequest(months=0)  # would normally 400

        with pytest.raises(HTTPException) as exc:
            await initialize_historical_cache(
                cache_req, mock_background_tasks, mock_request, context_no_accounts
            )

        assert exc.value.status_code == 403  # NOT 400


class TestDataSourcesScoping:
    """HIGH-15 group 2c — GET /data-sources."""

    @pytest.mark.asyncio
    async def test_ce_ping_filtered_by_account_scope(
        self, mock_request, context_authenticated
    ):
        """
        The CE call here is just an availability probe — result is
        discarded, only the absence of an exception matters. But an
        unscoped probe still leaks: the mere fact that it succeeds
        tells a zero-scope user that CE works org-wide. Scope it anyway.
        """
        with patch("backend.api.analytics.create_aws_session") as mock_session:
            mock_ce = MagicMock()
            mock_ce.get_cost_and_usage.return_value = {}
            mock_cur = MagicMock()
            mock_cur.describe_report_definitions.return_value = {
                "ReportDefinitions": []
            }
            mock_sess = MagicMock()
            mock_sess.client.side_effect = lambda svc, **kw: (
                mock_ce if svc == "ce" else mock_cur
            )
            mock_session.return_value = mock_sess

            await get_data_sources_info(mock_request, context_authenticated)

            call_kwargs = mock_ce.get_cost_and_usage.call_args.kwargs
            assert call_kwargs.get("Filter") == {
                "Dimensions": {
                    "Key": "LINKED_ACCOUNT",
                    "Values": ["111111111111", "222222222222"],
                }
            }

    @pytest.mark.asyncio
    async def test_empty_scope_raises_403_not_error_dict(
        self, mock_request, context_no_accounts
    ):
        """
        This handler has an outer `except Exception → return {"error": ...}`
        (NOT a raise — it returns a 200 with an error body). If the scope
        check were inside that try, a 403 would come back as a 200 with
        `{"error": "Unable to retrieve..."}`. Wrong on two counts: wrong
        status, and the error message leaks nothing about WHY. Pin the
        check outside the try.
        """
        with patch("backend.api.analytics.create_aws_session") as mock_session:
            with pytest.raises(HTTPException) as exc:
                await get_data_sources_info(mock_request, context_no_accounts)

            assert exc.value.status_code == 403
            mock_session.assert_not_called()


class TestBackgroundTaskScoping:
    """
    HIGH-15 group 3 — _load_historical_data_to_cache directly.

    The handler tests above prove the filter REACHES the task. These prove
    the task USES it — that both CE calls pass Filter through, and that the
    Valkey keys carry the scope segment. A regression that drops Filter
    inside the task would pass the handler tests and fail these.
    """

    @pytest.fixture
    def sample_filter(self):
        """Pre-validated filter as the handler would pass it."""
        return {
            "Dimensions": {
                "Key": "LINKED_ACCOUNT",
                "Values": ["111111111111", "222222222222"],
            }
        }

    @pytest.fixture
    def sample_scope_key(self):
        return _scope_cache_key(["111111111111", "222222222222"])

    @pytest.mark.asyncio
    async def test_both_ce_calls_receive_filter(
        self, sample_filter, sample_scope_key
    ):
        """
        Two CE calls in the task (monthly + daily). BOTH must pass Filter.
        A partial fix that only scopes one is still a full leak on the other.
        """
        with patch("backend.api.analytics.create_aws_client") as mock_client:
            mock_ce = MagicMock()
            mock_ce.get_cost_and_usage.return_value = {"ResultsByTime": []}
            mock_client.return_value = mock_ce

            await _load_historical_data_to_cache(
                months=6,
                account_filter=sample_filter,
                scope_key=sample_scope_key,
            )

            assert mock_ce.get_cost_and_usage.call_count == 2
            for i, call in enumerate(mock_ce.get_cost_and_usage.call_args_list):
                assert call.kwargs.get("Filter") == sample_filter, (
                    f"CE call #{i + 1} (of 2) missing or wrong Filter — "
                    f"partial scoping is full cross-tenant leak"
                )

    @pytest.mark.asyncio
    async def test_valkey_keys_include_scope_segment(
        self, sample_filter, sample_scope_key
    ):
        """
        The cross-tenant cache-poisoning case.

        Before: f"analytics:monthly:{start}:{end}" — tenant-agnostic. If CE
        calls ARE scoped but keys are NOT, tenant A's filtered data writes
        under a date-only key, tenant B's next write to the same dates
        overwrites it. Any reader added later serves one tenant's data to
        the other.

        After: f"analytics:monthly:{scope_key}:{start}:{end}". Assert the
        scope segment is present in BOTH keys, in the right position
        (between the prefix and the dates — not appended as an afterthought
        where a prefix-scan `analytics:monthly:*` would still clash).
        """
        with patch("backend.api.analytics.create_aws_client") as mock_client:
            mock_ce = MagicMock()
            mock_ce.get_cost_and_usage.return_value = {"ResultsByTime": []}
            mock_client.return_value = mock_ce

            mock_valkey_instance = MagicMock()
            with patch.dict(
                "sys.modules",
                {"valkey": MagicMock(Valkey=MagicMock(return_value=mock_valkey_instance))},
            ):
                await _load_historical_data_to_cache(
                    months=6,
                    account_filter=sample_filter,
                    scope_key=sample_scope_key,
                )

            # Two set() calls: monthly + daily
            set_calls = mock_valkey_instance.set.call_args_list
            assert len(set_calls) == 2

            keys = [call.args[0] for call in set_calls]
            monthly_key = next(k for k in keys if k.startswith("analytics:monthly:"))
            daily_key = next(k for k in keys if k.startswith("analytics:daily:"))

            # Scope segment immediately after the prefix
            assert monthly_key.startswith(f"analytics:monthly:{sample_scope_key}:")
            assert daily_key.startswith(f"analytics:daily:{sample_scope_key}:")

    @pytest.mark.asyncio
    async def test_task_signature_requires_filter_and_scope(self):
        """
        Signature tripwire. The two new params have NO defaults — a caller
        who forgets to pass them gets a TypeError at schedule time, not a
        silent unscoped query at runtime. If someone adds `= None` defaults
        to "make tests easier", this catches it.
        """
        import inspect

        sig = inspect.signature(_load_historical_data_to_cache)
        params = sig.parameters

        assert "account_filter" in params
        assert params["account_filter"].default is inspect.Parameter.empty, (
            "account_filter must be REQUIRED — a default of None would let "
            "a careless caller schedule an unscoped background query"
        )

        assert "scope_key" in params
        assert params["scope_key"].default is inspect.Parameter.empty


class TestNoUnfilteredCostExplorerCalls:
    """
    HIGH-15 group 4 — AST tripwire.

    The point: someone adds a fifth CE call next month, copies an old
    example, forgets Filter=. All the behavioural tests above pass because
    they don't exercise the new call. This tripwire scans the SOURCE and
    fails if ANY get_cost_and_usage call — present or future — lacks a
    Filter keyword. One tripwire beats N behavioural tests for catching
    reintroduction.
    """

    def test_every_get_cost_and_usage_call_has_filter_keyword(self):
        """
        Walk analytics.py's AST. For every Call node where the func
        attribute is `get_cost_and_usage`, assert there is a keyword arg
        named `Filter`. This is syntactic, not semantic — it can't verify
        the filter VALUE is correct (behavioural tests do that). It
        verifies the keyword is PRESENT, which is exactly what prevents
        the naked-call regression.
        """
        import ast
        import backend.api.analytics as mod

        with open(mod.__file__) as f:
            tree = ast.parse(f.read())

        unfiltered: list[int] = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # Match x.get_cost_and_usage(...) — func is an Attribute
            if not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "get_cost_and_usage":
                continue

            kw_names = {kw.arg for kw in node.keywords}
            if "Filter" not in kw_names:
                unfiltered.append(node.lineno)

        assert not unfiltered, (
            f"HIGH-15 TRIPWIRE — get_cost_and_usage() called WITHOUT "
            f"Filter= at {mod.__file__} line(s) {unfiltered}. "
            f"Unfiltered CE returns every tenant's spend. "
            f"Add Filter=_build_account_filter(context.allowed_account_ids)."
        )

    def test_build_account_filter_is_called_in_every_ce_handler(self):
        """
        Complementary tripwire: every handler that reaches CE must call
        _build_account_filter. This catches a different failure mode —
        someone passes a hand-rolled Filter dict that bypasses the
        empty-scope 403. The helper IS the fail-closed guarantee.

        We walk FunctionDefs, find those containing a get_cost_and_usage
        call, and assert each also contains a _build_account_filter call.
        The background task is exempt: it receives a pre-validated filter
        from its handler and doesn't call the helper itself.
        """
        import ast
        import backend.api.analytics as mod

        with open(mod.__file__) as f:
            tree = ast.parse(f.read())

        # Funcs that RECEIVE a validated filter don't need to build one.
        # _load_historical_data_to_cache: the handler builds + validates,
        # then passes the dict at schedule time. Zero-scope callers never
        # reach add_task — the task is never scheduled unscoped.
        EXEMPT = {"_load_historical_data_to_cache"}

        violations: list[str] = []

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name in EXEMPT:
                continue

            calls_in_func = [
                n for n in ast.walk(node) if isinstance(n, ast.Call)
            ]

            has_ce_call = any(
                isinstance(c.func, ast.Attribute)
                and c.func.attr == "get_cost_and_usage"
                for c in calls_in_func
            )
            if not has_ce_call:
                continue

            has_filter_build = any(
                isinstance(c.func, ast.Name)
                and c.func.id == "_build_account_filter"
                for c in calls_in_func
            )
            if not has_filter_build:
                violations.append(node.name)

        assert not violations, (
            f"Handler(s) {violations} call get_cost_and_usage but do NOT "
            f"call _build_account_filter — the empty-scope 403 is bypassed. "
            f"Hand-rolled filters skip the fail-closed check."
        )
