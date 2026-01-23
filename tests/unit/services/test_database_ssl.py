"""
Tests for Database SSL Configuration

These tests verify that the database service properly configures SSL/TLS
to prevent man-in-the-middle attacks on database connections.
"""

import os
import ssl
import tempfile
import pytest
from unittest.mock import patch, MagicMock

from backend.services.database import create_ssl_context


class TestCreateSSLContext:
    """Test the create_ssl_context function"""

    def test_disable_returns_none(self):
        """Test that 'disable' mode returns None (no SSL)"""
        ctx = create_ssl_context("disable")
        assert ctx is None

    def test_disable_case_insensitive(self):
        """Test that SSL mode is case insensitive"""
        ctx = create_ssl_context("DISABLE")
        assert ctx is None

        ctx = create_ssl_context("Disable")
        assert ctx is None


class TestSSLModeRequire:
    """Test 'require' SSL mode (legacy, no verification)"""

    def test_require_creates_context(self):
        """Test that 'require' mode creates an SSL context"""
        ctx = create_ssl_context("require")
        assert ctx is not None
        assert isinstance(ctx, ssl.SSLContext)

    def test_require_no_hostname_check(self):
        """Test that 'require' mode disables hostname checking"""
        ctx = create_ssl_context("require")
        assert ctx.check_hostname is False

    def test_require_no_cert_verification(self):
        """Test that 'require' mode disables certificate verification"""
        ctx = create_ssl_context("require")
        assert ctx.verify_mode == ssl.CERT_NONE


class TestSSLModeAllow:
    """Test 'allow' SSL mode"""

    def test_allow_creates_context(self):
        """Test that 'allow' mode creates an SSL context"""
        ctx = create_ssl_context("allow")
        assert ctx is not None

    def test_allow_no_verification(self):
        """Test that 'allow' mode disables verification"""
        ctx = create_ssl_context("allow")
        assert ctx.check_hostname is False
        assert ctx.verify_mode == ssl.CERT_NONE


class TestSSLModePrefer:
    """Test 'prefer' SSL mode (default)"""

    def test_prefer_creates_context(self):
        """Test that 'prefer' mode creates an SSL context"""
        ctx = create_ssl_context("prefer")
        assert ctx is not None

    def test_prefer_no_verification(self):
        """Test that 'prefer' mode disables verification"""
        ctx = create_ssl_context("prefer")
        assert ctx.check_hostname is False
        assert ctx.verify_mode == ssl.CERT_NONE


class TestSSLModeVerifyCA:
    """Test 'verify-ca' SSL mode (certificate verification without hostname)"""

    def test_verify_ca_creates_context(self):
        """Test that 'verify-ca' mode creates an SSL context"""
        ctx = create_ssl_context("verify-ca")
        assert ctx is not None

    def test_verify_ca_requires_cert(self):
        """Test that 'verify-ca' mode requires certificate verification"""
        ctx = create_ssl_context("verify-ca")
        assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_verify_ca_no_hostname_check(self):
        """Test that 'verify-ca' mode does NOT verify hostname"""
        ctx = create_ssl_context("verify-ca")
        assert ctx.check_hostname is False

    def test_verify_ca_with_ca_cert_file(self):
        """Test that 'verify-ca' loads CA certificate from file"""
        # Create a temporary file to simulate a CA cert
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pem', delete=False) as f:
            # Write a minimal PEM structure (won't be valid but tests file loading)
            f.write("-----BEGIN CERTIFICATE-----\n")
            f.write("MIIBkTCB+wIJAKHBfCqx\n")  # Fake cert data
            f.write("-----END CERTIFICATE-----\n")
            temp_path = f.name

        try:
            # This will raise an error because the cert is invalid,
            # but we're testing that the file path is checked
            with pytest.raises(ssl.SSLError):
                create_ssl_context("verify-ca", ca_cert_path=temp_path)
        finally:
            os.unlink(temp_path)

    def test_verify_ca_missing_ca_cert_raises(self):
        """Test that missing CA certificate file raises ValueError"""
        with pytest.raises(ValueError) as exc_info:
            create_ssl_context("verify-ca", ca_cert_path="/nonexistent/ca.pem")

        assert "CA certificate file not found" in str(exc_info.value)


