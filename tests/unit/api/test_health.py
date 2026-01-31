"""
Tests for HIGH-2: Health Endpoint Information Disclosure

Verifies:
1. Public probes (/health, /liveness, /readiness) expose no infrastructure
   details, service topology, or raw exception strings.
2. /health/detailed is not whitelisted as a public path — the auth middleware
   will require a valid JWT before the handler runs.
3. Every _check_* helper logs the real error via structlog and returns only
   a generic status message — never bucket names, DB names, S3 paths, or
   raw exception text.
"""

import inspect
import json

import pytest
from unittest.mock import AsyncMock, Mock, patch

from backend.api.health import (
    health_check,
    liveness_probe,
    readiness_probe,
    detailed_health,
    _check_database,
    _check_valkey,
    _check_vector_store,
    _check_llm_services,
    _check_aws_services,
)


# ---------------------------------------------------------------------------
# Public probes — must never expose infrastructure details
# ---------------------------------------------------------------------------


class TestPublicProbes:
    """Every public probe must return the minimum possible payload."""

    @pytest.mark.asyncio
    async def test_health_returns_status_only(self):
        result = await health_check()
        assert result == {"status": "healthy"}

    @pytest.mark.asyncio
    async def test_health_has_no_service_details(self):
        result = await health_check()
        for forbidden in ("services", "version", "uptime", "database",
                          "valkey", "aws", "error", "timestamp"):
            assert forbidden not in result

    @pytest.mark.asyncio
    async def test_liveness_keys(self):
        result = await liveness_probe()
        assert set(result.keys()) == {"status", "timestamp"}
        assert result["status"] == "alive"

    @pytest.mark.asyncio
    async def test_readiness_keys(self):
        result = await readiness_probe()
        assert set(result.keys()) == {"status", "timestamp"}
        assert result["status"] == "ready"

    @pytest.mark.asyncio
    async def test_readiness_exposes_no_topology(self):
        result = await readiness_probe()
        assert "database_available" not in result
        assert "vector_store_available" not in result
        assert "reason" not in result

    def test_readiness_source_has_no_exception_leak(self):
        """The handler must be a simple return — no except block can leak."""
        source = inspect.getsource(readiness_probe)
        assert "str(e)" not in source
        assert "except" not in source


# ---------------------------------------------------------------------------
# Authentication gate for /health/detailed
# ---------------------------------------------------------------------------


class TestDetailedHealthGate:
    def test_detailed_path_not_in_public_paths(self):
        from backend.middleware.authentication import AuthenticationMiddleware
        assert "/health/detailed" not in AuthenticationMiddleware.PUBLIC_PATHS

    def test_detailed_health_has_user_dependency(self):
        """The handler signature must include a 'user' parameter (from Depends)."""
        sig = inspect.signature(detailed_health)
        assert "user" in sig.parameters


# ---------------------------------------------------------------------------
# _check_database sanitisation
# ---------------------------------------------------------------------------


class TestDatabaseCheckSanitisation:
    @pytest.mark.asyncio
    async def test_error_response_is_generic(self):
        secret = "Connection refused to 10.0.0.5:5432 db=finops_prod"
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(side_effect=Exception(secret))
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        db = Mock()
        db.engine.begin = Mock(return_value=mock_cm)

        with patch('backend.api.health.logger') as mock_log:
            result = await _check_database(db)

        assert result["status"] == "unhealthy"
        assert result["error"] == "database unavailable"
        assert secret not in json.dumps(result)
        mock_log.error.assert_called_once()
        assert secret in str(mock_log.error.call_args)

    @pytest.mark.asyncio
    async def test_none_service_returns_unavailable(self):
        result = await _check_database(None)
        assert result["status"] == "unavailable"


# ---------------------------------------------------------------------------
# _check_valkey sanitisation
# ---------------------------------------------------------------------------


class TestValkeyCheckSanitisation:
    @pytest.mark.asyncio
    async def test_error_response_is_generic(self):
        secret = "Could not connect to valkey at 172.16.0.10:6379"
        mock_valkey_mod = Mock()
        mock_valkey_mod.Valkey = Mock(side_effect=Exception(secret))

        with patch.dict('sys.modules', {
            'valkey': mock_valkey_mod,
            'config': Mock(),
            'config.settings': Mock(get_settings=Mock(return_value=Mock(
                valkey_host='localhost', valkey_port=6379, valkey_db=0,
            ))),
        }):
            with patch('backend.api.health.logger') as mock_log:
                result = await _check_valkey()

        assert result["status"] == "unhealthy"
        assert result["error"] == "cache service unavailable"
        assert "172.16.0.10" not in json.dumps(result)
        assert "Could not connect" not in json.dumps(result)
        mock_log.error.assert_called_once()


