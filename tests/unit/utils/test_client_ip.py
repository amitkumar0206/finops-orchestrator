"""
HIGH-12 + HIGH-35 regression tests — trusted-proxy-depth X-Forwarded-For parsing.

The bug: both rate_limiting.py and login_throttle.py used
`X-Forwarded-For.split(",")[0]` — the LEFTMOST entry, which is entirely
attacker-controlled. AWS ALB *appends* the connecting peer's IP to any existing
XFF header; it does not strip inbound spoofed entries.

Attack: `curl -H "X-Forwarded-For: $RANDOM" ...` on every request → each
request sees a fresh IP → per-IP rate limits and login throttle Layer 1 never
fire. Password-spray protection was completely bypassed.

Fix: take the Nth-from-last entry, where N = trusted proxy count.

These tests use the explicit `trusted_proxy_count=` override so they're
deterministic regardless of environment/settings-cache state. One test
exercises the settings-driven default path via a patch.
"""

import ast
import pathlib

from unittest.mock import Mock, patch

from backend.utils.client_ip import get_client_ip, _tcp_peer


# ─── Request mock — wires exactly what get_client_ip reads ───────────────────

def _req(xff: str | None = None, tcp_peer: str = "10.0.0.99"):
    """
    Build a Request mock. tcp_peer is the ALB's own IP from the backend's
    perspective (request.client.host). xff is the X-Forwarded-For header
    value as received — i.e. AFTER all trusted proxies have appended.
    """
    r = Mock()
    r.headers = {"X-Forwarded-For": xff} if xff is not None else {}
    r.client = Mock(host=tcp_peer)
    return r


def _req_no_client(xff: str | None = None):
    """Request with no TCP peer (test mocks, Unix sockets)."""
    r = Mock()
    r.headers = {"X-Forwarded-For": xff} if xff is not None else {}
    r.client = None
    return r


# ═══════════════════════════════════════════════════════════════════════════
# Single ALB — trusted_proxy_count=1 (default AWS topology)
# ═══════════════════════════════════════════════════════════════════════════

class TestSingleALB:
    """
    One trusted proxy. ALB appends the connecting client's IP as the
    rightmost entry. hops[-1] is the real client; anything to the left
    is attacker-prependable garbage.
    """

    def test_single_entry_returns_that_entry(self):
        """Client sent no XFF → ALB appended exactly one entry (the client)."""
        ip = get_client_ip(_req(xff="203.0.113.5"), trusted_proxy_count=1)
        assert ip == "203.0.113.5"

    def test_spoofed_prefix_ignored_rightmost_wins(self):
        """
        HIGH-12/HIGH-35 PRIMARY REGRESSION.

        Pre-fix: .split(",")[0] → "1.1.1.1" (attacker-controlled spoof).
        Post-fix: hops[-1] → "203.0.113.5" (ALB-appended, trustworthy).

        The attacker can prepend as many fake entries as they want — they
        cannot modify what the ALB appends on the right.
        """
        ip = get_client_ip(
            _req(xff="1.1.1.1, 2.2.2.2, 203.0.113.5"),
            trusted_proxy_count=1,
        )
        assert ip == "203.0.113.5"
        assert ip != "1.1.1.1"  # explicit: the old vulnerable value

    def test_many_spoofed_entries_still_rightmost(self):
        """Attacker prepends 10 fake IPs — still defeated."""
        spoofs = ", ".join(f"10.{i}.{i}.{i}" for i in range(10))
        ip = get_client_ip(
            _req(xff=f"{spoofs}, 203.0.113.5"),
            trusted_proxy_count=1,
        )
        assert ip == "203.0.113.5"

    def test_whitespace_stripped(self):
        """Real-world XFF has inconsistent spacing. Must not leak into keys."""
        ip = get_client_ip(
            _req(xff="  1.1.1.1  ,   203.0.113.5   "),
            trusted_proxy_count=1,
        )
        assert ip == "203.0.113.5"
        assert " " not in ip

    def test_tcp_peer_not_returned_when_xff_present(self):
        """
        With a trusted proxy, the TCP peer IS the proxy. Returning it would
        attribute every request in the fleet to the ALB's own IP.
        """
        ip = get_client_ip(
            _req(xff="203.0.113.5", tcp_peer="10.0.0.99"),
            trusted_proxy_count=1,
        )
        assert ip == "203.0.113.5"
        assert ip != "10.0.0.99"


# ═══════════════════════════════════════════════════════════════════════════
# CloudFront → ALB — trusted_proxy_count=2
# ═══════════════════════════════════════════════════════════════════════════