class TestSSLModeVerifyFull:
    """Test 'verify-full' SSL mode (RECOMMENDED for production)"""

    def test_verify_full_creates_context(self):
        """Test that 'verify-full' mode creates an SSL context"""
        ctx = create_ssl_context("verify-full")
        assert ctx is not None

    def test_verify_full_requires_cert(self):
        """Test that 'verify-full' mode requires certificate verification"""
        ctx = create_ssl_context("verify-full")
        assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_verify_full_checks_hostname(self):
        """Test that 'verify-full' mode verifies hostname"""
        ctx = create_ssl_context("verify-full")
        assert ctx.check_hostname is True

    def test_verify_full_missing_ca_cert_raises(self):
        """Test that missing CA certificate file raises ValueError"""
        with pytest.raises(ValueError) as exc_info:
            create_ssl_context("verify-full", ca_cert_path="/nonexistent/ca.pem")

        assert "CA certificate file not found" in str(exc_info.value)


class TestInvalidSSLMode:
    """Test invalid SSL mode handling"""

    def test_invalid_mode_raises_valueerror(self):
        """Test that invalid SSL mode raises ValueError"""
        with pytest.raises(ValueError) as exc_info:
            create_ssl_context("invalid")

        assert "Invalid SSL mode" in str(exc_info.value)
        assert "disable" in str(exc_info.value)  # Should list valid modes

    def test_empty_mode_raises_valueerror(self):
        """Test that empty SSL mode raises ValueError"""
        with pytest.raises(ValueError):
            create_ssl_context("")


class TestClientCertificates:
    """Test client certificate (mutual TLS) configuration"""

    def test_client_cert_missing_file_raises(self):
        """Test that missing client certificate file raises ValueError"""
        with pytest.raises(ValueError) as exc_info:
            create_ssl_context(
                "verify-full",
                client_cert_path="/nonexistent/client.pem",
                client_key_path="/nonexistent/client.key"
            )

        assert "Client certificate file not found" in str(exc_info.value)

    def test_client_key_missing_file_raises(self):
        """Test that missing client key file raises ValueError"""
        # Create temp cert file but not key
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pem', delete=False) as f:
            f.write("cert")
            cert_path = f.name

        try:
            with pytest.raises(ValueError) as exc_info:
                create_ssl_context(
                    "verify-full",
                    client_cert_path=cert_path,
                    client_key_path="/nonexistent/client.key"
                )

            assert "Client key file not found" in str(exc_info.value)
        finally:
            os.unlink(cert_path)


class TestSSLContextSecurityProperties:
    """Test that SSL contexts have proper security properties"""

    def test_verify_full_is_secure(self):
        """Test that verify-full mode provides proper security"""
        ctx = create_ssl_context("verify-full")

        # SECURITY: Must require certificate
        assert ctx.verify_mode == ssl.CERT_REQUIRED

        # SECURITY: Must check hostname
        assert ctx.check_hostname is True

    def test_verify_ca_requires_certificate(self):
        """Test that verify-ca mode requires certificate"""
        ctx = create_ssl_context("verify-ca")

        # SECURITY: Must require certificate
        assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_legacy_modes_warn_about_security(self):
        """Test that legacy modes (require, prefer, allow) are marked as insecure"""
        for mode in ["require", "prefer", "allow"]:
            ctx = create_ssl_context(mode)

            # These modes don't verify certificates
            assert ctx.verify_mode == ssl.CERT_NONE
            assert ctx.check_hostname is False


