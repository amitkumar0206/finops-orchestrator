"""Admin and self-service endpoints for config-backed demo identities."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from backend.config.settings import get_settings
from backend.middleware.authentication import AuthenticatedUser, require_auth
from backend.services.demo_identity_store import get_demo_identity_store

router = APIRouter(prefix="/api/demo", tags=["demo-admin"])
settings = get_settings()


def _ensure_demo_identity_mode() -> None:
    if not settings.config_demo_auth_enabled:
        raise HTTPException(status_code=404, detail="Config-backed demo identity mode is not enabled")


def _require_admin_user(user: AuthenticatedUser) -> None:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")


# ─── Request / Response models ─────────────────────────────────────────────────

class DemoUserUsageResponse(BaseModel):
    user: Dict[str, Any]
    usage: Dict[str, Any]
    recent_activity: List[Dict[str, Any]]


class DemoAdminSummaryResponse(BaseModel):
    organization: Dict[str, Any]
    totals: Dict[str, Any]
    feature_access_counts: Dict[str, int]
    recent_activity: List[Dict[str, Any]]
    users: List[Dict[str, Any]]
    departments: List[Dict[str, Any]]


class DemoUserCreateRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=120)
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)
    department: Optional[str] = Field(default=None, max_length=120)
    department_id: Optional[str] = Field(default=None, max_length=120)
    title: Optional[str] = Field(default=None, max_length=120)
    org_role: str = Field(default="member", pattern="^(owner|admin|member|viewer|developer|devops)$")
    is_admin: bool = False
    is_active: bool = True
    monthly_token_limit: int = Field(default=250000, ge=0, le=50000000)
    token_limit_override: bool = False
    token_topup_tokens: int = Field(default=0, ge=0, le=50000000)
    allowed_account_ids: List[str] = Field(default_factory=list)
    feature_access: Dict[str, bool] = Field(default_factory=dict)


class DemoUserUpdateRequest(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)
    department: Optional[str] = Field(default=None, max_length=120)
    department_id: Optional[str] = Field(default=None, max_length=120)
    title: Optional[str] = Field(default=None, max_length=120)
    org_role: Optional[str] = Field(default=None, pattern="^(owner|admin|member|viewer|developer|devops)$")
    is_admin: Optional[bool] = None
    is_active: Optional[bool] = None
    monthly_token_limit: Optional[int] = Field(default=None, ge=0, le=50000000)
    token_limit_override: Optional[bool] = None
    token_topup_tokens: Optional[int] = Field(default=None, ge=0, le=50000000)
    allowed_account_ids: Optional[List[str]] = None
    feature_access: Optional[Dict[str, bool]] = None


class DepartmentCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: Optional[str] = Field(default=None, max_length=500)
    monthly_token_limit: int = Field(default=0, ge=0, le=500000000)


class DepartmentUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    description: Optional[str] = Field(default=None, max_length=500)
    monthly_token_limit: Optional[int] = Field(default=None, ge=0, le=500000000)


class OrgSettingsUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=200)
    monthly_token_budget: Optional[int] = Field(default=None, ge=0, le=5000000000)


# ─── Self-service endpoints ────────────────────────────────────────────────────

@router.get("/me/usage", response_model=DemoUserUsageResponse)
async def get_my_demo_usage(user: AuthenticatedUser = Depends(require_auth)):
    _ensure_demo_identity_mode()
    store = get_demo_identity_store()
    usage = await store.get_user_usage(user.user_id)
    return DemoUserUsageResponse(**usage)


# ─── Admin summary ─────────────────────────────────────────────────────────────

@router.get("/admin/summary", response_model=DemoAdminSummaryResponse)
async def get_demo_admin_summary(user: AuthenticatedUser = Depends(require_auth)):
    _ensure_demo_identity_mode()
    _require_admin_user(user)
    store = get_demo_identity_store()
    summary = await store.get_admin_summary()
    return DemoAdminSummaryResponse(**summary)


# ─── User management ───────────────────────────────────────────────────────────

@router.get("/admin/users")
async def list_demo_users(user: AuthenticatedUser = Depends(require_auth)):
    _ensure_demo_identity_mode()
    _require_admin_user(user)
    store = get_demo_identity_store()
    return {"users": await store.list_users()}


@router.post("/admin/users")
async def create_demo_user(payload: DemoUserCreateRequest, user: AuthenticatedUser = Depends(require_auth)):
    _ensure_demo_identity_mode()
    _require_admin_user(user)
    store = get_demo_identity_store()
    try:
        created_user, generated_password = await store.create_user(payload.model_dump(), created_by=user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "user": created_user,
        "generated_password": generated_password,
    }


@router.patch("/admin/users/{user_id}")
async def update_demo_user(user_id: str, payload: DemoUserUpdateRequest, user: AuthenticatedUser = Depends(require_auth)):
    _ensure_demo_identity_mode()
    _require_admin_user(user)
    store = get_demo_identity_store()
    updates = {key: value for key, value in payload.model_dump().items() if value is not None}
    try:
        updated_user = await store.update_user(user_id, updates, updated_by=user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {"user": updated_user}


# ─── Department management ─────────────────────────────────────────────────────

@router.get("/admin/departments")
async def list_departments(user: AuthenticatedUser = Depends(require_auth)):
    """List all departments with live usage statistics."""
    _ensure_demo_identity_mode()
    _require_admin_user(user)
    store = get_demo_identity_store()
    departments = await store.list_departments()
    return {"departments": departments}


@router.post("/admin/departments")
async def create_department(payload: DepartmentCreateRequest, user: AuthenticatedUser = Depends(require_auth)):
    """Create a new department."""
    _ensure_demo_identity_mode()
    _require_admin_user(user)
    store = get_demo_identity_store()
    try:
        department = await store.create_department(payload.model_dump(), created_by=user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"department": department}


@router.patch("/admin/departments/{dept_id}")
async def update_department(dept_id: str, payload: DepartmentUpdateRequest, user: AuthenticatedUser = Depends(require_auth)):
    """Update an existing department's name, description, or token limit."""
    _ensure_demo_identity_mode()
    _require_admin_user(user)
    store = get_demo_identity_store()
    updates = {key: value for key, value in payload.model_dump().items() if value is not None}
    try:
        department = await store.update_department(dept_id, updates, updated_by=user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"department": department}


