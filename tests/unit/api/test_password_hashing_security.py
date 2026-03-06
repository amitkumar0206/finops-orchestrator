"""
Security tests for password hashing - HIGH-NEW-2 vulnerability fix

Tests the PBKDF2 password hashing implementation to ensure:
- Sufficient iterations (600,000 for new passwords)
- Backward compatibility with legacy hashes (100,000 iterations)
- Proper version tracking
- Secure password verification
- Automatic hash migration on login
"""

import pytest
import time

from backend.api.auth import (
    hash_password,
    verify_password,
    generate_salt,
    PASSWORD_HASH_VERSION_LEGACY,
    PASSWORD_HASH_VERSION_CURRENT,
    PASSWORD_HASH_ITERATIONS,
)


class TestPasswordHashingSecurity:
    """Test password hashing security implementation"""

    def test_password_hash_version_constants(self):
        """Verify password hash version constants are properly defined"""
        assert PASSWORD_HASH_VERSION_LEGACY == 1
        assert PASSWORD_HASH_VERSION_CURRENT == 2

        assert PASSWORD_HASH_ITERATIONS[1] == 100000
        assert PASSWORD_HASH_ITERATIONS[2] == 600000

    def test_hash_password_default_uses_current_version(self):
        """New passwords should use current version (600k iterations) by default"""
        password = "TestPassword123!"
        salt = generate_salt()

        # Hash without specifying version (should use current)
        hash1 = hash_password(password, salt)

        # Hash with explicitly current version
        hash2 = hash_password(password, salt, version=PASSWORD_HASH_VERSION_CURRENT)

        # Should be identical
        assert hash1 == hash2

    def test_hash_password_legacy_version(self):
        """Legacy version (100k iterations) should still work for backward compatibility"""
        password = "TestPassword123!"
        salt = generate_salt()

        # Hash with legacy version
        legacy_hash = hash_password(password, salt, version=PASSWORD_HASH_VERSION_LEGACY)

        # Should produce a valid hash
        assert isinstance(legacy_hash, str)
        assert len(legacy_hash) == 64  # SHA-256 produces 32 bytes = 64 hex chars

    def test_different_versions_produce_different_hashes(self):
        """Same password with same salt but different versions should produce different hashes"""
        password = "TestPassword123!"
        salt = generate_salt()

        hash_v1 = hash_password(password, salt, version=1)
        hash_v2 = hash_password(password, salt, version=2)

        # Different iteration counts should produce different hashes
        assert hash_v1 != hash_v2

    def test_hash_password_deterministic(self):
        """Same password and salt should always produce same hash"""
        password = "TestPassword123!"
        salt = "a" * 64  # Fixed salt for testing

        hash1 = hash_password(password, salt, version=2)
        hash2 = hash_password(password, salt, version=2)

        assert hash1 == hash2

    def test_hash_password_different_salts(self):
        """Same password with different salts should produce different hashes"""
        password = "TestPassword123!"
        salt1 = generate_salt()
        salt2 = generate_salt()

        hash1 = hash_password(password, salt1)
        hash2 = hash_password(password, salt2)

        assert hash1 != hash2

    def test_generate_salt_randomness(self):
        """Salt generation should produce unique random values"""
        salt1 = generate_salt()
        salt2 = generate_salt()
        salt3 = generate_salt()

        # All salts should be different
        assert salt1 != salt2
        assert salt2 != salt3
        assert salt1 != salt3

        # All salts should be 64 characters (32 bytes hex)
        assert len(salt1) == 64
        assert len(salt2) == 64
        assert len(salt3) == 64

    def test_verify_password_correct(self):
        """Verify password should return True for correct password"""
        password = "TestPassword123!"
        salt = generate_salt()

        hashed = hash_password(password, salt, version=2)

        assert verify_password(password, salt, hashed, version=2) is True

    def test_verify_password_incorrect(self):
        """Verify password should return False for incorrect password"""
        correct_password = "TestPassword123!"
        wrong_password = "WrongPassword456!"
        salt = generate_salt()

        hashed = hash_password(correct_password, salt, version=2)

        assert verify_password(wrong_password, salt, hashed, version=2) is False

    def test_verify_password_legacy_version(self):
        """Should be able to verify passwords hashed with legacy version"""
        password = "TestPassword123!"
        salt = generate_salt()

        # Hash with legacy version (100k iterations)
        legacy_hash = hash_password(password, salt, version=PASSWORD_HASH_VERSION_LEGACY)

        # Verify using legacy version
        assert verify_password(password, salt, legacy_hash, version=PASSWORD_HASH_VERSION_LEGACY) is True

    def test_verify_password_version_mismatch_fails(self):
        """Verifying with wrong version should fail"""
        password = "TestPassword123!"
        salt = generate_salt()

        # Hash with version 1 (100k iterations)
        hash_v1 = hash_password(password, salt, version=1)

        # Try to verify with version 2 (600k iterations) - should fail
        assert verify_password(password, salt, hash_v1, version=2) is False

    def test_verify_password_constant_time_comparison(self):
        """Verify password should use constant-time comparison"""
        password = "TestPassword123!"
        salt = generate_salt()
        hashed = hash_password(password, salt)

        # Test with correct password
        result1 = verify_password(password, salt, hashed)

        # Test with incorrect password (same length)
        wrong_password = "WrongPassword123!"
        result2 = verify_password(wrong_password, salt, hashed)

        assert result1 is True
        assert result2 is False

        # Note: We can't reliably test timing attack resistance in unit tests
        # but the code uses secrets.compare_digest which is constant-time

    def test_owasp_recommended_iterations(self):
        """Current version should meet OWASP recommendations (600k+ for PBKDF2-SHA256)"""
        current_iterations = PASSWORD_HASH_ITERATIONS[PASSWORD_HASH_VERSION_CURRENT]

        # OWASP recommends minimum 600,000 iterations for PBKDF2-SHA256 (2023+)
        assert current_iterations >= 600000, \
            f"Current iteration count ({current_iterations}) below OWASP minimum (600,000)"

    def test_hash_produces_valid_hex_string(self):
        """Hash should produce valid hexadecimal string"""
        password = "TestPassword123!"
        salt = generate_salt()

        hashed = hash_password(password, salt)

        # Should be valid hex
        try:
            int(hashed, 16)
            valid_hex = True
        except ValueError:
            valid_hex = False

        assert valid_hex is True
        assert len(hashed) == 64  # SHA-256 = 32 bytes = 64 hex chars

    def test_hash_password_empty_password(self):
        """Should be able to hash empty password (though not recommended)"""
        password = ""
        salt = generate_salt()

        hashed = hash_password(password, salt)

        assert isinstance(hashed, str)
        assert len(hashed) == 64

    def test_hash_password_unicode_characters(self):
        """Should properly handle unicode characters in password"""
        password = "Password123!@#测试🔒"
        salt = generate_salt()

        hashed = hash_password(password, salt)

        # Verify it works
        assert verify_password(password, salt, hashed)

    def test_hash_password_very_long_password(self):
        """Should handle very long passwords"""
        password = "A" * 1000  # 1000 character password
        salt = generate_salt()

        hashed = hash_password(password, salt)

        # Verify it works
        assert verify_password(password, salt, hashed)

    def test_performance_600k_iterations(self):
        """600k iterations should take reasonable time (< 1 second on modern hardware)"""
        password = "TestPassword123!"
        salt = generate_salt()

        start = time.time()
        hash_password(password, salt, version=PASSWORD_HASH_VERSION_CURRENT)
        elapsed = time.time() - start

        # Should complete in under 1 second on modern hardware
        # This is a soft limit - actual time depends on hardware
        # Main goal is to ensure it's not taking minutes
        assert elapsed < 5.0, f"Password hashing too slow: {elapsed:.2f}s"


