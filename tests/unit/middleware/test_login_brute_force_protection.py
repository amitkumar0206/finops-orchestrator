"""
HIGH-1 regression tests — login brute-force protection.

The bug: /api/auth/login had no rate limiting, no account lockout, no
failed-attempt tracking. Unlimited password guesses per account.

These tests cover the throttle in four layers:
  1. LoginThrottle unit tests — against an in-memory fake of CacheService's
     public surface (get/set/delete/incr_with_window/ttl), so the throttle
     logic runs FOR REAL, not mocked away.
  2. login() integration — the endpoint actually calls check/record/clear
     in the right places.
  3. Fail-open behavior — cache unavailable doesn't lock users out.
  4. Source tripwires — the wiring can't be accidentally removed.
"""

import ast
import inspect
import textwrap
import time

import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from fastapi import HTTPException

from backend.middleware import login_throttle as lt_module
from backend.middleware.login_throttle import LoginThrottle
from backend.api.auth import login, LoginRequest


# ─── In-memory CacheService fake ─────────────────────────────────────────────
#
# The HIGH-32 lesson: tests that mock the storage layer test control flow, not
# behavior. Here we use a REAL dict-backed fake that implements the exact
# CacheService methods LoginThrottle calls — so the throttle's counting,
# key-derivation, and progressive-backoff logic execute unmodified.

class _FakeCache:
    """
    Dict-backed fake of CacheService's get/set/delete/incr_with_window/ttl.
    TTL is tracked as an absolute expiry timestamp and checked on read.
    """

    def __init__(self):
        self._store: dict[str, str] = {}
        self._expiry: dict[str, float] = {}

    def _expired(self, key: str) -> bool:
        exp = self._expiry.get(key)
        return exp is not None and time.monotonic() >= exp

    def _maybe_evict(self, key: str) -> None:
        if self._expired(key):
            self._store.pop(key, None)
            self._expiry.pop(key, None)

    async def get(self, key: str):
        self._maybe_evict(key)
        return self._store.get(key)

    async def set(self, key: str, value: str, ttl_seconds=None) -> bool:
        self._store[key] = value
        if ttl_seconds:
            self._expiry[key] = time.monotonic() + ttl_seconds
        else:
            self._expiry.pop(key, None)
        return True

    async def delete(self, key: str) -> bool:
        self._store.pop(key, None)
        self._expiry.pop(key, None)
        return True

    async def incr_with_window(self, key: str, window_seconds: int):
        self._maybe_evict(key)
        current = int(self._store.get(key, "0"))
        new = current + 1
        self._store[key] = str(new)
        # NX semantics: only set TTL if not already present
        if key not in self._expiry:
            self._expiry[key] = time.monotonic() + window_seconds
        return new

    async def ttl(self, key: str):
        self._maybe_evict(key)
        if key not in self._store:
            return 0
        exp = self._expiry.get(key)
        if exp is None:
            return 0
        return max(0, int(exp - time.monotonic()))

    async def is_connected(self) -> bool:
        return True


class _UnavailableCache:
    """Simulates Valkey down — every method returns the unavailable sentinel."""

    async def get(self, key):
        return None

    async def set(self, key, value, ttl_seconds=None):
        return False

    async def delete(self, key):
        return False

    async def incr_with_window(self, key, window_seconds):
        return None

    async def ttl(self, key):
        return None

    async def is_connected(self):
        return False


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def fake_cache():
    return _FakeCache()


@pytest.fixture
def throttle(fake_cache):
    return LoginThrottle(fake_cache)


@pytest.fixture
def reset_throttle_singleton():
    """Module-level singleton persists across tests — snapshot & restore."""
    snapshot = lt_module._login_throttle
    lt_module._login_throttle = None
    yield
    lt_module._login_throttle = snapshot


def _req(ip: str = "203.0.113.7", xff: str | None = None):
    """Request mock — wires exactly what _get_client_ip reads."""
    r = MagicMock()
    r.headers = {"X-Forwarded-For": xff} if xff else {}
    r.client = Mock(host=ip)
    return r


@pytest.fixture(autouse=True)
def _pin_trusted_proxy_count():
    """
    SECURITY (HIGH-35): LoginThrottle._get_client_ip delegates to
    utils.client_ip.get_client_ip, which reads trusted_proxy_count from
    the lru_cached get_settings(). Pin to 1 (single ALB) so every test in
    this module sees deterministic hops[-1] behavior regardless of what
    an earlier test module left in the settings cache.

    Existing single-entry-XFF tests are unaffected: for a 1-element list,
    hops[-1] == hops[0]. Only multi-entry XFF tests (the HIGH-35 regression
    class below) actually depend on this.
    """
    fake = Mock(trusted_proxy_count=1)
    with patch("backend.utils.client_ip.get_settings", return_value=fake):
        yield