# ---------------------------------------------------------------------------
# _check_vector_store sanitisation
# ---------------------------------------------------------------------------


class TestVectorStoreCheckSanitisation:
    @pytest.mark.asyncio
    async def test_error_response_is_generic(self):
        secret = "ChromaDB collection 'finops_vectors' not found at /data/chroma"
        vs = Mock()
        vs.collection.count = Mock(side_effect=Exception(secret))

        with patch('backend.api.health.logger') as mock_log:
            result = await _check_vector_store(vs)

        assert result["status"] == "unhealthy"
        assert result["error"] == "vector store unavailable"
        assert "finops_vectors" not in json.dumps(result)
        assert "/data/chroma" not in json.dumps(result)
        mock_log.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_none_service_returns_unavailable(self):
        result = await _check_vector_store(None)
        assert result["status"] == "unavailable"


# ---------------------------------------------------------------------------
# _check_llm_services sanitisation
# ---------------------------------------------------------------------------


class TestLLMCheckSanitisation:
    @pytest.mark.asyncio
    async def test_error_response_is_generic(self):
        secret = "ThrottlingException on anthropic.claude-3-sonnet arn:aws:bedrock:us-east-1:123456789012"
        mock_client = Mock()
        mock_client.invoke_model = Mock(side_effect=Exception(secret))

        with patch('backend.utils.aws_session.create_aws_client', return_value=mock_client):
            with patch.dict('sys.modules', {
                'config': Mock(),
                'config.settings': Mock(get_settings=Mock(return_value=Mock(
                    aws_region='us-east-1',
                    bedrock_model_id='anthropic.claude-3-sonnet',
                ))),
            }):
                with patch('backend.api.health.logger') as mock_log:
                    result = await _check_llm_services()

        assert result["status"] == "unhealthy"
        assert result["error"] == "LLM service unavailable"
        resp = json.dumps(result)
        assert "123456789012" not in resp
        assert "anthropic" not in resp
        assert "ThrottlingException" not in resp
        mock_log.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_success_excludes_model_id_and_quota(self):
        mock_response = {
            "ResponseMetadata": {"HTTPStatusCode": 200},
            "ConsumedQuota": {"InputTokens": 5},
        }
        mock_client = Mock()
        mock_client.invoke_model = Mock(return_value=mock_response)

        with patch('backend.utils.aws_session.create_aws_client', return_value=mock_client):
            with patch.dict('sys.modules', {
                'config': Mock(),
                'config.settings': Mock(get_settings=Mock(return_value=Mock(
                    aws_region='us-west-2',
                    bedrock_model_id='anthropic.claude-secret-model',
                ))),
            }):
                result = await _check_llm_services()

        assert result["status"] == "healthy"
        resp = json.dumps(result)
        assert "claude-secret-model" not in resp
        assert "model_id" not in result.get("details", {})
        assert "quota" not in result.get("details", {})
        assert "ConsumedQuota" not in resp


# ---------------------------------------------------------------------------
# _check_aws_services sanitisation
# ---------------------------------------------------------------------------


def _mock_settings():
    return Mock(
        cur_s3_bucket='s3://secret-finops-bucket/path',
        cur_s3_prefix='cur/secret-prefix',
        aws_cur_database='secret_finops_db',
        aws_cur_table='secret_cur_table',
        athena_output_location='s3://secret-bucket/athena-output/',
        athena_workgroup='secret-workgroup',
    )


def _patch_settings():
    return patch.dict('sys.modules', {
        'config': Mock(),
        'config.settings': Mock(get_settings=Mock(return_value=_mock_settings())),
    })


def _healthy_aws_mocks():
    """Return (session_mock, athena, s3, ce) all returning success."""
    mock_athena = Mock()
    mock_athena.list_work_groups = Mock(return_value={})
    mock_athena.get_database = Mock(return_value={})
    mock_athena.start_query_execution = Mock(return_value={"QueryExecutionId": "qid"})
    mock_athena.get_query_execution = Mock(return_value={
        "QueryExecution": {"Status": {"State": "SUCCEEDED"}}
    })

    mock_s3 = Mock()
    mock_s3.head_bucket = Mock(return_value={})
    mock_s3.list_objects_v2 = Mock(return_value={"KeyCount": 1})

    mock_ce = Mock()
    mock_ce.get_cost_and_usage = Mock(return_value={})

    def client_factory(svc):
        return {"athena": mock_athena, "s3": mock_s3, "ce": mock_ce}[svc]

    mock_session = Mock()
    mock_session.client = Mock(side_effect=client_factory)
    return mock_session, mock_athena, mock_s3, mock_ce


