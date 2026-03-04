"""
Tests for field-level encryption utility (CRIT-9 remediation).
"""

import os
import pytest
from unittest.mock import patch

from backend.utils.encryption import (
    DecryptionError,
    FieldEncryptor,
    get_field_encryptor,
    reset_field_encryptor,
)


# ---------------------------------------------------------------------------
# FieldEncryptor unit tests
# ---------------------------------------------------------------------------

class TestFieldEncryptorRoundtrip:
    """Encrypt then decrypt must return the original value."""

    def _make(self, key: str = "test-key-that-is-at-least-32-chars-long!!") -> FieldEncryptor:
        return FieldEncryptor(key)

    def test_roundtrip_simple_string(self):
        enc = self._make()
        assert enc.decrypt_string(enc.encrypt_string("hello world")) == "hello world"

    def test_roundtrip_empty_string(self):
        enc = self._make()
        assert enc.decrypt_string(enc.encrypt_string("")) == ""

    def test_roundtrip_unicode(self):
        enc = self._make()
        text = "Unicode: \u00e9\u00e0\u00fc \u4f60\u597d \U0001f512"
        assert enc.decrypt_string(enc.encrypt_string(text)) == text

    def test_roundtrip_long_string(self):
        enc = self._make()
        text = "x" * 10_000
        assert enc.decrypt_string(enc.encrypt_string(text)) == text

    def test_roundtrip_json(self):
        enc = self._make()
        data = {"api_key": "sk-12345", "nested": {"a": [1, 2, 3]}}
        assert enc.decrypt_json(enc.encrypt_json(data)) == data

    def test_roundtrip_json_empty_dict(self):
        enc = self._make()
        assert enc.decrypt_json(enc.encrypt_json({})) == {}

    def test_roundtrip_special_characters(self):
        enc = self._make()
        text = "arn:aws:iam::123456789012:role/cross-account-role"
        assert enc.decrypt_string(enc.encrypt_string(text)) == text

    def test_ciphertext_differs_from_plaintext(self):
        enc = self._make()
        plain = "secret-value"
        cipher = enc.encrypt_string(plain)
        assert cipher != plain

    def test_two_encryptions_produce_different_ciphertext(self):
        """Fernet includes a timestamp and IV so ciphertexts should differ."""
        enc = self._make()
        c1 = enc.encrypt_string("same")
        c2 = enc.encrypt_string("same")
        assert c1 != c2


class TestKeyDerivation:
    """Key derivation must be deterministic for the same input."""

    def test_same_key_produces_compatible_encryptors(self):
        key = "deterministic-key-for-testing-purposes-here"
        e1 = FieldEncryptor(key)
        e2 = FieldEncryptor(key)
        cipher = e1.encrypt_string("data")
        assert e2.decrypt_string(cipher) == "data"

    def test_different_keys_are_incompatible(self):
        e1 = FieldEncryptor("key-one-xxxxxxxxxxxxxxxxxxxxxxxx")
        e2 = FieldEncryptor("key-two-xxxxxxxxxxxxxxxxxxxxxxxx")
        cipher = e1.encrypt_string("data")
        with pytest.raises(DecryptionError):
            e2.decrypt_string(cipher)


class TestDecryptionErrors:
    """Verify that bad input is handled gracefully."""

    def _make(self) -> FieldEncryptor:
        return FieldEncryptor("test-key-that-is-at-least-32-chars-long!!")

    def test_wrong_key_raises_decryption_error(self):
        enc1 = FieldEncryptor("key-aaa-xxxxxxxxxxxxxxxxxxxxxx!!")
        enc2 = FieldEncryptor("key-bbb-xxxxxxxxxxxxxxxxxxxxxx!!")
        cipher = enc1.encrypt_string("secret")
        with pytest.raises(DecryptionError):
            enc2.decrypt_string(cipher)

    def test_corrupt_ciphertext_raises_decryption_error(self):
        enc = self._make()
        with pytest.raises(DecryptionError):
            enc.decrypt_string("not-a-valid-ciphertext!!!")

    def test_empty_ciphertext_raises_decryption_error(self):
        enc = self._make()
        with pytest.raises(DecryptionError):
            enc.decrypt_string("")

    def test_encrypt_non_string_raises_type_error(self):
        enc = self._make()
        with pytest.raises(TypeError):
            enc.encrypt_string(12345)  # type: ignore[arg-type]

    def test_decrypt_non_string_raises_type_error(self):
        enc = self._make()
        with pytest.raises(TypeError):
            enc.decrypt_string(12345)  # type: ignore[arg-type]

    def test_decrypt_json_invalid_json_raises(self):
        enc = self._make()
        cipher = enc.encrypt_string("not json")
        with pytest.raises(Exception):
            enc.decrypt_json(cipher)


# ---------------------------------------------------------------------------
# Singleton / factory tests
# ---------------------------------------------------------------------------

class TestGetFieldEncryptor:
    """Tests for the module-level singleton factory."""

    def setup_method(self):
        reset_field_encryptor()
        self._orig = os.environ.copy()

    def teardown_method(self):
        os.environ.clear()
        os.environ.update(self._orig)
        reset_field_encryptor()

    def test_production_without_key_raises(self):
        os.environ.pop("FIELD_ENCRYPTION_KEY", None)
        os.environ["ENVIRONMENT"] = "production"
        with pytest.raises(ValueError, match="FIELD_ENCRYPTION_KEY"):
            get_field_encryptor()

    def test_production_with_short_key_raises(self):
        os.environ["FIELD_ENCRYPTION_KEY"] = "short"
        os.environ["ENVIRONMENT"] = "production"
        with pytest.raises(ValueError, match="at least 32 characters"):
            get_field_encryptor()

    def test_production_with_valid_key_succeeds(self):
        os.environ["FIELD_ENCRYPTION_KEY"] = "a" * 48
        os.environ["ENVIRONMENT"] = "production"
        enc = get_field_encryptor()
        assert enc.decrypt_string(enc.encrypt_string("ok")) == "ok"

    def test_development_auto_generates_key(self):
        os.environ.pop("FIELD_ENCRYPTION_KEY", None)
        os.environ["ENVIRONMENT"] = "development"
        os.environ["PYTEST_CURRENT_TEST"] = "yes"
        enc = get_field_encryptor()
        assert enc.decrypt_string(enc.encrypt_string("dev")) == "dev"

    def test_singleton_returns_same_instance(self):
        os.environ["FIELD_ENCRYPTION_KEY"] = "b" * 48
        os.environ["ENVIRONMENT"] = "development"
        assert get_field_encryptor() is get_field_encryptor()