# ═══════════════════════════════════════════════════════════════════════════
# LoginThrottle — unit tests against the fake cache
# ═══════════════════════════════════════════════════════════════════════════

class TestPerEmailLimit:
    """
    EMAIL_LIMIT=5 per 15min. Attempts 1-5 get through to the password check;
    attempt 6 is blocked with a 429 and engages the progressive lockout.
    """

    @pytest.mark.asyncio
    async def test_first_five_attempts_clear(self, throttle):
        """check() reads without incrementing; record_failure() increments."""
        for i in range(LoginThrottle.EMAIL_LIMIT):
            await throttle.check(_req(), "target@example.com")  # no raise
            await throttle.record_failure(_req(), "target@example.com")

    @pytest.mark.asyncio
    async def test_sixth_attempt_blocked_with_429(self, throttle):
        """
        HIGH-1 PRIMARY REGRESSION (per-email).
        Pre-fix: attempt N+1 sailed through. Post-fix: 429 + Retry-After.
        """
        for _ in range(LoginThrottle.EMAIL_LIMIT):
            await throttle.check(_req(), "target@example.com")
            await throttle.record_failure(_req(), "target@example.com")

        with pytest.raises(HTTPException) as exc:
            await throttle.check(_req(), "target@example.com")

        assert exc.value.status_code == 429
        assert exc.value.detail["error"] == "Too many login attempts"
        assert exc.value.detail["retry_after"] > 0
        assert "Retry-After" in exc.value.headers
        assert int(exc.value.headers["Retry-After"]) > 0

    @pytest.mark.asyncio
    async def test_different_emails_independent_counters(self, throttle):
        """Exhausting alice doesn't affect bob."""
        for _ in range(LoginThrottle.EMAIL_LIMIT):
            await throttle.record_failure(_req(), "alice@example.com")

        # alice blocked
        with pytest.raises(HTTPException):
            await throttle.check(_req(), "alice@example.com")

        # bob untouched
        await throttle.check(_req(), "bob@example.com")  # no raise

    @pytest.mark.asyncio
    async def test_email_case_insensitive_shares_counter(self, throttle):
        """
        Alice@Example.com and alice@example.com MUST share a counter.
        Without .lower() before hashing, an attacker multiplies their
        budget: 5 attempts × 2^(chars) case variants.
        """
        # Split attempts across case variants
        await throttle.record_failure(_req(), "alice@example.com")
        await throttle.record_failure(_req(), "Alice@example.com")
        await throttle.record_failure(_req(), "ALICE@example.com")
        await throttle.record_failure(_req(), "aLiCe@example.com")
        await throttle.record_failure(_req(), "alicE@example.com")

        # Any variant now blocked — limit reached across all of them combined
        with pytest.raises(HTTPException):
            await throttle.check(_req(), "alice@example.com")
        with pytest.raises(HTTPException):
            await throttle.check(_req(), "ALICE@EXAMPLE.COM")

    @pytest.mark.asyncio
    async def test_clear_on_success_resets_email_counter(self, throttle):
        """Successful login proves the password — prior failures were typos."""
        for _ in range(LoginThrottle.EMAIL_LIMIT - 1):
            await throttle.record_failure(_req(), "alice@example.com")

        await throttle.clear_on_success("alice@example.com")

        # Fresh budget
        for _ in range(LoginThrottle.EMAIL_LIMIT):
            await throttle.check(_req(), "alice@example.com")
            await throttle.record_failure(_req(), "alice@example.com")


