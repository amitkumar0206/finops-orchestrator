"""
Field-level encryption for sensitive database columns.

Uses Fernet symmetric encryption with PBKDF2-derived keys to protect
credentials stored in the database (CRIT-9 remediation).
"""

import base64
import json
import logging
import os
import warnings

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

# Static salt derived from application identifier — prevents rainbow tables.
# Not secret; its purpose is domain separation.
_STATIC_SALT = b"finops-ai-cost-intelligence-field-encryption-v1"

_PBKDF2_ITERATIONS = 600_000


class DecryptionError(Exception):
    """Raised when decryption fails (wrong key, corrupt ciphertext, etc.)."""


class FieldEncryptor:
    """Fernet-based encryption for sensitive database fields."""

    def __init__(self, key: str):
        derived = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=_STATIC_SALT,
            iterations=_PBKDF2_ITERATIONS,
        ).derive(key.encode())
        fernet_key = base64.urlsafe_b64encode(derived)
        self._fernet = Fernet(fernet_key)

    def encrypt_string(self, plaintext: str) -> str:
        """Encrypt a plaintext string and return base64-encoded ciphertext."""
        if not isinstance(plaintext, str):
            raise TypeError("plaintext must be a string")
        token = self._fernet.encrypt(plaintext.encode("utf-8"))
        return base64.urlsafe_b64encode(token).decode("ascii")

    def decrypt_string(self, ciphertext: str) -> str:
        """Decrypt a base64-encoded ciphertext and return the plaintext string."""
        if not isinstance(ciphertext, str):
            raise TypeError("ciphertext must be a string")
        try:
            token = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
            return self._fernet.decrypt(token).decode("utf-8")
        except (InvalidToken, Exception) as exc:
            raise DecryptionError(f"Decryption failed: {type(exc).__name__}") from exc

    def encrypt_json(self, data: dict) -> str:
        """JSON-serialize a dict then encrypt it."""
        return self.encrypt_string(json.dumps(data, separators=(",", ":")))

    def decrypt_json(self, ciphertext: str) -> dict:
        """Decrypt ciphertext and JSON-parse the result."""
        plaintext = self.decrypt_string(ciphertext)
        return json.loads(plaintext)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_encryptor_instance: FieldEncryptor | None = None


def get_field_encryptor() -> FieldEncryptor:
    """Return a module-level singleton FieldEncryptor.

    Key source: ``FIELD_ENCRYPTION_KEY`` environment variable.

    * **Production** (``ENVIRONMENT=production``): raises ``ValueError`` if
      the key is missing or shorter than 32 characters.
    * **Development / test**: auto-generates a random key with a warning.
    """
    global _encryptor_instance
    if _encryptor_instance is not None:
        return _encryptor_instance

    key = os.environ.get("FIELD_ENCRYPTION_KEY")
    environment = os.environ.get("ENVIRONMENT", "development").lower()
    is_production = environment == "production"

    if not key or len(key) < 32:
        if is_production:
            raise ValueError(
                "CRITICAL: FIELD_ENCRYPTION_KEY environment variable must be set "
                "to a value of at least 32 characters in production. "
                "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        # Development / testing — auto-generate with warning
        import secrets as _secrets

        key = _secrets.token_urlsafe(48)
        is_testing = (
            os.environ.get("PYTEST_CURRENT_TEST") is not None
            or os.environ.get("TESTING", "").lower() in ("1", "true", "yes")
        )
        if not is_testing:
            warnings.warn(
                "FIELD_ENCRYPTION_KEY not set — using auto-generated key. "
                "Encrypted data will be unreadable after restart.",
                UserWarning,
                stacklevel=2,
            )

    _encryptor_instance = FieldEncryptor(key)
    return _encryptor_instance


def reset_field_encryptor() -> None:
    """Reset the singleton (used in tests)."""
    global _encryptor_instance
    _encryptor_instance = None