class TestCloudFrontPlusALB:
    """
    Two trusted proxies. Chain: client → CloudFront → ALB → backend.
    CloudFront appends client IP; ALB appends CloudFront's IP.
    hops[-2] is the real client; hops[-1] is CloudFront's egress IP.
    """

    def test_two_entries_returns_second_from_right(self):
        """
        Client sent no XFF. CloudFront appended client (203.0.113.5),
        ALB appended CloudFront (130.176.1.1).
        """
        ip = get_client_ip(
            _req(xff="203.0.113.5, 130.176.1.1"),
            trusted_proxy_count=2,
        )
        assert ip == "203.0.113.5"

    def test_spoofed_prefix_with_depth_two(self):
        """
        Client spoofs "10.0.0.1". CloudFront appends real client (203.0.113.5).
        ALB appends CloudFront (130.176.1.1). hops[-2] defeats the spoof.

        Pre-fix with .split(",")[0]: "10.0.0.1" — attacker wins.
        Post-fix with hops[-2]: "203.0.113.5" — attacker loses.
        """
        ip = get_client_ip(
            _req(xff="10.0.0.1, 203.0.113.5, 130.176.1.1"),
            trusted_proxy_count=2,
        )
        assert ip == "203.0.113.5"
        assert ip != "10.0.0.1"

    def test_depth_two_does_not_return_cloudfront_ip(self):
        """
        Getting this wrong (using hops[-1] with depth=2) would attribute
        every request to CloudFront's egress — effectively no per-IP limits.
        """
        ip = get_client_ip(
            _req(xff="203.0.113.5, 130.176.1.1"),
            trusted_proxy_count=2,
        )
        assert ip != "130.176.1.1"


# ═══════════════════════════════════════════════════════════════════════════
# Direct connection — trusted_proxy_count=0
# ═══════════════════════════════════════════════════════════════════════════

class TestDirectConnection:
    """
    No trusted proxy. ANY X-Forwarded-For header is entirely
    attacker-controlled — there's no proxy to append a verified entry.
    Must ignore XFF entirely and use the TCP peer.
    """

    def test_xff_ignored_tcp_peer_used(self):
        """
        HIGH-12/HIGH-35 SECONDARY REGRESSION.

        With depth=0, trusting ANY part of XFF is wrong. An attacker
        connecting directly can set XFF to anything. The TCP peer is
        the only trustworthy signal.
        """
        ip = get_client_ip(
            _req(xff="1.1.1.1, 2.2.2.2, 3.3.3.3", tcp_peer="198.51.100.7"),
            trusted_proxy_count=0,
        )
        assert ip == "198.51.100.7"
        assert ip not in ("1.1.1.1", "2.2.2.2", "3.3.3.3")

    def test_no_xff_tcp_peer_used(self):
        ip = get_client_ip(_req(tcp_peer="198.51.100.7"), trusted_proxy_count=0)
        assert ip == "198.51.100.7"

    def test_negative_depth_treated_as_zero(self):
        """Defensive: ge=0 on the Field prevents this in prod, but the
        function should not crash or mis-index on a bad override."""
        ip = get_client_ip(
            _req(xff="1.1.1.1", tcp_peer="198.51.100.7"),
            trusted_proxy_count=-1,
        )
        assert ip == "198.51.100.7"


# ═══════════════════════════════════════════════════════════════════════════
# Fallback paths — XFF absent, malformed, or chain too short
# ═══════════════════════════════════════════════════════════════════════════

