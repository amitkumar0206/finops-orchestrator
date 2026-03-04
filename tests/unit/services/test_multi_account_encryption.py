"""
Tests verifying CRIT-9 remediation in multi_account_service:
role_arn and external_id are encrypted on write and decrypted on read.
"""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.utils.encryption import FieldEncryptor, reset_field_encryptor


# Shared test encryption key
_TEST_KEY = "test-encryption-key-that-is-at-least-32-characters-long-here"


@pytest.fixture(autouse=True)
def _setup_env():
    """Ensure a known encryption key is set for all tests."""
    orig = os.environ.copy()
    os.environ["FIELD_ENCRYPTION_KEY"] = _TEST_KEY
    os.environ["ENVIRONMENT"] = "development"
    os.environ.setdefault("PYTEST_CURRENT_TEST", "yes")
    reset_field_encryptor()
    yield
    os.environ.clear()
    os.environ.update(orig)
    reset_field_encryptor()


def _encryptor() -> FieldEncryptor:
    return FieldEncryptor(_TEST_KEY)


class TestRegisterAccountEncryption:
    """register_account must encrypt role_arn and external_id."""

    @pytest.mark.asyncio
    async def test_register_encrypts_role_arn_and_external_id(self):
        from backend.services.multi_account_service import MultiAccountService

        svc = MultiAccountService.__new__(MultiAccountService)
        svc.db = AsyncMock()
        svc.sts_client = MagicMock()

        # Mock successful validation
        svc._validate_account_access = AsyncMock(return_value={
            "success": True,
            "credentials": {"AccessKeyId": "x", "SecretAccessKey": "y", "SessionToken": "z"},
        })
        svc.db.execute = AsyncMock(return_value={
            "id": "uuid-1", "account_id": "123456789012",
            "account_name": "test", "status": "ACTIVE",
        })

        await svc.register_account(
            account_id="123456789012",
            account_name="test",
            role_arn="arn:aws:iam::123456789012:role/my-role",
            created_by="admin@test.com",
            external_id="ext-secret-123",
        )

        # Verify the INSERT was called
        call_args = svc.db.execute.call_args
        positional = call_args[0]

        # The SQL query is positional[0]; param values start at positional[1]
        query = positional[0]
        assert "role_arn_encrypted" in query
        assert "external_id_encrypted" in query

        # Plaintext columns should contain marker
        # role_arn is $7, external_id is $8 in the query
        assert positional[7] == "[ENCRYPTED]"  # role_arn marker
        assert positional[8] == "[ENCRYPTED]"  # external_id marker

        # Encrypted values should be decryptable
        enc = _encryptor()
        role_arn_enc = positional[9]  # role_arn_encrypted
        ext_id_enc = positional[10]   # external_id_encrypted
        assert enc.decrypt_string(role_arn_enc) == "arn:aws:iam::123456789012:role/my-role"
        assert enc.decrypt_string(ext_id_enc) == "ext-secret-123"

    @pytest.mark.asyncio
    async def test_register_handles_null_external_id(self):
        from backend.services.multi_account_service import MultiAccountService

        svc = MultiAccountService.__new__(MultiAccountService)
        svc.db = AsyncMock()
        svc.sts_client = MagicMock()
        svc._validate_account_access = AsyncMock(return_value={
            "success": True, "credentials": {},
        })
        svc.db.execute = AsyncMock(return_value={
            "id": "uuid-1", "account_id": "111111111111",
            "account_name": "test2", "status": "ACTIVE",
        })

        await svc.register_account(
            account_id="111111111111",
            account_name="test2",
            role_arn="arn:aws:iam::111111111111:role/role",
            created_by="admin@test.com",
            external_id=None,
        )

        call_args = svc.db.execute.call_args[0]
        # external_id_encrypted should be None when external_id is None
        assert call_args[10] is None


class TestGetAccountCredentialsDecryption:
    """get_account_credentials must decrypt encrypted columns."""

    @pytest.mark.asyncio
    async def test_decrypts_encrypted_columns(self):
        from backend.services.multi_account_service import MultiAccountService

        enc = _encryptor()
        encrypted_arn = enc.encrypt_string("arn:aws:iam::222222222222:role/role")
        encrypted_ext = enc.encrypt_string("my-external-id")

        svc = MultiAccountService.__new__(MultiAccountService)
        svc.db = AsyncMock()
        svc.sts_client = MagicMock()

        svc.db.fetch_one = AsyncMock(return_value={
            "role_arn": "[ENCRYPTED]",
            "external_id": "[ENCRYPTED]",
            "role_arn_encrypted": encrypted_arn,
            "external_id_encrypted": encrypted_ext,
            "status": "ACTIVE",
        })
        svc._validate_account_access = AsyncMock(return_value={
            "success": True,
            "credentials": {"AccessKeyId": "a", "SecretAccessKey": "b", "SessionToken": "c"},
        })

        creds = await svc.get_account_credentials("222222222222")

        # Verify the decrypted values were passed to _validate_account_access
        validate_call = svc._validate_account_access.call_args[0]
        assert validate_call[0] == "arn:aws:iam::222222222222:role/role"
        assert validate_call[1] == "my-external-id"
        assert creds == {"AccessKeyId": "a", "SecretAccessKey": "b", "SessionToken": "c"}

    @pytest.mark.asyncio
    async def test_falls_back_to_plaintext_when_encrypted_column_null(self):
        """Backward compat: pre-migration rows have no encrypted columns."""
        from backend.services.multi_account_service import MultiAccountService

        svc = MultiAccountService.__new__(MultiAccountService)
        svc.db = AsyncMock()
        svc.sts_client = MagicMock()

        svc.db.fetch_one = AsyncMock(return_value={
            "role_arn": "arn:aws:iam::333333333333:role/old-role",
            "external_id": "old-ext-id",
            "role_arn_encrypted": None,
            "external_id_encrypted": None,
            "status": "ACTIVE",
        })
        svc._validate_account_access = AsyncMock(return_value={
            "success": True,
            "credentials": {"AccessKeyId": "x", "SecretAccessKey": "y", "SessionToken": "z"},
        })

        await svc.get_account_credentials("333333333333")

        validate_call = svc._validate_account_access.call_args[0]
        assert validate_call[0] == "arn:aws:iam::333333333333:role/old-role"
        assert validate_call[1] == "old-ext-id"

    @pytest.mark.asyncio
    async def test_account_not_found_raises(self):
        from backend.services.multi_account_service import MultiAccountService

        svc = MultiAccountService.__new__(MultiAccountService)
        svc.db = AsyncMock()
        svc.sts_client = MagicMock()
        svc.db.fetch_one = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="not found"):
            await svc.get_account_credentials("999999999999")

    @pytest.mark.asyncio
    async def test_inactive_account_raises(self):
        from backend.services.multi_account_service import MultiAccountService

        svc = MultiAccountService.__new__(MultiAccountService)
        svc.db = AsyncMock()
        svc.sts_client = MagicMock()
        svc.db.fetch_one = AsyncMock(return_value={
            "role_arn": "x", "external_id": None,
            "role_arn_encrypted": None, "external_id_encrypted": None,
            "status": "INACTIVE",
        })

        with pytest.raises(ValueError, match="not active"):
            await svc.get_account_credentials("444444444444")
