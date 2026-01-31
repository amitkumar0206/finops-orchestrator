"""
Tests for AWS Session Factory

Tests secure AWS session creation using IAM roles and the default credential chain.
"""

import pytest
from unittest.mock import patch, MagicMock
import warnings

from backend.utils.aws_session import (
    create_aws_session,
    create_aws_client,
    create_aws_resource,
    get_default_retry_config,
    verify_aws_credentials,
    _check_explicit_credentials_configured,
)


class TestCreateAwsSession:
    """Tests for create_aws_session function"""

    def test_creates_session_with_default_region(self):
        """Test that session is created with default region from settings"""
        with patch('backend.utils.aws_session.boto3.Session') as mock_session:
            mock_session.return_value = MagicMock()

            session = create_aws_session()

            # Should be called without explicit credentials
            mock_session.assert_called_once()
            call_kwargs = mock_session.call_args[1]
            assert 'aws_access_key_id' not in call_kwargs
            assert 'aws_secret_access_key' not in call_kwargs
            assert 'region_name' in call_kwargs

    def test_creates_session_with_custom_region(self):
        """Test that session respects custom region parameter"""
        with patch('backend.utils.aws_session.boto3.Session') as mock_session:
            mock_session.return_value = MagicMock()

            session = create_aws_session(region_name='eu-west-1')

            call_kwargs = mock_session.call_args[1]
            assert call_kwargs['region_name'] == 'eu-west-1'

    def test_creates_session_with_profile_name(self):
        """Test that session can use a profile name for local development"""
        with patch('backend.utils.aws_session.boto3.Session') as mock_session:
            mock_session.return_value = MagicMock()

            session = create_aws_session(profile_name='dev-profile')

            call_kwargs = mock_session.call_args[1]
            assert call_kwargs['profile_name'] == 'dev-profile'

    def test_no_explicit_credentials_passed(self):
        """Test that NO explicit credentials are ever passed to boto3"""
        with patch('backend.utils.aws_session.boto3.Session') as mock_session:
            mock_session.return_value = MagicMock()

            # Even if settings have credentials configured
            with patch('backend.config.settings.get_settings') as mock_settings:
                mock_settings.return_value = MagicMock(
                    aws_access_key_id='AKIAIOSFODNN7EXAMPLE',
                    aws_secret_access_key='wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY',
                    aws_region='us-east-1'
                )

                session = create_aws_session()

            # Verify no credentials passed
            call_kwargs = mock_session.call_args[1]
            assert 'aws_access_key_id' not in call_kwargs
            assert 'aws_secret_access_key' not in call_kwargs


class TestExplicitCredentialsWarning:
    """Tests for deprecation warning when explicit credentials are configured"""

    def test_warns_when_explicit_credentials_configured(self):
        """Test that a deprecation warning is issued when credentials are set"""
        with patch('backend.config.settings.get_settings') as mock_settings:
            mock_settings.return_value = MagicMock(
                aws_access_key_id='AKIAIOSFODNN7EXAMPLE',
                aws_secret_access_key='wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY',
            )

            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                result = _check_explicit_credentials_configured()

                assert result is True
                # Should have issued a deprecation warning
                deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
                assert len(deprecation_warnings) >= 1
                assert 'deprecated' in str(deprecation_warnings[0].message).lower()

    def test_no_warning_when_no_credentials(self):
        """Test no warning when credentials are not configured"""
        with patch('backend.config.settings.get_settings') as mock_settings:
            mock_settings.return_value = MagicMock(
                aws_access_key_id=None,
                aws_secret_access_key=None,
            )

            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                result = _check_explicit_credentials_configured()

                assert result is False


class TestCreateAwsClient:
    """Tests for create_aws_client function"""

    def test_creates_client_for_service(self):
        """Test that client is created for specified service"""
        with patch('backend.utils.aws_session.create_aws_session') as mock_session_fn:
            mock_session = MagicMock()
            mock_client = MagicMock()
            mock_session.client.return_value = mock_client
            mock_session_fn.return_value = mock_session

            client = create_aws_client('s3')

            mock_session.client.assert_called_once_with('s3')
            assert client == mock_client

    def test_creates_client_with_custom_config(self):
        """Test that client respects custom botocore config"""
        from botocore.config import Config
        custom_config = Config(max_pool_connections=100)

        with patch('backend.utils.aws_session.create_aws_session') as mock_session_fn:
            mock_session = MagicMock()
            mock_session_fn.return_value = mock_session

            client = create_aws_client('athena', config=custom_config)

            mock_session.client.assert_called_once_with('athena', config=custom_config)


