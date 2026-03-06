"""
Login brute-force protection — Valkey-backed, per-IP + per-email, progressive backoff.

SECURITY (HIGH-1): /api/auth/login previously had no rate limiting, no account
lockout, and no failed-attempt tracking. An attacker could:
  - Password-spray: one IP, many emails, common passwords (caught by IP limit)
  - Credential-stuff / target: many IPs, one email (caught by email limit +
    progressive lockout)

Design:
  - Check BEFORE any DB access — no DB timing oracle, and the 429 response is
    identical whether the submitted email corresponds to a real account or not
    (MED-15 account-enumeration defense — we throttle attempts-on-email, not
    attempts-on-account).
  - Count FAILED attempts only; clear the email counter on successful login.
    IP counter is NOT cleared — it's shared across users behind the same NAT
    and a successful login by one user mustn't reset the protection against
    another user spraying from the same egress IP.
  - Progressive backoff: each time the email limit is hit, a strike is
    recorded and the lockout duration doubles (15m → 30m → 1h → ... → 24h cap).
    Strikes decay after 24h clean.
  - Fail-OPEN when Valkey is unavailable. This is the OPPOSITE of the
    token-blacklist check (cache_service.py:212 — fail-closed), and that
    asymmetry is deliberate:
      · Revoked tokens are KNOWN-compromised → a cache outage must not let them
        through; locking everyone out is the lesser harm.
      · Login throttle fail-closed → total site outage for the duration of the
        cache incident. The password check still runs (PBKDF2 600k iterations
        slows brute force regardless). Degraded protection > total outage.
    The fail-open path logs a WARNING so ops can alert on it.

X-Forwarded-For parsing (HIGH-35 fix): delegates to utils.client_ip, which
uses trusted-proxy-depth semantics. The prior implementation took the
leftmost XFF entry (attacker-controlled), allowing password-spray attackers
to bypass Layer 1 entirely by setting a random XFF on each request. The
per-email Layer 2 still caught targeted attacks, but spray was unprotected.
"""

import hashlib
from typing import Optional

import structlog
from fastapi import HTTPException, Request, status

from backend.services.cache_service import CacheService, get_cache_service
from backend.utils.client_ip import get_client_ip
from backend.utils.pii_masking import mask_email

logger = structlog.get_logger(__name__)


