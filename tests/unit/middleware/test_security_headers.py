"""
Tests for Security Headers Middleware

These tests verify that the security headers middleware properly adds
all required security headers to HTTP responses.
"""

import pytest
from unittest.mock import Mock, AsyncMock
from starlette.responses import Response
from starlette.testclient import TestClient
from fastapi import FastAPI

from backend.middleware.security_headers import (
    SecurityHeadersMiddleware,
    get_default_csp,
    get_default_permissions_policy,
)


@pytest.fixture
def app():
    """Create a test FastAPI application"""
    app = FastAPI()

    @app.get("/test")
    async def test_endpoint():
        return {"message": "test"}

    return app


class TestSecurityHeadersMiddleware:
    """Test SecurityHeadersMiddleware"""

    def test_adds_x_frame_options(self, app):
        """Test that X-Frame-Options header is added"""
        app.add_middleware(SecurityHeadersMiddleware, x_frame_options="DENY")
        client = TestClient(app)

        response = client.get("/test")

        assert response.headers.get("X-Frame-Options") == "DENY"

    def test_adds_x_content_type_options(self, app):
        """Test that X-Content-Type-Options header is added"""
        app.add_middleware(SecurityHeadersMiddleware, x_content_type_options="nosniff")
        client = TestClient(app)

        response = client.get("/test")

        assert response.headers.get("X-Content-Type-Options") == "nosniff"

    def test_adds_x_xss_protection(self, app):
        """Test that X-XSS-Protection header is added"""
        app.add_middleware(SecurityHeadersMiddleware, x_xss_protection="1; mode=block")
        client = TestClient(app)

        response = client.get("/test")

        assert response.headers.get("X-XSS-Protection") == "1; mode=block"

    def test_adds_referrer_policy(self, app):
        """Test that Referrer-Policy header is added"""
        app.add_middleware(
            SecurityHeadersMiddleware,
            referrer_policy="strict-origin-when-cross-origin"
        )
        client = TestClient(app)

        response = client.get("/test")

        assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_adds_permissions_policy(self, app):
        """Test that Permissions-Policy header is added"""
        app.add_middleware(
            SecurityHeadersMiddleware,
            permissions_policy="geolocation=(), microphone=()"
        )
        client = TestClient(app)

        response = client.get("/test")

        assert response.headers.get("Permissions-Policy") == "geolocation=(), microphone=()"


class TestHSTSConfiguration:
    """Test HSTS (Strict-Transport-Security) configuration"""

    def test_hsts_disabled_by_default(self, app):
        """Test that HSTS is disabled by default"""
        app.add_middleware(SecurityHeadersMiddleware)
        client = TestClient(app)

        response = client.get("/test")

        assert response.headers.get("Strict-Transport-Security") is None

    def test_hsts_enabled(self, app):
        """Test that HSTS can be enabled"""
        app.add_middleware(SecurityHeadersMiddleware, enable_hsts=True)
        client = TestClient(app)

        response = client.get("/test")

        hsts = response.headers.get("Strict-Transport-Security")
        assert hsts is not None
        assert "max-age=" in hsts

    def test_hsts_custom_max_age(self, app):
        """Test HSTS with custom max-age"""
        app.add_middleware(
            SecurityHeadersMiddleware,
            enable_hsts=True,
            hsts_max_age=86400  # 1 day
        )
        client = TestClient(app)

        response = client.get("/test")

        hsts = response.headers.get("Strict-Transport-Security")
        assert "max-age=86400" in hsts

    def test_hsts_include_subdomains(self, app):
        """Test HSTS with includeSubDomains"""
        app.add_middleware(
            SecurityHeadersMiddleware,
            enable_hsts=True,
            hsts_include_subdomains=True
        )
        client = TestClient(app)

        response = client.get("/test")

        hsts = response.headers.get("Strict-Transport-Security")
        assert "includeSubDomains" in hsts

    def test_hsts_preload(self, app):
        """Test HSTS with preload directive"""
        app.add_middleware(
            SecurityHeadersMiddleware,
            enable_hsts=True,
            hsts_include_subdomains=True,
            hsts_preload=True
        )
        client = TestClient(app)

        response = client.get("/test")

        hsts = response.headers.get("Strict-Transport-Security")
        assert "preload" in hsts

    def test_hsts_custom_value(self, app):
        """Test custom HSTS header value"""
        app.add_middleware(
            SecurityHeadersMiddleware,
            strict_transport_security="max-age=0"  # Disable HSTS
        )
        client = TestClient(app)

        response = client.get("/test")

        assert response.headers.get("Strict-Transport-Security") == "max-age=0"