class TestCreateAwsResource:
    """Tests for create_aws_resource function"""

    def test_creates_resource_for_service(self):
        """Test that resource is created for specified service"""
        with patch('backend.utils.aws_session.create_aws_session') as mock_session_fn:
            mock_session = MagicMock()
            mock_resource = MagicMock()
            mock_session.resource.return_value = mock_resource
            mock_session_fn.return_value = mock_session

            resource = create_aws_resource('s3')

            mock_session.resource.assert_called_once_with('s3')
            assert resource == mock_resource


class TestGetDefaultRetryConfig:
    """Tests for get_default_retry_config function"""

    def test_returns_config_with_defaults(self):
        """Test that config has default retry settings"""
        config = get_default_retry_config()

        assert config.retries['max_attempts'] == 3
        assert config.retries['mode'] == 'adaptive'

    def test_respects_custom_max_attempts(self):
        """Test that custom max_attempts is respected"""
        config = get_default_retry_config(max_attempts=5)

        assert config.retries['max_attempts'] == 5

    def test_respects_custom_mode(self):
        """Test that custom retry mode is respected"""
        config = get_default_retry_config(mode='standard')

        assert config.retries['mode'] == 'standard'

    def test_respects_custom_pool_connections(self):
        """Test that custom max_pool_connections is respected"""
        config = get_default_retry_config(max_pool_connections=100)

        assert config.max_pool_connections == 100


class TestVerifyAwsCredentials:
    """Tests for verify_aws_credentials function"""

    def test_returns_valid_when_credentials_work(self):
        """Test successful credential verification"""
        with patch('backend.utils.aws_session.create_aws_session') as mock_session_fn:
            mock_session = MagicMock()
            mock_sts = MagicMock()
            mock_sts.get_caller_identity.return_value = {
                'Account': '123456789012',
                'Arn': 'arn:aws:iam::123456789012:user/test',
                'UserId': 'AIDAIOSFODNN7EXAMPLE',
            }
            mock_session.client.return_value = mock_sts
            mock_session_fn.return_value = mock_session

            result = verify_aws_credentials()

            assert result['valid'] is True
            assert result['identity']['account'] == '123456789012'
            assert result['method'] == 'default_credential_chain'

    def test_returns_invalid_when_credentials_fail(self):
        """Test failed credential verification"""
        with patch('backend.utils.aws_session.create_aws_session') as mock_session_fn:
            mock_session = MagicMock()
            mock_session.client.side_effect = Exception('Invalid credentials')
            mock_session_fn.return_value = mock_session

            result = verify_aws_credentials()

            assert result['valid'] is False
            assert 'Invalid credentials' in result['error']


class TestSecurityNoExplicitCredentials:
    """Security tests to verify no explicit credentials are used"""

    def test_session_factory_signature_has_no_credentials(self):
        """Verify create_aws_session signature doesn't accept credentials"""
        import inspect
        sig = inspect.signature(create_aws_session)
        params = list(sig.parameters.keys())

        # These should NOT be accepted as parameters
        assert 'aws_access_key_id' not in params
        assert 'aws_secret_access_key' not in params
        assert 'access_key' not in params
        assert 'secret_key' not in params

    def test_client_factory_signature_has_no_credentials(self):
        """Verify create_aws_client signature doesn't accept credentials"""
        import inspect
        sig = inspect.signature(create_aws_client)
        params = list(sig.parameters.keys())

        assert 'aws_access_key_id' not in params
        assert 'aws_secret_access_key' not in params

    def test_resource_factory_signature_has_no_credentials(self):
        """Verify create_aws_resource signature doesn't accept credentials"""
        import inspect
        sig = inspect.signature(create_aws_resource)
        params = list(sig.parameters.keys())

        assert 'aws_access_key_id' not in params
        assert 'aws_secret_access_key' not in params
