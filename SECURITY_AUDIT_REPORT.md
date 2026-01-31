# Security Audit Report — FinOps AI Cost Intelligence Platform

**Date:** 2026-01-31
**Previous Audit:** 2026-01-21 (updated 2026-01-31)
**Auditor:** Full-stack penetration test & static code analysis
**Scope:** Backend (Python/FastAPI), Frontend (React/TypeScript), Infrastructure (CloudFormation, Docker, Nginx)

---

## Executive Summary

This report replaces the previous version. Every previously documented fix has been re-verified against the actual source code. **One prior fix (HIGH-4: AWS Credentials) was incorrectly marked as fully resolved** — `execute_query_v2.py`, the primary query-execution path, and six other backend services still instantiate raw `boto3.client()` objects, bypassing the IAM-role session factory that was introduced to replace them. Additionally, a previously documented medium-severity Jinja2 risk has been **upgraded to HIGH** after confirming a concrete exploit path through user-supplied report templates.

| Severity | Verified Fixed | Open (carried) | New / Re-graded |
|----------|---------------|-----------------|-----------------|
| CRITICAL | 8             | 0               | 0               |
| HIGH     | 10            | 0               | 4 (SSTI↑, SSRF, IAM, metrics) |
| MEDIUM   | 3             | 6               | 4 (sourcemaps, CDN, cron, error-leak) |
| LOW      | 2             | 0               | 2 (defaults, audit params) |

---

## 1 — VERIFIED FIXED (No action needed)

The following issues were documented in previous audits, and the fixes have been confirmed against current source code. They are retained here for the audit trail only.

| # | Issue | Fix Commit/Evidence |
|---|-------|---------------------|
| F-1 | Authentication bypass via `X-User-Email` header | `middleware/authentication.py` — header path removed entirely; JWT-only |
| F-2 | Hardcoded `SECRET_KEY` default | `config/settings.py:275-280` — startup crash if not set; 32-char minimum enforced |
| F-3 | SSL `CERT_NONE` on database connections | `services/database.py:100-120` — `verify-full` mode works correctly. **Note:** default is still `prefer` (see MED-7) |
| F-4 | CORS wildcard with credentials | `main.py:149-156` + `settings.py:610-654` — explicit origins/methods/headers |
| F-5 | Missing security headers | `middleware/security_headers.py` — CSP, HSTS, X-Frame-Options, etc. |
| F-6 | SQL injection in `athena_query_service.py` | Service-code allowlist validation via `validate_service_code()` |
| F-7 | Token revocation (logout did nothing) | `cache_service.py` SHA-256 blacklist; checked in `authentication.py`. Fail-closed behaviour confirmed (see F-9) |
| F-8 | Exposed ANTHROPIC_AUTH_TOKEN in `.claude/` | Removed from git tracking (commit `ac0a3a2`); token should be rotated |
| F-9 | Token blacklist fails open when Valkey is unavailable | `cache_service.py:211-224, 236-249` — all four fail-open paths changed to fail-closed (`return True`). Exception handlers in both check functions also hardened. 543 tests pass. |
| F-10 | Incomplete IAM-Role Migration: Raw `boto3.client()` in production paths | All six files migrated to `create_aws_session()` + `AwsService` constants. Cross-account AssumeRole path in `multi_account_service.py` intentionally preserved. AST-based and runtime tests added (`test_iam_migration.py`). 568 tests pass. |
| F-11 | Health Endpoint Information Disclosure | Public probes (`/health`, `/liveness`, `/readiness`) stripped to minimal payloads — no topology, no exception strings. All detailed checks moved behind `/health/detailed` with `require_auth` dependency. Every `_check_*` helper logs raw errors via structlog and returns only generic status messages. Athena table check broadened to catch `Exception` (not just `ClientError`) for resilience. S3 path, database name, table name, model ID, quota, and query failure reasons removed from all responses. 26 sanitisation tests added (`test_health.py`). 598 tests pass. |
| F-12 | Internal Exception Details Exposed in API Responses | All 24 `str(e)`/`f"…{str(e)}…"` leaks across 6 API files replaced with generic messages (400→"Invalid request…", 500→"An internal error occurred…", 503→"Service temporarily unavailable.", auth→"Authentication failed"). Every handler now logs the real exception via `structlog` before raising. Two additional leaks discovered and fixed: `execution_result.get("error")` in `athena_queries.py` response body, and `"error": str(e)` in `analytics.py` `get_data_sources_info` fallback. `phase3_enterprise.py` was missing its structlog import — added. 33 tests added (`test_exception_sanitisation.py`): 5 AST-based static checks + 28 runtime tests covering all 6 files. 631 tests pass. |
| F-13 | Deprecated `regex` validator silently ignored | `phase3_enterprise.py:42` — `Field(..., regex=…)` replaced with `Field(..., pattern=…)`. Pydantic v2 raises `PydanticUserError` at class-definition time on `regex`, so the constraint was never enforced. Fix applied as prerequisite for F-12 test imports; verified by the `pattern=` assertion in F-12's static analysis. |