class TestPerIpLimit:
    """
    IP_LIMIT=20 per 15min. Catches password-spraying: one IP, many emails.
    """

    @pytest.mark.asyncio
    async def test_ip_limit_blocks_across_emails(self, throttle):
        """
        HIGH-1 PRIMARY REGRESSION (per-IP).
        Attacker spraying from one IP across many emails hits the IP limit
        even though no single email reaches EMAIL_LIMIT.
        """
        ip = "198.51.100.42"
        # 20 failures across 20 DIFFERENT emails — no email counter trips
        for i in range(LoginThrottle.IP_LIMIT):
            await throttle.check(_req(ip=ip), f"spray{i}@example.com")
            await throttle.record_failure(_req(ip=ip), f"spray{i}@example.com")

        # 21st attempt from same IP blocked, regardless of email
        with pytest.raises(HTTPException) as exc:
            await throttle.check(_req(ip=ip), "fresh@example.com")
        assert exc.value.status_code == 429
        assert "this address" in exc.value.detail["message"]

    @pytest.mark.asyncio
    async def test_different_ips_independent(self, throttle):
        """Rotating IPs evades the IP limit (that's what per-email is for)."""
        for i in range(LoginThrottle.IP_LIMIT):
            await throttle.record_failure(_req(ip="198.51.100.1"), f"e{i}@x.com")

        with pytest.raises(HTTPException):
            await throttle.check(_req(ip="198.51.100.1"), "new@x.com")

        # Different IP, clear
        await throttle.check(_req(ip="198.51.100.2"), "new@x.com")

    @pytest.mark.asyncio
    async def test_clear_on_success_does_not_reset_ip_counter(self, throttle):
        """
        IP counter is shared NAT. Alice's successful login must NOT reset
        the protection against Mallory spraying from the same gateway.
        """
        ip = "198.51.100.99"
        for i in range(LoginThrottle.IP_LIMIT):
            await throttle.record_failure(_req(ip=ip), f"mallory{i}@example.com")

        # Alice succeeds from the same gateway
        await throttle.clear_on_success("alice@example.com")

        # IP still at limit — Mallory still blocked
        with pytest.raises(HTTPException):
            await throttle.check(_req(ip=ip), "mallory-next@example.com")

    @pytest.mark.asyncio
    async def test_x_forwarded_for_used_when_present(self, throttle):
        """
        Behind ALB, client.host is the ALB's IP. XFF carries the real client.
        Single-entry XFF → hops[-1] == that entry (unchanged by HIGH-35 fix).
        """
        # Same client.host, different XFF → different counters
        for i in range(LoginThrottle.IP_LIMIT):
            await throttle.record_failure(
                _req(ip="10.0.0.1", xff="203.0.113.50"), f"e{i}@x.com"
            )

        with pytest.raises(HTTPException):
            await throttle.check(_req(ip="10.0.0.1", xff="203.0.113.50"), "a@x.com")

        # Same ALB IP, different XFF — clear
        await throttle.check(_req(ip="10.0.0.1", xff="203.0.113.99"), "a@x.com")


