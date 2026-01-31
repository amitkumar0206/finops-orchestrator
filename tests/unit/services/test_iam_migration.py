"""
Tests for HIGH-1: Incomplete IAM-Role Migration

Verifies that all production AWS client creation paths use the secure
create_aws_session() factory instead of raw boto3.client() calls.

The only intentional exception is multi_account_service.py's
get_athena_client_for_account(), which uses temporary credentials from
STS AssumeRole for cross-account access — that usage is architecturally correct.
"""

import ast
import os

import pytest
from unittest.mock import patch, MagicMock

from backend.utils.aws_constants import TRUSTED_ADVISOR_REGION

# Resolve path to backend source tree relative to this test file
_BACKEND_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..', 'backend')
)


def _read_source(relative_path: str) -> str:
    """Read a source file relative to the backend root."""
    with open(os.path.join(_BACKEND_ROOT, relative_path)) as f:
        return f.read()


def _find_raw_boto3_calls(source: str) -> list:
    """
    AST-walk source and return (lineno, description) for any raw
    boto3.client() or boto3.session.Session() calls.
    """
    tree = ast.parse(source)
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # boto3.client(...)
        if (isinstance(func, ast.Attribute)
                and func.attr == 'client'
                and isinstance(func.value, ast.Name)
                and func.value.id == 'boto3'):
            hits.append((node.lineno, "boto3.client()"))
        # boto3.session.Session(...)
        if (isinstance(func, ast.Attribute)
                and func.attr == 'Session'
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == 'session'
                and isinstance(func.value.value, ast.Name)
                and func.value.value.id == 'boto3'):
            hits.append((node.lineno, "boto3.session.Session()"))
    return hits


# Files fully migrated — must have zero raw boto3 calls
_FULLY_MIGRATED = [
    "agents/execute_query_v2.py",
    "services/llm_service.py",
    "services/infrastructure_analyzer.py",
    "services/aws_optimization_signals.py",
    "services/arn_resolver.py",
]


class TestStaticAnalysis:
    """AST-based verification that raw boto3 calls are eliminated."""

    @pytest.mark.parametrize("source_file", _FULLY_MIGRATED)
    def test_no_raw_boto3_calls(self, source_file):
        """Fully-migrated file must contain no raw boto3.client() or boto3.session.Session()."""
        violations = _find_raw_boto3_calls(_read_source(source_file))
        assert violations == [], (
            f"{source_file} still contains raw boto3 calls:\n"
            + "\n".join(f"  line {ln}: {desc}" for ln, desc in violations)
        )

    @pytest.mark.parametrize("source_file", _FULLY_MIGRATED)
    def test_imports_session_factory(self, source_file):
        """Fully-migrated file must import create_aws_session."""
        assert "create_aws_session" in _read_source(source_file)

    @pytest.mark.parametrize("source_file", _FULLY_MIGRATED + ["services/multi_account_service.py"])
    def test_uses_aws_service_constants(self, source_file):
        """All migrated files must reference AwsService constants."""
        assert "AwsService" in _read_source(source_file)

    def test_multi_account_exactly_one_raw_boto3_call(self):
        """multi_account_service.py must retain exactly one raw boto3.client() for cross-account AssumeRole."""
        violations = _find_raw_boto3_calls(_read_source("services/multi_account_service.py"))
        assert len(violations) == 1, (
            f"Expected exactly 1 raw boto3.client() (cross-account path), "
            f"found {len(violations)}: {violations}"
        )

    def test_multi_account_cross_account_path_preserved(self):
        """The AssumeRole cross-account client must still use explicit temporary credentials."""
        source = _read_source("services/multi_account_service.py")
        assert "aws_access_key_id=credentials['AccessKeyId']" in source
        assert "aws_session_token=credentials['SessionToken']" in source

    def test_arn_resolver_s3_path_uses_helper(self):
        """resolve_s3_resource must route through get_boto3_client, not direct boto3."""
        source = _read_source("services/arn_resolver.py")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == 'resolve_s3_resource':
                func_src = ast.get_source_segment(source, node)
                assert 'boto3.client' not in func_src, (
                    "resolve_s3_resource still uses boto3.client() directly"
                )
                assert 'get_boto3_client' in func_src, (
                    "resolve_s3_resource does not call get_boto3_client()"
                )
                return
        pytest.fail("resolve_s3_resource not found in arn_resolver.py")


class TestAthenaExecutorUsesSessionFactory:
    """Runtime verification: AthenaExecutor client creation."""

    def test_client_created_via_session(self):
        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client

        with patch('backend.agents.execute_query_v2.create_aws_session', return_value=mock_session):
            from backend.agents.execute_query_v2 import AthenaExecutor
            executor = AthenaExecutor()

        mock_session.client.assert_called_once_with('athena')
        assert executor.athena_client is mock_client


class TestBedrockLLMServiceUsesSessionFactory:
    """Runtime verification: BedrockLLMService client creation."""

    def test_client_created_via_session(self):
        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client

        with patch('backend.services.llm_service.create_aws_session', return_value=mock_session):
            from backend.services.llm_service import BedrockLLMService
            svc = BedrockLLMService()

        mock_session.client.assert_called_once_with('bedrock-runtime')
        assert svc.bedrock_client is mock_client
        assert svc.initialized is True


