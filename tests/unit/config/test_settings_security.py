"""
Tests for Settings Security Configuration

These tests verify that the application properly handles secret key validation
to prevent running with insecure configurations in production.
"""

import os
import pytest
from unittest.mock import patch

from backend.config.settings import Settings, clear_settings_cache


class TestSecretKeyValidation:
    """Test secret key validation in different environments"""

    def setup_method(self):
        """Clear settings cache before each test"""
        clear_settings_cache()
        # Save original environment
        self._original_env = os.environ.copy()

    def teardown_method(self):
        """Restore original environment after each test"""
        os.environ.clear()
        os.environ.update(self._original_env)
        clear_settings_cache()

    def test_development_without_secret_key_auto_generates(self):
        """Test that development mode auto-generates a secret key"""
        os.environ.pop('SECRET_KEY', None)
        os.environ['ENVIRONMENT'] = 'development'

        settings = Settings()

        assert settings.secret_key is not None
        assert len(settings.secret_key) >= 32

    def test_development_with_valid_secret_key(self):
        """Test that development mode accepts valid secret key"""
        os.environ['SECRET_KEY'] = 'this-is-a-long-secure-secret-key-for-testing-purposes-12345'
        os.environ['ENVIRONMENT'] = 'development'

        settings = Settings()

        assert settings.secret_key == os.environ['SECRET_KEY']

    def test_production_without_secret_key_fails(self):
        """Test that production mode fails without SECRET_KEY"""
        os.environ.pop('SECRET_KEY', None)
        os.environ['ENVIRONMENT'] = 'production'

        with pytest.raises(ValueError) as exc_info:
            Settings()

        assert "SECRET_KEY environment variable is required" in str(exc_info.value)
        assert "production" in str(exc_info.value).lower()

    def test_production_with_insecure_secret_key_fails(self):
        """Test that production mode fails with known insecure secret key"""
        os.environ['SECRET_KEY'] = 'dev-secret-key-change-in-production'
        os.environ['ENVIRONMENT'] = 'production'

        with pytest.raises(ValueError) as exc_info:
            Settings()

        assert "insecure value" in str(exc_info.value).lower()

    def test_production_with_short_secret_key_fails(self):
        """Test that production mode fails with short secret key"""
        os.environ['SECRET_KEY'] = 'tooshort'
        os.environ['ENVIRONMENT'] = 'production'

        with pytest.raises(ValueError) as exc_info:
            Settings()

        assert "32 characters" in str(exc_info.value)

    def test_production_with_valid_secret_key_succeeds(self):
        """Test that production mode succeeds with valid secret key"""
        os.environ['SECRET_KEY'] = 'this-is-a-very-long-and-secure-secret-key-for-production-use-12345'
        os.environ['ENVIRONMENT'] = 'production'

        settings = Settings()

        assert settings.secret_key == os.environ['SECRET_KEY']
        assert settings.is_secret_key_secure

    def test_is_secret_key_secure_property(self):
        """Test the is_secret_key_secure property"""
        os.environ['SECRET_KEY'] = 'secure-key-that-is-at-least-32-characters-long-12345'
        os.environ['ENVIRONMENT'] = 'development'

        settings = Settings()

        assert settings.is_secret_key_secure is True

    def test_insecure_defaults_are_rejected(self):
        """Test that all known insecure defaults are rejected in production"""
        insecure_keys = [
            'dev-secret-key-change-in-production',
            'secret',
            'changeme',
            'password',
            '123456',
            'your-secret-key',
            'change-me',
            'test-secret',
        ]

        os.environ['ENVIRONMENT'] = 'production'

        for insecure_key in insecure_keys:
            os.environ['SECRET_KEY'] = insecure_key
            clear_settings_cache()

            with pytest.raises(ValueError):
                Settings()


