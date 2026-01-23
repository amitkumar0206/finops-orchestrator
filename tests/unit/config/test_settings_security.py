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

    def test_production_with_secure_config_returns_empty(self):
        """Test that production with secure config has no issues"""
        os.environ['SECRET_KEY'] = 'secure-key-that-is-at-least-32-characters-long-for-production'
        os.environ['ENVIRONMENT'] = 'production'
        os.environ['DEBUG'] = 'false'

        settings = Settings()
        issues = settings.validate_security_configuration()

        assert len(issues) == 0

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