class TestXffSpoofingDoesNotBypassIpLayer:
    """
    HIGH-35 REGRESSION — X-Forwarded-For spoofing in login throttle.

    The bug (inherited by F-40 from rate_limiting.py's HIGH-12):
    _get_client_ip took X-Forwarded-For.split(",")[0] — the LEFTMOST
    entry. AWS ALB *appends* the connecting peer's IP; it does not strip
    inbound spoofed entries. An attacker password-spraying from one real
    IP could set a random XFF prefix on each request → each request saw
    a fresh "IP" → Layer 1 (per-IP, IP_LIMIT=20) never fired.

    Layer 2 (per-email) still caught TARGETED attacks — the email doesn't
    change — but SPRAY attacks (one IP, many emails, common passwords)
    were completely unprotected.

    Fix: delegate to utils.client_ip.get_client_ip which uses trusted-
    proxy-depth semantics (hops[-N]). With N=1 (single ALB), the
    ALB-appended rightmost entry is the real client. Attacker can prepend
    garbage but cannot modify what the ALB appends.
    """

    @pytest.mark.asyncio
    async def test_spray_with_rotating_spoofed_xff_blocked(self, throttle):
        """
        HIGH-35 PRIMARY REGRESSION.

        One real attacker IP (203.0.113.66) behind the ALB. On each
        request, the attacker sets a different spoofed X-Forwarded-For
        prefix. The ALB appends the real IP as the rightmost entry.

        Pre-fix: .split(",")[0] → each request sees a fresh spoofed IP →
                 IP counter never accumulates → spray runs forever.
        Post-fix: hops[-1] → every request sees 203.0.113.66 → IP counter
                  accumulates normally → 21st request blocked with 429.
        """
        real_attacker_ip = "203.0.113.66"
        alb_ip = "10.0.0.1"  # TCP peer — constant, but irrelevant when XFF present

        # 20 spray attempts across 20 different emails (no email trips
        # Layer 2), each with a DIFFERENT spoofed leftmost XFF entry but
        # the SAME real rightmost entry (what the ALB would append).
        for i in range(LoginThrottle.IP_LIMIT):
            spoofed_xff = f"99.99.{i}.{i}, {real_attacker_ip}"
            await throttle.check(
                _req(ip=alb_ip, xff=spoofed_xff), f"spray{i}@example.com"
            )  # no raise — budget not yet exhausted
            await throttle.record_failure(
                _req(ip=alb_ip, xff=spoofed_xff), f"spray{i}@example.com"
            )

        # 21st attempt with yet another fresh spoof — if the leftmost
        # entry were trusted, this would look like a brand-new IP.
        # Post-fix: the real rightmost IP has 20 failures → BLOCKED.
        with pytest.raises(HTTPException) as exc:
            await throttle.check(
                _req(ip=alb_ip, xff=f"99.99.255.255, {real_attacker_ip}"),
                "spray-next@example.com",
            )

        assert exc.value.status_code == 429, (
            "HIGH-35 REGRESSION: varying the spoofed X-Forwarded-For "
            "prefix must NOT reset the per-IP counter. If this fails, "
            "the leftmost-XFF bug is back and password-spray protection "
            "(Layer 1) is bypassable by setting a random XFF on each "
            "request. Fix: ensure LoginThrottle._get_client_ip delegates "
            "to utils.client_ip.get_client_ip."
        )
        assert "address" in exc.value.detail["message"]

    @pytest.mark.asyncio
    async def test_spoofed_leftmost_ignored_for_key_derivation(self, throttle):
        """
        Unit-level pin: the spoofed leftmost entry does not affect the key.
        Two requests from the same real client with different spoofs share
        a counter.
        """
        real = "203.0.113.66"

        # Exhaust the IP limit under spoof A
        for i in range(LoginThrottle.IP_LIMIT):
            await throttle.record_failure(
                _req(ip="10.0.0.1", xff=f"1.1.1.1, {real}"), f"e{i}@x.com"
            )

        # Check under spoof B — same real IP, so still blocked.
        # Pre-fix: "2.2.2.2" would be a fresh bucket → clear.
        with pytest.raises(HTTPException):
            await throttle.check(
                _req(ip="10.0.0.1", xff=f"2.2.2.2, {real}"), "new@x.com"
            )

    @pytest.mark.asyncio
    async def test_genuinely_different_clients_still_independent(self, throttle):
        """
        Sanity: the fix doesn't over-collapse. Two DIFFERENT real clients
        (different rightmost entries) behind the same ALB keep independent
        counters. The ALB's own IP (TCP peer) being constant is irrelevant.
        """
        alb_ip = "10.0.0.1"

        # Client A exhausts their budget
        for i in range(LoginThrottle.IP_LIMIT):
            await throttle.record_failure(
                _req(ip=alb_ip, xff="203.0.113.10"), f"a{i}@x.com"
            )
        with pytest.raises(HTTPException):
            await throttle.check(_req(ip=alb_ip, xff="203.0.113.10"), "a@x.com")

        # Client B (different rightmost entry) — fresh budget
        await throttle.check(
            _req(ip=alb_ip, xff="203.0.113.20"), "b@x.com"
        )  # no raise