---

## 2 — HIGH SEVERITY

### HIGH-1 — Incomplete IAM-Role Migration: Raw `boto3.client()` in Production Paths — FIXED

**Status:** FIXED — see F-10 in Section 1.

All six files migrated from raw `boto3.client()` / `boto3.session.Session()` to `create_aws_session()` + `AwsService` constants. The single intentional exception — `multi_account_service.py`'s `get_athena_client_for_account()`, which constructs an Athena client from STS AssumeRole temporary credentials for cross-account access — was preserved unchanged. An AST-based static analysis test suite (`TestStaticAnalysis`) confirms zero raw boto3 calls remain in the five fully-migrated files and exactly one in `multi_account_service.py`. Per-service runtime tests verify each class creates its clients through the session factory.

---

### HIGH-2 — Health Endpoint Information Disclosure — FIXED

**Status:** FIXED — see F-11 in Section 1.

Public probes (`/health`, `/liveness`, `/readiness`) now return only minimal payloads with no topology, service details, or exception strings. All comprehensive service checks have been moved to `/health/detailed`, which is gated by `require_auth` (JWT required). Every `_check_*` helper logs the real exception via structlog and returns only a generic status string. Specific removals: `cur_s3_location` (full S3 path) deleted entirely; `athena_database` success returns `"available"` instead of the database name; `athena_table` success returns `"queryable"` instead of the table name; query failure `StateChangeReason` is logged but never returned; LLM `model_id` and `ConsumedQuota` removed from success details. The Athena table check's exception handler was broadened from `ClientError` to `Exception` so that non-AWS exceptions during that sub-check are also caught and sanitised rather than propagating to the outer handler.

---

### HIGH-3 — Internal Exception Details Exposed in API Responses — FIXED

**Status:** FIXED — see F-12 in Section 1.

All 24 leak points across `analytics.py`, `athena_queries.py`, `saved_views.py`, `organizations.py`, `phase3_enterprise.py`, and `auth.py` have been replaced with generic messages. Every handler logs the real exception via structlog before raising. Two additional response-body leaks (not in the original grep) were discovered and fixed: `execution_result.get("error")` passed directly into the `AthenaQueryResponse` body, and `str(e)` in the `get_data_sources_info` fallback dict. `phase3_enterprise.py` was missing its structlog import entirely — added. 33 tests (5 AST static + 28 runtime) added in `tests/unit/api/test_exception_sanitisation.py`.

---

### HIGH-4 — Jinja2 Server-Side Template Injection (SSTI)

**CVSS Estimate:** 8.8
**Status:** OPEN (upgraded from MED-5; exploit path confirmed)
**File:** `backend/services/scheduled_report_service.py:264`

Previously logged as a medium-risk "potential" issue. Re-analysis confirms a **concrete, exploitable path**:

1. User submits `POST /reports/scheduled` with a `report_template` field (`phase3_enterprise.py:107` — no input validation).
2. The template string is stored in the database.
3. When the report executes, `_generate_html()` passes it directly to Jinja2 `Template()`:

```python
# scheduled_report_service.py:263-266
template_str = report.get('report_template') or self._get_default_template()
template = Template(template_str)          # <-- unsandboxed Jinja2
html_content = template.render(...)        # <-- arbitrary code execution
```