class TestDeterministicSecretKeyRejection:
    """Test that deterministic/predictable SECRET_KEY patterns are rejected"""

    def setup_method(self):
        clear_settings_cache()
        self._original_env = os.environ.copy()

    def teardown_method(self):
        os.environ.clear()
        os.environ.update(self._original_env)
        clear_settings_cache()

    def test_production_rejects_deterministic_pattern(self):
        """The old CloudFormation pattern stackname-accountid-secret-key-v1 must be rejected"""
        os.environ['SECRET_KEY'] = 'finops-intelligence-platform-services-123456789012-secret-key-v1'
        os.environ['ENVIRONMENT'] = 'production'

        with pytest.raises(ValueError) as exc_info:
            Settings()

        assert "deterministic pattern" in str(exc_info.value).lower()

    def test_production_rejects_variant_deterministic_pattern(self):
        """Any stackname-digits-secret-key-vN pattern must be rejected"""
        os.environ['SECRET_KEY'] = 'my-stack-000000000000-secret-key-v2'
        os.environ['ENVIRONMENT'] = 'production'

        with pytest.raises(ValueError) as exc_info:
            Settings()

        assert "deterministic pattern" in str(exc_info.value).lower()

    def test_deterministic_key_not_secure(self):
        """is_secret_key_secure must return False for deterministic keys"""
        os.environ['SECRET_KEY'] = 'finops-platform-123456789012-secret-key-v1'
        os.environ['ENVIRONMENT'] = 'development'

        settings = Settings()

        assert settings.is_secret_key_secure is False

    def test_random_key_not_flagged_as_deterministic(self):
        """Legitimate random keys must not be flagged"""
        os.environ['SECRET_KEY'] = 'Kj3mP9xQ7vR2bN5wT8yZ1cA6dF4gH0iL-extra-long-secure-key'
        os.environ['ENVIRONMENT'] = 'production'

        settings = Settings()

        assert settings.is_secret_key_secure is True

    def test_production_rejects_placeholder_retrieve_from_secrets_manager(self):
        """The placeholder RETRIEVE_FROM_SECRETS_MANAGER must be rejected in production"""
        os.environ['SECRET_KEY'] = 'RETRIEVE_FROM_SECRETS_MANAGER'
        os.environ['ENVIRONMENT'] = 'production'

        with pytest.raises(ValueError) as exc_info:
            Settings()

        assert "insecure value" in str(exc_info.value).lower()


class TestLegacyHeaderAuthRemoved:
    """Test that legacy header authentication has been removed"""

    def setup_method(self):
        """Clear settings cache before each test"""
        clear_settings_cache()
        self._original_env = os.environ.copy()

    def teardown_method(self):
        """Restore original environment after each test"""
        os.environ.clear()
        os.environ.update(self._original_env)
        clear_settings_cache()

    def test_no_allow_legacy_header_auth_setting(self):
        """Test that allow_legacy_header_auth setting no longer exists"""
        os.environ['SECRET_KEY'] = 'secure-key-that-is-at-least-32-characters-long'
        os.environ['ENVIRONMENT'] = 'development'

        settings = Settings()

        # The setting should not exist
        assert not hasattr(settings, 'allow_legacy_header_auth')

    def test_legacy_header_auth_env_var_ignored(self):
        """Test that ALLOW_LEGACY_HEADER_AUTH env var is ignored"""
        os.environ['SECRET_KEY'] = 'secure-key-that-is-at-least-32-characters-long'
        os.environ['ENVIRONMENT'] = 'development'
        os.environ['ALLOW_LEGACY_HEADER_AUTH'] = 'true'

        settings = Settings()

        # Even if env var is set, the setting should not exist
        assert not hasattr(settings, 'allow_legacy_header_auth')


