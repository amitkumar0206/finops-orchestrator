"""Feature access enforcement for config-backed demo identities."""

from __future__ import annotations

from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from backend.config.settings import get_settings
from backend.services.demo_identity_store import get_demo_identity_store

settings = get_settings()


class FeatureAccessMiddleware(BaseHTTPMiddleware):
    """Enforce per-feature access and token quotas in config-backed demo mode."""

    def _required_feature(self, path: str) -> Optional[str]:
        if path.startswith("/api/demo/admin"):
            return "admin_console"
        if path.startswith("/api/v1/chat") or path.startswith("/api/v1/stream") or path.startswith("/api/v1/suggestions") or path.startswith("/api/v1/conversations"):
            return "chat"
        if path.startswith("/api/v1/iac-generate/"):
            return "generate"
        if path.startswith("/api/v1/iac/") or path.startswith("/api/v1/opportunities"):
            return "analyze"
        return None

    async def dispatch(self, request: Request, call_next) -> Response:
        if not settings.config_demo_auth_enabled:
            return await call_next(request)

        required_feature = self._required_feature(request.url.path)
        if not required_feature:
            return await call_next(request)

        auth_user = getattr(request.state, "auth_user", None)
        if not auth_user or not auth_user.is_authenticated:
            return JSONResponse(status_code=401, content={"detail": "Authentication required"})

        store = get_demo_identity_store()
        user_record = await store.get_user_record_by_email(auth_user.email)
        if not user_record or not user_record.get("is_active", True):
            return JSONResponse(status_code=403, content={"detail": "User is not active in the demo store"})

        if user_record.get("is_admin"):
            return await call_next(request)

        feature_access = user_record.get("feature_access") or {}
        if not feature_access.get(required_feature, False):
            return JSONResponse(
                status_code=403,
                content={"detail": f"Feature '{required_feature}' is disabled for this user"},
            )

        if required_feature in {"chat", "analyze", "generate"}:
            usage = user_record.get("usage") or {}
            token_limit = int(user_record.get("monthly_token_limit") or 0)
            token_used = int(usage.get("monthly_token_used") or 0)
            if token_limit and token_used >= token_limit:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Monthly demo token allotment exhausted for this user"},
                )

        return await call_next(request)