The `jinja2.Template` class without `SandboxedEnvironment` allows access to Python internals. A malicious template such as the following achieves remote code execution:

```
{{ config.__class__.__init__.__globals__['os'].popen('id').read() }}
```

#### Remediation

```python
from jinja2 import SandboxedEnvironment

env = SandboxedEnvironment(
    autoescape=True,                          # prevent XSS in output
    undefined=jinja2.StrictUndefined          # fail on unknown variables
)
template = env.from_string(template_str)
html_content = template.render(...)
```

Additionally, validate `report_template` input length and reject templates containing suspicious patterns (`__`, `config`, `import`, `globals`, `getattr`, `subclasses`).

#### Claude Code Fix Instructions

```
In backend/services/scheduled_report_service.py:

1. Replace line 10:
   BEFORE: from jinja2 import Template
   AFTER:  from jinja2.sandbox import SandboxedEnvironment
           import jinja2

2. Replace lines 263-264 in _generate_html():
   BEFORE:
       template_str = report.get('report_template') or self._get_default_template()
       template = Template(template_str)

   AFTER:
       template_str = report.get('report_template') or self._get_default_template()
       env = SandboxedEnvironment(autoescape=True, undefined=jinja2.StrictUndefined)
       template = env.from_string(template_str)

3. In phase3_enterprise.py, add input validation for report_template in
   ScheduledReportCreate (or in the endpoint handler before passing to the service):

       BLOCKED_PATTERNS = ['__', 'config', 'import', 'globals', 'getattr', 'subclasses', 'mro']

       @field_validator('report_template')
       @classmethod
       def validate_template(cls, v):
           if v is None:
               return v
           for pattern in BLOCKED_PATTERNS:
               if pattern in v:
                   raise ValueError(f"Report template contains disallowed content: {pattern}")
           return v
```

---

### HIGH-5 — Server-Side Request Forgery (SSRF) via Webhook Delivery

**CVSS Estimate:** 8.1
**Status:** OPEN (new finding)
**File:** `backend/services/scheduled_report_service.py:352-358`

When a scheduled report is configured with `WEBHOOK` delivery, the URLs come directly from user input (`recipients.webhooks`) and are called with no validation:

```python
async def _deliver_via_webhook(self, webhooks: List[str], result: Dict):
    async with aiohttp.ClientSession() as session:
        for webhook_url in webhooks:
            await session.post(webhook_url, json=result)   # no validation
```

**Exploit scenarios:**
- `http://169.254.169.254/latest/meta-data/` — EC2 instance metadata (credential theft)
- `http://localhost:5432/` — internal database port scan
- `http://internal-vpc-service/admin` — lateral movement to private services
- `http://attacker.com/exfil` — exfiltrate cost data to external party

#### Remediation

1. Maintain an allowlist of approved webhook domains configured by administrators.
2. Block all requests to private/reserved IP ranges (RFC 1918, 169.254.x.x, 127.x.x.x, ::1).
3. Enforce HTTPS-only for webhook targets.

#### Claude Code Fix Instructions

```
In backend/services/scheduled_report_service.py, replace _deliver_via_webhook:

import ipaddress
from urllib.parse import urlparse

BLOCKED_CIDRS = [
    ipaddress.ip_network('10.0.0.0/8'),
    ipaddress.ip_network('172.16.0.0/12'),
    ipaddress.ip_network('192.168.0.0/16'),
    ipaddress.ip_network('169.254.0.0/16'),   # IMDS
    ipaddress.ip_network('127.0.0.0/8'),
]

def _validate_webhook_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != 'https':
        raise ValueError(f"Webhook must use HTTPS: {url}")
    # Resolve hostname and check against blocked CIDRs
    import socket
    try:
        ip = socket.gethostbyname(parsed.hostname)
        for cidr in BLOCKED_CIDRS:
            if ipaddress.ip_address(ip) in cidr:
                raise ValueError(f"Webhook target is in a blocked network: {ip}")
    except socket.gaierror:
        raise ValueError(f"Cannot resolve webhook hostname: {parsed.hostname}")

async def _deliver_via_webhook(self, webhooks, result):
    async with aiohttp.ClientSession() as session:
        for url in webhooks:
            _validate_webhook_url(url)       # raises before any network call
            await session.post(url, json=result)
```