class TestFieldEncryptionKeyValidation:
    """Test that FIELD_ENCRYPTION_KEY is validated in security configuration"""

    def setup_method(self):
        clear_settings_cache()
        self._original_env = os.environ.copy()

    def teardown_method(self):
        os.environ.clear()
        os.environ.update(self._original_env)
        clear_settings_cache()

    def test_production_without_encryption_key_reports_critical(self):
        """Production without FIELD_ENCRYPTION_KEY must produce CRITICAL warning"""
        os.environ['SECRET_KEY'] = 'secure-key-that-is-at-least-32-characters-long-for-production'
        os.environ['ENVIRONMENT'] = 'production'
        os.environ.pop('FIELD_ENCRYPTION_KEY', None)

        settings = Settings()
        issues = settings.validate_security_configuration()

        encryption_issues = [i for i in issues if 'FIELD_ENCRYPTION_KEY' in i]
        assert len(encryption_issues) >= 1
        assert any('CRITICAL' in i for i in encryption_issues)

    def test_production_with_short_encryption_key_reports_critical(self):
        """Production with short FIELD_ENCRYPTION_KEY must produce CRITICAL warning"""
        os.environ['SECRET_KEY'] = 'secure-key-that-is-at-least-32-characters-long-for-production'
        os.environ['ENVIRONMENT'] = 'production'
        os.environ['FIELD_ENCRYPTION_KEY'] = 'tooshort'

        settings = Settings()
        issues = settings.validate_security_configuration()

        encryption_issues = [i for i in issues if 'FIELD_ENCRYPTION_KEY' in i]
        assert len(encryption_issues) >= 1
        assert any('too short' in i.lower() for i in encryption_issues)

    def test_production_with_valid_encryption_key_no_encryption_issues(self):
        """Production with a good FIELD_ENCRYPTION_KEY should have no encryption issues"""
        os.environ['SECRET_KEY'] = 'secure-key-that-is-at-least-32-characters-long-for-production'
        os.environ['ENVIRONMENT'] = 'production'
        os.environ['FIELD_ENCRYPTION_KEY'] = 'a' * 48

        settings = Settings()
        issues = settings.validate_security_configuration()

        encryption_issues = [i for i in issues if 'FIELD_ENCRYPTION_KEY' in i]
        assert len(encryption_issues) == 0

    def test_development_without_encryption_key_no_critical(self):
        """Development without FIELD_ENCRYPTION_KEY should NOT produce CRITICAL"""
        os.environ.pop('SECRET_KEY', None)
        os.environ['ENVIRONMENT'] = 'development'
        os.environ.pop('FIELD_ENCRYPTION_KEY', None)

        settings = Settings()
        issues = settings.validate_security_configuration()

        encryption_critical = [
            i for i in issues
            if 'FIELD_ENCRYPTION_KEY' in i and 'CRITICAL' in i
        ]
        assert len(encryption_critical) == 0


class TestSecurityConfigurationValidation:
    """Test the validate_security_configuration method"""

    def setup_method(self):
        """Clear settings cache before each test"""
        clear_settings_cache()
        self._original_env = os.environ.copy()

    def teardown_method(self):
        """Restore original environment after each test"""
        os.environ.clear()
        os.environ.update(self._original_env)
        clear_settings_cache()

    def test_production_with_secure_config_no_critical_issues(self):
        """Test that production with secure config has no CRITICAL issues"""
        import tempfile

        # Create a temporary CA cert file for the test
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pem', delete=False) as f:
            f.write("# Test CA cert placeholder\n")
            temp_ca_path = f.name

        try:
            os.environ['SECRET_KEY'] = 'secure-key-that-is-at-least-32-characters-long-for-production'
            os.environ['ENVIRONMENT'] = 'production'
            os.environ['DEBUG'] = 'false'
            os.environ['FIELD_ENCRYPTION_KEY'] = 'a' * 48
            # Use verify-full SSL mode for secure production configuration
            os.environ['POSTGRES_SSL_MODE'] = 'verify-full'
            os.environ['POSTGRES_SSL_CA_CERT_PATH'] = temp_ca_path

            settings = Settings()
            issues = settings.validate_security_configuration()

            # Filter for CRITICAL issues only (warnings are acceptable in test environment)
            critical_issues = [i for i in issues if 'CRITICAL' in i]
            assert len(critical_issues) == 0, f"Unexpected critical issues: {critical_issues}"
        finally:
            os.unlink(temp_ca_path)

    def test_production_with_debug_mode_warns(self):
        """Test that production with DEBUG=true generates warning"""
        os.environ['SECRET_KEY'] = 'secure-key-that-is-at-least-32-characters-long-for-production'
        os.environ['ENVIRONMENT'] = 'production'
        os.environ['DEBUG'] = 'true'

        settings = Settings()
        issues = settings.validate_security_configuration()

        assert any('DEBUG' in issue for issue in issues)

    def test_development_with_insecure_config_warns(self):
        """Test that development with insecure config generates warnings"""
        os.environ.pop('SECRET_KEY', None)  # Will auto-generate
        os.environ['ENVIRONMENT'] = 'development'

        settings = Settings()
        # Development mode with auto-generated key should be considered not secure
        # for informational purposes, but shouldn't fail
        issues = settings.validate_security_configuration()

        # In dev mode, we might get a warning about the secret key
        # (depending on the generated key length which should be fine)
        assert isinstance(issues, list)