class TestProgressiveBackoff:
    """
    Hitting EMAIL_LIMIT engages a lockout. Each successive lockout doubles:
    15m → 30m → 1h → ... → 24h cap. Strikes decay after 24h clean.
    """

    async def _exhaust_and_trigger(self, throttle, email: str) -> HTTPException:
        """Fill the email bucket, then check() to trigger lockout. Returns the 429."""
        for _ in range(LoginThrottle.EMAIL_LIMIT):
            await throttle.record_failure(_req(), email)
        with pytest.raises(HTTPException) as exc:
            await throttle.check(_req(), email)
        return exc.value

    @pytest.mark.asyncio
    async def test_first_lockout_is_base_duration(self, throttle):
        exc = await self._exhaust_and_trigger(throttle, "victim@example.com")
        retry_after = exc.detail["retry_after"]
        # ~15 minutes (allow tiny slop from test execution time)
        assert LoginThrottle.BASE_LOCKOUT_SECONDS - 5 <= retry_after <= LoginThrottle.BASE_LOCKOUT_SECONDS

    @pytest.mark.asyncio
    async def test_second_lockout_doubles(self, throttle, fake_cache):
        """
        After the first lockout expires (simulated by deleting the lockout key
        but keeping the strike counter), hitting the limit again doubles the
        lockout duration.
        """
        email = "victim@example.com"

        # Strike 1 → 15m
        exc1 = await self._exhaust_and_trigger(throttle, email)
        first_lockout = exc1.detail["retry_after"]

        # Simulate lockout expiry: remove lockout key, keep strike key.
        # (In production, Valkey TTL does this. Strike TTL is 24h, lockout TTL
        # is 15m, so strike outlives lockout.)
        await fake_cache.delete(throttle._email_lockout_key(email))

        # Strike 2 → 30m
        exc2 = await self._exhaust_and_trigger(throttle, email)
        second_lockout = exc2.detail["retry_after"]

        # Roughly doubled (allow test-timing slop)
        assert second_lockout > first_lockout * 1.5
        assert LoginThrottle.BASE_LOCKOUT_SECONDS * 2 - 5 <= second_lockout <= LoginThrottle.BASE_LOCKOUT_SECONDS * 2

    @pytest.mark.asyncio
    async def test_lockout_capped_at_max(self, throttle, fake_cache):
        """2^(strikes-1) × 15m eventually exceeds 24h — must cap."""
        email = "persistent@example.com"

        # Drive strikes up to where the uncapped value would exceed 24h.
        # 15m × 2^7 = 1920m = 32h > 24h, so strike 8 should hit the cap.
        for _ in range(8):
            await self._exhaust_and_trigger(throttle, email)
            await fake_cache.delete(throttle._email_lockout_key(email))

        # Strike 9 — still capped
        exc = await self._exhaust_and_trigger(throttle, email)
        assert exc.detail["retry_after"] <= LoginThrottle.MAX_LOCKOUT_SECONDS

    @pytest.mark.asyncio
    async def test_active_lockout_blocks_before_counter_check(self, throttle, fake_cache):
        """
        Layer 0 fires before layers 1/2. During an active lockout, check()
        raises immediately without reading the failure counters at all.
        """
        email = "locked@example.com"
        await self._exhaust_and_trigger(throttle, email)

        # Lockout is now active. Further checks raise on lockout, not on count.
        with pytest.raises(HTTPException) as exc:
            await throttle.check(_req(), email)
        assert "locked" in exc.value.detail["message"].lower()

    @pytest.mark.asyncio
    async def test_clear_on_success_clears_strikes_and_lockout(self, throttle, fake_cache):
        """
        A successful login during a brute-force campaign means either (a) the
        legitimate user got in, or (b) the attacker succeeded — either way the
        throttle state is moot. Reset to give the legit user a clean slate.
        """
        email = "recovered@example.com"

        # Strike 1, lockout active
        await self._exhaust_and_trigger(throttle, email)
        # Simulate lockout expiry
        await fake_cache.delete(throttle._email_lockout_key(email))
        # Strike 2 recorded but user now remembers their password
        for _ in range(LoginThrottle.EMAIL_LIMIT - 1):
            await throttle.record_failure(_req(), email)

        await throttle.clear_on_success(email)

        # Strike counter cleared — next exhaustion is strike 1 again (15m, not 60m)
        exc = await self._exhaust_and_trigger(throttle, email)
        assert exc.detail["retry_after"] <= LoginThrottle.BASE_LOCKOUT_SECONDS


class TestKeyDerivation:
    """
    Cache keys are SHA-256(normalized). Pins the PII-at-rest and key-injection
    defenses.
    """

    def test_email_key_is_hashed_not_plaintext(self, throttle):
        """No raw email in the Valkey key — `KEYS login:*` mustn't leak PII."""
        email = "alice.secret@example.com"
        key = throttle._email_fail_key(email)
        assert email not in key
        assert email.lower() not in key
        # SHA-256 hex is 64 chars
        suffix = key.removeprefix(LoginThrottle.EMAIL_KEY_PREFIX)
        assert len(suffix) == 64
        assert all(c in "0123456789abcdef" for c in suffix)

    def test_ip_key_is_hashed_blocks_key_injection(self, throttle):
        """
        Attacker-controlled X-Forwarded-For → cache key. Hashing neutralizes
        any protocol injection (newlines, wildcards, FLUSHALL).
        """
        malicious_xff = "evil\r\nFLUSHALL\r\n*"
        key = throttle._ip_key(malicious_xff)
        assert "\r" not in key
        assert "\n" not in key
        assert "FLUSHALL" not in key
        assert "*" not in key

    def test_email_normalization_deterministic(self, throttle):
        """All case variants hash to the same key (load-bearing for the limit)."""
        variants = ["Alice@Example.com", "alice@example.com", "ALICE@EXAMPLE.COM"]
        keys = {throttle._email_fail_key(e) for e in variants}
        assert len(keys) == 1

    def test_four_key_prefixes_distinct(self, throttle):
        """
        Same email → 4 different keys (fail/strike/lockout + ip). No collision
        between a user's failure counter and their strike counter.
        """
        email = "x@y.com"
        keys = {
            throttle._email_fail_key(email),
            throttle._email_strike_key(email),
            throttle._email_lockout_key(email),
            throttle._ip_key("203.0.113.1"),
        }
        assert len(keys) == 4