---

### HIGH-6 — Unmasked PII (Email) in Authentication Logs

**CVSS Estimate:** 5.3
**Status:** OPEN (carried from previous audit as HIGH-5)
**File:** `backend/api/auth.py`, lines 146, 153, 161, 172

```python
logger.warning("login_failed_user_not_found", email=request.email)
logger.warning("login_failed_wrong_password", email=request.email)
```

Raw email addresses are written to structured logs on every failed login attempt. This creates a GDPR-reportable PII exposure in log aggregation systems.

#### Remediation

The project already ships `mask_email()` in `backend/utils/pii_masking.py`:

```python
from backend.utils.pii_masking import mask_email

logger.warning("login_failed", email=mask_email(request.email))
# Output: jo***@example.com
```

#### Claude Code Fix Instructions

```
In backend/api/auth.py:

1. Add import at top:
   from backend.utils.pii_masking import mask_email

2. Replace every occurrence of email=request.email in logger calls with:
   email=mask_email(request.email)

   Affected lines: 146, 153, 161, 172 (verify exact lines — search for "email=request.email")
```

---

## 3 — MEDIUM SEVERITY

### MED-1 — Account Scoping Fails Open

**File:** `backend/middleware/account_scoping.py:111-122`

When the database query that loads a user's account permissions throws any exception, the middleware catches it and attaches an **empty context** — which has **zero account restrictions**:

```python
except Exception as e:
    logger.error("failed_to_load_request_context", ...)
    request.state.context = create_empty_context(user_email or 'anonymous')
    # ← request continues with NO account filtering
```

An attacker who can trigger this exception (e.g., via a database connection blip) can bypass multi-tenant isolation for the duration of the outage.

#### Remediation

Fail closed — return an HTTP 503 instead of continuing:

```python
except Exception as e:
    logger.error("failed_to_load_request_context", error=str(e), exc_info=True)
    from starlette.responses import JSONResponse
    return JSONResponse(
        status_code=503,
        content={"detail": "Unable to verify account permissions. Please try again."}
    )
```

#### Claude Code Fix Instructions

```
In backend/middleware/account_scoping.py, replace lines 111-122:

BEFORE:
    except Exception as e:
        logger.error(...)
        request.state.context = create_empty_context(user_email or 'anonymous')
        request.state.request_id = request_id
    return await call_next(request)

AFTER:
    except Exception as e:
        logger.error(
            "failed_to_load_request_context",
            error=str(e),
            request_id=str(request_id),
            exc_info=True,
        )
        from starlette.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={"detail": "Unable to verify account permissions. Please try again later."}
        )
```

---

### MED-2 — Unauthenticated Prometheus Metrics Endpoint

**File:** `backend/main.py` — `/metrics` route

```python
@app.get("/metrics")
async def metrics():
    return generate_latest().decode('utf-8')
```

No authentication. Prometheus metrics expose endpoint paths, HTTP methods, status codes, and request latency — all useful for mapping the internal API surface before an attack.

#### Remediation

Gate `/metrics` behind a check for an internal network source IP or an admin token:

```python
@app.get("/metrics")
async def metrics(request: Request):
    # Option A: restrict to ECS internal network
    if request.client and request.client.host not in ALLOWED_SCRAPER_IPS:
        raise HTTPException(status_code=403, detail="Forbidden")
    return generate_latest().decode('utf-8')
```

#### Claude Code Fix Instructions

```
In backend/main.py, add a source-IP guard to the /metrics endpoint:

BEFORE:
    @app.get("/metrics")
    async def metrics():
        return generate_latest().decode('utf-8')

AFTER:
    from starlette.requests import Request as StarletteRequest

    @app.get("/metrics")
    async def metrics(request: StarletteRequest):
        # Allow only localhost and ECS internal network
        allowed = {"127.0.0.1", "::1"}  # extend with ECS task CIDR if known
        client_ip = request.client.host if request.client else None
        if client_ip not in allowed:
            raise HTTPException(status_code=403, detail="Forbidden")
        return generate_latest().decode('utf-8')
```

---