class TestPasswordHashingBackwardCompatibility:
    """Test backward compatibility with legacy password hashes"""

    def test_can_verify_legacy_hash(self):
        """Should be able to verify passwords hashed with 100k iterations"""
        password = "TestPassword123!"
        salt = "0123456789abcdef" * 4  # Fixed salt for reproducibility

        # Create hash with legacy version (100k iterations)
        legacy_hash = hash_password(password, salt, version=1)

        # Should be able to verify with version 1
        assert verify_password(password, salt, legacy_hash, version=1) is True

    def test_cannot_verify_legacy_hash_with_current_version(self):
        """Legacy hash should NOT verify if using current version iterations"""
        password = "TestPassword123!"
        salt = "0123456789abcdef" * 4

        # Hash with legacy version
        legacy_hash = hash_password(password, salt, version=1)

        # Should NOT verify with current version (different iteration count)
        assert verify_password(password, salt, legacy_hash, version=2) is False

    def test_migration_scenario(self):
        """Simulate migrating a user's password from v1 to v2"""
        password = "UserPassword123!"
        salt = generate_salt()

        # Step 1: User's existing password (v1 - 100k iterations)
        old_hash = hash_password(password, salt, version=1)

        # Step 2: User logs in - verify with v1
        assert verify_password(password, salt, old_hash, version=1) is True

        # Step 3: On successful login, rehash with v2
        new_hash = hash_password(password, salt, version=2)

        # Step 4: Future logins use v2
        assert verify_password(password, salt, new_hash, version=2) is True

        # Verify old and new hashes are different
        assert old_hash != new_hash