class TestFailOpen:
    """
    Cache unavailable → throttle degrades gracefully. OPPOSITE of token
    blacklist (which fails closed). See module docstring for the rationale.
    """

    @pytest.mark.asyncio
    async def test_check_allows_when_cache_unavailable(self):
        """Cache outage doesn't lock everyone out of the app."""
        throttle = LoginThrottle(_UnavailableCache())
        # No raise — fail-open
        await throttle.check(_req(), "anyone@example.com")

    @pytest.mark.asyncio
    async def test_record_failure_silent_when_cache_unavailable(self):
        throttle = LoginThrottle(_UnavailableCache())
        await throttle.record_failure(_req(), "anyone@example.com")  # no raise

    @pytest.mark.asyncio
    async def test_fail_open_logs_warning(self):
        """Ops must know the protection is degraded."""
        throttle = LoginThrottle(_UnavailableCache())
        with patch.object(lt_module, "logger") as mock_logger:
            await throttle.check(_req(), "anyone@example.com")
        mock_logger.warning.assert_called()
        event_name = mock_logger.warning.call_args[0][0]
        assert "degraded" in event_name or "fail_open" in event_name


class TestNoPiiInThrottleLogs:
    """
    HIGH-6 tie-in: throttle logs must mask emails, matching auth.py's use of
    mask_email(). A throttle that leaks PII defeats the F-21 fix.
    """

    @pytest.mark.asyncio
    async def test_lockout_log_masks_email(self, throttle):
        canary = "brutus.mcforceface@leakme.example"
        for _ in range(LoginThrottle.EMAIL_LIMIT):
            await throttle.record_failure(_req(), canary)

        with patch.object(lt_module, "logger") as mock_logger:
            with pytest.raises(HTTPException):
                await throttle.check(_req(), canary)

        all_log_args = str(mock_logger.warning.call_args_list)
        assert canary not in all_log_args
        # The masked form IS present (proves email was logged, just masked)
        assert "br***" in all_log_args

    @pytest.mark.asyncio
    async def test_record_failure_log_masks_email(self, throttle):
        canary = "victim.realuser@sensitive.example"
        with patch.object(lt_module, "logger") as mock_logger:
            await throttle.record_failure(_req(), canary)
        all_log_args = str(mock_logger.info.call_args_list)
        assert canary not in all_log_args


# ═══════════════════════════════════════════════════════════════════════════
# login() endpoint integration — throttle is wired correctly
# ═══════════════════════════════════════════════════════════════════════════

def _db_returning(user_row):
    """Mock get_db factory matching the pattern in test_auth_pii_masking.py."""
    mock_db = MagicMock()
    mock_conn = AsyncMock()
    mock_result = MagicMock()
    mock_mappings = MagicMock()
    mock_mappings.first.return_value = user_row
    mock_result.mappings.return_value = mock_mappings

    async def mock_execute(*args, **kwargs):
        return mock_result

    mock_conn.execute = mock_execute
    mock_conn.__aenter__.return_value = mock_conn
    mock_db.engine.begin.return_value = mock_conn
    return AsyncMock(return_value=mock_db)