### MED-3 — LLM Raw Response Logged at Debug Level

**File:** `backend/services/text_to_sql_service.py:659`

```python
logger.debug("LLM raw response", response_length=len(raw_response), response_preview=raw_response[:200])
```

LLM responses include the full SQL query (with table names, filters, and potentially account-scoping data). If log level is set to DEBUG in any environment, this data is written to log aggregators.

#### Remediation

Remove the `response_preview` field or replace it with a hash:

```python
logger.debug("LLM raw response", response_length=len(raw_response))
```

#### Claude Code Fix Instructions

```
In backend/services/text_to_sql_service.py line 659:

BEFORE: logger.debug("LLM raw response", response_length=len(raw_response), response_preview=raw_response[:200])
AFTER:  logger.debug("LLM raw response", response_length=len(raw_response))
```

---

### MED-4 — Weak Password Policy

**File:** `backend/api/auth.py`, line ~40

```python
password: str = Field(..., min_length=1)  # accepts any single character
```

#### Remediation

```python
import re

password: str = Field(..., min_length=12)

@field_validator('password')
@classmethod
def validate_password_strength(cls, v):
    if not re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&]).{12,}$', v):
        raise ValueError(
            'Password must be ≥12 characters and include uppercase, lowercase, a digit, and a special character.'
        )
    return v
```

---

### MED-5 — SSE Stream Data Injection

**File:** `backend/api/chat.py`, lines ~297, 300, 309, 311, 317

Server-Sent Events are constructed via f-strings with unsanitized variables:

```python
yield f"data: {{'type': 'start', 'conversation_id': '{conversation_id}'}}\n\n"
```

A crafted `conversation_id` containing `\n\ndata:` can inject arbitrary SSE messages into the stream.

#### Remediation

Use `json.dumps()` for all SSE payloads:

```python
import json
yield f"data: {json.dumps({'type': 'start', 'conversation_id': conversation_id})}\n\n"
```

#### Claude Code Fix Instructions

```
In backend/api/chat.py:

1. Add: import json   (if not already imported)

2. Replace every f-string SSE yield with json.dumps():
   BEFORE: yield f"data: {{'type': 'start', 'conversation_id': '{conversation_id}'}}\n\n"
   AFTER:  yield f"data: {json.dumps({'type': 'start', 'conversation_id': conversation_id})}\n\n"

   Apply to all yield statements in the streaming generator (lines ~297-317).
```

---

### MED-6 — Missing Rate Limit on Token Validation Endpoint

**File:** `backend/api/auth.py`, `/api/auth/validate` endpoint

The token-validation endpoint has no rate limiting, allowing an attacker to probe thousands of tokens per minute to determine validity.

#### Remediation

Apply the existing rate-limiting middleware configuration to this endpoint explicitly, or add it to the high-rate-limit tier alongside login.

---

### MED-7 — Default SSL Mode is "prefer" (Unverified)

**File:** `backend/config/settings.py`, line ~135

The default `POSTGRES_SSL_MODE=prefer` negotiates encryption but does not verify the server certificate, leaving connections vulnerable to man-in-the-middle attacks in transit.

#### Remediation

Change the default to `verify-full` for production deployments. If the self-signed CA is used in staging, provide its path via `POSTGRES_SSL_CA_CERT`.

---

### MED-8 — Production Sourcemaps Exposed

**File:** `frontend/vite.config.ts`

```typescript
build: {
    sourcemap: true,   // unconditional — applies to production builds
}
```

Sourcemaps expose the original TypeScript source, component structure, and API call patterns to anyone inspecting the JavaScript bundle.

#### Remediation

```typescript
build: {
    sourcemap: process.env.NODE_ENV !== 'production',
}
```

Or set `sourcemap: 'hidden'` to generate sourcemaps for error tracking without shipping them to the client.

#### Claude Code Fix Instructions

```
In frontend/vite.config.ts, replace:
    sourcemap: true

With:
    sourcemap: process.env.NODE_ENV !== 'production',
```

---

### MED-9 — xlsx Package Fetched from External CDN

**File:** `frontend/package.json`

```json
"xlsx": "https://cdn.sheetjs.com/xlsx-0.20.3/xlsx-0.20.3.tgz"
```

