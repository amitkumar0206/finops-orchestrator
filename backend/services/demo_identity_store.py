"""Config-backed demo identity store for no-database demo deployments."""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

from backend.config.settings import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

PASSWORD_HASH_VERSION_CURRENT = 2
PASSWORD_HASH_ITERATIONS = {
    1: 100000,
    2: 600000,
}
DEFAULT_FEATURE_ACCESS = {
    "chat": False,
    "analyze": False,
    "generate": False,
    "opportunities": False,
    "cur_analysis": False,
    "admin_console": False,
}

# Default org-level monthly token budget if not set in store
DEFAULT_ORG_MONTHLY_TOKEN_BUDGET = 2_000_000


def estimate_text_tokens(text: str) -> int:
    """Approximate token count for demo usage tracking."""
    normalized = (text or "").strip()
    if not normalized:
        return 0
    return max(1, (len(normalized) + 3) // 4)


def _hash_password(password: str, salt: str, version: int = PASSWORD_HASH_VERSION_CURRENT) -> str:
    iterations = PASSWORD_HASH_ITERATIONS.get(version, PASSWORD_HASH_ITERATIONS[PASSWORD_HASH_VERSION_CURRENT])
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()


def _verify_password(password: str, salt: str, expected_hash: str, version: int = PASSWORD_HASH_VERSION_CURRENT) -> bool:
    computed_hash = _hash_password(password, salt, version)
    return secrets.compare_digest(computed_hash, expected_hash)


class DemoIdentityStore:
    """Lightweight JSON-backed identity, feature, and usage store for demo mode."""

    def __init__(self, store_path: Optional[str] = None):
        self._lock = asyncio.Lock()
        self._path = self._resolve_path(store_path or settings.demo_identity_store_path)

    def _resolve_path(self, raw_path: str) -> Path:
        path = Path(raw_path)
        if path.is_absolute():
            return path
        return Path(__file__).resolve().parents[2] / path

    def _read_unlocked(self) -> Dict[str, Any]:
        if settings.demo_identity_store_backend != "file":
            raise RuntimeError(
                f"Unsupported DEMO_IDENTITY_STORE_BACKEND='{settings.demo_identity_store_backend}'. "
                "Only 'file' is implemented in this demo build."
            )

        if not self._path.exists():
            raise FileNotFoundError(f"Demo identity store not found: {self._path}")

        with self._path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _write_unlocked(self, data: Dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
        tmp_path.replace(self._path)

    def _sanitize_user(
        self,
        user: Dict[str, Any],
        *,
        include_password_hint: bool = False,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        sanitized = deepcopy(user)
        for sensitive_key in ("password_hash", "password_salt", "password_hash_version"):
            sanitized.pop(sensitive_key, None)

        if not include_password_hint:
            sanitized.pop("demo_password_hint", None)

        usage = sanitized.setdefault("usage", {})
        if data is not None:
            _, limit, topup_tokens = self._effective_user_limit_unlocked(data, sanitized)
        else:
            limit = int(sanitized.get("monthly_token_limit") or 0)
            topup_tokens = max(int(sanitized.get("token_topup_tokens") or 0), 0)
        used = int(usage.get("monthly_token_used") or 0)
        usage["monthly_token_limit"] = limit
        usage["monthly_token_used"] = used
        usage["remaining_tokens"] = max(limit - used, 0) if limit else None
        usage["monthly_token_utilization_pct"] = round((used / limit) * 100, 1) if limit else 0.0

        sanitized["feature_access"] = {
            **DEFAULT_FEATURE_ACCESS,
            **(sanitized.get("feature_access") or {}),
        }
        sanitized["token_topup_tokens"] = topup_tokens
        sanitized["token_limit_override"] = topup_tokens > 0
        sanitized["effective_monthly_token_limit"] = limit
        return sanitized

    def _append_activity(
        self,
        data: Dict[str, Any],
        *,
        actor_user_id: str,
        action: str,
        target_user_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        activity_log = data.setdefault("activity_log", [])
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor_user_id": actor_user_id,
            "target_user_id": target_user_id,
            "action": action,
            "details": details or {},
        }
        activity_log.append(entry)
        if len(activity_log) > 300:
            del activity_log[:-300]

    def _get_user_index(self, data: Dict[str, Any], *, user_id: Optional[str] = None, email: Optional[str] = None) -> Optional[int]:
        users = data.get("users", [])
        for index, user in enumerate(users):
            if user_id and user.get("id") == user_id:
                return index
            if email and str(user.get("email", "")).lower() == email.lower():
                return index
        return None

    def _get_department_index(self, data: Dict[str, Any], *, dept_id: Optional[str] = None, name: Optional[str] = None) -> Optional[int]:
        departments = (data.get("organization") or {}).get("departments", [])
        for index, dept in enumerate(departments):
            if dept_id and dept.get("id") == dept_id:
                return index
            if name and str(dept.get("name", "")).lower() == name.lower():
                return index
        return None

    # ─── Department helpers ───────────────────────────────────────────────

    def _dept_usage_stats(self, data: Dict[str, Any], dept_id: str) -> Dict[str, Any]:
        """Compute aggregate token usage for a department from its users."""
        users = data.get("users", [])
        dept_users = [u for u in users if u.get("department_id") == dept_id]
        total_limit = sum(self._effective_user_limit_unlocked(data, u)[1] for u in dept_users)
        total_used = sum(int((u.get("usage") or {}).get("monthly_token_used") or 0) for u in dept_users)
        return {
            "user_count": len(dept_users),
            "active_user_count": len([u for u in dept_users if u.get("is_active", True)]),
            "total_user_token_limit": total_limit,
            "total_token_used": total_used,
            "total_token_remaining": max(total_limit - total_used, 0),
        }

    def _department_limit_unlocked(self, data: Dict[str, Any], department_id: Optional[str]) -> int:
        if not department_id:
            return 0
        dept_index = self._get_department_index(data, dept_id=department_id)
        if dept_index is None:
            return 0
        organization = data.get("organization") or {}
        departments = organization.get("departments") or []
        return int((departments[dept_index] or {}).get("monthly_token_limit") or 0)

    def _effective_user_limit_unlocked(self, data: Dict[str, Any], user: Dict[str, Any]) -> Tuple[int, int, int]:
        """Return (base_limit, effective_limit, topup_tokens) for a user."""
        department_id = user.get("department_id")
        topup_tokens = max(int(user.get("token_topup_tokens") or 0), 0)
        if department_id:
            base_limit = self._department_limit_unlocked(data, department_id)
        else:
            base_limit = int(user.get("monthly_token_limit") or 0)
        return base_limit, base_limit + topup_tokens, topup_tokens

    # ─── Public read methods ──────────────────────────────────────────────

    async def get_demo_catalog(self) -> List[Dict[str, Any]]:
        async with self._lock:
            data = self._read_unlocked()
            catalog = []
            for user in data.get("users", []):
                catalog.append({
                    "id": user.get("id"),
                    "email": user.get("email"),
                    "full_name": user.get("full_name"),
                    "org_role": user.get("org_role", "member"),
                    "department": user.get("department"),
                    "feature_access": {**DEFAULT_FEATURE_ACCESS, **(user.get("feature_access") or {})},
                    "demo_password_hint": user.get("demo_password_hint"),
                })
            return catalog

    async def get_organization(self) -> Dict[str, Any]:
        async with self._lock:
            data = self._read_unlocked()
            return deepcopy(data.get("organization") or {})

    async def get_user_record_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            data = self._read_unlocked()
            index = self._get_user_index(data, email=email)
            if index is None:
                return None
            return deepcopy(data["users"][index])

    async def get_user_record_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            data = self._read_unlocked()
            index = self._get_user_index(data, user_id=user_id)
            if index is None:
                return None
            return deepcopy(data["users"][index])

    async def get_user_view_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        record = await self.get_user_record_by_email(email)
        if not record:
            return None
        return self._sanitize_user(record)

    async def authenticate_user(self, email: str, password: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            data = self._read_unlocked()
            index = self._get_user_index(data, email=email)
            if index is None:
                return None

            user = data["users"][index]
            if not user.get("is_active", True):
                return None

            if not _verify_password(
                password=password,
                salt=str(user.get("password_salt") or ""),
                expected_hash=str(user.get("password_hash") or ""),
                version=int(user.get("password_hash_version") or PASSWORD_HASH_VERSION_CURRENT),
            ):
                return None

            user["last_login_at"] = datetime.now(timezone.utc).isoformat()
            usage = user.setdefault("usage", {})
            usage["logins"] = int(usage.get("logins") or 0) + 1
            usage["last_activity_at"] = user["last_login_at"]
            self._append_activity(
                data,
                actor_user_id=user["id"],
                action="login",
                target_user_id=user["id"],
                details={"email": user.get("email")},
            )
            self._write_unlocked(data)
            return deepcopy(user)

    async def list_users(self) -> List[Dict[str, Any]]:
        async with self._lock:
            data = self._read_unlocked()
            return [self._sanitize_user(user, data=data) for user in data.get("users", [])]

    # ─── Department CRUD ──────────────────────────────────────────────────

    async def list_departments(self) -> List[Dict[str, Any]]:
        """Return all departments with live usage statistics."""
        async with self._lock:
            data = self._read_unlocked()
            organization = data.get("organization") or {}
            departments = deepcopy(organization.get("departments") or [])
            for dept in departments:
                dept["usage"] = self._dept_usage_stats(data, dept["id"])
            return departments

    async def create_department(self, payload: Dict[str, Any], *, created_by: str) -> Dict[str, Any]:
        """Create a new department. Raises ValueError on duplicate name."""
        async with self._lock:
            data = self._read_unlocked()
            organization = data.setdefault("organization", {})
            departments = organization.setdefault("departments", [])

            name = str(payload.get("name") or "").strip()
            if not name:
                raise ValueError("Department name is required")
            if self._get_department_index(data, name=name) is not None:
                raise ValueError(f"A department named '{name}' already exists")

            monthly_token_limit = int(payload.get("monthly_token_limit") or 0)
            now_iso = datetime.now(timezone.utc).isoformat()
            dept = {
                "id": f"dept-{secrets.token_hex(8)}",
                "name": name,
                "description": str(payload.get("description") or "").strip() or None,
                "monthly_token_limit": monthly_token_limit,
                "created_at": now_iso,
                "updated_at": now_iso,
            }
            departments.append(dept)
            self._append_activity(
                data,
                actor_user_id=created_by,
                action="department_created",
                details={"department_name": name, "monthly_token_limit": monthly_token_limit},
            )
            self._write_unlocked(data)
            dept_out = deepcopy(dept)
            dept_out["usage"] = self._dept_usage_stats(data, dept["id"])
            return dept_out

    async def update_department(self, dept_id: str, updates: Dict[str, Any], *, updated_by: str) -> Dict[str, Any]:
        """Update an existing department. Raises ValueError if not found."""
        async with self._lock:
            data = self._read_unlocked()
            index = self._get_department_index(data, dept_id=dept_id)
            if index is None:
                raise ValueError("Department not found")

            organization = data.get("organization") or {}
            dept = organization["departments"][index]

            if "name" in updates:
                new_name = str(updates["name"] or "").strip()
                if not new_name:
                    raise ValueError("Department name cannot be blank")
                # Check for duplicate (ignore self)
                existing_index = self._get_department_index(data, name=new_name)
                if existing_index is not None and existing_index != index:
                    raise ValueError(f"A department named '{new_name}' already exists")
                dept["name"] = new_name

            if "description" in updates:
                dept["description"] = str(updates["description"] or "").strip() or None

            if "monthly_token_limit" in updates:
                dept["monthly_token_limit"] = int(updates["monthly_token_limit"] or 0)

            dept["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._append_activity(
                data,
                actor_user_id=updated_by,
                action="department_updated",
                details={"department_id": dept_id, "updated_fields": sorted(list(updates.keys()))},
            )
            self._write_unlocked(data)
            dept_out = deepcopy(dept)
            dept_out["usage"] = self._dept_usage_stats(data, dept_id)
            return dept_out

    async def delete_department(self, dept_id: str, *, deleted_by: str) -> None:
        """Delete a department. Raises ValueError if users are still assigned to it."""
        async with self._lock:
            data = self._read_unlocked()
            index = self._get_department_index(data, dept_id=dept_id)
            if index is None:
                raise ValueError("Department not found")

            # Check if any active users belong to this department
            users_in_dept = [u for u in data.get("users", []) if u.get("department_id") == dept_id]
            if users_in_dept:
                raise ValueError(
                    f"Cannot delete department: {len(users_in_dept)} user(s) are still assigned to it. "
                    "Move or reassign users first."
                )

            organization = data.get("organization") or {}
            dept_name = organization["departments"][index].get("name", dept_id)
            del organization["departments"][index]
            self._append_activity(
                data,
                actor_user_id=deleted_by,
                action="department_deleted",
                details={"department_id": dept_id, "department_name": dept_name},
            )
            self._write_unlocked(data)

    # ─── Org settings ─────────────────────────────────────────────────────

    async def get_org_settings(self) -> Dict[str, Any]:
        """Return org-level settings including the monthly token budget."""
        async with self._lock:
            data = self._read_unlocked()
            return self._compute_org_settings_unlocked(data)

    async def update_org_settings(self, updates: Dict[str, Any], *, updated_by: str) -> Dict[str, Any]:
        """Update org-level settings (name, monthly_token_budget). Admin only."""
        async with self._lock:
            data = self._read_unlocked()
            organization = data.setdefault("organization", {})

            if "monthly_token_budget" in updates:
                organization["monthly_token_budget"] = int(updates["monthly_token_budget"] or 0)

            if "name" in updates:
                name = str(updates["name"] or "").strip()
                if name:
                    organization["name"] = name

            self._append_activity(
                data,
                actor_user_id=updated_by,
                action="org_settings_updated",
                details={"updated_fields": sorted(list(updates.keys()))},
            )
            self._write_unlocked(data)
            # Return computed settings without re-acquiring the lock
            # (asyncio.Lock is not reentrant — calling get_org_settings() here would deadlock)
            return self._compute_org_settings_unlocked(data)

    def _compute_org_settings_unlocked(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Compute org settings dict from already-loaded data (call only while lock is held)."""
        organization = deepcopy(data.get("organization") or {})
        organization.setdefault("monthly_token_budget", DEFAULT_ORG_MONTHLY_TOKEN_BUDGET)
        users = data.get("users", [])
        total_used = sum(int((u.get("usage") or {}).get("monthly_token_used") or 0) for u in users)
        departments = organization.get("departments", [])
        total_dept_allocated = sum(int(d.get("monthly_token_limit") or 0) for d in departments)
        organization["usage"] = {
            "total_token_used": total_used,
            "total_dept_allocated": total_dept_allocated,
            "unallocated": max(organization["monthly_token_budget"] - total_dept_allocated, 0),
            "utilization_pct": round(
                (total_used / organization["monthly_token_budget"]) * 100, 1
            ) if organization["monthly_token_budget"] else 0.0,
        }
        return organization

    # ─── Token summary ────────────────────────────────────────────────────

    async def get_token_summary(self) -> Dict[str, Any]:
        """Return full token quota hierarchy: org → departments → users."""
        async with self._lock:
            data = self._read_unlocked()
            organization = data.get("organization") or {}
            org_budget = int(organization.get("monthly_token_budget") or DEFAULT_ORG_MONTHLY_TOKEN_BUDGET)
            departments = organization.get("departments") or []
            users = [self._sanitize_user(u, data=data) for u in data.get("users", [])]

            total_used = sum(int((u.get("usage") or {}).get("monthly_token_used") or 0) for u in users)
            total_dept_allocated = sum(int(d.get("monthly_token_limit") or 0) for d in departments)

            dept_summaries = []
            for dept in departments:
                dept_id = dept["id"]
                dept_users = [u for u in users if u.get("department_id") == dept_id]
                dept_used = sum(int((u.get("usage") or {}).get("monthly_token_used") or 0) for u in dept_users)
                dept_limit = int(dept.get("monthly_token_limit") or 0)
                dept_summaries.append({
                    "id": dept_id,
                    "name": dept["name"],
                    "description": dept.get("description"),
                    "monthly_token_limit": dept_limit,
                    "total_token_used": dept_used,
                    "total_token_remaining": max(dept_limit - dept_used, 0),
                    "utilization_pct": round((dept_used / dept_limit) * 100, 1) if dept_limit else 0.0,
                    "user_count": len(dept_users),
                    "users": [
                        {
                            "id": u["id"],
                            "full_name": u["full_name"],
                            "email": u["email"],
                            "monthly_token_limit": u.get("effective_monthly_token_limit") or 0,
                            "token_topup_tokens": u.get("token_topup_tokens") or 0,
                            "token_limit_override": (u.get("token_topup_tokens") or 0) > 0,
                            "monthly_token_used": (u.get("usage") or {}).get("monthly_token_used") or 0,
                            "utilization_pct": (u.get("usage") or {}).get("monthly_token_utilization_pct") or 0.0,
                        }
                        for u in dept_users
                    ],
                })

            # Users without a department
            unassigned_users = [u for u in users if not u.get("department_id")]

            return {
                "org_budget": org_budget,
                "total_dept_allocated": total_dept_allocated,
                "unallocated_budget": max(org_budget - total_dept_allocated, 0),
                "total_token_used": total_used,
                "org_utilization_pct": round((total_used / org_budget) * 100, 1) if org_budget else 0.0,
                "departments": dept_summaries,
                "unassigned_user_count": len(unassigned_users),
            }

    # ─── User CRUD ────────────────────────────────────────────────────────

    async def create_user(self, payload: Dict[str, Any], *, created_by: str) -> Tuple[Dict[str, Any], Optional[str]]:
        async with self._lock:
            data = self._read_unlocked()
            if self._get_user_index(data, email=str(payload.get("email") or "")) is not None:
                raise ValueError("A user with that email already exists")

            # Department validation
            department_id = str(payload.get("department_id") or "").strip() or None
            department_name: Optional[str] = None
            if department_id:
                dept_index = self._get_department_index(data, dept_id=department_id)
                if dept_index is None:
                    raise ValueError(f"Department with id '{department_id}' not found")
                organization = data.get("organization") or {}
                department_name = organization["departments"][dept_index].get("name")
            elif str(payload.get("department") or "").strip():
                # Fall back to department name look-up for backwards compatibility
                department_name = str(payload.get("department") or "").strip()
                dept_index = self._get_department_index(data, name=department_name)
                if dept_index is not None:
                    organization = data.get("organization") or {}
                    department_id = organization["departments"][dept_index].get("id")

            generated_password = None
            password = str(payload.get("password") or "").strip()
            if not password:
                generated_password = secrets.token_urlsafe(10)
                password = generated_password

            salt = secrets.token_hex(32)
            feature_access = {
                **DEFAULT_FEATURE_ACCESS,
                **(payload.get("feature_access") or {}),
            }

            organization = data.get("organization") or {}
            default_accounts = organization.get("allowed_account_ids") or []
            now_iso = datetime.now(timezone.utc).isoformat()

            user = {
                "id": secrets.token_hex(16),
                "email": str(payload.get("email") or "").strip().lower(),
                "full_name": str(payload.get("full_name") or "").strip() or str(payload.get("email") or ""),
                "department": department_name,
                "department_id": department_id,
                "title": str(payload.get("title") or "").strip() or None,
                "org_role": str(payload.get("org_role") or "member").strip() or "member",
                "is_active": bool(payload.get("is_active", True)),
                "is_admin": bool(payload.get("is_admin", False)),
                "allowed_account_ids": list(payload.get("allowed_account_ids") or default_accounts),
                "feature_access": feature_access,
                "monthly_token_limit": int(payload.get("monthly_token_limit") or 250000),
                "token_topup_tokens": max(int(payload.get("token_topup_tokens") or 0), 0),
                "token_limit_override": bool(payload.get("token_topup_tokens") or 0),
                "usage": {
                    "monthly_token_used": 0,
                    "queries_run": 0,
                    "analysis_runs": 0,
                    "generate_runs": 0,
                    "logins": 0,
                    "feature_usage": {},
                    "last_activity_at": now_iso,
                },
                "preferences": {},
                "password_salt": salt,
                "password_hash": _hash_password(password, salt),
                "password_hash_version": PASSWORD_HASH_VERSION_CURRENT,
                "created_at": now_iso,
                "updated_at": now_iso,
            }
            data.setdefault("users", []).append(user)
            self._append_activity(
                data,
                actor_user_id=created_by,
                action="user_created",
                target_user_id=user["id"],
                details={
                    "email": user["email"],
                    "org_role": user["org_role"],
                    "department_id": department_id,
                },
            )
            self._write_unlocked(data)
            return self._sanitize_user(user, data=data), generated_password

    async def update_user(self, user_id: str, updates: Dict[str, Any], *, updated_by: str) -> Dict[str, Any]:
        async with self._lock:
            data = self._read_unlocked()
            index = self._get_user_index(data, user_id=user_id)
            if index is None:
                raise ValueError("User not found")

            user = data["users"][index]
            mutable_fields = {
                "full_name",
                "title",
                "org_role",
                "is_active",
                "is_admin",
                "monthly_token_limit",
                "token_topup_tokens",
            }

            for field in mutable_fields:
                if field in updates:
                    user[field] = updates[field]

            if "token_limit_override" in updates and "token_topup_tokens" not in updates:
                # Backward compatibility for older clients toggling the legacy flag.
                if not bool(updates.get("token_limit_override")):
                    user["token_topup_tokens"] = 0

            user["token_topup_tokens"] = max(int(user.get("token_topup_tokens") or 0), 0)
            user["token_limit_override"] = user["token_topup_tokens"] > 0

            # Department change
            if "department_id" in updates:
                new_dept_id = str(updates["department_id"] or "").strip() or None
                if new_dept_id:
                    dept_index = self._get_department_index(data, dept_id=new_dept_id)
                    if dept_index is None:
                        raise ValueError(f"Department with id '{new_dept_id}' not found")
                    organization = data.get("organization") or {}
                    user["department"] = organization["departments"][dept_index].get("name")
                else:
                    user["department"] = None
                user["department_id"] = new_dept_id
            elif "department" in updates:
                # Legacy name-based update (for backwards compatibility)
                dept_name = str(updates["department"] or "").strip() or None
                if dept_name:
                    dept_index = self._get_department_index(data, name=dept_name)
                    if dept_index is not None:
                        organization = data.get("organization") or {}
                        user["department_id"] = organization["departments"][dept_index].get("id")
                user["department"] = dept_name

            if "allowed_account_ids" in updates:
                user["allowed_account_ids"] = list(updates.get("allowed_account_ids") or [])

            if "feature_access" in updates:
                user["feature_access"] = {
                    **DEFAULT_FEATURE_ACCESS,
                    **(user.get("feature_access") or {}),
                    **(updates.get("feature_access") or {}),
                }

            password = str(updates.get("password") or "").strip()
            if password:
                salt = secrets.token_hex(32)
                user["password_salt"] = salt
                user["password_hash"] = _hash_password(password, salt)
                user["password_hash_version"] = PASSWORD_HASH_VERSION_CURRENT

            user["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._append_activity(
                data,
                actor_user_id=updated_by,
                action="user_updated",
                target_user_id=user_id,
                details={
                    "updated_fields": sorted(list(updates.keys())),
                },
            )
            self._write_unlocked(data)
            return self._sanitize_user(user, data=data)

    async def get_user_usage(self, user_id: str) -> Dict[str, Any]:
        async with self._lock:
            data = self._read_unlocked()
            index = self._get_user_index(data, user_id=user_id)
            if index is None:
                raise ValueError("User not found")

            user = data["users"][index]
            activities = [
                activity for activity in data.get("activity_log", [])
                if activity.get("actor_user_id") == user_id or activity.get("target_user_id") == user_id
            ][-20:]

            sanitized_user = self._sanitize_user(user, data=data)
            return {
                "user": sanitized_user,
                "usage": sanitized_user.get("usage") or {},
                "recent_activity": activities[::-1],
            }

    async def get_admin_summary(self) -> Dict[str, Any]:
        async with self._lock:
            data = self._read_unlocked()
            organization = data.get("organization") or {}
            users = [self._sanitize_user(user, data=data) for user in data.get("users", [])]
            active_users = [user for user in users if user.get("is_active", True)]
            total_limit = sum(int(user.get("monthly_token_limit") or 0) for user in users)
            total_used = sum(int((user.get("usage") or {}).get("monthly_token_used") or 0) for user in users)
            org_budget = int(organization.get("monthly_token_budget") or DEFAULT_ORG_MONTHLY_TOKEN_BUDGET)
            departments = organization.get("departments") or []
            total_dept_allocated = sum(int(d.get("monthly_token_limit") or 0) for d in departments)

            feature_counts = {key: 0 for key in DEFAULT_FEATURE_ACCESS}
            for user in users:
                for feature, enabled in (user.get("feature_access") or {}).items():
                    if enabled and feature in feature_counts:
                        feature_counts[feature] += 1

            dept_summaries = []
            for dept in departments:
                dept_id = dept["id"]
                dept_users = [u for u in users if u.get("department_id") == dept_id]
                dept_used = sum(int((u.get("usage") or {}).get("monthly_token_used") or 0) for u in dept_users)
                dept_limit = int(dept.get("monthly_token_limit") or 0)
                dept_summaries.append({
                    "id": dept_id,
                    "name": dept["name"],
                    "description": dept.get("description"),
                    "monthly_token_limit": dept_limit,
                    "total_token_used": dept_used,
                    "user_count": len(dept_users),
                    "utilization_pct": round((dept_used / dept_limit) * 100, 1) if dept_limit else 0.0,
                })

            return {
                "organization": deepcopy(organization),
                "totals": {
                    "user_count": len(users),
                    "active_user_count": len(active_users),
                    "admin_count": len([user for user in users if user.get("is_admin")]),
                    "department_count": len(departments),
                    "org_monthly_token_budget": org_budget,
                    "total_dept_allocated": total_dept_allocated,
                    "unallocated_budget": max(org_budget - total_dept_allocated, 0),
                    "monthly_token_limit": total_limit,
                    "monthly_token_used": total_used,
                    "monthly_token_remaining": max(total_limit - total_used, 0),
                },
                "feature_access_counts": feature_counts,
                "recent_activity": list(reversed((data.get("activity_log") or [])[-30:])),
                "users": users,
                "departments": dept_summaries,
            }

    async def record_feature_usage(
        self,
        user_id: str,
        *,
        feature: str,
        tokens_used: int = 0,
        request_units: int = 1,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        async with self._lock:
            data = self._read_unlocked()
            index = self._get_user_index(data, user_id=user_id)
            if index is None:
                return

            user = data["users"][index]
            usage = user.setdefault("usage", {})
            feature_usage = usage.setdefault("feature_usage", {})
            feature_usage[feature] = int(feature_usage.get(feature) or 0) + max(int(request_units), 0)
            usage["monthly_token_used"] = int(usage.get("monthly_token_used") or 0) + max(int(tokens_used), 0)
            usage["last_activity_at"] = datetime.now(timezone.utc).isoformat()

            if feature == "chat":
                usage["queries_run"] = int(usage.get("queries_run") or 0) + max(int(request_units), 0)
            elif feature == "analyze":
                usage["analysis_runs"] = int(usage.get("analysis_runs") or 0) + max(int(request_units), 0)
            elif feature == "generate":
                usage["generate_runs"] = int(usage.get("generate_runs") or 0) + max(int(request_units), 0)

            self._append_activity(
                data,
                actor_user_id=user_id,
                target_user_id=user_id,
                action=f"feature_usage:{feature}",
                details={
                    "tokens_used": max(int(tokens_used), 0),
                    "request_units": max(int(request_units), 0),
                    **(details or {}),
                },
            )
            self._write_unlocked(data)


_demo_identity_store: Optional[DemoIdentityStore] = None


def get_demo_identity_store() -> DemoIdentityStore:
    global _demo_identity_store
    if _demo_identity_store is None:
        _demo_identity_store = DemoIdentityStore()
    return _demo_identity_store


