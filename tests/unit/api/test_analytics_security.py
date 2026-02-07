"""
Security tests for Analytics API - CRIT-4 vulnerability fix

Tests authentication requirements for analytics endpoints to prevent:
- Unauthenticated access to cost data
- Infrastructure information disclosure
- Unauthorized triggering of expensive AWS operations
"""

import pytest
from uuid import UUID, uuid4
from unittest.mock import AsyncMock, MagicMock, patch
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
    """Authenticated user context"""
    return RequestContext(
        user_id=sample_user_id,
        user_email="user@company.com",
        organization_id=sample_org_id,
        is_admin=False,
        org_role="member",
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