This bypasses npm's integrity verification. If the CDN is compromised or the URL is re-pointed, a malicious package is installed without detection.

#### Remediation

Pin to the npm registry and lock with a checksum:

```json
"xlsx": "0.20.3"
```

Then run `npm install` and commit the updated `package-lock.json` (which records the registry hash).

---

### MED-10 — Internal Error Details Leaked in Chat Response

**File:** `backend/agents/multi_agent_workflow.py`, lines in the `except` block of `execute_multi_agent_query()`

```python
"message": f"I encountered an error: {str(e)}. Please try rephrasing your question."
```

Python exception `str(e)` is returned to the end user in the chat response. This can leak file paths, database connection strings, or AWS ARNs.

#### Remediation

```python
logger.error("query_execution_failed", error=str(e), exc_info=True)
return {
    ...
    "message": "I encountered an error while processing your request. Please try rephrasing your question.",
    ...
}
```

#### Claude Code Fix Instructions

```
In backend/agents/multi_agent_workflow.py, find the except block near the end
of execute_multi_agent_query() that returns:
    "message": f"I encountered an error: {str(e)}..."

Replace with:
    logger.error("query_execution_failed", error=str(e), exc_info=True)
    ...
    "message": "I encountered an error while processing your request. Please try rephrasing your question.",

Remove str(e) from both "message" and "final_response" fields.
Also remove str(e) from the "metadata.error" field — replace with a generic token or omit entirely.
```

---

### MED-11 — Unvalidated Cron Expression

**File:** `backend/services/scheduled_report_service.py:380`

```python
cron = croniter(cron_expression, datetime.utcnow())
```

User-supplied `cron_expression` has no validation. While `croniter` raises `ValueError` on syntax errors, expressions like `* * * * *` (every minute) can cause resource exhaustion if many reports are created.

#### Remediation

Add a minimum interval check after parsing:

```python
cron = croniter(cron_expression, datetime.utcnow())
next_run = cron.get_next(datetime)
if (next_run - datetime.utcnow()).total_seconds() < 3600:
    raise ValueError("Cron expression must have a minimum interval of 1 hour")
```

### MED-12 — Token Blacklist Fails Open When Valkey Is Unavailable — FIXED

**Status:** FIXED — see F-9 in Section 1.

All four fail-open return paths in `is_access_token_blacklisted()` and `is_refresh_token_blacklisted()` now return `True` (fail-closed): both the `_client is None` guard and the `except Exception` handler in each function. Log events upgraded from `warning` to `error` to surface cache outages in monitoring. Two existing tests corrected to assert fail-closed behavior; two new tests added covering the exception-handler paths. `test_valid_token_authenticates` in `test_authentication.py` was missing a cache service mock (it previously passed only because fail-open masked the gap) — mock added consistent with the pattern used by adjacent tests in the same class.

---

## 4 — LOW SEVERITY

### LOW-1 — Weak Default Passwords in docker-compose

**File:** `docker-compose.yml`

```yaml
POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-finops_password}
VALKEY_PASSWORD:   ${VALKEY_PASSWORD:-valkey_password}
```

If no `.env` file exists, these trivially-guessable defaults are used silently. A developer who forgets to create `.env` ships a system with known credentials.

#### Remediation

Remove the fallback defaults. Let Docker fail loudly if the variables are not set:

```yaml
POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?Error: POSTGRES_PASSWORD is required}
```

---

### LOW-2 — Deprecated `regex` Validator in Pydantic Model — FIXED

**Status:** FIXED — see F-13 in Section 1.

`Field(..., regex=…)` replaced with `Field(..., pattern=…)` in `phase3_enterprise.py`. Under Pydantic v2, the old `regex` keyword raises `PydanticUserError` at class-definition time rather than silently ignoring the constraint. The fix was applied as a prerequisite for the HIGH-3 test suite and is verified by a static assertion in `TestStaticAnalysis`.

---

### LOW-3 — Unbounded Audit Query Parameters

**File:** `backend/api/phase3_enterprise.py`, `/audit/recent` endpoint

```python
async def get_recent_audit_logs(
    hours: int = 24,    # no upper bound
    limit: int = 1000,  # no upper bound
```