class TestFallbacks:
    """
    When XFF is unusable, fall back to the TCP peer. The TCP peer behind a
    proxy IS the proxy's IP — not ideal, but rate-limiting everyone through
    the proxy's bucket is strictly safer than trusting attacker-controlled
    data.
    """

    def test_xff_absent_falls_back_to_tcp_peer(self):
        """
        Header missing. Either the proxy was bypassed (VPC misconfiguration —
        backend should only accept connections from the ALB security group)
        or this is local dev. TCP peer is the best signal available.
        """
        ip = get_client_ip(_req(tcp_peer="10.0.0.99"), trusted_proxy_count=1)
        assert ip == "10.0.0.99"

    def test_chain_shorter_than_depth_falls_back(self):
        """
        depth=2 but only 1 entry in XFF. With 2 trusted proxies, the SHORTEST
        legitimate chain is 2 entries (client sent no XFF → each proxy
        appended one). A 1-entry chain means a proxy was bypassed or
        TRUSTED_PROXY_COUNT is misconfigured. Don't trust a partial chain —
        a naive hops[-2] here would IndexError or return garbage.
        """
        ip = get_client_ip(
            _req(xff="203.0.113.5", tcp_peer="10.0.0.99"),
            trusted_proxy_count=2,
        )
        assert ip == "10.0.0.99"

    def test_chain_exactly_at_depth_works(self):
        """Boundary: len(hops) == depth. Legitimate minimal chain."""
        ip = get_client_ip(
            _req(xff="203.0.113.5, 130.176.1.1"),
            trusted_proxy_count=2,
        )
        assert ip == "203.0.113.5"  # hops[-2] of a 2-list = hops[0]

    def test_empty_segments_filtered(self):
        """
        Malformed but observed in the wild: `,,1.2.3.4,`. Without filtering,
        the empty-string hops would poison len(hops) and the index math.
        """
        ip = get_client_ip(
            _req(xff=",, 203.0.113.5 ,"),
            trusted_proxy_count=1,
        )
        assert ip == "203.0.113.5"

    def test_all_empty_segments_falls_back(self):
        """`X-Forwarded-For: , ,` → zero valid hops → TCP peer."""
        ip = get_client_ip(
            _req(xff=" , , ", tcp_peer="10.0.0.99"),
            trusted_proxy_count=1,
        )
        assert ip == "10.0.0.99"

    def test_empty_string_xff_falls_back(self):
        """`X-Forwarded-For: ` (empty value) → falsy → TCP peer."""
        ip = get_client_ip(
            _req(xff="", tcp_peer="10.0.0.99"),
            trusted_proxy_count=1,
        )
        assert ip == "10.0.0.99"

    def test_no_client_returns_unknown_literal(self):
        """
        request.client is None (test mocks, Unix sockets). Returning None
        would crash the SHA-256 key-derivation downstream — return a
        stable sentinel string instead.
        """
        ip = get_client_ip(_req_no_client(), trusted_proxy_count=1)
        assert ip == "unknown"

    def test_tcp_peer_helper_directly(self):
        """_tcp_peer is the single fallback point — pin it."""
        assert _tcp_peer(_req(tcp_peer="198.51.100.1")) == "198.51.100.1"
        assert _tcp_peer(_req_no_client()) == "unknown"


# ═══════════════════════════════════════════════════════════════════════════
# Settings-driven default path
# ═══════════════════════════════════════════════════════════════════════════

class TestSettingsIntegration:
    """
    When trusted_proxy_count is not passed explicitly, get_client_ip reads
    settings.trusted_proxy_count. Production call sites (rate_limiting.py,
    login_throttle.py) use this path. Patch get_settings on the client_ip
    module to avoid the lru_cache and Settings() instantiation side effects.
    """

    def test_none_override_reads_from_settings(self):
        """The per-client SaaS configurability path — no explicit override."""
        fake_settings = Mock(trusted_proxy_count=1)
        with patch(
            "backend.utils.client_ip.get_settings", return_value=fake_settings
        ):
            ip = get_client_ip(_req(xff="1.1.1.1, 203.0.113.5"))
        assert ip == "203.0.113.5"

    def test_settings_depth_two(self):
        """Tenant with CloudFront+ALB sets TRUSTED_PROXY_COUNT=2."""
        fake_settings = Mock(trusted_proxy_count=2)
        with patch(
            "backend.utils.client_ip.get_settings", return_value=fake_settings
        ):
            ip = get_client_ip(_req(xff="1.1.1.1, 203.0.113.5, 130.176.1.1"))
        assert ip == "203.0.113.5"

    def test_settings_depth_zero(self):
        """Local dev / direct connection: TRUSTED_PROXY_COUNT=0 → XFF ignored."""
        fake_settings = Mock(trusted_proxy_count=0)
        with patch(
            "backend.utils.client_ip.get_settings", return_value=fake_settings
        ):
            ip = get_client_ip(_req(xff="1.1.1.1", tcp_peer="127.0.0.1"))
        assert ip == "127.0.0.1"

    def test_explicit_override_beats_settings(self):
        """
        Explicit arg takes precedence. Ensures test determinism — a test
        passing trusted_proxy_count=1 is immune to env/settings drift.
        """
        fake_settings = Mock(trusted_proxy_count=99)  # would crash if used
        with patch(
            "backend.utils.client_ip.get_settings", return_value=fake_settings
        ):
            ip = get_client_ip(
                _req(xff="1.1.1.1, 203.0.113.5"),
                trusted_proxy_count=1,
            )
        assert ip == "203.0.113.5"