class TestPasswordHashingSecurityRegression:
    """Regression tests to ensure security requirements are maintained"""

    def test_no_hardcoded_100k_in_default_path(self):
        """Ensure default hash_password() doesn't use insecure 100k iterations"""
        password = "TestPassword123!"
        salt = generate_salt()

        # Hash using default (no version specified)
        default_hash = hash_password(password, salt)

        # Hash using explicitly v2
        v2_hash = hash_password(password, salt, version=2)

        # Should match v2, not v1
        assert default_hash == v2_hash

    def test_verify_uses_constant_time_comparison(self):
        """Ensure verify_password uses secrets.compare_digest for timing attack resistance"""
        # This test verifies the code uses the secure comparison function
        # by checking the implementation uses secrets.compare_digest

        import inspect
        source = inspect.getsource(verify_password)

        assert "secrets.compare_digest" in source, \
            "verify_password must use secrets.compare_digest for constant-time comparison"

    def test_minimum_iteration_count_enforced(self):
        """Ensure current version meets minimum security requirements"""
        # NIST SP 800-63B and OWASP recommend minimum 600,000 iterations
        min_required = 600000

        current_iterations = PASSWORD_HASH_ITERATIONS[PASSWORD_HASH_VERSION_CURRENT]

        assert current_iterations >= min_required, \
            f"Iteration count {current_iterations} below security minimum {min_required}"

    def test_all_versions_defined(self):
        """Ensure all referenced versions have iteration counts defined"""
        assert PASSWORD_HASH_VERSION_LEGACY in PASSWORD_HASH_ITERATIONS
        assert PASSWORD_HASH_VERSION_CURRENT in PASSWORD_HASH_ITERATIONS

    def test_salt_length_sufficient(self):
        """Ensure generated salt is at least 256 bits (32 bytes)"""
        salt = generate_salt()

        # Salt should be 64 hex characters = 32 bytes = 256 bits
        assert len(salt) >= 64, \
            f"Salt length {len(salt)} insufficient (minimum 64 hex chars for 256 bits)"

    def test_hash_output_length(self):
        """Ensure hash output is correct length for SHA-256"""
        password = "TestPassword123!"
        salt = generate_salt()

        hashed = hash_password(password, salt)

        # SHA-256 produces 32 bytes = 64 hex characters
        assert len(hashed) == 64, \
            f"Hash length {len(hashed)} incorrect (expected 64 for SHA-256)"


class TestPasswordHashingEdgeCases:
    """Test edge cases and error handling"""

    def test_null_byte_in_password(self):
        """Should handle null bytes in password"""
        password = "Password\x00WithNull"
        salt = generate_salt()

        hashed = hash_password(password, salt)

        # Verify it works
        assert verify_password(password, salt, hashed)

    def test_special_characters_in_password(self):
        """Should handle all special characters"""
        password = "!@#$%^&*()_+-=[]{}|;':\",./<>?`~"
        salt = generate_salt()

        hashed = hash_password(password, salt)

        assert verify_password(password, salt, hashed)

    def test_invalid_version_defaults_to_current(self):
        """Invalid version number should default to current version"""
        password = "TestPassword123!"
        salt = generate_salt()

        # Try with invalid version (999)
        hash_invalid = hash_password(password, salt, version=999)

        # Should use current version as fallback
        hash_current = hash_password(password, salt, version=PASSWORD_HASH_VERSION_CURRENT)

        assert hash_invalid == hash_current


# ═══════════════════════════════════════════════════════════════════════════
# HIGH-13 — Long Password Denial of Service
# ═══════════════════════════════════════════════════════════════════════════
#
# The hash_password() function above happily hashes 10MB of input — that is
# correct and NOT the bug (test_hash_password_very_long_password confirms it).
# The bug is that nothing stops a 10MB password from REACHING hash_password()
# via the login endpoint. F-24 raised iterations to 600,000 — a 10MB body now
# costs minutes of CPU per request. The fix is a bound on the request model,
# so Pydantic rejects with 422 before the hasher is ever called.
#
# These tests exercise LoginRequest directly. Model validation is where the
# DoS is stopped — hash_password() is never reached for rejected inputs.