class TestContentSecurityPolicy:
    """Test Content-Security-Policy configuration"""

    def test_csp_not_added_by_default(self, app):
        """Test that CSP is not added when not configured"""
        app.add_middleware(SecurityHeadersMiddleware)
        client = TestClient(app)

        response = client.get("/test")

        assert response.headers.get("Content-Security-Policy") is None

    def test_csp_custom_policy(self, app):
        """Test custom CSP policy"""
        csp = "default-src 'self'; script-src 'self'"
        app.add_middleware(
            SecurityHeadersMiddleware,
            content_security_policy=csp
        )
        client = TestClient(app)

        response = client.get("/test")

        assert response.headers.get("Content-Security-Policy") == csp

    def test_default_csp_production(self):
        """Test default CSP for production is strict"""
        csp = get_default_csp(is_production=True)

        # Production should have strict CSP
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "'unsafe-eval'" not in csp

    def test_default_csp_development(self):
        """Test default CSP for development is more permissive"""
        csp = get_default_csp(is_production=False)

        # Development allows unsafe-inline/eval for dev tools
        assert "default-src 'self'" in csp
        assert "'unsafe-inline'" in csp or "'unsafe-eval'" in csp


class TestCustomHeaders:
    """Test custom headers functionality"""

    def test_custom_headers_added(self, app):
        """Test that custom headers can be added"""
        app.add_middleware(
            SecurityHeadersMiddleware,
            custom_headers={
                "X-Custom-Header": "custom-value",
                "X-Another-Header": "another-value",
            }
        )
        client = TestClient(app)

        response = client.get("/test")

        assert response.headers.get("X-Custom-Header") == "custom-value"
        assert response.headers.get("X-Another-Header") == "another-value"


class TestDefaultPermissionsPolicy:
    """Test default Permissions-Policy"""

    def test_default_permissions_policy(self):
        """Test that default permissions policy disables sensitive features"""
        policy = get_default_permissions_policy()

        assert "geolocation=()" in policy
        assert "microphone=()" in policy
        assert "camera=()" in policy
        assert "payment=()" in policy


class TestAllHeadersCombined:
    """Test all security headers together"""

    def test_all_headers_added(self, app):
        """Test that all security headers are added when configured"""
        app.add_middleware(
            SecurityHeadersMiddleware,
            x_frame_options="DENY",
            x_content_type_options="nosniff",
            x_xss_protection="1; mode=block",
            enable_hsts=True,
            hsts_max_age=31536000,
            content_security_policy="default-src 'self'",
            referrer_policy="strict-origin-when-cross-origin",
            permissions_policy="geolocation=()",
        )
        client = TestClient(app)

        response = client.get("/test")

        # Verify all headers are present
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-XSS-Protection") == "1; mode=block"
        assert "max-age=" in response.headers.get("Strict-Transport-Security", "")
        assert response.headers.get("Content-Security-Policy") == "default-src 'self'"
        assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert response.headers.get("Permissions-Policy") == "geolocation=()"

    def test_headers_on_error_responses(self, app):
        """Test that security headers are added on HTTP error responses"""
        from fastapi import HTTPException

        @app.get("/error")
        async def error_endpoint():
            raise HTTPException(status_code=404, detail="Not found")

        app.add_middleware(
            SecurityHeadersMiddleware,
            x_frame_options="DENY",
            x_content_type_options="nosniff",
        )
        client = TestClient(app)

        response = client.get("/error")

        # Headers should be present on error responses
        assert response.status_code == 404
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert response.headers.get("X-Content-Type-Options") == "nosniff"

