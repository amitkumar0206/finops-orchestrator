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
    "admin_console": False,
}


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

    def _sanitize_user(self, user: Dict[str, Any], *, include_password_hint: bool = False) -> Dict[str, Any]:
        sanitized = deepcopy(user)
        for sensitive_key in ("password_hash", "password_salt", "password_hash_version"):
            sanitized.pop(sensitive_key, None)

        if not include_password_hint:
            sanitized.pop("demo_password_hint", None)

        usage = sanitized.setdefault("usage", {})
        limit = int(sanitized.get("monthly_token_limit") or 0)
        used = int(usage.get("monthly_token_used") or 0)
        usage["monthly_token_limit"] = limit
        usage["monthly_token_used"] = used
        usage["remaining_tokens"] = max(limit - used, 0) if limit else None
        usage["monthly_token_utilization_pct"] = round((used / limit) * 100, 1) if limit else 0.0

        sanitized["feature_access"] = {
            **DEFAULT_FEATURE_ACCESS,
            **(sanitized.get("feature_access") or {}),
        }
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
            return [self._sanitize_user(user) for user in data.get("users", [])]

    async def create_user(self, payload: Dict[str, Any], *, created_by: str) -> Tuple[Dict[str, Any], Optional[str]]:
        async with self._lock:
            data = self._read_unlocked()
            if self._get_user_index(data, email=str(payload.get("email") or "")) is not None:
                raise ValueError("A user with that email already exists")

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
                "department": str(payload.get("department") or "").strip() or None,
                "title": str(payload.get("title") or "").strip() or None,
                "org_role": str(payload.get("org_role") or "member").strip() or "member",
                "is_active": bool(payload.get("is_active", True)),
                "is_admin": bool(payload.get("is_admin", False)),
                "allowed_account_ids": list(payload.get("allowed_account_ids") or default_accounts),
                "feature_access": feature_access,
                "monthly_token_limit": int(payload.get("monthly_token_limit") or 250000),
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
                },
            )
            self._write_unlocked(data)
            return self._sanitize_user(user), generated_password

    async def update_user(self, user_id: str, updates: Dict[str, Any], *, updated_by: str) -> Dict[str, Any]:
        async with self._lock:
            data = self._read_unlocked()
            index = self._get_user_index(data, user_id=user_id)
            if index is None:
                raise ValueError("User not found")

            user = data["users"][index]
            mutable_fields = {
                "full_name",
                "department",
                "title",
                "org_role",
                "is_active",
                "is_admin",
                "monthly_token_limit",
            }

            for field in mutable_fields:
                if field in updates:
                    user[field] = updates[field]

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
            return self._sanitize_user(user)

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

            sanitized_user = self._sanitize_user(user)
            return {
                "user": sanitized_user,
                "usage": sanitized_user.get("usage") or {},
                "recent_activity": activities[::-1],
            }

    async def get_admin_summary(self) -> Dict[str, Any]:
        async with self._lock:
            data = self._read_unlocked()
            users = [self._sanitize_user(user) for user in data.get("users", [])]
            active_users = [user for user in users if user.get("is_active", True)]
            total_limit = sum(int(user.get("monthly_token_limit") or 0) for user in users)
            total_used = sum(int((user.get("usage") or {}).get("monthly_token_used") or 0) for user in users)
            feature_counts = {key: 0 for key in DEFAULT_FEATURE_ACCESS}
            for user in users:
                for feature, enabled in (user.get("feature_access") or {}).items():
                    if enabled and feature in feature_counts:
                        feature_counts[feature] += 1

            return {
                "organization": deepcopy(data.get("organization") or {}),
                "totals": {
                    "user_count": len(users),
                    "active_user_count": len(active_users),
                    "admin_count": len([user for user in users if user.get("is_admin")]),
                    "monthly_token_limit": total_limit,
                    "monthly_token_used": total_used,
                    "monthly_token_remaining": max(total_limit - total_used, 0),
                },
                "feature_access_counts": feature_counts,
                "recent_activity": list(reversed((data.get("activity_log") or [])[-30:])),
                "users": users,
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