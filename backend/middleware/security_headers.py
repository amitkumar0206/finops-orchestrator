"""
Security Headers Middleware

Adds essential security headers to all HTTP responses to protect against
common web vulnerabilities like clickjacking, XSS, and MIME sniffing.

Security Headers Added:
- X-Frame-Options: Prevents clickjacking attacks
- X-Content-Type-Options: Prevents MIME type sniffing
- X-XSS-Protection: Enables browser XSS filtering (legacy)
- Strict-Transport-Security: Enforces HTTPS connections
- Content-Security-Policy: Controls resource loading
- Referrer-Policy: Controls referrer information
- Permissions-Policy: Controls browser features

References:
- https://owasp.org/www-project-secure-headers/
- https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers
"""

from typing import Optional, Dict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
import structlog

logger = structlog.get_logger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware that adds security headers to all HTTP responses.

    This helps protect against common web vulnerabilities including:
    - Clickjacking (X-Frame-Options)
    - MIME type sniffing (X-Content-Type-Options)
    - Cross-site scripting (X-XSS-Protection, CSP)
    - Protocol downgrade attacks (HSTS)
    """

    def __init__(
        self,
        app,
        x_frame_options: str = "DENY",
        x_content_type_options: str = "nosniff",
        x_xss_protection: str = "1; mode=block",
        strict_transport_security: Optional[str] = None,
        content_security_policy: Optional[str] = None,
        referrer_policy: str = "strict-origin-when-cross-origin",
        permissions_policy: Optional[str] = None,
        enable_hsts: bool = False,
        hsts_max_age: int = 31536000,  # 1 year
        hsts_include_subdomains: bool = True,
        hsts_preload: bool = False,
        custom_headers: Optional[Dict[str, str]] = None,
    ):
        """
        Initialize security headers middleware.

        Args:
            app: The ASGI application
            x_frame_options: X-Frame-Options header value (DENY, SAMEORIGIN, or ALLOW-FROM uri)
            x_content_type_options: X-Content-Type-Options header value
            x_xss_protection: X-XSS-Protection header value
            strict_transport_security: Custom HSTS header (overrides enable_hsts settings)
            content_security_policy: Content-Security-Policy header value
            referrer_policy: Referrer-Policy header value
            permissions_policy: Permissions-Policy header value
            enable_hsts: Whether to enable HSTS (for production HTTPS)
            hsts_max_age: HSTS max-age in seconds (default: 1 year)
            hsts_include_subdomains: Include subdomains in HSTS
            hsts_preload: Enable HSTS preload (requires submission to preload list)
            custom_headers: Additional custom security headers
        """
        super().__init__(app)

        self.headers: Dict[str, str] = {}

        # X-Frame-Options - Prevents clickjacking
        if x_frame_options:
            self.headers["X-Frame-Options"] = x_frame_options

        # X-Content-Type-Options - Prevents MIME sniffing
        if x_content_type_options:
            self.headers["X-Content-Type-Options"] = x_content_type_options

        # X-XSS-Protection - Legacy XSS protection (still useful for older browsers)
        if x_xss_protection:
            self.headers["X-XSS-Protection"] = x_xss_protection

        # Strict-Transport-Security (HSTS) - Forces HTTPS
        if strict_transport_security:
            self.headers["Strict-Transport-Security"] = strict_transport_security
        elif enable_hsts:
            hsts_value = f"max-age={hsts_max_age}"
            if hsts_include_subdomains:
                hsts_value += "; includeSubDomains"
            if hsts_preload:
                hsts_value += "; preload"
            self.headers["Strict-Transport-Security"] = hsts_value

        # Content-Security-Policy - Controls resource loading
        if content_security_policy:
            self.headers["Content-Security-Policy"] = content_security_policy

        # Referrer-Policy - Controls referrer information
        if referrer_policy:
            self.headers["Referrer-Policy"] = referrer_policy

        # Permissions-Policy - Controls browser features
        if permissions_policy:
            self.headers["Permissions-Policy"] = permissions_policy

        # Add any custom headers
        if custom_headers:
            self.headers.update(custom_headers)

        logger.info(
            "security_headers_middleware_initialized",
            headers=list(self.headers.keys()),
            hsts_enabled=enable_hsts or bool(strict_transport_security),
            csp_enabled=bool(content_security_policy),
        )

    async def dispatch(self, request: Request, call_next) -> Response:
        """Add security headers to the response"""
        try:
            response = await call_next(request)
        except Exception:
            # Re-raise the exception - FastAPI's exception handlers will create
            # the response, and since this middleware wraps the whole app,
            # we'll add headers to that response too
            raise

        # Add all configured security headers
        for header_name, header_value in self.headers.items():
            response.headers[header_name] = header_value

        return response


def get_default_csp(is_production: bool = False) -> str:
    """
    Get a default Content-Security-Policy suitable for most applications.

    Args:
        is_production: Whether this is a production environment

    Returns:
        CSP header value string
    """
    if is_production:
        # Strict CSP for production
        return "; ".join([
            "default-src 'self'",
            "script-src 'self'",
            "style-src 'self' 'unsafe-inline'",  # unsafe-inline often needed for CSS frameworks
            "img-src 'self' data: https:",
            "font-src 'self'",
            "connect-src 'self'",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self'",
        ])
    else:
        # More permissive CSP for development
        return "; ".join([
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'",  # Allow for dev tools
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: https: http:",
            "font-src 'self' data:",
            "connect-src 'self' ws: wss: http: https:",  # Allow WebSocket for HMR
            "frame-ancestors 'self'",
        ])


def get_default_permissions_policy() -> str:
    """
    Get a default Permissions-Policy that disables unnecessary browser features.

    Returns:
        Permissions-Policy header value string
    """
    return ", ".join([
        "geolocation=()",
        "microphone=()",
        "camera=()",
        "payment=()",
        "usb=()",
    ])
