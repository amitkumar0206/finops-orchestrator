"""
Trusted-proxy-aware client IP extraction.

SECURITY (HIGH-12, HIGH-35): Prior to this module, both rate_limiting.py and
login_throttle.py used `X-Forwarded-For.split(",")[0]` — the LEFTMOST entry,
which is entirely attacker-controlled. AWS ALB *appends* the connecting peer's
IP to the existing XFF header; it does not strip inbound spoofed entries.

Attack: `curl -H "X-Forwarded-For: $RANDOM" ...` on every request → each
request sees a fresh IP → per-IP rate limits and login throttle Layer 1 never
fire. Password-spray protection was completely bypassed.

Fix: take the Nth-from-last entry, where N = number of trusted proxies between
the client and the backend. An attacker can prepend garbage to the left of the
chain but cannot modify what trusted proxies append on the right.

    Client 203.0.113.5 sends:  X-Forwarded-For: 10.0.0.1, 10.0.0.2   (spoofed)
    ALB appends peer IP:       X-Forwarded-For: 10.0.0.1, 10.0.0.2, 203.0.113.5
    Backend with depth=1:      hops[-1] = 203.0.113.5  ✓ (spoof defeated)

    CloudFront → ALB (depth=2):
    Client sends:              X-Forwarded-For: 10.0.0.1             (spoofed)
    CloudFront appends:        X-Forwarded-For: 10.0.0.1, 203.0.113.5
    ALB appends CF's IP:       X-Forwarded-For: 10.0.0.1, 203.0.113.5, 130.176.x.x
    Backend with depth=2:      hops[-2] = 203.0.113.5  ✓

The proxy count is per-client configurable via `settings.trusted_proxy_count`
(SaaS: different tenants deploy behind different topologies). Default 1 (ALB).
Set to 0 for local dev or direct-connection deployments — XFF is ignored
entirely and the TCP peer address is used.

This is the ONLY place X-Forwarded-For should be parsed. Both call sites
(rate_limiting.py, login_throttle.py) delegate here. An AST tripwire in
tests/unit/utils/test_client_ip.py enforces that no `.split(",")[0]` pattern
on X-Forwarded-For appears anywhere in middleware/.
"""

from fastapi import Request

from backend.config.settings import get_settings


def get_client_ip(
    request: Request,
    trusted_proxy_count: int | None = None,
) -> str:
    """
    Extract the real client IP using trusted-proxy-depth semantics.

    Args:
        request: FastAPI request object.
        trusted_proxy_count: Number of trusted reverse proxies. If None,
            reads from settings.trusted_proxy_count. Explicit override is
            provided for tests and for callers that need deterministic
            behavior independent of environment configuration.

    Returns:
        The client IP as a string. Falls back to the TCP peer address
        (request.client.host) — and ultimately the literal "unknown" — when
        X-Forwarded-For is absent, malformed, or shorter than the trusted
        depth (which indicates either a bypassed proxy or misconfiguration;
        in both cases the TCP peer is the best available signal).
    """
    if trusted_proxy_count is None:
        trusted_proxy_count = get_settings().trusted_proxy_count

    # trusted_proxy_count == 0: direct connection. ANY X-Forwarded-For header
    # is entirely attacker-controlled — there is no trusted proxy to append a
    # verified entry. Ignore the header and use the TCP peer.
    if trusted_proxy_count <= 0:
        return _tcp_peer(request)

    forwarded = request.headers.get("X-Forwarded-For")
    if not forwarded:
        # Header absent. Either the request bypassed the proxy (shouldn't be
        # possible in a properly secured VPC — backend should only accept
        # connections from the ALB's security group) or this is local dev.
        # TCP peer is the best signal we have.
        return _tcp_peer(request)

    # Split and strip. Filter empty segments — `X-Forwarded-For: ,,1.2.3.4,`
    # (malformed but observed in the wild) would otherwise yield empty hops.
    hops = [h.strip() for h in forwarded.split(",") if h.strip()]

    if len(hops) < trusted_proxy_count:
        # Chain shorter than trusted depth. With N trusted proxies, the
        # shortest legitimate chain is exactly N entries (a client that sent
        # no XFF — each proxy appended one). Fewer entries means a proxy was
        # bypassed or TRUSTED_PROXY_COUNT is misconfigured. Don't trust a
        # partial chain; fall back to TCP peer.
        return _tcp_peer(request)

    # Take the Nth-from-last entry — the rightmost entry appended by the
    # outermost trusted proxy, which saw the real client's connection.
    # Everything to the left of this point is attacker-prependable.
    return hops[-trusted_proxy_count]


def _tcp_peer(request: Request) -> str:
    """TCP peer address, or 'unknown' if unavailable (test mocks, Unix sockets)."""
    return request.client.host if request.client else "unknown"