A user can request `hours=999999` and `limit=1000000`, generating an extremely large database query with no guardrails.

#### Remediation

Add `le` constraints:

```python
hours: int = Field(default=24, ge=1, le=168)     # max 1 week
limit: int = Field(default=100, ge=1, le=1000)
```

---

## 5 — DEPENDENCY VULNERABILITIES

The following CVEs were flagged in the previous audit. Verify that pinned versions are actually installed in the production image:

| Package | Min Required | CVE |
|---------|-------------|-----|
| aiohttp | ≥ 3.13.3 | CVE-2025-69223 |
| starlette | ≥ 0.49.1 | CVE-2025-62727 |
| urllib3 | ≥ 2.6.3 | CVE-2025-66418 |
| langchain-core | ≥ 0.3.81 | CVE-2025-65106 |
| langgraph-checkpoint | ≥ 3.0.0 | CVE-2025-64439 |
| pypdf | ≥ 6.6.0 | CVE-2025-62707 |
| filelock | ≥ 3.20.3 | CVE-2025-68146 |
| marshmallow | ≥ 3.26.2 | CVE-2025-68480 |

**Verification:**
```bash
cd backend && pip list | grep -iE "aiohttp|starlette|urllib3|langchain-core|langgraph|pypdf|filelock|marshmallow"
```

---

## 6 — POSITIVE SECURITY CONTROLS (Correctly Implemented)

| Control | Location | Notes |
|---------|----------|-------|
| JWT-only authentication | `middleware/authentication.py` | No header fallback; expiry enforced |
| Token blacklisting on logout | `services/cache_service.py` | SHA-256 hash; TTL matches token lifetime |
| SQL service-code allowlist | `utils/sql_validation.py` | Used in `athena_query_service.py` |
| Account ID regex validation | `services/request_context.py` | `^[0-9]{12}$` |
| PII masking utilities | `utils/pii_masking.py` | Available but under-used (see HIGH-6) |
| Rate limiting middleware | `middleware/rate_limiting.py` | Sliding window; per-endpoint tuning |
| Security headers middleware | `middleware/security_headers.py` | CSP, HSTS, X-Frame-Options |
| Secret key enforcement | `config/settings.py:275-280` | Rejects known-weak values; 32-char min |
| CORS explicit config | `main.py` + `settings.py` | No wildcards with credentials |
| Centralized error utilities | `utils/errors.py` | Generic messages enforced across all API handlers (HIGH-3 fixed) |
| Account-scoping SQL injection prevention | `athena_query_service.py` | Account IDs validated via `^[0-9]{12}$` regex before injection |

---

## 7 — REMEDIATION PRIORITY

### Immediate — Fix Before Any Production Traffic

| # | Finding | Effort |
|---|---------|--------|
| 1 | **HIGH-4** Jinja2 SSTI — `SandboxedEnvironment` | Single file change |
| 2 | **HIGH-5** SSRF via webhooks — URL validation | Single function addition |

### Before GA / Next Sprint

| # | Finding | Effort |
|---|---------|--------|
| 3 | **HIGH-6** Email PII in logs — apply mask_email | 4-line change |
| 4 | **MED-1** Account scoping fail-closed | 5-line change |
| 5 | **MED-10** Chat error message sanitization | 2-line change |

### Within 30 Days

| # | Finding |
|---|---------|
| 6 | MED-2 through MED-11 (all medium items) |
| 7 | LOW-1, LOW-3 |
| 8 | Dependency version verification |
| 9 | External penetration test |

---

## 8 — COMPLIANCE NOTES

| Framework | Gap | Action |
|-----------|-----|--------|
| **SOC 2** | Audit logs exist but fail-open on scoping errors | Fix MED-1 |
| **GDPR** | Email PII in logs | Fix HIGH-6 |
| **AWS Well-Architected** | Incomplete IAM role usage | Fixed (HIGH-1 / F-10) |
| **OWASP Top 10** | A03 Injection (SSTI) | Fix HIGH-4 |
| **OWASP Top 10** | A10 SSRF | Fix HIGH-5 |

---

*Report generated: 2026-01-31. All findings verified against source at commit 513a898.*