class TestLoginEndpointThrottleWiring:
    """
    These don't re-test the throttle logic — they verify login() invokes
    check/record_failure/clear_on_success at the right points.
    """

    @pytest.fixture
    def mock_throttle(self):
        t = AsyncMock()
        t.check = AsyncMock(return_value=None)
        t.record_failure = AsyncMock(return_value=None)
        t.clear_on_success = AsyncMock(return_value=None)
        return t

    @pytest.mark.asyncio
    async def test_check_called_before_db_access(self, mock_throttle):
        """
        Throttle check MUST precede DB. If check() raises, get_db() is never
        called — no DB timing oracle, no account-existence leak via 429 timing.
        """
        mock_throttle.check.side_effect = HTTPException(status_code=429, detail="blocked")
        mock_get_db = AsyncMock()

        with patch("backend.api.auth.get_login_throttle", new=AsyncMock(return_value=mock_throttle)), \
             patch("backend.api.auth.get_db", mock_get_db):
            with pytest.raises(HTTPException) as exc:
                await login(
                    LoginRequest(email="any@example.com", password="whatever8"),
                    _req(),
                )

        assert exc.value.status_code == 429
        mock_throttle.check.assert_awaited_once()
        mock_get_db.assert_not_called()  # ← the load-bearing assertion

    @pytest.mark.asyncio
    @pytest.mark.parametrize("failure_path,user_row,verify_password", [
        ("user_not_found", None, None),
        (
            "user_inactive",
            {
                "id": "u1", "email": "x@y.com", "is_active": False,
                "password_hash": "h", "password_salt": "s",
                "password_hash_version": 2, "is_admin": False,
                "default_organization_id": None, "full_name": "X",
            },
            None,
        ),
        (
            "no_password",
            {
                "id": "u1", "email": "x@y.com", "is_active": True,
                "password_hash": None, "password_salt": None,
                "password_hash_version": 2, "is_admin": False,
                "default_organization_id": None, "full_name": "X",
            },
            None,
        ),
        (
            "wrong_password",
            {
                "id": "u1", "email": "x@y.com", "is_active": True,
                "password_hash": "h", "password_salt": "s",
                "password_hash_version": 2, "is_admin": False,
                "default_organization_id": None, "full_name": "X",
            },
            False,
        ),
    ])
    async def test_record_failure_called_on_every_401_path(
        self, mock_throttle, failure_path, user_row, verify_password
    ):
        """
        All 4 failure paths record. Including user_not_found — recording for
        non-existent emails is CORRECT (MED-15: counter mustn't leak existence).
        """
        patches = [
            patch("backend.api.auth.get_login_throttle", new=AsyncMock(return_value=mock_throttle)),
            patch("backend.api.auth.get_db", _db_returning(user_row)),
        ]
        if verify_password is not None:
            patches.append(patch("backend.api.auth.verify_password", return_value=verify_password))

        for p in patches:
            p.start()
        try:
            with pytest.raises(HTTPException) as exc:
                await login(
                    LoginRequest(email="victim@example.com", password="wrong-pw"),
                    _req(ip="203.0.113.1"),
                )
        finally:
            for p in patches:
                p.stop()

        assert exc.value.status_code == 401, f"{failure_path}: expected 401"
        mock_throttle.record_failure.assert_awaited_once()
        mock_throttle.clear_on_success.assert_not_called()

        # record_failure receives the email — so even the user-not-found path
        # increments the per-email counter for that non-existent address
        _, email_arg = mock_throttle.record_failure.await_args.args
        assert email_arg == "victim@example.com"

    @pytest.mark.asyncio
    async def test_clear_on_success_called_after_successful_login(self, mock_throttle):
        """Success clears email state (but not IP — see throttle unit tests)."""
        user_row = {
            "id": "u1", "email": "alice@example.com", "is_active": True,
            "full_name": "Alice", "password_hash": "h", "password_salt": "s",
            "password_hash_version": 2, "is_admin": False,
            "default_organization_id": None,
        }
        token_pair = MagicMock(access_token="at", refresh_token="rt")
        authenticator = MagicMock(create_token_pair=MagicMock(return_value=token_pair))
        settings = MagicMock(jwt_access_token_expiry_minutes=60)

        with patch("backend.api.auth.get_login_throttle", new=AsyncMock(return_value=mock_throttle)), \
             patch("backend.api.auth.get_db", _db_returning(user_row)), \
             patch("backend.api.auth.verify_password", return_value=True), \
             patch("backend.api.auth.get_authenticator", return_value=authenticator), \
             patch("backend.api.auth.get_settings", return_value=settings):
            resp = await login(
                LoginRequest(email="alice@example.com", password="correct!"),
                _req(),
            )

        assert resp.access_token == "at"
        mock_throttle.clear_on_success.assert_awaited_once_with("alice@example.com")
        mock_throttle.record_failure.assert_not_called()


