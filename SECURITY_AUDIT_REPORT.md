# Security Audit Report

## FinOps AI Cost Intelligence Platform

| | |
|---|---|
| **Report Date** | 2026-03-05 |
| **Previous Audits** | 2026-03-04, 2026-02-08, 2026-01-31 |
| **Methodology** | Penetration test, static code analysis, dependency scanning, infrastructure review |
| **Scope** | Backend (Python/FastAPI), Frontend (React/TypeScript), Infrastructure (CloudFormation, Docker, Nginx), Database Models & Migrations, Dependencies |

---

## Table of Contents

| # | Section | Description |
|---|---------|-------------|
| 1 | [Executive Summary](#1--executive-summary) | Risk overview, progress, and systemic findings |
| 2 | [Open Vulnerability Matrix](#2--open-vulnerability-matrix) | All open issues in one sortable table |
| 3 | [Critical Vulnerabilities](#3--critical-vulnerabilities-1-open) | Detailed analysis & remediation for CRITICAL findings |
| 4 | [High Vulnerabilities](#4--high-vulnerabilities-33-open) | Detailed analysis & remediation for HIGH findings |
| 5 | [Medium Vulnerabilities](#5--medium-vulnerabilities-28-open) | Detailed analysis & remediation for MEDIUM findings |
| 6 | [Low Vulnerabilities](#6--low-vulnerabilities-13-open) | Concise table of LOW findings with fixes |
| 7 | [SaaS Multi-Tenant Checklist](#7--saas-multi-tenant-security-checklist) | Per-client configurability requirements |
| 8 | [Remediation Roadmap](#8--prioritized-remediation-roadmap) | Phased action plan |
| A | [Appendix: Fixed Issues](#appendix-a--fixed-issues) | Pointer to historical fix record |

---

## 1 — Executive Summary

This is the fourth comprehensive security audit. Since the 2026-03-04 audit, **CRIT-10 and CRIT-11 have been fixed** (the unauthenticated streaming and reports endpoints). Deep-dive verification of recently-merged rate-limiting and encryption code additionally uncovered **4 new vulnerabilities** — two of which are HIGH-severity defects in newly-introduced security controls.

### Risk Dashboard

```
 CRITICAL  █  1 open     (was 3, -2 fixed)    ← IMMEDIATE ACTION REQUIRED
 HIGH      █████████████████████████████████  33 open    (was 31)
 MEDIUM    ████████████████████████████  28 open    (was 27, +2 new, -1 fixed)
 LOW       █████████████  13 open    (unchanged)
 ──────────────────────────────────────────
 TOTAL OPEN: 75          FIXED: 35 (historical)
```

| Severity | Previously Open | Fixed This Cycle | New Findings | **Total Open** |
|:---------|:---------------:|:----------------:|:------------:|:--------------:|
| CRITICAL | 3 | **2** | 0 | **1** |
| HIGH | 31 | 0 | +2 | **33** |
| MEDIUM | 27 | **1** | +2 | **28** |
| LOW | 13 | 0 | 0 | **13** |
| **Total** | **74** | **3** | **+4** | **75** |

### Top 3 Systemic Risks

> **1. Security Controls That Don't Work**
> The new per-user rate limiter (HIGH-32) creates a fresh in-memory limiter on **every request**, so the limit is never enforced. The CRIT-9 field-encryption fix will **crash production** because `FIELD_ENCRYPTION_KEY` was never added to the ECS task definition (HIGH-33). **Security features must be verified end-to-end, not just unit-tested.**

> **2. Inconsistent Authentication Enforcement**
> The opportunities API still lacks mandatory authentication — `api/opportunities.py` has **zero** `Depends(get_request_context)` or `Depends(require_auth)` decorators. *(All four chat endpoints were hardened this cycle — see F-33. Reports endpoints were secured this cycle — see F-35.)*

> **3. Missing Multi-Tenant Isolation**
> Many database tables and API queries lack `organization_id` scoping, enabling cross-tenant data leakage across client organizations in this SaaS platform.

### What Was Fixed Since Last Audit

| ID | Issue | Severity | Evidence |
|:---|:------|:--------:|:---------|
| CRIT-10 → **F-33** | Unauthenticated Streaming Endpoint with Cross-Tenant Access | CRITICAL | `api/chat.py` rewritten with centralized `require_conversation_owner()` + `resolve_owned_conversation()` helpers. **All four endpoints** (`/chat`, `/stream`, GET/DELETE `/conversations/{id}`) now: (a) require auth via `Depends(get_request_context)` — `/chat`'s IP/anon fallback removed; (b) verify conversation ownership via a single code path; (c) pass `organization_id` + `account_ids` to the agent workflow. Unified audit event `unauthorized_conversation_attempt` with `action` field. 45 regression tests. |
| MED-5 → **F-34** | SSE Stream Data Injection | MEDIUM | `api/chat.py:437` — SSE error path now emits a static message; exception text is logged server-side only (resolved as part of the F-33 rewrite). |
| CRIT-11 → **F-35** | Unauthenticated Reports Endpoints | CRITICAL | `api/reports.py` — both endpoints now require `Depends(get_request_context)` (401 on missing auth). Response contract includes `organization_id` + `account_ids` to establish tenant-scoping for future implementation. Audit events `reports_listed` / `report_generation_requested` emit `user_id` + `organization_id` (no email — MED-28 compliant). Router-level tripwire test enforces every future route must carry the auth dependency. 15 tests in `tests/unit/api/test_reports_security.py`. |

See [`FIXED_SECURITY_ISSUES.md`](./FIXED_SECURITY_ISSUES.md) for the full historical record of 35 fixed issues.

### Partial Improvements Noted

| ID | Issue | Status | Evidence |
|:---|:------|:-------|:---------|
| MED-3 | LLM raw response logged | **PARTIAL** | `text_to_sql_service.py:661` now truncates to 200-char preview (was full response) |
| MED-15 | Account enumeration via login errors | **PARTIAL** | 3 of 4 failure paths now return identical message; "Account is disabled" at `auth.py:208` still differs |

---

## 2 — Open Vulnerability Matrix

All **75 open issues** sorted by severity and CVSS score. Use this table as a tracking dashboard.

### Critical (1)

| ID | Title | CVSS | Location | Discovered |
|:---|:------|:----:|:---------|:-----------|
| CRIT-12 | SQL Injection via Date Params in Athena Queries | 8.6 | `services/athena_query_service.py:153-337` | 2026-03-04 |

### High (33)

| ID | Title | CVSS | Location | Discovered |
|:---|:------|:----:|:---------|:-----------|
| HIGH-1 | No Brute Force Protection on Login | 7.5 | `api/auth.py:175-324` | 2026-02-08 |
| HIGH-3 | Missing CSRF Protection | 7.2 | Application-wide | 2026-02-08 |
| HIGH-4 | Race Condition in Opportunity Cost Calculations | 7.8 | `services/opportunities_service.py:150-200` | 2026-02-08 |
| HIGH-5 | TOCTOU in Saved Views Access Control | 7.5 | `services/saved_views_service.py:142-170` | 2026-02-08 |
| HIGH-6 | Mass Assignment in Opportunity Updates | 7.5 | `api/opportunities.py:300-330` | 2026-02-08 |
| HIGH-7 | In-Memory Rate Limiting Ineffective | 7.5 | `middleware/rate_limiting.py:23-51` | 2026-02-08 |
| HIGH-8 | Fail-Open Cache Bypass in Auth Middleware | 8.1 | `middleware/authentication.py:209-222` | 2026-02-08 |
| HIGH-9 | Dynamic SQL Column Names in opportunities_service | 7.8 | `services/opportunities_service.py:446-462` | 2026-02-08 |
| HIGH-10 | Race Condition in Saved Views Default Flag | 7.5 | `services/saved_views_service.py:76-84` | 2026-02-08 |
| HIGH-11 | TOCTOU in Organization Member Limit | 6.8 | `services/organization_service.py:336-352` | 2026-02-08 |
| HIGH-12 | X-Forwarded-For Spoofing Bypasses Rate Limits | 7.5 | `middleware/rate_limiting.py:60-63` | 2026-03-04 |
| HIGH-13 | Long Password Denial of Service | 7.5 | `api/auth.py:42` | 2026-03-04 |
| HIGH-14 | Missing Tenant Isolation in Conversation Access | 8.0 | `services/conversation_manager.py:139-424` | 2026-03-04 |
| HIGH-15 | Missing Tenant Isolation on Analytics Endpoints | 8.0 | `api/analytics.py:63-318` | 2026-03-04 |
| HIGH-16 | IDOR on Organization Details | 7.5 | `api/organizations.py:147-165` | 2026-03-04 |
| HIGH-17 | Missing Membership Verify on Org Switch | 8.5 | `api/organizations.py:111-144` | 2026-03-04 |
| HIGH-18 | Arbitrary Permission Strings in Role Creation | 7.8 | `api/phase3_enterprise.py:93-96` | 2026-03-04 |
| HIGH-19 | Path/Body Param Mismatch in Account Perms | 7.5 | `api/phase3_enterprise.py:241-258` | 2026-03-04 |
| HIGH-20 | Missing Auth on Opportunities Endpoints | 8.5 | `api/opportunities.py:67-71` | 2026-03-04 |
| HIGH-21 | Backend Docker Container Runs as Root | 7.0 | `backend/Dockerfile` | 2026-03-04 |
| HIGH-22 | Frontend Docker Container Runs as Root | 7.0 | `frontend/Dockerfile` | 2026-03-04 |
| HIGH-23 | No Security Headers in Nginx | 7.5 | `frontend/nginx.conf` | 2026-03-04 |
| HIGH-24 | Valkey Transit Encryption Disabled | 7.5 | `cloudformation/main-stack.yaml:412` | 2026-03-04 |
| HIGH-25 | Overly Broad IAM Policies (Wildcard Resources) | 7.5 | `cloudformation/main-stack.yaml:520-588` | 2026-03-04 |
| HIGH-26 | Database/Cache Ports Exposed to Host | 7.0 | `docker-compose.yml:12-13,28-29` | 2026-03-04 |
| HIGH-27 | Supply Chain Risk: Non-Registry Dependency | 7.0 | `frontend/package.json:36` | 2026-03-04 |
| HIGH-28 | Missing org_id on Multiple DB Tables | 8.0 | Multiple migration files | 2026-03-04 |
| HIGH-29 | Prompt Injection in Text-to-SQL Service | 7.8 | `services/text_to_sql_service.py:632-659` | 2026-03-04 |
| HIGH-30 | SSTI Blocklist Bypass in Report Templates | 7.5 | `api/phase3_enterprise.py:42-68` | 2026-03-04 |
| HIGH-31 | Password Hash Column Indexed | 7.0 | `alembic/versions/013_*.py:39` | 2026-03-04 |
| **HIGH-32** | **Per-User Rate Limiter Ineffective (Fresh Instance Per Request)** | **7.5** | **`middleware/rate_limiting.py:469-473`** | **2026-03-05** |
| **HIGH-33** | **FIELD_ENCRYPTION_KEY Missing from Infrastructure Config** | **7.0** | **`cloudformation/ecs-services.yaml`** | **2026-03-05** |

### Medium (28)

| ID | Title | CVSS | Location | Discovered |
|:---|:------|:----:|:---------|:-----------|
| MED-1 | Account Scoping Fails Open | 6.5 | `middleware/account_scoping.py:111-122` | 2026-01-31 |
| MED-2 | Unauthenticated Prometheus Metrics | 6.5 | `main.py:278-281` | 2026-01-31 |
| MED-3 | LLM Response Preview Still Logged | 5.0 | `services/text_to_sql_service.py:661` | 2026-01-31 |
| MED-4 | Weak Password Policy | 6.5 | `api/auth.py:42` | 2026-01-31 |
| MED-6 | Missing Rate Limit on Token Validation | 5.3 | `api/auth.py` | 2026-01-31 |
| MED-7 | Default SSL Mode Unverified | 5.9 | `services/database.py:67-77` | 2026-01-31 |
| MED-8 | Production Sourcemaps Exposed | 5.3 | `frontend/vite.config.ts:24` | 2026-01-31 |
| MED-9 | Unvalidated Cron Expression | 5.3 | `services/scheduled_report_service.py:380` | 2026-01-31 |
| MED-10 | Internal Error Details in Chat Response | 6.2 | `agents/multi_agent_workflow.py` | 2026-01-31 |
| MED-11 | Stack Traces in Development Mode | 6.5 | `main.py:240-252` | 2026-02-08 |
| MED-12 | Race Condition in Org Member Management | 6.8 | `services/organization_service.py:286-367` | 2026-02-08 |
| MED-13 | TOCTOU in Org Member Removal | 6.5 | `services/organization_service.py:369-436` | 2026-02-08 |
| MED-14 | No Validation in Cost Aggregation | 6.2 | `services/multi_account_service.py:166-205` | 2026-02-08 |
| MED-15 | Account Enumeration via "Account is disabled" | 5.3 | `api/auth.py:204-209` | 2026-03-04 |
| MED-16 | Inconsistent PII Masking Across Codebase | 5.3 | Multiple files (see MED-28 for extended scope) | 2026-03-04 |
| MED-17 | Salt Reused During Password Hash Migration | 5.5 | `api/auth.py:246-250` | 2026-03-04 |
| MED-18 | JWT is_admin Not Re-Verified Per Request | 6.0 | `middleware/authentication.py:224-230` | 2026-03-04 |
| MED-19 | Unbounded Memory Growth in Rate Limiter | 5.5 | `middleware/rate_limiting.py:49-50` | 2026-03-04 |
| MED-20 | CSV Injection in Frontend Export | 5.5 | `frontend/src/utils/exportUtils.ts:90-99` | 2026-03-04 |
| MED-21 | CORS Includes localhost in Production | 5.0 | `cloudformation/ecs-services.yaml:158-162` | 2026-03-04 |
| MED-22 | 7-Day Log Retention Insufficient | 5.0 | `cloudformation/ecs-services.yaml:90,96` | 2026-03-04 |
| MED-23 | WAF Removed from Infrastructure | 6.0 | `cloudformation/main-stack.yaml:495` | 2026-03-04 |
| MED-24 | Unbounded RBAC Permission Cache | 5.5 | `services/rbac_service.py:25-78` | 2026-03-04 |
| MED-25 | Auto-Create User on First Login | 6.0 | `services/rbac_service.py:260-285` | 2026-03-04 |
| MED-26 | Singleton Service with Mutable Org ID | 6.5 | `services/opportunities_service.py:999-1012` | 2026-03-04 |
| MED-27 | Database Connection Leak on Exception | 5.5 | `services/opportunities_service.py:261-474` | 2026-03-04 |
| **MED-28** | **Unmasked Emails in New Rate-Limit Code Paths** | **5.3** | **`rate_limiting.py:461,485`; `admin/rate_limits.py:397`** | **2026-03-05** |
| **MED-29** | **Unvalidated Role String in Rate-Limit Admin API** | **5.0** | **`api/admin/rate_limits.py:33`** | **2026-03-05** |

### Low (13)

| ID | Title | CVSS | Location | Discovered |
|:---|:------|:----:|:---------|:-----------|
| LOW-1 | Weak Default Passwords in docker-compose | 4.3 | `docker-compose.yml:10,30,55,58` | 2026-01-31 |
| LOW-2 | Unbounded Audit Query Parameters | 4.3 | `api/phase3_enterprise.py:390-423` | 2026-01-31 |
| LOW-3 | Short Hash in PII Masking (32 bits) | 4.3 | `utils/pii_masking.py:74-76` | 2026-02-08 |
| LOW-4 | Organization Slug Collision Risk | 3.1 | `services/organization_service.py:68-80` | 2026-02-08 |
| LOW-5 | Default DB Credentials in Settings | 4.0 | `config/settings.py:136-139` | 2026-03-04 |
| LOW-6 | HSTS Disabled by Default | 4.0 | `config/settings.py:68-72` | 2026-03-04 |
| LOW-7 | Missing JWT Audience Claim | 3.5 | `utils/auth.py:158-173` | 2026-03-04 |
| LOW-8 | No Refresh Token Rotation | 4.3 | `api/auth.py:327-412` | 2026-03-04 |
| LOW-9 | Insecure Default Secret Accepted | 4.0 | `utils/auth.py:121-132` | 2026-03-04 |
| LOW-10 | Permission Names in Error Messages | 3.1 | `services/rbac_service.py:208-252` | 2026-03-04 |
| LOW-11 | Redundant is_admin Flag vs RBAC | 3.5 | `alembic/versions/008_*.py:39` | 2026-03-04 |
| LOW-12 | Nginx Server Version Disclosure | 3.0 | `frontend/nginx.conf` | 2026-03-04 |
| LOW-13 | Empty SECRET_KEY Default in Docker Compose | 4.3 | `docker-compose.yml:59` | 2026-03-04 |

---

## 3 — Critical Vulnerabilities (1 Open)

### CRIT-12 — SQL Injection via Date Parameters in Athena Queries

| | |
|:---|:---|
| **CVSS** | 8.6 |
| **File** | `backend/services/athena_query_service.py` |
| **Lines** | 153-337 (six methods) |
| **Since** | 2026-03-04 |

**Verified still vulnerable** — `_generate_top_services_query` at line 166 interpolates `start_date`/`end_date` into SQL via f-strings without validation:
```python
query = f"WHERE line_item_usage_start_date >= DATE '{start_date}'"
# Input: "2025-01-01'; DROP TABLE cur_table; --" → SQL injection
```

**Remediation:**
```python
DATE_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$')
def validate_date(value, field_name):
    if not value or not DATE_PATTERN.match(str(value)):
        raise ValueError(f"Invalid {field_name}")
    return str(value)
```

**Claude Code Fix Instructions:**
```
In backend/services/athena_query_service.py:
1. Add DATE_PATTERN regex and validate_date() at top of file
2. Call validate_date() at start of ALL six _generate_*_query methods
3. Also validate limit: limit = int(limit)
```

---

## 4 — High Vulnerabilities (33 Open)

### NEW FINDINGS (2026-03-05)

#### HIGH-32 — Per-User Rate Limiter Ineffective (Fresh Instance Per Request)
**File:** `backend/middleware/rate_limiting.py:469-473` | **CVSS:** 7.5 | **Discovered:** 2026-03-05

The per-user rate-limit layer in `check_athena_export_rate_limit()` constructs a **new** `RateLimiter` instance on every request:
```python
user_limiter = RateLimiter(
    requests_per_window=per_user_limit,
    window_seconds=3600,
    use_org_key=False
)
```
Because `RateLimiter._storage` is instance-scoped in-memory, each request starts with an **empty** storage dict — the per-user limit is **never enforced**. The intended fairness control is a no-op.

**Impact:** A single malicious/misbehaving user can consume the entire organization quota. The two-layer design degrades to a single org-level limit.

**Remediation:** Cache per-user limiters in a module-level dict keyed by `(user_id, endpoint)`, similar to `_athena_export_limiters`. Or better: implement Valkey-backed limiting (fixes HIGH-7, HIGH-12, MED-19 simultaneously).

---

#### HIGH-33 — FIELD_ENCRYPTION_KEY Missing from Infrastructure Configuration
**File:** `infrastructure/cloudformation/ecs-services.yaml` | **CVSS:** 7.0 | **Discovered:** 2026-03-05

The CRIT-9 fix added `FIELD_ENCRYPTION_KEY` with **production-fatal validation** at `settings.py:667-676` and `encryption.py:95-101`:
```python
if is_production:
    raise ValueError("CRITICAL: FIELD_ENCRYPTION_KEY ... must be set")
```
However, the ECS task definition (`ecs-services.yaml:119-167`) has **no entry** for `FIELD_ENCRYPTION_KEY` in either `Environment` or `Secrets` sections. Since `ENVIRONMENT=production` is set at line 151, **the backend container will crash on startup**.

**Impact:** Deployment blocker — the CRIT-9 fix cannot reach production. If the validation is removed to "fix" the crash, sensitive credentials will be stored **unencrypted** again.

**Remediation:** Add to `ecs-services.yaml` `Secrets` block:
```yaml
- Name: FIELD_ENCRYPTION_KEY
  ValueFrom: !Sub 'arn:aws:secretsmanager:${AWS::Region}:${AWS::AccountId}:secret:finops/field-encryption-key'
```
And add a corresponding `AWS::SecretsManager::Secret` with `GenerateSecretString` (length ≥48) to `main-stack.yaml`, plus the IAM `secretsmanager:GetSecretValue` grant.

---

### Authentication & Access Control

#### HIGH-1 — No Brute Force Protection on Login
**File:** `backend/api/auth.py:175-324` | **CVSS:** 7.5

No rate limiting, no account lockout, no failed attempt tracking on `/api/auth/login`.

**Remediation:** Per-IP and per-email rate limiting via Valkey. Max 5 attempts/15 min per email, 20 per IP. Progressive delays. Return 429 with Retry-After header.

#### HIGH-3 — Missing CSRF Protection
**Files:** Application-wide | **CVSS:** 7.2

No CSRF middleware exists. `allow_credentials=True` in CORS config.

**Remediation:** Add CSRF middleware for state-changing endpoints. Add `SameSite=Strict` if cookies are used.

#### HIGH-8 — Fail-Open Cache Bypass in Auth Middleware
**File:** `backend/middleware/authentication.py:209-222` | **CVSS:** 8.1 | **Status:** ⚠️ PARTIAL

**Verified still vulnerable.** Cache service correctly fails closed, but the middleware wraps it in `except Exception` that **skips the check**:
```python
except Exception as e:
    logger.debug("blacklist_check_skipped", error=str(e))  # FAILS OPEN
```

**Remediation:** Change to `raise TokenInvalidError("Unable to verify token status")`.

#### HIGH-13 — Long Password Denial of Service
**File:** `backend/api/auth.py:42` | **CVSS:** 7.5

**Verified:**
```python
password: str = Field(..., min_length=1)  # No max_length!
```
10MB password + PBKDF2 600k iterations = massive CPU consumption.

**Remediation:** `password: str = Field(..., min_length=8, max_length=128)`

#### HIGH-17 — Missing Membership Verification on Organization Switch
**File:** `backend/api/organizations.py:111-144` | **CVSS:** 8.5

**Verified:** `switch_organization()` calls `organization_service.switch_organization()` without first verifying the user is a member of the target org. Relies entirely on service-layer checks.

**Remediation:** Verify membership before calling `switch_organization()`.

#### HIGH-20 — Missing Authentication on Opportunities Endpoints
**File:** `backend/api/opportunities.py:67-71` | **CVSS:** 8.5

**Verified:** Grep for `Depends(get_request_context)` and `Depends(require_auth)` in this file returns **zero matches**. All endpoints use `get_context_from_request()` which returns `None` for unauthenticated requests. Service operates without tenant isolation when context is `None`.

**Remediation:** Replace with `Depends(get_request_context)` on all endpoints.

---

### Tenant Isolation

#### HIGH-14 — Missing Tenant Isolation in Conversation Access (Service Layer)
**File:** `backend/services/conversation_manager.py:139-424` | **CVSS:** 8.0

**Verified:** `get_conversation_history()` at line 139 accepts `thread_id` without verifying user ownership at the service layer. Any caller who invokes this method directly with a known `thread_id` can read another user's conversations.

> **Note:** As of 2026-03-05 (F-33), all chat **API endpoints** enforce ownership via the centralized `require_conversation_owner()` helper in `api/chat.py:40-80` before calling this service. This finding remains open because the service method itself still lacks defense-in-depth — any new caller (scheduled job, admin tool, future endpoint) that bypasses the API layer gets no protection.

**Remediation:** Add `user_id` parameter and `WHERE user_id = $N` to all queries in the service layer itself.

#### HIGH-15 — Missing Tenant Isolation on Analytics Endpoints
**File:** `backend/api/analytics.py:63-318` | **CVSS:** 8.0

**Verified:** AWS Cost Explorer calls at line 77 are not filtered by user's organization or account IDs. Any authenticated user sees aggregate costs from all AWS accounts.

**Remediation:** Pass `context.account_ids` to Cost Explorer `Filter` parameter.

#### HIGH-16 — IDOR on Organization Details
**File:** `backend/api/organizations.py:147-165` | **CVSS:** 7.5

**Verified:** `GET /organizations/{org_id}` calls `organization_service.get_organization(org_id)` without membership check.

**Remediation:** Verify user membership before returning details.

#### HIGH-28 — Missing org_id Tenant Isolation on Multiple DB Tables
**Files:** `alembic/versions/006_*.py`, `009_*.py` | **CVSS:** 8.0

Tables without `organization_id`: `scheduled_reports`, `report_executions`, `dashboard_templates`, `cost_allocation_rules`, `chargeback_reports`, `ticketing_integrations`, `tickets`.

**Remediation:** Create migration adding `organization_id` (FK, NOT NULL) to each table.

---

### Injection & Input Validation

#### HIGH-9 — Dynamic SQL Column Names in opportunities_service
**File:** `backend/services/opportunities_service.py:446-462` | **CVSS:** 7.8

**Verified still vulnerable:**
```python
columns = list(data.keys())
query = f"INSERT INTO opportunities ({', '.join(columns)}) VALUES ..."
```

**Remediation:** Define `ALLOWED_COLUMNS` set and validate before query construction.

#### HIGH-12 — X-Forwarded-For Spoofing Bypasses Rate Limits
**File:** `backend/middleware/rate_limiting.py:60-63` | **CVSS:** 7.5

**Verified:** Trusts first entry in `X-Forwarded-For` header directly. Attacker can set arbitrary IPs.

**Remediation:** Configure trusted proxy depth. Only trust Nth-from-last entry.

#### HIGH-18 — Arbitrary Permission Strings in Role Creation
**File:** `backend/api/phase3_enterprise.py:93-96` | **CVSS:** 7.8

**Verified:** `POST /rbac/roles` accepts `permissions: List[str]` without allowlist validation.

**Remediation:** Validate against RBAC config's known permission set.

#### HIGH-19 — Path/Body Parameter Mismatch in Account Permissions
**File:** `backend/api/phase3_enterprise.py:241-258` | **CVSS:** 7.5

**Verified:** Line 253 uses `permission.account_id` from body instead of path `account_id`.

**Remediation:** Validate `permission.account_id == account_id` or use path parameter exclusively.

#### HIGH-29 — Prompt Injection in Text-to-SQL Service
**File:** `backend/services/text_to_sql_service.py:632-659` | **CVSS:** 7.8

User queries interpolated into LLM prompt. `UNION SELECT` and SQL comments only logged as warnings (not blocked). Account filter bypassed if keyword already present in SQL.

**Remediation:** Block (not warn on) dangerous patterns. Validate account filter references only allowed accounts.

#### HIGH-30 — SSTI Blocklist Bypass in Report Templates
**File:** `backend/api/phase3_enterprise.py:42-68` | **CVSS:** 7.5

**Verified:** Blocklist approach at line 42-44 can be bypassed via Unicode homoglyphs, Jinja2 filter chains (`|attr`), or unlisted objects (`request`, `session`, `cycler`, `joiner`, `namespace`).

**Remediation:** Switch from blocklist to allowlist approach. Only permit explicitly-safe variables/filters.

---

### Race Conditions

#### HIGH-4 — Race Condition in Opportunity Cost Calculations
**File:** `backend/services/opportunities_service.py:150-200` | **CVSS:** 7.8

Non-atomic read-modify-write patterns. **Fix:** `SELECT ... FOR UPDATE` in a transaction.

#### HIGH-5 — TOCTOU in Saved Views Access Control
**File:** `backend/services/saved_views_service.py:142-170` | **CVSS:** 7.5

**Verified:** SELECT + ownership check + UPDATE in separate queries at lines 162-164. **Fix:** `SELECT ... FOR UPDATE`.

#### HIGH-6 — Mass Assignment in Opportunity Updates
**File:** `backend/api/opportunities.py:300-330` | **CVSS:** 7.5

**Verified:** Line 307 uses `body.model_dump(exclude_none=True)` — passes all non-None fields to `update_opportunity()`. **Fix:** Add allowlist of updatable fields.

#### HIGH-7 — In-Memory Rate Limiting Ineffective Across Instances
**File:** `backend/middleware/rate_limiting.py:23-51` | **CVSS:** 7.5

**Verified:** In-memory only, no Valkey backend. Each worker has isolated counters. **Fix:** Valkey-backed rate limiting with `INCR` + `EXPIRE`.

#### HIGH-10 — Race Condition in Saved Views Default Flag
**File:** `backend/services/saved_views_service.py:76-84` | **CVSS:** 7.5

**Verified:** Concurrent requests can create multiple defaults. **Fix:** Unique partial index or `FOR UPDATE`.

#### HIGH-11 — TOCTOU in Organization Member Limit
**File:** `backend/services/organization_service.py:336-352` | **CVSS:** 6.8

**Verified:** Count check at line 337 + add at line 341 not atomic. **Fix:** `INSERT ... WHERE (SELECT COUNT(*) ...) < limit`.

---

### Infrastructure

#### HIGH-21 & HIGH-22 — Docker Containers Run as Root
**Files:** `backend/Dockerfile`, `frontend/Dockerfile` | **CVSS:** 7.0

**Verified:** Neither creates a non-root user. Backend explicitly uses `/root/.local`. **Fix:**
```dockerfile
# Backend:
RUN adduser --disabled-password --gecos '' appuser
USER appuser
# Frontend:
RUN adduser -D -g '' appuser && chown -R appuser:appuser /usr/share/nginx/html
USER appuser
```

#### HIGH-23 — No Security Headers in Nginx Configuration
**File:** `frontend/nginx.conf` | **CVSS:** 7.5

**Verified:** Missing CSP, X-Frame-Options, HSTS, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, `server_tokens off`.

**Remediation:**
```nginx
server_tokens off;
add_header X-Frame-Options "DENY" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Content-Security-Policy "default-src 'self';" always;
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
```

#### HIGH-24 — Valkey Transit Encryption Disabled in Production
**File:** `infrastructure/cloudformation/main-stack.yaml:412` | **CVSS:** 7.5

**Verified:** `TransitEncryptionEnabled: false` — cache traffic (including tokens) in plaintext within VPC.

**Fix:** Set `true` and update Valkey connection to use TLS.

#### HIGH-25 — Overly Broad IAM Policies with Wildcard Resources
**File:** `infrastructure/cloudformation/main-stack.yaml:520-588` | **CVSS:** 7.5

**Verified:** `Resource: '*'` for CloudWatch Logs (line 520), Glue (570), Athena (579), Cost Explorer (588). **Fix:** Scope to specific ARNs.

#### HIGH-26 — Database/Cache Ports Exposed to Host
**File:** `docker-compose.yml:12-13,28-29` | **CVSS:** 7.0

**Verified:** PostgreSQL (`5432:5432`) and Valkey (`6379:6379`) mapped to host ports. **Fix:** Remove `ports` sections; use Docker internal network only.

#### HIGH-27 — Supply Chain Risk: Non-Registry Dependency
**File:** `frontend/package.json:36` | **CVSS:** 7.0

**Verified:**
```json
"xlsx": "https://cdn.sheetjs.com/xlsx-0.20.3/xlsx-0.20.3.tgz"
```

Bypasses npm integrity checks. **Fix:** Pin with integrity hash in `package-lock.json` or vendor the dependency.

#### HIGH-31 — Password Hash Column Indexed
**File:** `alembic/versions/013_add_password_fields_secure_hashing.py:39` | **CVSS:** 7.0

**Verified:**
```python
op.create_index('idx_users_password_hash', 'users', ['password_hash'])
```

No legitimate use case for searching by password hash. Aids attacker with DB access. **Fix:** Drop the index in a new migration.

---

## 5 — Medium Vulnerabilities (28 Open)

### NEW FINDINGS (2026-03-05)

#### MED-28 — Unmasked Emails in New Rate-Limit Code Paths
**Files:** `middleware/rate_limiting.py:461,485`; `api/admin/rate_limits.py:397` | **CVSS:** 5.3

The newly-added rate-limiting code logs raw email addresses, undermining the F-21 PII-masking fix:
```python
# rate_limiting.py:461
logger.warning(..., user_email=user_email)
# rate_limiting.py:485
logger.warning("Per-user rate limit exceeded", user_email=user_email, ...)
# admin/rate_limits.py:397
logger.info("user_rate_limit_set", user_email=user['email'], ...)
```

**Extended scope for MED-16** — additional unmasked email logging confirmed in:
- `api/analytics.py:49,67,210,254`
- `services/saved_views_service.py:124` (`created_by=context.user_email`)
- `services/organization_service.py:357,359` (`user_email=user_email`, `added_by=context.user_email`)
- `api/organizations.py:193`
- `api/athena_queries.py:68,138,178,255`
- ~~`api/chat.py`~~ — resolved as part of F-33 (user_email removed from `conversation_accessed` / `conversation_deleted` log events)

**Remediation:** Apply `mask_email()` to all `user_email` / `created_by` / `added_by` fields in logger calls. Add a regression test that greps for `user_email=.*\.email` / `user_email=context\.user_email` patterns not wrapped in `mask_email()`.

#### MED-29 — Unvalidated Role String in Rate-Limit Admin API
**File:** `api/admin/rate_limits.py:33` | **CVSS:** 5.0

```python
class RateLimitRoleConfig(BaseModel):
    role: str = Field(..., description="User role: owner, admin, or member")
```
No allowlist validation — accepts any string. An admin could set limits for a nonexistent role (silent failure / dead config), or an attacker with compromised admin creds could probe for role names.

**Remediation:** Use `Literal['owner', 'admin', 'member']` or add a field validator.

---

### Middleware & Configuration

| ID | Title | File | Remediation |
|:---|:------|:-----|:------------|
| MED-1 | Account scoping fails open | `middleware/account_scoping.py:111-122` | Change to fail-closed behavior |
| MED-7 | Default SSL mode unverified | `services/database.py:67-77` | Default to `verify-full` |
| MED-8 | Production sourcemaps exposed | `frontend/vite.config.ts:24` | Set `sourcemap: false` or `'hidden'` |
| MED-11 | Stack traces in dev mode | `main.py:240-252` | Ensure `ENVIRONMENT=production` in all deployed envs |
| MED-21 | CORS includes localhost in prod | `ecs-services.yaml:158-162` | Remove localhost origins from production config |
| MED-22 | 7-day log retention | `ecs-services.yaml:90,96` | Set to 90+ days for SOC 2/HIPAA compliance |
| MED-23 | WAF removed | `main-stack.yaml:495` | Reinstate AWS WAF for app-layer protection |

### Authentication & Authorization

| ID | Title | File | Remediation |
|:---|:------|:-----|:------------|
| MED-2 | Unauthenticated `/metrics` | `main.py:278-281` | Add auth or restrict to internal network |
| MED-4 | Weak password policy | `api/auth.py:42` | Add `min_length=8`, complexity regex, `max_length=128` |
| MED-6 | No rate limit on `/validate` | `api/auth.py` | Add rate limiting to prevent token enumeration |
| MED-15 | Account enumeration via "Account is disabled" | `api/auth.py:204-209` | Return identical "Invalid email or password" for inactive accounts |
| MED-17 | Salt reused in hash migration | `api/auth.py:246-250` | Generate new salt via `generate_salt()` during migration |
| MED-18 | JWT `is_admin` not re-verified | `middleware/authentication.py:224-230` | Check admin status on sensitive operations |
| MED-25 | Auto-create user on first login | `services/rbac_service.py:260-285` | Require explicit provisioning in multi-tenant SaaS |

### Data & Injection

| ID | Title | File | Remediation |
|:---|:------|:-----|:------------|
| MED-3 | LLM response preview logged (partial fix) | `services/text_to_sql_service.py:661` | Remove preview entirely or add PII scrubbing |
| MED-9 | Unvalidated cron expression | `services/scheduled_report_service.py:380` | Validate against safe patterns |
| MED-10 | Internal error details in chat | `agents/multi_agent_workflow.py` | Sanitize agent errors before returning to client |
| MED-14 | No validation in cost aggregation | `services/multi_account_service.py:166-205` | Validate account IDs and date ranges |
| MED-16 | Inconsistent PII masking | Multiple files | Apply `mask_email()` consistently (see MED-28 for full list) |
| MED-20 | CSV injection in export | `frontend/src/utils/exportUtils.ts:90-99` | Prefix dangerous values (`=`,`+`,`-`,`@`) with `'` |

### Race Conditions & Resource Management

| ID | Title | File | Remediation |
|:---|:------|:-----|:------------|
| MED-12 | Race in org member management | `services/organization_service.py:286-367` | Use `FOR UPDATE` or serializable transactions |
| MED-13 | TOCTOU in org member removal | `services/organization_service.py:369-436` | Use atomic operations |
| MED-19 | Unbounded memory in rate limiter | `middleware/rate_limiting.py:49-50` | Add periodic cleanup or use Valkey with TTL |
| MED-24 | Unbounded RBAC permission cache | `services/rbac_service.py:25-78` | Add TTL-based eviction and max entries |
| MED-26 | Singleton service with mutable org ID | `services/opportunities_service.py:999-1012` | Use request-scoped instances |
| MED-27 | DB connection leak on exception | `services/opportunities_service.py:261-474` | Use `try/finally` or context managers |

---

## 6 — Low Vulnerabilities (13 Open)

| ID | Title | File | Remediation |
|:---|:------|:-----|:------------|
| LOW-1 | Weak default passwords in docker-compose | `docker-compose.yml:10,30,55,58` | Use strong random defaults or require env vars |
| LOW-2 | Unbounded audit query params | `api/phase3_enterprise.py:390-423` | Add `max_hours=720`, `max_limit=10000` |
| LOW-3 | Short hash in PII masking (32 bits) | `utils/pii_masking.py:74-76` | Use 16+ hex chars (64+ bits entropy) |
| LOW-4 | Organization slug collision | `services/organization_service.py:68-80` | Retry with random suffix on collision |
| LOW-5 | Default DB credentials in settings | `config/settings.py:136-139` | Add production validation for DB password |
| LOW-6 | HSTS disabled by default | `config/settings.py:68-72` | Change default to `True` |
| LOW-7 | Missing JWT audience claim | `utils/auth.py:158-173` | Add `aud` claim and validate on decode |
| LOW-8 | No refresh token rotation | `api/auth.py:327-412` | Issue new refresh token on each refresh |
| LOW-9 | Insecure default key accepted | `utils/auth.py:121-132` | Raise exception instead of warning |
| LOW-10 | Permission names in error msgs | `services/rbac_service.py:208-252` | Return generic "Permission denied" |
| LOW-11 | Redundant `is_admin` flag vs RBAC | `alembic/versions/008_*.py:39` | Deprecate in favor of RBAC roles |
| LOW-12 | Nginx server version disclosure | `frontend/nginx.conf` | Add `server_tokens off;` |
| LOW-13 | Empty SECRET_KEY default | `docker-compose.yml:59` | Require SECRET_KEY or fail startup |

---

## 7 — SaaS Multi-Tenant Security Checklist

This is a SaaS platform serving multiple client organizations. All configurations must be tenant-aware.

| Area | Current State | Required State | Priority |
|:-----|:-------------|:---------------|:--------:|
| Database Row-Level Security | Partial — many tables lack `organization_id` | ALL tables must have `organization_id` NOT NULL with FK | P0 |
| API Route Scoping | Inconsistent — some endpoints unscoped | ALL data endpoints must filter by `context.organization_id` | P0 |
| AWS Account Isolation | Partial — analytics endpoints unscoped | Cost Explorer queries must filter by org's allowed accounts | P0 |
| Conversation Isolation | API layer enforced via `require_conversation_owner()` (F-33); service layer still open (HIGH-14) | Scoped to user + organization at service layer | P1 |
| Rate Limits | Global in-memory; per-user layer broken (HIGH-32) | Per-organization configurable limits in Valkey; functional per-user layer | P1 |
| Secret Key | Single key for all tenants | Consider per-tenant JWT signing keys | P2 |
| RBAC Roles | Global | Per-organization custom roles (add `org_id` to roles table) | P2 |
| Reports | Auth + org scope contract in place (F-35); real impl must filter by `organization_id` + `account_ids` | Enforced at service layer once implemented | P1 |
| Audit Logs | `organization_id` nullable | Must be NOT NULL for all entries | P1 |
| Cache Keys | Global namespace | Prefix with `org:{org_id}:` for tenant isolation | P2 |
| Field Encryption | Code ready; **key not provisioned (HIGH-33)** | `FIELD_ENCRYPTION_KEY` in Secrets Manager + ECS `Secrets` | **P0** |

---

## 8 — Prioritized Remediation Roadmap

### Phase 1 — Immediate (Do Now)

| # | Action | Issues Resolved |
|:--|:-------|:---------------|
| 1 | **Provision FIELD_ENCRYPTION_KEY in Secrets Manager** (deployment blocker) | **HIGH-33** |
| 2 | Fix SQL injection in Athena date params | CRIT-12 |
| 3 | Add auth to unprotected endpoints | HIGH-20 |
| 4 | **Fix per-user rate limiter (cache instances)** | **HIGH-32** |

### Phase 2 — Within 2 Weeks

| # | Action | Issues Resolved |
|:--|:-------|:---------------|
| 1 | Brute force protection on login | HIGH-1 |
| 2 | Tenant isolation across all services | HIGH-14, HIGH-15, HIGH-16, HIGH-17, HIGH-28 |
| 3 | Fix dynamic SQL (column name allowlist) | HIGH-9 |
| 4 | Container security (non-root users) | HIGH-21, HIGH-22 |
| 5 | Nginx hardening | HIGH-23, LOW-12 |
| 6 | Infrastructure security | HIGH-24, HIGH-25, HIGH-26 |
| 7 | Fail-closed on blacklist check error | HIGH-8 |

### Phase 3 — Within 1 Month

| # | Action | Issues Resolved |
|:--|:-------|:---------------|
| 1 | PII masking consistency (all log statements) | MED-16, MED-28 |
| 2 | Distributed rate limiting (Valkey backend) | HIGH-7, HIGH-12, MED-19 |
| 3 | Password policy strengthening | MED-4, HIGH-13 |
| 4 | Fix race conditions | HIGH-4, HIGH-5, HIGH-10, HIGH-11 |
| 5 | Infrastructure compliance | MED-22, MED-23 |
| 6 | Input validation on admin APIs | MED-29, HIGH-18 |

### Phase 4 — Ongoing

| # | Action | Issues Resolved |
|:--|:-------|:---------------|
| 1 | Address all LOW findings | LOW-1 through LOW-13 |
| 2 | Implement refresh token rotation | LOW-8 |
| 3 | Add JWT audience claims | LOW-7 |
| 4 | Review and update RBAC config | LOW-11 |

---

## Appendix A — Fixed Issues

All historically fixed vulnerabilities are tracked in [`FIXED_SECURITY_ISSUES.md`](./FIXED_SECURITY_ISSUES.md).

---

*Report generated: 2026-03-05 | Next audit recommended: 2026-04-05*
*Total tracked: 75 open + 35 fixed = 110 vulnerabilities across 4 audit cycles*
