"""
Tests for token quota management and department features.

Covers:
- Department CRUD (create / list / update / delete)
- Org-level token budget (get / update)
- User ↔ department assignment (create_user, update_user)
- Per-user token limit override flag
- Token summary hierarchy (org → dept → users)
- Admin-only guard logic via the API endpoints
- Regression: admin summary includes departments + org budget fields
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.demo_identity_store import (
    DEFAULT_ORG_MONTHLY_TOKEN_BUDGET,
    DemoIdentityStore,
    _hash_password,
)

# ─── Fixtures ─────────────────────────────────────────────────────────────────

ADMIN_ID = "aaaa-0000-admin"
MEMBER_ID = "bbbb-1111-member"
DEPT_ID = "dept-test-engineering"


def _minimal_store_data() -> Dict[str, Any]:
    """Return a minimal but valid demo identity store dict."""
    salt = "testsalt1234"
    # Use version=1 (100k iterations) in tests so fixtures run fast without
    # affecting business logic being tested.
    pw_hash = _hash_password("TestPass!99", salt, version=1)
    return {
        "version": 2,
        "organization": {
            "id": "org-test-001",
            "name": "Test Org",
            "slug": "test-org",
            "subscription_tier": "enterprise",
            "monthly_token_budget": 1_000_000,
            "allowed_account_ids": ["000000000000"],
            "departments": [
                {
                    "id": DEPT_ID,
                    "name": "Engineering",
                    "description": "Core engineering team",
                    "monthly_token_limit": 400_000,
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                }
            ],
        },
        "users": [
            {
                "id": ADMIN_ID,
                "email": "admin@test.demo",
                "full_name": "Test Admin",
                "department": "Engineering",
                "department_id": DEPT_ID,
                "title": "Platform Lead",
                "org_role": "owner",
                "is_admin": True,
                "is_active": True,
                "token_topup_tokens": 50_000,
                "token_limit_override": True,
                "monthly_token_limit": 500_000,
                "allowed_account_ids": ["000000000000"],
                "feature_access": {
                    "chat": True,
                    "analyze": True,
                    "generate": True,
                    "opportunities": True,
                    "admin_console": True,
                },
                "usage": {
                    "monthly_token_used": 120_000,
                    "queries_run": 50,
                    "analysis_runs": 5,
                    "generate_runs": 3,
                    "logins": 8,
                    "feature_usage": {},
                    "last_activity_at": "2026-04-01T10:00:00+00:00",
                },
                "preferences": {},
                "password_salt": salt,
                "password_hash": pw_hash,
                "password_hash_version": 1,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            },
            {
                "id": MEMBER_ID,
                "email": "member@test.demo",
                "full_name": "Test Member",
                "department": "Engineering",
                "department_id": DEPT_ID,
                "title": "Engineer",
                "org_role": "member",
                "is_admin": False,
                "is_active": True,
                "token_topup_tokens": 0,
                "token_limit_override": False,
                "monthly_token_limit": 200_000,
                "allowed_account_ids": ["000000000000"],
                "feature_access": {
                    "chat": True,
                    "analyze": True,
                    "generate": False,
                    "opportunities": True,
                    "admin_console": False,
                },
                "usage": {
                    "monthly_token_used": 80_000,
                    "queries_run": 30,
                    "analysis_runs": 2,
                    "generate_runs": 0,
                    "logins": 5,
                    "feature_usage": {},
                    "last_activity_at": "2026-04-01T08:00:00+00:00",
                },
                "preferences": {},
                "password_salt": salt,
                "password_hash": pw_hash,
                "password_hash_version": 1,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            },
        ],
        "activity_log": [],
    }


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    """Write minimal store JSON to tmp file and return path."""
    p = tmp_path / "demo_identity_store.json"
    p.write_text(json.dumps(_minimal_store_data(), indent=2))
    return p


@pytest.fixture
def store(store_path: Path) -> DemoIdentityStore:
    """Return a DemoIdentityStore pointing to the temp file."""
    with (
        patch("backend.services.demo_identity_store.settings") as mock_settings,
    ):
        mock_settings.demo_identity_store_path = str(store_path)
        mock_settings.demo_identity_store_backend = "file"
        s = DemoIdentityStore(store_path=str(store_path))
        yield s


# ─── Department CRUD ──────────────────────────────────────────────────────────

class TestDepartmentCRUD:

    @pytest.mark.asyncio
    async def test_list_departments_returns_existing(self, store: DemoIdentityStore):
        depts = await store.list_departments()
        assert len(depts) == 1
        dept = depts[0]
        assert dept["name"] == "Engineering"
        assert dept["monthly_token_limit"] == 400_000

    @pytest.mark.asyncio
    async def test_list_departments_includes_usage_stats(self, store: DemoIdentityStore):
        depts = await store.list_departments()
        usage = depts[0]["usage"]
        assert usage["user_count"] == 2
        assert usage["active_user_count"] == 2
        assert usage["total_token_used"] == 120_000 + 80_000

    @pytest.mark.asyncio
    async def test_create_department(self, store: DemoIdentityStore):
        dept = await store.create_department(
            {"name": "Data Science", "description": "ML team", "monthly_token_limit": 300_000},
            created_by=ADMIN_ID,
        )
        assert dept["name"] == "Data Science"
        assert dept["monthly_token_limit"] == 300_000
        assert dept["id"].startswith("dept-")

        # Verify persisted
        depts = await store.list_departments()
        assert any(d["name"] == "Data Science" for d in depts)

    @pytest.mark.asyncio
    async def test_create_department_duplicate_name_raises(self, store: DemoIdentityStore):
        with pytest.raises(ValueError, match="already exists"):
            await store.create_department(
                {"name": "Engineering", "monthly_token_limit": 0},
                created_by=ADMIN_ID,
            )

    @pytest.mark.asyncio
    async def test_update_department(self, store: DemoIdentityStore):
        updated = await store.update_department(
            DEPT_ID,
            {"monthly_token_limit": 600_000, "description": "Updated desc"},
            updated_by=ADMIN_ID,
        )
        assert updated["monthly_token_limit"] == 600_000
        assert updated["description"] == "Updated desc"

    @pytest.mark.asyncio
    async def test_update_department_name(self, store: DemoIdentityStore):
        updated = await store.update_department(DEPT_ID, {"name": "Platform Engineering"}, updated_by=ADMIN_ID)
        assert updated["name"] == "Platform Engineering"

    @pytest.mark.asyncio
    async def test_update_department_not_found(self, store: DemoIdentityStore):
        with pytest.raises(ValueError, match="not found"):
            await store.update_department("dept-nonexistent", {"name": "X"}, updated_by=ADMIN_ID)

    @pytest.mark.asyncio
    async def test_delete_department_with_users_raises(self, store: DemoIdentityStore):
        with pytest.raises(ValueError, match="user"):
            await store.delete_department(DEPT_ID, deleted_by=ADMIN_ID)

    @pytest.mark.asyncio
    async def test_delete_department_success(self, store: DemoIdentityStore):
        # Move users out first, then delete
        await store.update_user(ADMIN_ID, {"department_id": None}, updated_by=ADMIN_ID)
        await store.update_user(MEMBER_ID, {"department_id": None}, updated_by=ADMIN_ID)

        await store.delete_department(DEPT_ID, deleted_by=ADMIN_ID)
        depts = await store.list_departments()
        assert not any(d["id"] == DEPT_ID for d in depts)

    @pytest.mark.asyncio
    async def test_delete_department_not_found(self, store: DemoIdentityStore):
        with pytest.raises(ValueError, match="not found"):
            await store.delete_department("dept-does-not-exist", deleted_by=ADMIN_ID)


# ─── Org Settings ─────────────────────────────────────────────────────────────

class TestOrgSettings:

    @pytest.mark.asyncio
    async def test_get_org_settings(self, store: DemoIdentityStore):
        org = await store.get_org_settings()
        assert org["monthly_token_budget"] == 1_000_000
        assert "usage" in org
        usage = org["usage"]
        assert usage["total_dept_allocated"] == 400_000
        assert usage["unallocated"] == 600_000

    @pytest.mark.asyncio
    async def test_update_org_monthly_budget(self, store: DemoIdentityStore):
        org = await store.update_org_settings({"monthly_token_budget": 5_000_000}, updated_by=ADMIN_ID)
        assert org["monthly_token_budget"] == 5_000_000

    @pytest.mark.asyncio
    async def test_update_org_name(self, store: DemoIdentityStore):
        org = await store.update_org_settings({"name": "Acme Corp"}, updated_by=ADMIN_ID)
        assert org["name"] == "Acme Corp"

    @pytest.mark.asyncio
    async def test_org_settings_utilization_pct(self, store: DemoIdentityStore):
        org = await store.get_org_settings()
        # 200k used / 1M budget = 20%
        assert org["usage"]["utilization_pct"] == pytest.approx(20.0, abs=0.5)

    @pytest.mark.asyncio
    async def test_default_budget_used_when_missing(self, store: DemoIdentityStore, store_path: Path):
        # Remove monthly_token_budget from the stored JSON
        data = json.loads(store_path.read_text())
        data["organization"].pop("monthly_token_budget", None)
        store_path.write_text(json.dumps(data))
        org = await store.get_org_settings()
        assert org["monthly_token_budget"] == DEFAULT_ORG_MONTHLY_TOKEN_BUDGET


# ─── User ↔ Department Assignment ────────────────────────────────────────────

class TestUserDepartmentAssignment:

    @pytest.mark.asyncio
    async def test_create_user_with_department_id(self, store: DemoIdentityStore):
        user, _ = await store.create_user(
            {
                "email": "newbie@test.demo",
                "full_name": "New Bie",
                "department_id": DEPT_ID,
                "monthly_token_limit": 150_000,
            },
            created_by=ADMIN_ID,
        )
        assert user["department_id"] == DEPT_ID
        assert user["department"] == "Engineering"

    @pytest.mark.asyncio
    async def test_create_user_with_invalid_department_id_raises(self, store: DemoIdentityStore):
        with pytest.raises(ValueError, match="not found"):
            await store.create_user(
                {"email": "bad@test.demo", "full_name": "Bad Dept", "department_id": "dept-nonexistent"},
                created_by=ADMIN_ID,
            )

    @pytest.mark.asyncio
    async def test_update_user_department_id(self, store: DemoIdentityStore):
        # Create a new dept
        new_dept = await store.create_department({"name": "Product", "monthly_token_limit": 250_000}, created_by=ADMIN_ID)
        updated = await store.update_user(MEMBER_ID, {"department_id": new_dept["id"]}, updated_by=ADMIN_ID)
        assert updated["department_id"] == new_dept["id"]
        assert updated["department"] == "Product"

    @pytest.mark.asyncio
    async def test_update_user_department_id_to_none(self, store: DemoIdentityStore):
        updated = await store.update_user(MEMBER_ID, {"department_id": None}, updated_by=ADMIN_ID)
        assert updated["department_id"] is None
        assert updated["department"] is None

    @pytest.mark.asyncio
    async def test_update_user_invalid_department_id_raises(self, store: DemoIdentityStore):
        with pytest.raises(ValueError, match="not found"):
            await store.update_user(MEMBER_ID, {"department_id": "dept-fake"}, updated_by=ADMIN_ID)


# ─── Token Limit Override ─────────────────────────────────────────────────────

class TestTokenLimitOverride:

    @pytest.mark.asyncio
    async def test_user_has_token_limit_override_flag(self, store: DemoIdentityStore):
        users = await store.list_users()
        admin = next(u for u in users if u["id"] == ADMIN_ID)
        member = next(u for u in users if u["id"] == MEMBER_ID)
        assert admin["token_limit_override"] is True
        assert admin["token_topup_tokens"] == 50_000
        assert member["token_limit_override"] is False
        assert member["token_topup_tokens"] == 0

    @pytest.mark.asyncio
    async def test_set_token_limit_override(self, store: DemoIdentityStore):
        updated = await store.update_user(
            MEMBER_ID,
            {"token_topup_tokens": 99_000},
            updated_by=ADMIN_ID,
        )
        assert updated["token_limit_override"] is True
        assert updated["token_topup_tokens"] == 99_000

    @pytest.mark.asyncio
    async def test_clear_token_limit_override(self, store: DemoIdentityStore):
        updated = await store.update_user(ADMIN_ID, {"token_topup_tokens": 0}, updated_by=ADMIN_ID)
        assert updated["token_limit_override"] is False
        assert updated["token_topup_tokens"] == 0

    @pytest.mark.asyncio
    async def test_new_user_has_override_flag_false_by_default(self, store: DemoIdentityStore):
        user, _ = await store.create_user(
            {"email": "fresh@test.demo", "full_name": "Fresh User", "department_id": DEPT_ID},
            created_by=ADMIN_ID,
        )
        assert user.get("token_limit_override") is False


# ─── Token Summary Hierarchy ──────────────────────────────────────────────────

class TestTokenSummary:

    @pytest.mark.asyncio
    async def test_token_summary_structure(self, store: DemoIdentityStore):
        summary = await store.get_token_summary()
        assert "org_budget" in summary
        assert "total_dept_allocated" in summary
        assert "unallocated_budget" in summary
        assert "total_token_used" in summary
        assert "org_utilization_pct" in summary
        assert "departments" in summary
        assert "unassigned_user_count" in summary

    @pytest.mark.asyncio
    async def test_token_summary_org_budget(self, store: DemoIdentityStore):
        summary = await store.get_token_summary()
        assert summary["org_budget"] == 1_000_000
        assert summary["total_dept_allocated"] == 400_000
        assert summary["unallocated_budget"] == 600_000

    @pytest.mark.asyncio
    async def test_token_summary_dept_usage(self, store: DemoIdentityStore):
        summary = await store.get_token_summary()
        dept = next(d for d in summary["departments"] if d["id"] == DEPT_ID)
        assert dept["total_token_used"] == 120_000 + 80_000
        assert dept["monthly_token_limit"] == 400_000
        assert dept["user_count"] == 2

    @pytest.mark.asyncio
    async def test_token_summary_dept_has_user_list(self, store: DemoIdentityStore):
        summary = await store.get_token_summary()
        dept = next(d for d in summary["departments"] if d["id"] == DEPT_ID)
        assert len(dept["users"]) == 2
        user_ids = {u["id"] for u in dept["users"]}
        assert ADMIN_ID in user_ids
        assert MEMBER_ID in user_ids

    @pytest.mark.asyncio
    async def test_token_summary_unassigned_users(self, store: DemoIdentityStore):
        # Move one user out
        await store.update_user(MEMBER_ID, {"department_id": None}, updated_by=ADMIN_ID)
        summary = await store.get_token_summary()
        assert summary["unassigned_user_count"] == 1


# ─── Admin Summary Regression ─────────────────────────────────────────────────

class TestAdminSummaryRegression:

    @pytest.mark.asyncio
    async def test_admin_summary_includes_departments(self, store: DemoIdentityStore):
        summary = await store.get_admin_summary()
        assert "departments" in summary
        assert len(summary["departments"]) == 1
        dept = summary["departments"][0]
        assert dept["name"] == "Engineering"
        assert "utilization_pct" in dept

    @pytest.mark.asyncio
    async def test_admin_summary_totals_include_org_budget(self, store: DemoIdentityStore):
        summary = await store.get_admin_summary()
        totals = summary["totals"]
        assert totals["org_monthly_token_budget"] == 1_000_000
        assert totals["total_dept_allocated"] == 400_000
        assert totals["unallocated_budget"] == 600_000
        assert totals["department_count"] == 1

    @pytest.mark.asyncio
    async def test_admin_summary_includes_users(self, store: DemoIdentityStore):
        summary = await store.get_admin_summary()
        assert len(summary["users"]) == 2
        # Passwords must NOT be exposed
        for u in summary["users"]:
            assert "password_hash" not in u
            assert "password_salt" not in u

    @pytest.mark.asyncio
    async def test_admin_summary_token_limit_override_preserved(self, store: DemoIdentityStore):
        summary = await store.get_admin_summary()
        admin = next(u for u in summary["users"] if u["id"] == ADMIN_ID)
        assert admin["token_limit_override"] is True