@router.delete("/admin/departments/{dept_id}")
async def delete_department(dept_id: str, user: AuthenticatedUser = Depends(require_auth)):
    """Delete a department. Fails if any users are still assigned to it."""
    _ensure_demo_identity_mode()
    _require_admin_user(user)
    store = get_demo_identity_store()
    try:
        await store.delete_department(dept_id, deleted_by=user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"detail": "Department deleted successfully"}


# ─── Org settings ──────────────────────────────────────────────────────────────

@router.get("/admin/org-settings")
async def get_org_settings(user: AuthenticatedUser = Depends(require_auth)):
    """Return org-level settings including the monthly token budget."""
    _ensure_demo_identity_mode()
    _require_admin_user(user)
    store = get_demo_identity_store()
    org = await store.get_org_settings()
    return {"organization": org}


@router.patch("/admin/org-settings")
async def update_org_settings(payload: OrgSettingsUpdateRequest, user: AuthenticatedUser = Depends(require_auth)):
    """Update the org-level monthly token budget or name. Admin only."""
    _ensure_demo_identity_mode()
    _require_admin_user(user)
    store = get_demo_identity_store()
    updates = {key: value for key, value in payload.model_dump().items() if value is not None}
    try:
        org = await store.update_org_settings(updates, updated_by=user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"organization": org}


# ─── Token quota summary ───────────────────────────────────────────────────────

@router.get("/admin/token-summary")
async def get_token_summary(user: AuthenticatedUser = Depends(require_auth)):
    """Return full token quota hierarchy: org → departments → users."""
    _ensure_demo_identity_mode()
    _require_admin_user(user)
    store = get_demo_identity_store()
    summary = await store.get_token_summary()
    return summary