from pydantic import ValidationError
from backend.api.auth import LoginRequest


class TestLoginRequestPasswordLengthBounds:
    """HIGH-13 regression — LoginRequest.password rejects DoS-sized inputs."""

    # ── max_length: the DoS guard ──────────────────────────────────────────

    def test_rejects_password_over_128_chars(self):
        """
        HIGH-13 PRIMARY REGRESSION. 129 chars must fail model validation.
        Pre-fix: accepted, fed to 600k-iteration PBKDF2 → CPU hostage.
        Post-fix: ValidationError at the Pydantic layer, hasher never runs.
        """
        with pytest.raises(ValidationError) as exc:
            LoginRequest(email="a@b.com", password="A" * 129)
        # Confirm it's the length bound that fired, not something incidental
        assert any(
            e["type"] == "string_too_long" and e["loc"] == ("password",)
            for e in exc.value.errors()
        ), f"expected string_too_long on password, got {exc.value.errors()}"

    def test_accepts_password_exactly_128_chars(self):
        """Boundary — 128 is the max, inclusive. NIST SP 800-63B requires
        accepting ≥64; 128 gives headroom for passphrase users without
        opening a DoS window."""
        req = LoginRequest(email="a@b.com", password="A" * 128)
        assert len(req.password) == 128

    @pytest.mark.parametrize("size", [256, 1024, 10_000, 1_000_000])
    def test_rejects_dos_sized_passwords(self, size):
        """
        HIGH-13 PROOF OF IMPACT across sizes. The 1MB case is the attack —
        pre-fix, that single request ties up a PBKDF2 worker for minutes.
        A handful of concurrent 1MB logins = service unavailable.
        """
        payload = "A" * size
        with pytest.raises(ValidationError):
            LoginRequest(email="a@b.com", password=payload)
        # Explicitly confirm the hasher is never reached: model validation
        # raised, so we never got a LoginRequest instance to pass downstream.

    # ── min_length: incidental hardening (MED-4 partial) ───────────────────

    def test_rejects_password_under_8_chars(self):
        """Not the DoS — the other end of the range. MED-4's length floor."""
        with pytest.raises(ValidationError) as exc:
            LoginRequest(email="a@b.com", password="short")  # 5
        assert any(
            e["type"] == "string_too_short" and e["loc"] == ("password",)
            for e in exc.value.errors()
        )

    def test_rejects_empty_password(self):
        """Pre-fix min_length=1 would reject empty too — but min_length=8 is
        the intentional floor now. Explicit so a revert to =1 is visible."""
        with pytest.raises(ValidationError):
            LoginRequest(email="a@b.com", password="")

    def test_accepts_password_exactly_8_chars(self):
        """Boundary — 8 is the min, inclusive."""
        req = LoginRequest(email="a@b.com", password="Pass123!")
        assert req.password == "Pass123!"

    # ── realistic inputs still work ────────────────────────────────────────

    @pytest.mark.parametrize("pw", [
        "Correct Horse Battery Staple",            # 28 — XKCD passphrase
        "Tr0ub4dor&3",                             # 11 — classic
        "a-64-char-token-" + "x" * 48,             # 64 — NIST floor
        "🔒" * 30,                                 # 30 codepoints, unicode
    ])
    def test_accepts_realistic_passwords(self, pw):
        """Sanity — the fix doesn't break normal use. Every realistic
        password lands in [8, 128] codepoints."""
        req = LoginRequest(email="a@b.com", password=pw)
        assert req.password == pw

    # ── tripwire: bounds pinned on the Field itself ────────────────────────

    def test_field_constraints_pinned(self):
        """
        Source-level pin. If someone changes the Field definition — e.g.
        drops max_length during a "harmless" refactor — this fails even if
        the runtime tests above happen to pass for other reasons.
        """
        meta = LoginRequest.model_fields["password"].metadata
        max_lens = [m.max_length for m in meta if hasattr(m, "max_length")]
        min_lens = [m.min_length for m in meta if hasattr(m, "min_length")]
        assert 128 in max_lens, (
            f"HIGH-13 REGRESSION: LoginRequest.password has no max_length=128 "
            f"constraint. Field metadata: {meta}. Unbounded passwords × 600k "
            f"PBKDF2 iterations = CPU exhaustion DoS."
        )
        assert 8 in min_lens, f"min_length=8 missing. Field metadata: {meta}"
