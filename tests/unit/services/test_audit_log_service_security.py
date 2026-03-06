"""
Tests for Audit Log Service SQL Injection Fix (CRIT-3)

Verifies that get_recent_actions and get_failed_actions use parameterized
queries (make_interval) instead of vulnerable % string formatting.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.services.audit_log_service import AuditLogService


@pytest.fixture
def audit_service():
    """Create AuditLogService with mocked DatabaseService"""
    service = AuditLogService()
    service.db = MagicMock()
    service.db.fetch_all = AsyncMock(return_value=[])
    service.db.execute = AsyncMock()
    return service


class TestGetRecentActionsParameterized:
    """Verify get_recent_actions uses parameterized queries"""

    @pytest.mark.asyncio
    async def test_without_filter_uses_parameterized_interval(self, audit_service):
        """Query must use make_interval instead of string interpolation"""
        await audit_service.get_recent_actions(hours=24)

        audit_service.db.fetch_all.assert_called_once()
        query = audit_service.db.fetch_all.call_args[0][0]

        assert "make_interval(hours => $1)" in query
        assert "%" not in query
        assert "INTERVAL" not in query

    @pytest.mark.asyncio
    async def test_without_filter_passes_hours_as_parameter(self, audit_service):
        """hours value must be passed as a query parameter, not interpolated"""
        await audit_service.get_recent_actions(hours=48, limit=500)

        args = audit_service.db.fetch_all.call_args[0]
        # args: (query, hours, limit)
        assert args[1] == 48
        assert args[2] == 500

    @pytest.mark.asyncio
    async def test_with_filter_uses_parameterized_interval(self, audit_service):
        """Query with action_filter must also use make_interval"""
        await audit_service.get_recent_actions(hours=12, action_filter="login")

        query = audit_service.db.fetch_all.call_args[0][0]

        assert "make_interval(hours => $1)" in query
        assert "action = $2" in query
        assert "LIMIT $3" in query
        assert "%" not in query

    @pytest.mark.asyncio
    async def test_with_filter_passes_all_parameters(self, audit_service):
        """All parameters must be passed positionally with correct order"""
        await audit_service.get_recent_actions(
            hours=6, action_filter="query_executed", limit=200
        )

        args = audit_service.db.fetch_all.call_args[0]
        # args: (query, hours, action_filter, limit)
        assert args[1] == 6
        assert args[2] == "query_executed"
        assert args[3] == 200

    @pytest.mark.asyncio
    async def test_hours_cast_to_int(self, audit_service):
        """hours parameter must be cast to int to prevent type confusion"""
        await audit_service.get_recent_actions(hours="24")

        args = audit_service.db.fetch_all.call_args[0]
        assert args[1] == 24
        assert isinstance(args[1], int)

    @pytest.mark.asyncio
    async def test_hours_string_injection_blocked(self, audit_service):
        """String injection via hours parameter must raise ValueError"""
        with pytest.raises((ValueError, TypeError)):
            await audit_service.get_recent_actions(hours="1; DROP TABLE audit_logs;--")

    @pytest.mark.asyncio
    async def test_hours_float_cast_to_int(self, audit_service):
        """Float hours value must be safely cast to int"""
        await audit_service.get_recent_actions(hours=24.5)

        args = audit_service.db.fetch_all.call_args[0]
        assert args[1] == 24
        assert isinstance(args[1], int)


class TestGetFailedActionsParameterized:
    """Verify get_failed_actions uses parameterized queries"""

    @pytest.mark.asyncio
    async def test_uses_parameterized_interval(self, audit_service):
        """Query must use make_interval instead of string interpolation"""
        await audit_service.get_failed_actions(hours=24)

        query = audit_service.db.fetch_all.call_args[0][0]

        assert "make_interval(hours => $1)" in query
        assert "%" not in query
        assert "INTERVAL" not in query

    @pytest.mark.asyncio
    async def test_passes_hours_as_parameter(self, audit_service):
        """hours must be passed as query parameter"""
        await audit_service.get_failed_actions(hours=48, limit=50)

        args = audit_service.db.fetch_all.call_args[0]
        # args: (query, hours, limit)
        assert args[1] == 48
        assert args[2] == 50

    @pytest.mark.asyncio
    async def test_parameter_numbering_correct(self, audit_service):
        """Parameter numbering: $1=hours, $2=limit"""
        await audit_service.get_failed_actions(hours=24)

        query = audit_service.db.fetch_all.call_args[0][0]
        assert "$1" in query  # hours
        assert "$2" in query  # limit

    @pytest.mark.asyncio
    async def test_hours_cast_to_int(self, audit_service):
        """hours parameter must be cast to int"""
        await audit_service.get_failed_actions(hours="12")

        args = audit_service.db.fetch_all.call_args[0]
        assert args[1] == 12
        assert isinstance(args[1], int)

    @pytest.mark.asyncio
    async def test_hours_injection_blocked(self, audit_service):
        """SQL injection via hours must raise ValueError"""
        with pytest.raises((ValueError, TypeError)):
            await audit_service.get_failed_actions(hours="1' OR '1'='1")

    @pytest.mark.asyncio
    async def test_status_filter_still_present(self, audit_service):
        """Ensure the status IN filter is preserved after the fix"""
        await audit_service.get_failed_actions()

        query = audit_service.db.fetch_all.call_args[0][0]
        assert "status IN ('failure', 'denied')" in query


class TestNoStringInterpolationInQueries:
    """Verify no % string formatting remains in any query method"""

    @pytest.mark.asyncio
    async def test_get_recent_actions_no_percent_formatting(self, audit_service):
        """get_recent_actions must not use % formatting in SQL"""
        # Test both paths
        await audit_service.get_recent_actions(hours=24)
        query1 = audit_service.db.fetch_all.call_args[0][0]

        audit_service.db.fetch_all.reset_mock()
        await audit_service.get_recent_actions(hours=24, action_filter="test")
        query2 = audit_service.db.fetch_all.call_args[0][0]

        for query in [query1, query2]:
            # No Python string interpolation markers
            assert "%s" not in query
            assert "%d" not in query
            assert "% " not in query

    @pytest.mark.asyncio
    async def test_get_failed_actions_no_percent_formatting(self, audit_service):
        """get_failed_actions must not use % formatting in SQL"""
        await audit_service.get_failed_actions(hours=24)
        query = audit_service.db.fetch_all.call_args[0][0]

        assert "%s" not in query
        assert "%d" not in query
        assert "% " not in query