class TestAWSServicesCheckSanitisation:
    @pytest.mark.asyncio
    async def test_athena_error_sanitised(self):
        from botocore.exceptions import ClientError

        secret = "Access denied on arn:aws:athena:us-east-1:123456789012:workgroup/finops-wg"
        error = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": secret}},
            "ListWorkGroups",
        )

        mock_session, mock_athena, mock_s3, mock_ce = _healthy_aws_mocks()
        mock_athena.list_work_groups = Mock(side_effect=error)

        with _patch_settings():
            with patch('backend.utils.aws_session.create_aws_session', return_value=mock_session):
                with patch('backend.api.health.logger'):
                    result = await _check_aws_services()

        resp = json.dumps(result)
        assert "123456789012" not in resp
        assert "finops-wg" not in resp
        assert "AccessDeniedException" not in resp
        assert result["details"]["athena"] == "error: service unavailable"

    @pytest.mark.asyncio
    async def test_s3_error_sanitised(self):
        from botocore.exceptions import ClientError

        secret = "NoSuchBucket: The specified bucket secret-finops-bucket does not exist"
        error = ClientError(
            {"Error": {"Code": "NoSuchBucket", "Message": secret}},
            "HeadBucket",
        )

        mock_session, mock_athena, mock_s3, mock_ce = _healthy_aws_mocks()
        mock_s3.head_bucket = Mock(side_effect=error)

        with _patch_settings():
            with patch('backend.utils.aws_session.create_aws_session', return_value=mock_session):
                with patch('backend.api.health.logger'):
                    result = await _check_aws_services()

        resp = json.dumps(result)
        assert "secret-finops-bucket" not in resp
        assert "NoSuchBucket" not in resp
        assert result["details"]["s3_bucket"] == "error: service unavailable"

    def test_s3_path_removed_from_source(self):
        """cur_s3_location must not appear anywhere in the function."""
        source = inspect.getsource(_check_aws_services)
        assert "cur_s3_location" not in source

    @pytest.mark.asyncio
    async def test_database_name_not_leaked_on_error(self):
        from botocore.exceptions import ClientError

        error = ClientError(
            {"Error": {"Code": "InvalidDatabaseException", "Message": "not found"}},
            "GetDatabase",
        )

        mock_session, mock_athena, mock_s3, mock_ce = _healthy_aws_mocks()
        mock_athena.get_database = Mock(side_effect=error)
        mock_athena.start_query_execution = Mock(side_effect=Exception("no db"))

        with _patch_settings():
            with patch('backend.utils.aws_session.create_aws_session', return_value=mock_session):
                with patch('backend.api.health.logger'):
                    result = await _check_aws_services()

        resp = json.dumps(result)
        assert "secret_finops_db" not in resp
        assert "secret-finops-bucket" not in resp
        assert result["details"]["athena_database"] == "error: not found"

    @pytest.mark.asyncio
    async def test_database_name_not_leaked_on_success(self):
        """Even when the database check succeeds, the name must not appear."""
        mock_session, mock_athena, mock_s3, mock_ce = _healthy_aws_mocks()

        with _patch_settings():
            with patch('backend.utils.aws_session.create_aws_session', return_value=mock_session):
                with patch('backend.api.health.logger'):
                    with patch('asyncio.sleep', new_callable=AsyncMock):
                        result = await _check_aws_services()

        resp = json.dumps(result)
        assert "secret_finops_db" not in resp
        assert result["details"]["athena_database"] == "available"

    @pytest.mark.asyncio
    async def test_table_name_not_leaked_on_success(self):
        """On success, athena_table must be generic 'queryable'."""
        mock_session, mock_athena, mock_s3, mock_ce = _healthy_aws_mocks()

        with _patch_settings():
            with patch('backend.utils.aws_session.create_aws_session', return_value=mock_session):
                with patch('backend.api.health.logger'):
                    with patch('asyncio.sleep', new_callable=AsyncMock):
                        result = await _check_aws_services()

        resp = json.dumps(result)
        assert "secret_cur_table" not in resp
        assert result["details"]["athena_table"] == "queryable"

    @pytest.mark.asyncio
    async def test_query_failure_reason_not_leaked(self):
        """Athena query failure reason must not appear in the response."""
        secret_reason = "Table secret_cur_table not found in database secret_finops_db"

        mock_session, mock_athena, mock_s3, mock_ce = _healthy_aws_mocks()
        mock_athena.get_query_execution = Mock(return_value={
            "QueryExecution": {
                "Status": {
                    "State": "FAILED",
                    "StateChangeReason": secret_reason,
                }
            }
        })

        with _patch_settings():
            with patch('backend.utils.aws_session.create_aws_session', return_value=mock_session):
                with patch('backend.api.health.logger') as mock_log:
                    with patch('asyncio.sleep', new_callable=AsyncMock):
                        result = await _check_aws_services()

        resp = json.dumps(result)
        assert secret_reason not in resp
        assert "secret_cur_table" not in resp
        assert result["details"]["athena_table"] == "error: query failed"
        # The real reason must be in the log
        mock_log.error.assert_called()

    @pytest.mark.asyncio
    async def test_cost_explorer_error_sanitised(self):
        from botocore.exceptions import ClientError

        secret = "AccessDeniedException: User arn:aws:iam::123456789012:role/finops-role is not authorized"
        error = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": secret}},
            "GetCostAndUsage",
        )

        mock_session, mock_athena, mock_s3, mock_ce = _healthy_aws_mocks()
        mock_ce.get_cost_and_usage = Mock(side_effect=error)

        with _patch_settings():
            with patch('backend.utils.aws_session.create_aws_session', return_value=mock_session):
                with patch('backend.api.health.logger'):
                    with patch('asyncio.sleep', new_callable=AsyncMock):
                        result = await _check_aws_services()

        resp = json.dumps(result)
        assert "123456789012" not in resp
        assert "finops-role" not in resp
        assert result["details"]["cost_explorer"] == "error: service unavailable"

    @pytest.mark.asyncio
    async def test_outer_exception_sanitised(self):
        secret = "NoCredentialsError: Unable to locate credentials in /home/deploy/.aws"

        with _patch_settings():
            with patch('backend.utils.aws_session.create_aws_session', side_effect=Exception(secret)):
                with patch('backend.api.health.logger') as mock_log:
                    result = await _check_aws_services()

        assert result["status"] == "unhealthy"
        assert result["error"] == "AWS services unavailable"
        resp = json.dumps(result)
        assert "/home/deploy" not in resp
        assert "NoCredentialsError" not in resp
        mock_log.error.assert_called_once()