class TestInfrastructureAnalyzerUsesSessionFactory:
    """Runtime verification: InfrastructureAnalyzer creates all clients from one session."""

    def test_three_clients_from_single_session(self):
        mock_session = MagicMock()
        client_map = {}

        def _make_client(svc_name):
            client_map[svc_name] = MagicMock()
            return client_map[svc_name]

        mock_session.client.side_effect = _make_client

        with patch('backend.services.infrastructure_analyzer.create_aws_session', return_value=mock_session):
            from backend.services.infrastructure_analyzer import InfrastructureAnalyzer
            analyzer = InfrastructureAnalyzer()

        assert mock_session.client.call_count == 3
        called_services = {c.args[0] for c in mock_session.client.call_args_list}
        assert called_services == {'logs', 'cloudwatch', 'compute-optimizer'}
        assert analyzer.logs_client is client_map['logs']
        assert analyzer.cloudwatch_client is client_map['cloudwatch']
        assert analyzer.compute_optimizer_client is client_map['compute-optimizer']


class TestOptimizationSignalsUsesSessionFactory:
    """Runtime verification: AWSOptimizationSignalsService lazy client properties."""

    def test_session_stored_in_init(self):
        mock_session = MagicMock()

        with patch('backend.services.aws_optimization_signals.create_aws_session', return_value=mock_session):
            from backend.services.aws_optimization_signals import AWSOptimizationSignalsService
            svc = AWSOptimizationSignalsService(region='eu-west-1')

        assert svc._session is mock_session

    def test_ce_client_uses_stored_session(self):
        mock_session = MagicMock()
        mock_ce = MagicMock()
        mock_session.client.return_value = mock_ce

        with patch('backend.services.aws_optimization_signals.create_aws_session', return_value=mock_session):
            from backend.services.aws_optimization_signals import AWSOptimizationSignalsService
            svc = AWSOptimizationSignalsService()
            client = svc.ce_client

        mock_session.client.assert_any_call('ce')
        assert client is mock_ce

    def test_co_client_uses_stored_session(self):
        mock_session = MagicMock()
        mock_co = MagicMock()
        mock_session.client.return_value = mock_co

        with patch('backend.services.aws_optimization_signals.create_aws_session', return_value=mock_session):
            from backend.services.aws_optimization_signals import AWSOptimizationSignalsService
            svc = AWSOptimizationSignalsService()
            client = svc.co_client

        mock_session.client.assert_any_call('compute-optimizer')
        assert client is mock_co

    def test_support_client_creates_dedicated_session(self):
        """Trusted Advisor requires TRUSTED_ADVISOR_REGION; verify a dedicated session is created."""
        sessions = {}

        def factory(region_name=None):
            s = MagicMock()
            s.client.return_value = MagicMock()
            sessions[region_name] = s
            return s

        with patch('backend.services.aws_optimization_signals.create_aws_session', side_effect=factory):
            from backend.services.aws_optimization_signals import AWSOptimizationSignalsService
            svc = AWSOptimizationSignalsService(region='eu-west-1')
            _ = svc.support_client

        assert TRUSTED_ADVISOR_REGION in sessions, (
            f"support_client did not create a session scoped to {TRUSTED_ADVISOR_REGION}"
        )
        sessions[TRUSTED_ADVISOR_REGION].client.assert_called_with('support')


class TestMultiAccountServiceUsesSessionFactory:
    """Runtime verification: MultiAccountService STS client."""

    def test_sts_client_via_session(self):
        mock_session = MagicMock()
        mock_sts = MagicMock()
        mock_session.client.return_value = mock_sts

        with patch('backend.services.multi_account_service.create_aws_session', return_value=mock_session), \
             patch('backend.services.multi_account_service.DatabaseService'):
            from backend.services.multi_account_service import MultiAccountService
            svc = MultiAccountService()

        mock_session.client.assert_called_once_with('sts')
        assert svc.sts_client is mock_sts


class TestArnResolverUsesSessionFactory:
    """Runtime verification: arn_resolver helper delegates to session factory."""

    def test_helper_uses_factory(self):
        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client

        with patch('backend.services.arn_resolver.create_aws_session', return_value=mock_session) as mock_factory:
            from backend.services.arn_resolver import get_boto3_client
            result = get_boto3_client('ec2', 'ap-southeast-1')

        mock_factory.assert_called_once_with(region_name='ap-southeast-1')
        mock_session.client.assert_called_once_with('ec2')
        assert result is mock_client

    def test_helper_normalises_empty_region_to_none(self):
        """Empty string region must be normalised to None for the factory."""
        mock_session = MagicMock()
        mock_session.client.return_value = MagicMock()

        with patch('backend.services.arn_resolver.create_aws_session', return_value=mock_session) as mock_factory:
            from backend.services.arn_resolver import get_boto3_client
            get_boto3_client('s3', '')

        mock_factory.assert_called_once_with(region_name=None)