class LoginThrottle:
    # ── Limits per the audit brief ───────────────────────────────────────────
    IP_LIMIT = 20
    IP_WINDOW_SECONDS = 900  # 15 minutes

    EMAIL_LIMIT = 5
    EMAIL_WINDOW_SECONDS = 900  # 15 minutes

    # ── Progressive backoff ──────────────────────────────────────────────────
    # Lockout duration = BASE × 2^(strikes-1), capped at MAX.
    # strikes=1 → 15m, 2 → 30m, 3 → 1h, 4 → 2h, 5 → 4h, 6 → 8h, 7 → 16h, 8+ → 24h
    BASE_LOCKOUT_SECONDS = 900
    MAX_LOCKOUT_SECONDS = 86400  # 24h

    # Strikes themselves expire after 24h of no new strikes — a clean day
    # resets the escalation ladder.
    STRIKE_TTL_SECONDS = 86400

    # ── Key prefixes (matching CacheService TOKEN_BLACKLIST_PREFIX style) ────
    IP_KEY_PREFIX = "login:fail:ip:"
    EMAIL_KEY_PREFIX = "login:fail:email:"
    STRIKE_KEY_PREFIX = "login:strike:email:"
    LOCKOUT_KEY_PREFIX = "login:lockout:email:"

    def __init__(self, cache: CacheService):
        self._cache = cache

    # ── Key derivation ───────────────────────────────────────────────────────

    @staticmethod
    def _hash(value: str) -> str:
        """
        SHA-256 for cache keys. Serves three purposes:
          1. No PII-at-rest in Valkey (no raw emails/IPs in KEYS output).
          2. Blocks key-injection via crafted X-Forwarded-For (an attacker
             sending "X-Forwarded-For: *\r\nFLUSHALL" gets a hash, not a
             control sequence).
          3. Fixed-length keys regardless of input.
        """
        return hashlib.sha256(value.encode()).hexdigest()

    def _ip_key(self, ip: str) -> str:
        return f"{self.IP_KEY_PREFIX}{self._hash(ip)}"

    def _email_fail_key(self, email: str) -> str:
        # .lower() is LOAD-BEARING: Alice@Example.com and alice@example.com
        # must share a counter, or an attacker multiplies their attempt budget
        # by the number of case variants. EmailStr normalizes the domain but
        # NOT the local part (RFC 5321 says local parts are case-sensitive,
        # but ~every real mail server treats them case-insensitively).
        return f"{self.EMAIL_KEY_PREFIX}{self._hash(email.lower())}"

    def _email_strike_key(self, email: str) -> str:
        return f"{self.STRIKE_KEY_PREFIX}{self._hash(email.lower())}"

    def _email_lockout_key(self, email: str) -> str:
        return f"{self.LOCKOUT_KEY_PREFIX}{self._hash(email.lower())}"

    @staticmethod
    def _get_client_ip(http_request: Request) -> str:
        # SECURITY (HIGH-35): delegate to the shared trusted-proxy-depth
        # helper. The prior inline .split(",")[0] took the leftmost XFF
        # entry — attacker-controlled, allowing Layer 1 bypass via spoofing.
        return get_client_ip(http_request)

    # ── Public API ───────────────────────────────────────────────────────────

    async def check(self, http_request: Request, email: str) -> None:
        """
        Called at the top of login() BEFORE any DB access.
        Raises HTTPException 429 if throttled; returns None if clear.

        Reads counters without incrementing — increment happens only on
        confirmed failure (record_failure). This ordering means the Nth
        failed attempt gets through to the password check; attempt N+1 is
        blocked. With EMAIL_LIMIT=5, an attacker gets exactly 5 password
        guesses per 15-minute window before the lockout ladder engages.
        """
        ip = self._get_client_ip(http_request)

        # ── Layer 0: active progressive lockout ──
        lockout_remaining = await self._cache.ttl(self._email_lockout_key(email))
        if lockout_remaining is None:
            self._warn_degraded("lockout_check")
            return  # fail-open
        if lockout_remaining > 0:
            logger.warning(
                "login_throttle_lockout_active",
                email=mask_email(email),
                client_ip=ip,
                retry_after_seconds=lockout_remaining,
            )
            self._raise_429(
                retry_after=lockout_remaining,
                reason="Account temporarily locked due to repeated failed login attempts",
            )

        # ── Layer 1: per-IP failed-attempt count ──
        ip_count_raw = await self._cache.get(self._ip_key(ip))
        if ip_count_raw is None and not await self._cache.is_connected():
            self._warn_degraded("ip_check")
            return  # fail-open — can't distinguish "count=0" from "cache down" via get() alone
        ip_count = int(ip_count_raw) if ip_count_raw else 0
        if ip_count >= self.IP_LIMIT:
            logger.warning(
                "login_throttle_ip_exceeded",
                client_ip=ip,
                count=ip_count,
                limit=self.IP_LIMIT,
            )
            self._raise_429(
                retry_after=self.IP_WINDOW_SECONDS,
                reason="Too many failed login attempts from this address",
            )

        # ── Layer 2: per-email failed-attempt count ──
        email_count_raw = await self._cache.get(self._email_fail_key(email))
        email_count = int(email_count_raw) if email_count_raw else 0
        if email_count >= self.EMAIL_LIMIT:
            # Hit the per-email limit — engage the progressive-backoff lockout
            # BEFORE raising 429. The lockout TTL is what the 429 reports.
            lockout_seconds = await self._engage_lockout(email)
            logger.warning(
                "login_throttle_email_exceeded_lockout_engaged",
                email=mask_email(email),
                client_ip=ip,
                count=email_count,
                limit=self.EMAIL_LIMIT,
                lockout_seconds=lockout_seconds,
            )
            self._raise_429(
                retry_after=lockout_seconds,
                reason="Too many failed login attempts for this account",
            )

    async def record_failure(self, http_request: Request, email: str) -> None:
        """
        Called from every 401 path in login() — user-not-found, inactive,
        no-password, wrong-password. Recording for non-existent emails is
        correct: it prevents the attempt counter from leaking whether an
        account exists (MED-15).
        """
        ip = self._get_client_ip(http_request)

        ip_count = await self._cache.incr_with_window(
            self._ip_key(ip), self.IP_WINDOW_SECONDS
        )
        email_count = await self._cache.incr_with_window(
            self._email_fail_key(email), self.EMAIL_WINDOW_SECONDS
        )

        if ip_count is None or email_count is None:
            self._warn_degraded("record_failure")
            return

        logger.info(
            "login_failure_recorded",
            email=mask_email(email),
            client_ip=ip,
            ip_count=ip_count,
            ip_limit=self.IP_LIMIT,
            email_count=email_count,
            email_limit=self.EMAIL_LIMIT,
        )

    async def clear_on_success(self, email: str) -> None:
        """
        Called on successful login. Clears email-keyed state — the user has
        proven they know the password, so any prior failures were legitimate
        typos (or an attacker who's now locked out anyway because the real
        user just rotated credentials, which they didn't).

        Does NOT clear the IP counter. That counter is shared across everyone
        behind the same NAT/VPN egress — Alice logging in successfully must
        not reset the protection against Mallory spraying from the same
        corporate gateway.
        """
        await self._cache.delete(self._email_fail_key(email))
        await self._cache.delete(self._email_lockout_key(email))
        await self._cache.delete(self._email_strike_key(email))

    # ── Internals ────────────────────────────────────────────────────────────

    async def _engage_lockout(self, email: str) -> int:
        """
        Increment the strike counter, compute the lockout duration from it,
        set the lockout key with that TTL. Returns the lockout duration so
        the caller can put it in Retry-After.

        Also clears the failure counter — the lockout REPLACES it. When the
        lockout expires, the user gets a fresh EMAIL_LIMIT attempts before
        the NEXT (longer) lockout.
        """
        strikes = await self._cache.incr_with_window(
            self._email_strike_key(email), self.STRIKE_TTL_SECONDS
        )
        if strikes is None:
            # Cache went away between check() reading the count and here.
            # Fail-open: report the base window, don't set a lockout.
            self._warn_degraded("engage_lockout")
            return self.EMAIL_WINDOW_SECONDS

        lockout_seconds = min(
            self.BASE_LOCKOUT_SECONDS * (2 ** (strikes - 1)),
            self.MAX_LOCKOUT_SECONDS,
        )

        await self._cache.set(
            self._email_lockout_key(email), str(strikes), ttl_seconds=lockout_seconds
        )
        # Lockout replaces the failure window — when it lifts, fresh budget.
        await self._cache.delete(self._email_fail_key(email))

        return lockout_seconds

    def _raise_429(self, retry_after: int, reason: str) -> None:
        """
        Matches the 429 shape from rate_limiting.py:308-322 — detail dict with
        error/message/retry_after, Retry-After header, X-RateLimit-* headers.
        """
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "Too many login attempts",
                "message": f"{reason}. Please try again in {retry_after} seconds.",
                "retry_after": retry_after,
            },
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(self.EMAIL_LIMIT),
            },
        )

    @staticmethod
    def _warn_degraded(operation: str) -> None:
        logger.warning(
            "login_throttle_degraded_fail_open",
            operation=operation,
            message=(
                "Valkey unavailable — login brute-force protection DISABLED. "
                "Password check still runs (PBKDF2 600k iterations). "
                "Alert ops."
            ),
        )


# ── Singleton access ─────────────────────────────────────────────────────────

_login_throttle: Optional[LoginThrottle] = None


async def get_login_throttle() -> LoginThrottle:
    """Get or create the login throttle singleton (lazily wraps CacheService)."""
    global _login_throttle
    if _login_throttle is None:
        cache = await get_cache_service()
        _login_throttle = LoginThrottle(cache)
    return _login_throttle