# ═══════════════════════════════════════════════════════════════════════════
# AST tripwire — the vulnerable pattern cannot return
# ═══════════════════════════════════════════════════════════════════════════

class TestNoLeftmostXffPatternInMiddleware:
    """
    HIGH-12/HIGH-35 TRIPWIRE.

    The bug was `X-Forwarded-For.split(",")[0]` — grabbing the leftmost
    (attacker-controlled) entry. This tripwire walks the AST of every
    middleware module and fails if it finds `<anything>.split(",")[0]`
    anywhere. The pattern is distinctive enough that false positives are
    unlikely, and a false positive is far preferable to a silent regression.

    This is the ONLY place X-Forwarded-For should be parsed. If a new
    middleware needs the client IP, it must import get_client_ip.
    """

    MIDDLEWARE_DIR = (
        pathlib.Path(__file__).resolve().parents[3] / "backend" / "middleware"
    )

    def _find_split_comma_zero(self, tree: ast.Module) -> list[tuple[int, str]]:
        """
        Find `<expr>.split(",")[0]` nodes. Returns (lineno, unparsed) for each.

        Shape: Subscript(value=Call(func=Attribute(attr='split'),
                                    args=[Constant(',')]),
                         slice=Constant(0))
        """
        hits: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Subscript):
                continue
            # [0]
            sl = node.slice
            if not (isinstance(sl, ast.Constant) and sl.value == 0):
                continue
            # .split(...)
            call = node.value
            if not (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "split"
            ):
                continue
            # ("," or ', ')  — any comma separator is the XFF pattern
            if not (
                call.args
                and isinstance(call.args[0], ast.Constant)
                and isinstance(call.args[0].value, str)
                and "," in call.args[0].value
            ):
                continue
            hits.append((node.lineno, ast.unparse(node)))
        return hits

    def test_middleware_dir_exists(self):
        """Sanity: if the path is wrong the tripwire silently passes on nothing."""
        assert self.MIDDLEWARE_DIR.is_dir(), (
            f"Middleware directory not found at {self.MIDDLEWARE_DIR} — "
            f"tripwire path resolution is broken and the tripwire is not "
            f"protecting anything. Fix the path."
        )
        py_files = list(self.MIDDLEWARE_DIR.glob("*.py"))
        assert py_files, f"No .py files under {self.MIDDLEWARE_DIR}"

    def test_no_split_comma_zero_in_any_middleware(self):
        """
        The load-bearing tripwire. Parses every middleware/*.py and asserts
        the vulnerable `.split(",")[0]` pattern appears nowhere.

        If this fails: someone reintroduced the HIGH-12/HIGH-35 bug. Do NOT
        silence this test. Fix the code to call get_client_ip() instead.
        """
        violations: list[str] = []
        for py_file in sorted(self.MIDDLEWARE_DIR.glob("*.py")):
            source = py_file.read_text()
            tree = ast.parse(source, filename=str(py_file))
            for lineno, snippet in self._find_split_comma_zero(tree):
                violations.append(f"  {py_file.name}:{lineno}  →  {snippet}")

        assert not violations, (
            "HIGH-12/HIGH-35 REGRESSION — leftmost-XFF pattern found in "
            "middleware.\n\n"
            "`X-Forwarded-For.split(\",\")[0]` trusts the LEFTMOST entry, "
            "which is attacker-controlled. AWS ALB appends the real client "
            "IP as the RIGHTMOST entry. Taking leftmost lets an attacker "
            "bypass every IP-based control by setting a random XFF header.\n\n"
            "Fix: import get_client_ip from backend.utils.client_ip and "
            "call that instead.\n\n"
            "Violations:\n" + "\n".join(violations)
        )

    def test_both_middlewares_delegate_to_shared_helper(self):
        """
        Positive pin: both call sites import from utils.client_ip. Without
        this, a refactor that inlines the logic (correctly, at first) would
        pass the negative tripwire but drift over time.
        """
        for filename in ("login_throttle.py", "rate_limiting.py"):
            source = (self.MIDDLEWARE_DIR / filename).read_text()
            tree = ast.parse(source)
            imports_helper = any(
                isinstance(node, ast.ImportFrom)
                and node.module == "backend.utils.client_ip"
                and any(alias.name == "get_client_ip" for alias in node.names)
                for node in ast.walk(tree)
            )
            assert imports_helper, (
                f"{filename} must import get_client_ip from "
                f"backend.utils.client_ip. Inlined XFF parsing — even if "
                f"currently correct — will drift. One parser, one place."
            )