class TestLoginEndpointEndToEnd:
    """
    Full path with a REAL throttle + fake cache. This is the test that would
    have caught HIGH-1 — no mock_throttle, the actual counting runs.
    """

    @pytest.mark.asyncio
    async def test_sixth_wrong_password_attempt_returns_429(
        self, fake_cache, reset_throttle_singleton
    ):
        """
        HIGH-1 END-TO-END REGRESSION.
        Pre-fix: every wrong-password attempt returned 401, forever.
        Post-fix: attempts 1-5 → 401, attempt 6 → 429 with Retry-After header.
        """
        real_throttle = LoginThrottle(fake_cache)
        user_row = {
            "id": "u1", "email": "target@example.com", "is_active": True,
            "full_name": "Target", "password_hash": "h", "password_salt": "s",
            "password_hash_version": 2, "is_admin": False,
            "default_organization_id": None,
        }

        with patch("backend.api.auth.get_login_throttle", new=AsyncMock(return_value=real_throttle)), \
             patch("backend.api.auth.get_db", _db_returning(user_row)), \
             patch("backend.api.auth.verify_password", return_value=False):

            # Attempts 1-5: 401
            for i in range(LoginThrottle.EMAIL_LIMIT):
                with pytest.raises(HTTPException) as exc:
                    await login(
                        LoginRequest(email="target@example.com", password=f"guess-{i:02d}"),
                        _req(),
                    )
                assert exc.value.status_code == 401, (
                    f"Attempt {i + 1} should be 401 (password check runs), got {exc.value.status_code}"
                )

            # Attempt 6: 429 — the fix in action
            with pytest.raises(HTTPException) as exc:
                await login(
                    LoginRequest(email="target@example.com", password="guess-06"),
                    _req(),
                )
            assert exc.value.status_code == 429
            assert "Retry-After" in exc.value.headers
            assert int(exc.value.headers["Retry-After"]) > 0
            assert exc.value.detail["retry_after"] > 0

    @pytest.mark.asyncio
    async def test_ip_spray_blocked_end_to_end(self, fake_cache, reset_throttle_singleton):
        """
        One IP, many emails, all non-existent. 21st blocked by IP limit.
        Also confirms user-not-found path records (MED-15 defense).
        """
        real_throttle = LoginThrottle(fake_cache)
        ip = "198.51.100.200"

        with patch("backend.api.auth.get_login_throttle", new=AsyncMock(return_value=real_throttle)), \
             patch("backend.api.auth.get_db", _db_returning(None)):

            for i in range(LoginThrottle.IP_LIMIT):
                with pytest.raises(HTTPException) as exc:
                    await login(
                        LoginRequest(email=f"spray{i}@example.com", password="common123"),
                        _req(ip=ip),
                    )
                assert exc.value.status_code == 401

            with pytest.raises(HTTPException) as exc:
                await login(
                    LoginRequest(email="spray-next@example.com", password="common123"),
                    _req(ip=ip),
                )
            assert exc.value.status_code == 429
            assert "address" in exc.value.detail["message"]


# ═══════════════════════════════════════════════════════════════════════════
# Source tripwires — prevent accidental unwiring
# ═══════════════════════════════════════════════════════════════════════════

class TestSourceTripwires:
    """
    AST-based pins. If someone refactors login() and drops a throttle call,
    these fail. Matches the pattern from HIGH-32 / HIGH-34 tripwires.
    """

    def _login_ast(self):
        src = textwrap.dedent(inspect.getsource(login))
        return ast.parse(src)

    def _find_awaited_calls(self, tree, method_name: str) -> list:
        """Find `await <anything>.method_name(...)` nodes."""
        hits = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Await)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr == method_name
            ):
                hits.append(node)
        return hits

    def test_login_has_http_request_parameter(self):
        """Signature must accept Request for IP extraction."""
        sig = inspect.signature(login)
        assert "http_request" in sig.parameters, (
            "login() must accept http_request: Request for throttle IP extraction. "
            "Without it, per-IP limiting is impossible."
        )

    def test_throttle_check_called_in_login(self):
        """At least one `await <x>.check(...)` in login()."""
        hits = self._find_awaited_calls(self._login_ast(), "check")
        assert hits, (
            "login() must await throttle.check() — HIGH-1 brute-force guard. "
            "Removing this reopens unlimited password guessing."
        )

    def test_record_failure_called_four_times(self):
        """One per 401 path: not-found, inactive, no-password, wrong-password."""
        hits = self._find_awaited_calls(self._login_ast(), "record_failure")
        assert len(hits) == 4, (
            f"login() must await throttle.record_failure() on all 4 failure "
            f"paths, found {len(hits)}. Missing paths let an attacker bypass "
            f"the counter by triggering a different failure mode."
        )

    def test_clear_on_success_called_in_login(self):
        hits = self._find_awaited_calls(self._login_ast(), "clear_on_success")
        assert len(hits) == 1, (
            "login() must await throttle.clear_on_success() once on the happy "
            "path — without it, legitimate users with occasional typos "
            "accumulate toward lockout across sessions."
        )

    def test_check_precedes_get_db(self):
        """
        Ordering tripwire. throttle.check() must come BEFORE get_db() — else
        attackers get a DB timing oracle (429-on-nonexistent-email is fast,
        429-on-real-email is slow).
        """
        tree = self._login_ast()
        check_line = None
        get_db_line = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
                func = node.value.func
                if isinstance(func, ast.Attribute) and func.attr == "check":
                    check_line = check_line or node.lineno
                elif isinstance(func, ast.Name) and func.id == "get_db":
                    get_db_line = get_db_line or node.lineno
        assert check_line is not None, "throttle.check() not found"
        assert get_db_line is not None, "get_db() not found"
        assert check_line < get_db_line, (
            f"throttle.check() at line {check_line} must PRECEDE get_db() at "
            f"line {get_db_line}. Checking after DB access gives attackers a "
            f"timing oracle and defeats the MED-15 account-enumeration defense."
        )