# ---------------------------------------------------------------------------
# Gather-loop sanitisation in detailed_health
# ---------------------------------------------------------------------------


class TestDetailedHealthGatherSanitisation:
    """Exceptions propagated through asyncio.gather must be sanitised."""

    @pytest.mark.asyncio
    async def test_task_exception_not_leaked(self):
        secret = "psycopg2.OperationalError: FATAL password failed for user 'finops_svc'"

        request = Mock()
        request.app.state = Mock(spec=[])  # no db, no vector_store

        async def raise_secret():
            raise Exception(secret)

        async def healthy():
            return {"status": "healthy"}

        user = Mock()

        with patch('backend.api.health.logger') as mock_log:
            with patch('backend.api.health._check_valkey', raise_secret):
                with patch('backend.api.health._check_llm_services', healthy):
                    with patch('backend.api.health._check_aws_services', healthy):
                        result = await detailed_health(request, user)

        services_str = json.dumps(result.services)
        assert secret not in services_str
        assert "finops_svc" not in services_str
        assert result.services["valkey"]["error"] == "service unavailable"
        mock_log.error.assert_called()

    @pytest.mark.asyncio
    async def test_uninitialised_services_reported_safely(self):
        """Services not on app.state must appear as 'unavailable' with no leak."""
        request = Mock()
        request.app.state = Mock(spec=[])  # nothing initialised

        async def healthy():
            return {"status": "healthy"}

        user = Mock()

        with patch('backend.api.health._check_valkey', healthy):
            with patch('backend.api.health._check_llm_services', healthy):
                with patch('backend.api.health._check_aws_services', healthy):
                    result = await detailed_health(request, user)

        assert result.services["database"]["status"] == "unavailable"
        assert result.services["vector_store"]["status"] == "unavailable"
        # Generic messages only
        assert "database" not in result.services["database"].get("message", "").lower() or \
               result.services["database"]["message"] == "Database service not initialized"
