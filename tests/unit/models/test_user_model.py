"""
Comprehensive tests for the User ORM model.

Validates that the User model in database_models.py matches the DB schema
defined across migrations 008, 011, and 013.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect as sa_inspect

from backend.models.database_models import Base, User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _col(name: str):
    """Return the SQLAlchemy column object for *name* on the User model."""
    mapper = sa_inspect(User)
    return mapper.columns[name]


def _col_names():
    """Return a set of all column names on the User model."""
    mapper = sa_inspect(User)
    return set(mapper.columns.keys())


# ===========================================================================
# 1. Table-level properties
# ===========================================================================

class TestUserModelTableName:
    def test_tablename(self):
        assert User.__tablename__ == "users"

    def test_inherits_base(self):
        assert issubclass(User, Base)

    def test_registered_in_metadata(self):
        assert "users" in Base.metadata.tables


# ===========================================================================
# 2. Column presence, type, nullability, constraints, defaults
# ===========================================================================

class TestUserModelColumns:
    # --- id ---
    def test_id_is_uuid(self):
        col = _col("id")
        assert "UUID" in type(col.type).__name__.upper()

    def test_id_is_primary_key(self):
        assert _col("id").primary_key is True

    def test_id_has_server_default(self):
        assert _col("id").server_default is not None

    # --- email ---
    def test_email_type(self):
        col = _col("email")
        assert isinstance(col.type, type(_col("email").type))
        assert col.type.length == 255

    def test_email_not_nullable(self):
        assert _col("email").nullable is False

    def test_email_unique(self):
        assert _col("email").unique is True

    def test_email_indexed(self):
        assert _col("email").index is True

    # --- full_name ---
    def test_full_name_type_and_length(self):
        assert _col("full_name").type.length == 255

    def test_full_name_nullable(self):
        assert _col("full_name").nullable is True

    # --- is_active ---
    def test_is_active_not_nullable(self):
        assert _col("is_active").nullable is False

    def test_is_active_server_default_true(self):
        sd = _col("is_active").server_default
        assert sd is not None
        assert "true" in str(sd.arg).lower()

    # --- is_admin ---
    def test_is_admin_not_nullable(self):
        assert _col("is_admin").nullable is False

    def test_is_admin_server_default_false(self):
        sd = _col("is_admin").server_default
        assert sd is not None
        assert "false" in str(sd.arg).lower()

    # --- last_login_at ---
    def test_last_login_at_nullable(self):
        assert _col("last_login_at").nullable is True

    def test_last_login_at_timezone(self):
        assert _col("last_login_at").type.timezone is True

    # --- last_login_ip ---
    def test_last_login_ip_nullable(self):
        assert _col("last_login_ip").nullable is True

    def test_last_login_ip_type(self):
        assert "INET" in type(_col("last_login_ip").type).__name__.upper()

    # --- preferences ---
    def test_preferences_nullable(self):
        assert _col("preferences").nullable is True

    def test_preferences_type(self):
        assert "JSONB" in type(_col("preferences").type).__name__.upper()

    # --- created_at ---
    def test_created_at_not_nullable(self):
        assert _col("created_at").nullable is False

    def test_created_at_has_server_default(self):
        assert _col("created_at").server_default is not None

    def test_created_at_timezone(self):
        assert _col("created_at").type.timezone is True

    # --- updated_at ---
    def test_updated_at_not_nullable(self):
        assert _col("updated_at").nullable is False

    def test_updated_at_has_server_default(self):
        assert _col("updated_at").server_default is not None

    def test_updated_at_has_onupdate(self):
        assert _col("updated_at").onupdate is not None

    def test_updated_at_timezone(self):
        assert _col("updated_at").type.timezone is True

    # --- default_organization_id (migration 011) ---
    def test_default_organization_id_nullable(self):
        assert _col("default_organization_id").nullable is True

    def test_default_organization_id_is_uuid(self):
        assert "UUID" in type(_col("default_organization_id").type).__name__.upper()

    def test_default_organization_id_indexed(self):
        assert _col("default_organization_id").index is True

    def test_default_organization_id_fk(self):
        fks = _col("default_organization_id").foreign_keys
        assert len(fks) == 1
        fk = next(iter(fks))
        assert fk.target_fullname == "organizations.id"

    def test_default_organization_id_fk_ondelete(self):
        fk = next(iter(_col("default_organization_id").foreign_keys))
        assert fk.ondelete.upper() == "SET NULL"

    # --- password_hash (migration 013) ---
    def test_password_hash_nullable(self):
        assert _col("password_hash").nullable is True

    def test_password_hash_length(self):
        assert _col("password_hash").type.length == 128

    # --- password_salt (migration 013) ---
    def test_password_salt_nullable(self):
        assert _col("password_salt").nullable is True

    def test_password_salt_length(self):
        assert _col("password_salt").type.length == 64

    # --- password_hash_version (migration 013) ---
    def test_password_hash_version_not_nullable(self):
        assert _col("password_hash_version").nullable is False

    def test_password_hash_version_server_default(self):
        sd = _col("password_hash_version").server_default
        assert sd is not None
        assert "2" in str(sd.arg)

    # --- password_updated_at (migration 013) ---
    def test_password_updated_at_nullable(self):
        assert _col("password_updated_at").nullable is True

    def test_password_updated_at_timezone(self):
        assert _col("password_updated_at").type.timezone is True


# ===========================================================================
# 3. __repr__ safety
# ===========================================================================

class TestUserModelRepr:
    def test_repr_contains_class_name(self):
        u = User(id=uuid.uuid4(), email="test@example.com")
        assert "User" in repr(u)

    def test_repr_contains_email(self):
        u = User(id=uuid.uuid4(), email="test@example.com")
        assert "test@example.com" in repr(u)

    def test_repr_excludes_password_hash(self):
        u = User(
            id=uuid.uuid4(),
            email="test@example.com",
            password_hash="supersecret",
        )
        assert "supersecret" not in repr(u)

    def test_repr_excludes_password_salt(self):
        u = User(
            id=uuid.uuid4(),
            email="test@example.com",
            password_salt="saltyvalue",
        )
        assert "saltyvalue" not in repr(u)


# ===========================================================================
# 4. Instantiation
# ===========================================================================

class TestUserModelInstantiation:
    def test_create_with_required_fields(self):
        u = User(email="min@example.com")
        assert u.email == "min@example.com"

    def test_create_with_all_fields(self):
        uid = uuid.uuid4()
        org_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        u = User(
            id=uid,
            email="full@example.com",
            full_name="Full User",
            is_active=True,
            is_admin=False,
            last_login_at=now,
            last_login_ip="192.168.1.1",
            preferences={"theme": "dark"},
            created_at=now,
            updated_at=now,
            default_organization_id=org_id,
            password_hash="hash123",
            password_salt="salt456",
            password_hash_version=2,
            password_updated_at=now,
        )
        assert u.id == uid
        assert u.full_name == "Full User"
        assert u.preferences == {"theme": "dark"}
        assert u.default_organization_id == org_id
        assert u.password_hash == "hash123"
        assert u.password_salt == "salt456"
        assert u.password_hash_version == 2
        assert u.password_updated_at == now

    def test_sso_user_no_password(self):
        u = User(email="sso@corp.com", full_name="SSO User")
        assert u.password_hash is None
        assert u.password_salt is None
        assert u.password_updated_at is None


# ===========================================================================
# 5. Security properties
# ===========================================================================

class TestUserModelSecurityProperties:
    def test_password_hash_not_indexed_on_model(self):
        col = _col("password_hash")
        assert not col.index

    def test_password_salt_not_indexed(self):
        col = _col("password_salt")
        assert not col.index

    def test_email_is_indexed(self):
        assert _col("email").index is True

    def test_no_hardcoded_password_default(self):
        assert _col("password_hash").default is None
        assert _col("password_hash").server_default is None

    def test_no_hardcoded_salt_default(self):
        assert _col("password_salt").default is None
        assert _col("password_salt").server_default is None


# ===========================================================================
# 6. Column count regression
# ===========================================================================

class TestUserModelColumnCount:
    def test_exactly_15_columns(self):
        """Regression guard: migrations 008+011+013 define exactly 15 columns."""
        assert len(_col_names()) == 15

    def test_expected_column_names(self):
        expected = {
            "id", "email", "full_name", "is_active", "is_admin",
            "last_login_at", "last_login_ip", "preferences",
            "created_at", "updated_at",
            "default_organization_id",
            "password_hash", "password_salt", "password_hash_version",
            "password_updated_at",
        }
        assert _col_names() == expected