class TestSSLSettingsValidation:
    """Test SSL configuration validation in settings"""

    def setup_method(self):
        """Clear settings cache before each test"""
        from backend.config.settings import clear_settings_cache
        clear_settings_cache()
        self._original_env = os.environ.copy()

    def teardown_method(self):
        """Restore original environment after each test"""
        os.environ.clear()
        os.environ.update(self._original_env)
        from backend.config.settings import clear_settings_cache
        clear_settings_cache()

    def test_valid_ssl_modes(self):
        """Test that all valid SSL modes are accepted"""
        from backend.config.settings import Settings

        os.environ['SECRET_KEY'] = 'test-key-long-enough-for-testing-purposes-12345'
        os.environ['ENVIRONMENT'] = 'development'

        valid_modes = ['disable', 'allow', 'prefer', 'require', 'verify-ca', 'verify-full']

        for mode in valid_modes:
            os.environ['POSTGRES_SSL_MODE'] = mode
            from backend.config.settings import clear_settings_cache
            clear_settings_cache()

            settings = Settings()
            issues = settings.validate_database_ssl_configuration()

            # Should not have "Invalid POSTGRES_SSL_MODE" error
            assert not any("Invalid POSTGRES_SSL_MODE" in issue for issue in issues), \
                f"Mode '{mode}' should be valid"

    def test_invalid_ssl_mode_detected(self):
        """Test that invalid SSL mode is detected"""
        from backend.config.settings import Settings

        os.environ['SECRET_KEY'] = 'test-key-long-enough-for-testing-purposes-12345'
        os.environ['ENVIRONMENT'] = 'development'
        os.environ['POSTGRES_SSL_MODE'] = 'invalid-mode'

        settings = Settings()
        issues = settings.validate_database_ssl_configuration()

        assert any("Invalid POSTGRES_SSL_MODE" in issue for issue in issues)

    def test_verify_modes_require_ca_cert(self):
        """Test that verify-ca and verify-full require CA certificate path"""
        from backend.config.settings import Settings

        os.environ['SECRET_KEY'] = 'test-key-long-enough-for-testing-purposes-12345'
        os.environ['ENVIRONMENT'] = 'development'

        for mode in ['verify-ca', 'verify-full']:
            os.environ['POSTGRES_SSL_MODE'] = mode
            os.environ.pop('POSTGRES_SSL_CA_CERT_PATH', None)
            from backend.config.settings import clear_settings_cache
            clear_settings_cache()

            settings = Settings()
            issues = settings.validate_database_ssl_configuration()

            assert any("POSTGRES_SSL_CA_CERT_PATH is required" in issue for issue in issues), \
                f"Mode '{mode}' should require CA cert path"

    def test_production_ssl_disabled_warning(self):
        """Test that production with SSL disabled generates critical warning"""
        from backend.config.settings import Settings

        os.environ['SECRET_KEY'] = 'secure-key-that-is-at-least-32-characters-long-for-production'
        os.environ['ENVIRONMENT'] = 'production'
        os.environ['POSTGRES_SSL_MODE'] = 'disable'

        settings = Settings()
        issues = settings.validate_database_ssl_configuration()

        assert any("CRITICAL" in issue and "SSL is disabled" in issue for issue in issues)

    def test_production_weak_ssl_mode_warning(self):
        """Test that production with weak SSL mode generates warning"""
        from backend.config.settings import Settings

        os.environ['SECRET_KEY'] = 'secure-key-that-is-at-least-32-characters-long-for-production'
        os.environ['ENVIRONMENT'] = 'production'

        for mode in ['allow', 'prefer', 'require']:
            os.environ['POSTGRES_SSL_MODE'] = mode
            from backend.config.settings import clear_settings_cache
            clear_settings_cache()

            settings = Settings()
            issues = settings.validate_database_ssl_configuration()

            assert any("does not verify certificates" in issue for issue in issues), \
                f"Mode '{mode}' should generate warning in production"

    def test_rds_host_detection(self):
        """Test that RDS host is properly detected"""
        from backend.config.settings import Settings

        os.environ['SECRET_KEY'] = 'test-key-long-enough-for-testing-purposes-12345'
        os.environ['ENVIRONMENT'] = 'development'
        os.environ['POSTGRES_HOST'] = 'mydb.abc123.us-east-1.rds.amazonaws.com'
        os.environ['POSTGRES_SSL_MODE'] = 'require'

        settings = Settings()

        assert settings.is_rds_database is True
        assert settings.requires_ssl_verification is True

        issues = settings.validate_database_ssl_configuration()
        assert any("AWS RDS detected" in issue for issue in issues)

    def test_missing_ca_cert_file_detected(self):
        """Test that missing CA certificate file is detected"""
        from backend.config.settings import Settings

        os.environ['SECRET_KEY'] = 'test-key-long-enough-for-testing-purposes-12345'
        os.environ['ENVIRONMENT'] = 'development'
        os.environ['POSTGRES_SSL_MODE'] = 'verify-full'
        os.environ['POSTGRES_SSL_CA_CERT_PATH'] = '/nonexistent/ca-bundle.pem'

        settings = Settings()
        issues = settings.validate_database_ssl_configuration()

        assert any("SSL CA certificate file not found" in issue for issue in issues)
