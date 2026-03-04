# Security Audit Report

## FinOps AI Cost Intelligence Platform

| | |
|---|---|
| **Report Date** | 2026-03-04 |
| **Previous Audits** | 2026-02-08, 2026-01-31 |
| **Methodology** | Penetration test, static code analysis, dependency scanning, infrastructure review |
| **Scope** | Backend (Python/FastAPI), Frontend (React/TypeScript), Infrastructure (CloudFormation, Docker, Nginx), Database Models & Migrations, Dependencies |

---

## Table of Contents

| # | Section | Description |
|---|---------|-------------|
| 1 | [Executive Summary](#1--executive-summary) | Risk overview, progress, and systemic findings |
| 2 | [Open Vulnerability Matrix](#2--open-vulnerability-matrix) | All open issues in one sortable table |
| 3 | [Critical Vulnerabilities](#3--critical-vulnerabilities-5-open) | Detailed analysis & remediation for CRITICAL findings |
| 4 | [High Vulnerabilities](#4--high-vulnerabilities-31-open) | Detailed analysis & remediation for HIGH findings |
| 5 | [Medium Vulnerabilities](#5--medium-vulnerabilities-27-open) | Detailed analysis & remediation for MEDIUM findings |
| 6 | [Low Vulnerabilities](#6--low-vulnerabilities-13-open) | Concise table of LOW findings with fixes |
| 7 | [SaaS Multi-Tenant Checklist](#7--saas-multi-tenant-security-checklist) | Per-client configurability requirements |
| 8 | [Remediation Roadmap](#8--prioritized-remediation-roadmap) | Phased action plan |
| A | [Appendix: Fixed Issues](#appendix-a--fixed-issues-historical-record) | Verified fixes retained for audit trail |

---

## 1 — Executive Summary

This is the third comprehensive security audit. Since the 2026-02-08 audit, **8 additional issues have been fixed**. However, deep-dive analysis covering infrastructure configurations, database schema, frontend exports, and all API routes has uncovered **53 new vulnerabilities** not previously identified.

### Risk Dashboard

```
 CRITICAL  ███  3 open     (was 10)    ← IMMEDIATE ACTION REQUIRED
 HIGH      ████████████████████████████████  31 open    (was 10)
 MEDIUM    ███████████████████████████  27 open    (was 14)
 LOW       █████████████  13 open    (was 4)
 ──────────────────────────────────────────
 TOTAL OPEN: 74          FIXED: 32 (historical)
```

| Severity | Previously Open | Fixed This Cycle | New Findings | **Total Open** |
|:---------|:---------------:|:----------------:|:------------:|:--------------:|
| CRITICAL | 3 | 8 | +8 | **3** |
| HIGH | 10 | 1 | +22 | **31** |
| MEDIUM | 14 | 1 | +14 | **27** |
| LOW | 4 | 0 | +9 | **13** |
| **Total** | **31** | **10** | **+53** | **74** |

### Top 3 Systemic Risks

> **1. ~~Infrastructure Secrets in Git~~** *(FIXED)*
> ~~Production SECRET_KEY~~ (FIXED — moved to Secrets Manager), ~~AWS account IDs, RDS/Redis endpoints, and IAM role ARNs~~ (FIXED — replaced with placeholders in all config files, scripts, and documentation).

> **2. Inconsistent Authentication Enforcement**
> Several critical API endpoints (chat streaming, reports, opportunities) lack mandatory authentication, allowing anonymous or cross-tenant access to cost data.

> **3. Missing Multi-Tenant Isolation**
> Many database tables and API queries lack `organization_id` scoping, enabling cross-tenant data leakage across client organizations in this SaaS platform.

### What Was Fixed Since Last Audit

| ID | Issue | Severity | Evidence |
|:---|:------|:---------|:---------|
| CRIT-2 | Timing attack in password verification | CRITICAL | `secrets.compare_digest()` at `auth.py:164` |
| CRIT-3 | SQL Injection in Audit Log Service | CRITICAL | `make_interval(hours => $N)` parameterized queries + `int(hours)` validation; 15 tests |
| CRIT-4 | Missing User ORM Model | CRITICAL | `User` class with 15 columns matching migrations 008+011+013 in `database_models.py`; 50 tests |
| CRIT-5 | Hardcoded SECRET_KEY in task-def.json | CRITICAL | Replaced with Secrets Manager reference; deterministic pattern blocklist in `settings.py`; 17 tests |
| CRIT-6 | AWS Infrastructure Secrets Exposed in Repository | CRITICAL | All config files, scripts, docs converted to placeholders (`${AWS_ACCOUNT_ID}`, `${RDS_ENDPOINT}`, etc.); 27 tests in `test_no_infrastructure_secrets.py` |
| CRIT-7 | Predictable SECRET_KEY in CloudFormation | CRITICAL | Moved to ECS `Secrets` section with Secrets Manager ARN; `GenerateSecretString` in `main-stack.yaml` |
| CRIT-8 | Database Password in Plaintext ECS Env Vars | CRITICAL | Moved to Secrets Manager; `ecs-services.yaml` Secrets block; `DatabasePasswordSecret` in `main-stack.yaml`; IAM policy updated |
| CRIT-9 | Unencrypted Sensitive Credentials in Database | CRITICAL | Fernet field encryption in `backend/utils/encryption.py`; encrypted columns in migration 016; `multi_account_service.py` encrypt-on-write/decrypt-on-read |
| HIGH-2 | Insufficient PBKDF2 iterations | HIGH | 600,000 iterations (OWASP 2023+) at `auth.py:110` |
| MED-12 | Token blacklist fails open | MEDIUM | `cache_service.py:211-249` — fail-closed (`return True`) |

---

## 2 — Open Vulnerability Matrix

All **74 open issues** sorted by severity and CVSS score. Use this table as a tracking dashboard.

### Critical (3)

| ID | Title | CVSS | Location | Discovered |
|:---|:------|:----:|:---------|:-----------|
| CRIT-10 | Unauthenticated Streaming with Cross-Tenant Access | 9.8 | `api/chat.py:351-396` | 2026-03-04 |
| CRIT-11 | Unauthenticated Reports Endpoints | 8.5 | `api/reports.py:8-15` | 2026-03-04 |
| CRIT-12 | SQL Injection via Date Params in Athena Queries | 8.6 | `services/athena_query_service.py:158-337` | 2026-03-04 |

### High (31)

| ID | Title | CVSS | Location | Discovered |
|:---|:------|:----:|:---------|:-----------|
| HIGH-1 | No Brute Force Protection on Login | 7.5 | `api/auth.py:175-324` | 2026-02-08 |
| HIGH-3 | Missing CSRF Protection | 7.2 | Application-wide | 2026-02-08 |
| HIGH-4 | Race Condition in Opportunity Cost Calculations | 7.8 | `services/opportunities_service.py:155-194` | 2026-02-08 |
| HIGH-5 | TOCTOU in Saved Views Access Control | 7.5 | `services/saved_views_service.py:131-157` | 2026-02-08 |
| HIGH-6 | Mass Assignment in Opportunity Updates | 7.5 | `api/opportunities.py:313-376` | 2026-02-08 |
| HIGH-7 | In-Memory Rate Limiting Ineffective | 7.5 | `middleware/rate_limiting.py:23-51` | 2026-02-08 |
| HIGH-8 | Fail-Open Cache Bypass in Auth Middleware | 8.1 | `middleware/authentication.py:209-222` | 2026-02-08 |
| HIGH-9 | Dynamic SQL Column Names in opportunities_service | 7.8 | `services/opportunities_service.py:446-462` | 2026-02-08 |
| HIGH-10 | Race Condition in Saved Views Default Flag | 7.5 | `services/saved_views_service.py:76-84` | 2026-02-08 |
| HIGH-11 | TOCTOU in Organization Member Limit | 6.8 | `services/organization_service.py:336-352` | 2026-02-08 |
| HIGH-12 | X-Forwarded-For Spoofing Bypasses Rate Limits | 7.5 | `middleware/rate_limiting.py:59-63` | 2026-03-04 |
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
| HIGH-25 | Overly Broad IAM Policies (Wildcard Resources) | 7.5 | `cloudformation/main-stack.yaml:498-589` | 2026-03-04 |
| HIGH-26 | Database/Cache Ports Exposed to Host | 7.0 | `docker-compose.yml:12-13,28-29` | 2026-03-04 |
| HIGH-27 | Supply Chain Risk: Non-Registry Dependency | 7.0 | `frontend/package.json:36` | 2026-03-04 |
| HIGH-28 | Missing org_id on Multiple DB Tables | 8.0 | Multiple migration files | 2026-03-04 |
| HIGH-29 | Prompt Injection in Text-to-SQL Service | 7.8 | `services/text_to_sql_service.py:632-659` | 2026-03-04 |
| HIGH-30 | SSTI Blocklist Bypass in Report Templates | 7.5 | `api/phase3_enterprise.py:42-68` | 2026-03-04 |
| HIGH-31 | Password Hash Column Indexed | 7.0 | `alembic/versions/013_*.py:39` | 2026-03-04 |

### Medium (27)

| ID | Title | CVSS | Location | Discovered |
|:---|:------|:----:|:---------|:-----------|
| MED-1 | Account Scoping Fails Open | 6.5 | `middleware/account_scoping.py:111-122` | 2026-01-31 |
| MED-2 | Unauthenticated Prometheus Metrics | 6.5 | `main.py:278-281` | 2026-01-31 |
| MED-3 | LLM Raw Response Logged | 5.3 | `services/text_to_sql_service.py:659` | 2026-01-31 |
| MED-4 | Weak Password Policy | 6.5 | `api/auth.py:42` | 2026-01-31 |
| MED-5 | SSE Stream Data Injection | 6.1 | `api/chat.py:387` | 2026-01-31 |
| MED-6 | Missing Rate Limit on Token Validation | 5.3 | `api/auth.py` | 2026-01-31 |
| MED-7 | Default SSL Mode Unverified | 5.9 | `services/database.py:67-77` | 2026-01-31 |
| MED-8 | Production Sourcemaps Exposed | 5.3 | `frontend/vite.config.ts:24` | 2026-01-31 |
| MED-9 | Unvalidated Cron Expression | 5.3 | `services/scheduled_report_service.py:380` | 2026-01-31 |
| MED-10 | Internal Error Details in Chat Response | 6.2 | `agents/multi_agent_workflow.py` | 2026-01-31 |
| MED-11 | Stack Traces in Development Mode | 6.5 | `main.py:240-252` | 2026-02-08 |
| MED-12 | Race Condition in Org Member Management | 6.8 | `services/organization_service.py:286-367` | 2026-02-08 |
| MED-13 | TOCTOU in Org Member Removal | 6.5 | `services/organization_service.py:369-436` | 2026-02-08 |
| MED-14 | No Validation in Cost Aggregation | 6.2 | `services/multi_account_service.py:166-205` | 2026-02-08 |
| MED-15 | Account Enumeration via Login Errors | 5.3 | `api/auth.py:197-209` | 2026-03-04 |
| MED-16 | Inconsistent PII Masking Across Codebase | 5.3 | Multiple files | 2026-03-04 |
| MED-17 | Salt Reused During Password Hash Migration | 5.5 | `api/auth.py:246-249` | 2026-03-04 |
| MED-18 | JWT is_admin Not Re-Verified Per Request | 6.0 | `middleware/authentication.py:224-230` | 2026-03-04 |
| MED-19 | Unbounded Memory Growth in Rate Limiter | 5.5 | `middleware/rate_limiting.py:49-50` | 2026-03-04 |
| MED-20 | CSV Injection in Frontend Export | 5.5 | `frontend/src/utils/exportUtils.ts:90-99` | 2026-03-04 |
| MED-21 | CORS Includes localhost in Production | 5.0 | `cloudformation/ecs-services.yaml:164-168` | 2026-03-04 |
| MED-22 | 7-Day Log Retention Insufficient | 5.0 | `cloudformation/ecs-services.yaml:90,96` | 2026-03-04 |
| MED-23 | WAF Removed from Infrastructure | 6.0 | `cloudformation/main-stack.yaml:477` | 2026-03-04 |
| MED-24 | Unbounded RBAC Permission Cache | 5.5 | `services/rbac_service.py:25-78` | 2026-03-04 |
| MED-25 | Auto-Create User on First Login | 6.0 | `services/rbac_service.py:260-285` | 2026-03-04 |
| MED-26 | Singleton Service with Mutable Org ID | 6.5 | `services/opportunities_service.py:999-1012` | 2026-03-04 |
| MED-27 | Database Connection Leak on Exception | 5.5 | `services/opportunities_service.py:261-474` | 2026-03-04 |

### Low (13)

| ID | Title | CVSS | Location | Discovered |
|:---|:------|:----:|:---------|:-----------|
| LOW-1 | Weak Default Passwords in docker-compose | 4.3 | `docker-compose.yml:10,30,55,58` | 2026-01-31 |
| LOW-2 | Unbounded Audit Query Parameters | 4.3 | `api/phase3_enterprise.py:390-423` | 2026-01-31 |
| LOW-3 | Short Hash in PII Masking (32 bits) | 4.3 | `utils/pii_masking.py:74-76` | 2026-02-08 |
| LOW-4 | Organization Slug Collision Risk | 3.1 | `services/organization_service.py:68-80` | 2026-02-08 |
| LOW-5 | Default DB Credentials in Settings | 4.0 | `config/settings.py:128-132` | 2026-03-04 |
| LOW-6 | HSTS Disabled by Default | 4.0 | `config/settings.py:67-69` | 2026-03-04 |
| LOW-7 | Missing JWT Audience Claim | 3.5 | `utils/auth.py:158-173` | 2026-03-04 |
| LOW-8 | No Refresh Token Rotation | 4.3 | `api/auth.py:327-412` | 2026-03-04 |
| LOW-9 | Insecure Default Secret Accepted | 4.0 | `utils/auth.py:121-132` | 2026-03-04 |
| LOW-10 | Permission Names in Error Messages | 3.1 | `services/rbac_service.py:208-252` | 2026-03-04 |
| LOW-11 | Redundant is_admin Flag vs RBAC | 3.5 | `alembic/versions/008_*.py:39` | 2026-03-04 |
| LOW-12 | Nginx Server Version Disclosure | 3.0 | `frontend/nginx.conf` | 2026-03-04 |
| LOW-13 | Empty SECRET_KEY Default in Docker Compose | 4.3 | `docker-compose.yml:59` | 2026-03-04 |

---

## 3 — Critical Vulnerabilities (3 Open)

### ~~CRIT-8 — Database Password in Plaintext ECS Environment Variables~~ — FIXED

Moved `POSTGRES_PASSWORD` from plaintext `Environment` to ECS `Secrets` section backed by AWS Secrets Manager. `DATABASE_URL` removed (app constructs it from components). `DatabasePasswordSecret` resource and IAM policy added to `main-stack.yaml`. See Appendix A (F-31).

---

### ~~CRIT-9 — Unencrypted Sensitive Credentials in Database~~ — FIXED

Implemented Fernet-based field encryption (`backend/utils/encryption.py`) with PBKDF2-HMAC-SHA256 key derivation (600k iterations). Migration 016 adds `*_encrypted` columns. `multi_account_service.py` encrypts on write, decrypts on read, with backward compatibility for pre-migration rows. See Appendix A (F-32).

---

### CRIT-10 — Unauthenticated Streaming Endpoint with Cross-Tenant Access

| | |
|:---|:---|
| **CVSS** | 9.8 |
| **File** | `backend/api/chat.py` |
| **Lines** | 351-396 |
| **Since** | 2026-03-04 |

**Vulnerability:** `POST /stream` has **zero authentication** and **zero tenant isolation**:
```python
# No Depends(get_request_context) — no auth check
# No organization_id or account_ids passed to execute_multi_agent_query()
result = await execute_multi_agent_query(
    user_query=request.query, thread_id=thread_id,
    # Missing: organization_id, account_ids
)
```

**Impact:** Any unauthenticated user can query cost data from ALL organizations' AWS accounts.

**Remediation:** Add `context: RequestContext = Depends(get_request_context)` and pass scoping params.

---

### CRIT-11 — Unauthenticated Reports Endpoints

| | |
|:---|:---|
| **CVSS** | 8.5 |
| **File** | `backend/api/reports.py` |
| **Lines** | 8-15 |
| **Since** | 2026-03-04 |

Both `GET /` and `POST /generate` have zero auth, zero tenant isolation, zero rate limiting. Currently mocks, but will be exploitable once implemented.

**Remediation:** Add `Depends(get_request_context)` to both endpoints.

---

### CRIT-12 — SQL Injection via Date Parameters in Athena Queries

| | |
|:---|:---|
| **CVSS** | 8.6 |
| **File** | `backend/services/athena_query_service.py` |
| **Lines** | 158-337 (six methods) |
| **Since** | 2026-03-04 |

All six query generation methods interpolate `start_date`/`end_date` into SQL via f-strings without validation:
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

## 4 — High Vulnerabilities (31 Open)

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

Cache service correctly fails closed, but the middleware wraps it in `except Exception` that **skips the check**:
```python
except Exception as e:
    logger.debug("blacklist_check_skipped", error=str(e))  # FAILS OPEN
```

**Remediation:** Change to `raise TokenInvalidError("Unable to verify token status")`.

#### HIGH-13 — Long Password Denial of Service
**File:** `backend/api/auth.py:42` | **CVSS:** 7.5

```python
password: str = Field(..., min_length=1)  # No max_length!
```
10MB password + PBKDF2 600k iterations = massive CPU consumption.

**Remediation:** `password: str = Field(..., min_length=8, max_length=128)`

#### HIGH-17 — Missing Membership Verification on Organization Switch
**File:** `backend/api/organizations.py:111-144` | **CVSS:** 8.5

`PUT /organizations/current/{org_id}` may allow switching to any organization without membership check.

**Remediation:** Verify membership before calling `switch_organization()`.

#### HIGH-20 — Missing Authentication on Opportunities Endpoints
**File:** `backend/api/opportunities.py:67-71` | **CVSS:** 8.5

All endpoints use `get_context_from_request()` which returns `None` for unauthenticated requests. Service operates without tenant isolation when context is `None`.

**Remediation:** Replace with `Depends(get_request_context)` on all endpoints.

---

### Tenant Isolation

#### HIGH-14 — Missing Tenant Isolation in Conversation Access
**File:** `backend/services/conversation_manager.py:139-424` | **CVSS:** 8.0

All read methods accept `thread_id` without verifying user ownership. Any user who knows a `thread_id` can read another user's conversations.

**Remediation:** Add `user_id` parameter and `WHERE user_id = $N` to all queries.

#### HIGH-15 — Missing Tenant Isolation on Analytics Endpoints
**File:** `backend/api/analytics.py:63-318` | **CVSS:** 8.0

AWS Cost Explorer calls are not filtered by user's organization or account IDs. Any authenticated user sees aggregate costs from all AWS accounts.

**Remediation:** Pass `context.account_ids` to Cost Explorer filter.

#### HIGH-16 — IDOR on Organization Details
**File:** `backend/api/organizations.py:147-165` | **CVSS:** 7.5

`GET /organizations/{org_id}` returns any organization's details without membership check.

**Remediation:** Verify user membership before returning details.

#### HIGH-28 — Missing org_id Tenant Isolation on Multiple DB Tables
**Files:** `alembic/versions/006_*.py`, `009_*.py` | **CVSS:** 8.0

Tables without `organization_id`: `scheduled_reports`, `report_executions`, `dashboard_templates`, `cost_allocation_rules`, `chargeback_reports`, `ticketing_integrations`, `tickets`.

**Remediation:** Create migration adding `organization_id` (FK, NOT NULL) to each table.

---

### Injection & Input Validation

#### HIGH-9 — Dynamic SQL Column Names in opportunities_service
**File:** `backend/services/opportunities_service.py:446-462` | **CVSS:** 7.8

```python
columns = list(data.keys())
query = f"INSERT INTO opportunities ({', '.join(columns)}) VALUES ..."
```

**Remediation:** Define `ALLOWED_COLUMNS` set and validate before query construction.

#### HIGH-12 — X-Forwarded-For Spoofing Bypasses Rate Limits
**File:** `backend/middleware/rate_limiting.py:59-63` | **CVSS:** 7.5

Trusts first entry in `X-Forwarded-For` header directly. Attacker can set arbitrary IPs.

**Remediation:** Configure trusted proxy depth. Only trust Nth-from-last entry.

#### HIGH-18 — Arbitrary Permission Strings in Role Creation
**File:** `backend/api/phase3_enterprise.py:93-96` | **CVSS:** 7.8

`POST /rbac/roles` accepts `permissions: List[str]` without allowlist validation, enabling privilege escalation.

**Remediation:** Validate against RBAC config's known permission set.

#### HIGH-19 — Path/Body Parameter Mismatch in Account Permissions
**File:** `backend/api/phase3_enterprise.py:241-258` | **CVSS:** 7.5

Uses `permission.account_id` from body instead of path `account_id`. Attacker can grant permissions on wrong account.

**Remediation:** Validate `permission.account_id == account_id` or use path parameter exclusively.

#### HIGH-29 — Prompt Injection in Text-to-SQL Service
**File:** `backend/services/text_to_sql_service.py:632-659` | **CVSS:** 7.8

User queries interpolated into LLM prompt. `UNION SELECT` and SQL comments only logged as warnings (not blocked). Account filter bypassed if keyword already present in SQL.

**Remediation:** Block (not warn on) dangerous patterns. Validate account filter references only allowed accounts.

#### HIGH-30 — SSTI Blocklist Bypass in Report Templates
**File:** `backend/api/phase3_enterprise.py:42-68` | **CVSS:** 7.5

Blocklist can be bypassed via Unicode homoglyphs, Jinja2 filter chains, or unlisted objects (`request`, `session`, `cycler`).

**Remediation:** Switch from blocklist to allowlist approach.

---

### Race Conditions

#### HIGH-4 — Race Condition in Opportunity Cost Calculations
**File:** `backend/services/opportunities_service.py:155-194` | **CVSS:** 7.8

Non-atomic read-modify-write patterns. **Fix:** `SELECT ... FOR UPDATE` in a transaction.

#### HIGH-5 — TOCTOU in Saved Views Access Control
**File:** `backend/services/saved_views_service.py:131-157` | **CVSS:** 7.5

SELECT + ownership check + UPDATE in separate queries. **Fix:** `SELECT ... FOR UPDATE`.

#### HIGH-6 — Mass Assignment in Opportunity Updates
**File:** `backend/api/opportunities.py:313-376` | **CVSS:** 7.5

Update endpoint accepts arbitrary fields. **Fix:** Add allowlist of updatable fields.

#### HIGH-7 — In-Memory Rate Limiting Ineffective Across Instances
**File:** `backend/middleware/rate_limiting.py:23-51` | **CVSS:** 7.5

In-memory only, no Valkey backend. Each worker has isolated counters. **Fix:** Valkey-backed rate limiting with `INCR` + `EXPIRE`.

#### HIGH-10 — Race Condition in Saved Views Default Flag
**File:** `backend/services/saved_views_service.py:76-84` | **CVSS:** 7.5

Concurrent requests can create multiple defaults. **Fix:** Unique partial index or `FOR UPDATE`.

#### HIGH-11 — TOCTOU in Organization Member Limit
**File:** `backend/services/organization_service.py:336-352` | **CVSS:** 6.8

Count check + add not atomic. **Fix:** `INSERT ... WHERE (SELECT COUNT(*) ...) < limit`.

---

### Infrastructure

#### HIGH-21 & HIGH-22 — Docker Containers Run as Root
**Files:** `backend/Dockerfile`, `frontend/Dockerfile` | **CVSS:** 7.0

Neither creates a non-root user. **Fix:**
```dockerfile
# Backend:
RUN adduser --disabled-password --gecos '' appuser && USER appuser
# Frontend:
RUN adduser -D -g '' appuser && chown -R appuser:appuser /usr/share/nginx/html && USER appuser
```

#### HIGH-23 — No Security Headers in Nginx Configuration
**File:** `frontend/nginx.conf` | **CVSS:** 7.5

Missing: CSP, X-Frame-Options, HSTS, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, `server_tokens off`.

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

`TransitEncryptionEnabled: false` — cache traffic (including tokens) in plaintext within VPC.

**Fix:** Set `true` and update Valkey connection to use TLS.

#### HIGH-25 — Overly Broad IAM Policies with Wildcard Resources
**File:** `infrastructure/cloudformation/main-stack.yaml:498-589` | **CVSS:** 7.5

Multiple `Resource: '*'` for CloudWatch, Glue, Athena, Cost Explorer, SSM. **Fix:** Scope to specific ARNs.

#### HIGH-26 — Database/Cache Ports Exposed to Host
**File:** `docker-compose.yml:12-13,28-29` | **CVSS:** 7.0

PostgreSQL and Valkey mapped to host ports. **Fix:** Remove `ports` sections; use Docker internal network only.

#### HIGH-27 — Supply Chain Risk: Non-Registry Dependency
**File:** `frontend/package.json:36` | **CVSS:** 7.0

```json
"xlsx": "https://cdn.sheetjs.com/xlsx-0.20.3/xlsx-0.20.3.tgz"
```

Bypasses npm integrity checks. **Fix:** Pin with integrity hash or vendor the dependency.

#### HIGH-31 — Password Hash Column Indexed
**File:** `alembic/versions/013_add_password_fields_secure_hashing.py:39` | **CVSS:** 7.0

```python
op.create_index('idx_users_password_hash', 'users', ['password_hash'])
```

No legitimate use case for searching by password hash. Aids attacker with DB access. **Fix:** Drop the index in a new migration.

---

## 5 — Medium Vulnerabilities (27 Open)

### Middleware & Configuration

| ID | Title | File | Remediation |
|:---|:------|:-----|:------------|
| MED-1 | Account scoping fails open | `middleware/account_scoping.py:111-122` | Change to fail-closed behavior |
| MED-7 | Default SSL mode unverified | `services/database.py:67-77` | Default to `verify-full` |
| MED-8 | Production sourcemaps exposed | `frontend/vite.config.ts:24` | Set `sourcemap: false` or `'hidden'` |
| MED-11 | Stack traces in dev mode | `main.py:240-252` | Ensure `ENVIRONMENT=production` in all deployed envs |
| MED-21 | CORS includes localhost in prod | `ecs-services.yaml:164-168` | Remove localhost origins from production config |
| MED-22 | 7-day log retention | `ecs-services.yaml:90,96` | Set to 90+ days for SOC 2/HIPAA compliance |
| MED-23 | WAF removed | `main-stack.yaml:477` | Reinstate AWS WAF for app-layer protection |

### Authentication & Authorization

| ID | Title | File | Remediation |
|:---|:------|:-----|:------------|
| MED-2 | Unauthenticated `/metrics` | `main.py:278-281` | Add auth or restrict to internal network |
| MED-4 | Weak password policy | `api/auth.py:42` | Add `min_length=8`, complexity regex, `max_length=128` |
| MED-6 | No rate limit on `/validate` | `api/auth.py` | Add rate limiting to prevent token enumeration |
| MED-15 | Account enumeration via login errors | `api/auth.py:197-209` | Use identical error for all login failures |
| MED-17 | Salt reused in hash migration | `api/auth.py:246-249` | Generate new salt via `generate_salt()` |
| MED-18 | JWT `is_admin` not re-verified | `middleware/authentication.py:224-230` | Check admin status on sensitive operations |
| MED-25 | Auto-create user on first login | `services/rbac_service.py:260-285` | Require explicit provisioning in multi-tenant SaaS |

### Data & Injection

| ID | Title | File | Remediation |
|:---|:------|:-----|:------------|
| MED-3 | LLM raw response logged | `services/text_to_sql_service.py:659` | Truncate or redact before logging |
| MED-5 | SSE stream data injection | `api/chat.py:387` | Sanitize exception messages before SSE embedding |
| MED-9 | Unvalidated cron expression | `services/scheduled_report_service.py:380` | Validate against safe patterns |
| MED-10 | Internal error details in chat | `agents/multi_agent_workflow.py` | Sanitize agent errors before returning to client |
| MED-14 | No validation in cost aggregation | `services/multi_account_service.py:166-205` | Validate account IDs and date ranges |
| MED-16 | Inconsistent PII masking | Multiple files | Apply `mask_email()` consistently across all log statements |
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
| LOW-5 | Default DB credentials in settings | `config/settings.py:128-132` | Add production validation for DB password |
| LOW-6 | HSTS disabled by default | `config/settings.py:67-69` | Change default to `True` |
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
| Conversation Isolation | Missing — no user ownership checks | Scoped to user + organization | P1 |
| Rate Limits | Global in-memory | Per-organization configurable limits in Valkey | P1 |
| Secret Key | Single key for all tenants | Consider per-tenant JWT signing keys | P2 |
| RBAC Roles | Global | Per-organization custom roles (add `org_id` to roles table) | P2 |
| Reports | No org scoping | Must be scoped to organization | P1 |
| Audit Logs | `organization_id` nullable | Must be NOT NULL for all entries | P1 |
| Cache Keys | Global namespace | Prefix with `org:{org_id}:` for tenant isolation | P2 |

---

## 8 — Prioritized Remediation Roadmap

### Phase 1 — Immediate (Do Now)

| # | Action | Issues Resolved |
|:--|:-------|:---------------|
| 1 | Rotate and secure secrets (move to Secrets Manager) | ~~CRIT-5~~ (FIXED), ~~CRIT-6~~ (FIXED), ~~CRIT-7~~ (FIXED), ~~CRIT-8~~ (FIXED) |
| 2 | Fix SQL injections | ~~CRIT-3~~ (FIXED), CRIT-12 |
| 3 | Add auth to unprotected endpoints | CRIT-10, CRIT-11, HIGH-20 |
| 4 | Encrypt DB credentials | ~~CRIT-9~~ (FIXED) |
| 5 | ~~Create User ORM model~~ | ~~CRIT-4~~ (FIXED) |

### Phase 2 — Within 2 Weeks

| # | Action | Issues Resolved |
|:--|:-------|:---------------|
| 1 | Brute force protection on login | HIGH-1 |
| 2 | Tenant isolation across all services | HIGH-14, HIGH-15, HIGH-16, HIGH-17, HIGH-28 |
| 3 | Fix dynamic SQL (column name allowlist) | HIGH-9 |
| 4 | Container security (non-root users) | HIGH-21, HIGH-22 |
| 5 | Nginx hardening | HIGH-23, LOW-12 |
| 6 | Infrastructure security | HIGH-24, HIGH-25, HIGH-26 |

### Phase 3 — Within 1 Month

| # | Action | Issues Resolved |
|:--|:-------|:---------------|
| 1 | PII masking consistency | MED-16 |
| 2 | Distributed rate limiting | HIGH-7, HIGH-12, MED-19 |
| 3 | Password policy strengthening | MED-4, HIGH-13 |
| 4 | Fix race conditions | HIGH-4, HIGH-5, HIGH-10, HIGH-11 |
| 5 | Infrastructure compliance | MED-22, MED-23 |

### Phase 4 — Ongoing

| # | Action | Issues Resolved |
|:--|:-------|:---------------|
| 1 | Address all LOW findings | LOW-1 through LOW-13 |
| 2 | Implement refresh token rotation | LOW-8 |
| 3 | Add JWT audience claims | LOW-7 |
| 4 | Review and update RBAC config | LOW-11 |

---
---

## Appendix A — Fixed Issues (Historical Record)

The following **32 issues** were identified in previous audits and have been **confirmed fixed** in the current codebase. They are retained here solely for audit trail and compliance purposes.

| # | Issue | Severity | Fix Evidence | Fixed |
|:--|:------|:---------|:-------------|:------|
| F-1 | Auth bypass via `X-User-Email` header | HIGH | `middleware/authentication.py` — header path removed; JWT-only | 2026-01-31 |
| F-2 | Hardcoded `SECRET_KEY` default in settings | HIGH | `config/settings.py:275-280` — startup crash if not set; 32-char min | 2026-01-31 |
| F-3 | SSL `CERT_NONE` on DB connections | HIGH | `services/database.py:100-120` — `verify-full` mode works | 2026-01-31 |
| F-4 | CORS wildcard with credentials | HIGH | `main.py:149-156` + `settings.py:610-654` — explicit origins | 2026-01-31 |
| F-5 | Missing backend security headers | HIGH | `middleware/security_headers.py` — CSP, HSTS, X-Frame-Options | 2026-01-31 |
| F-6 | SQL injection in athena_query_service | HIGH | Service-code allowlist via `validate_service_code()` | 2026-01-31 |
| F-7 | Token revocation (logout did nothing) | HIGH | `cache_service.py` SHA-256 blacklist in `authentication.py` | 2026-01-31 |
| F-8 | Exposed ANTHROPIC_AUTH_TOKEN | HIGH | Removed from git tracking (commit `ac0a3a2`) | 2026-01-31 |
| F-9 | Conversation IDOR (CRIT-1) | CRITICAL | Commit `c6a72a1` — ownership validation on chat endpoints | 2026-01-31 |
| F-10 | Opportunities IDOR (CRIT-2) | CRITICAL | Commit `99a19f2` — per-user ownership validation | 2026-01-31 |
| F-11 | Saved Views IDOR (CRIT-3) | CRITICAL | Commit `60e313c` — comprehensive ownership validation | 2026-01-31 |
| F-12 | Unauthenticated Analytics (CRIT-4) | CRITICAL | Commit `cd50a7f` — authentication required on all analytics | 2026-01-31 |
| F-13 | LLM-Generated SQL Injection (CRIT-6) | CRITICAL | Commit `54a5983` — SQL validation strengthened | 2026-01-31 |
| F-14 | Hardcoded RBAC role checks | MEDIUM | Commit `ab4a347` — config-based RBAC system | 2026-02-08 |
| F-15 | Deprecated `regex` validator | LOW | `phase3_enterprise.py:42` — replaced with `pattern=` | 2026-02-08 |
| F-16 | Internal exception details exposed | HIGH | All 24 `str(e)` leaks replaced with generic messages; 33 tests | 2026-01-31 |
| F-17 | Health endpoint information disclosure | HIGH | Public probes stripped to minimal payloads; 26 tests | 2026-01-31 |
| F-18 | IAM role migration | HIGH | All six files migrated to `create_aws_session()`; AST tests | 2026-01-31 |
| F-19 | Command injection in migration script | CRITICAL | `validate_postgres_identifier()` + `shlex.quote()`; 31 tests | 2026-02-08 |
| F-20 | SSRF via webhook delivery | HIGH | HTTPS-only, 8 IP ranges blocked, hostname validation; 31 tests | 2026-02-08 |
| F-21 | Unmasked PII in auth logs | HIGH | `mask_email()` on 6 logger statements; 13 tests | 2026-02-08 |
| F-22 | Unauthenticated Athena endpoints | HIGH | Auth + rate limiting + audit on all 4 endpoints; 20 tests | 2026-02-08 |
| F-23 | Timing attack in password verification | CRITICAL | `secrets.compare_digest()` at `auth.py:164` | 2026-03-04 |
| F-24 | Insufficient PBKDF2 iterations | HIGH | 600,000 iterations (OWASP 2023+) at `auth.py:110` | 2026-02-08 |
| F-25 | Token blacklist fails open (cache_service) | MEDIUM | `cache_service.py:211-249` — fail-closed (`return True`) | 2026-02-08 |
| F-26 | SQL Injection in Audit Log Service (CRIT-3) | CRITICAL | `audit_log_service.py:227-277` — `make_interval(hours => $N)` parameterized queries + `int(hours)` validation; 15 tests in `test_audit_log_service_security.py` | 2026-03-04 |
| F-27 | Missing User ORM Model (CRIT-4) | CRITICAL | `database_models.py` — `User` class with 15 columns matching migrations 008+011+013; 50 tests in `test_user_model.py` | 2026-03-04 |
| F-28 | Hardcoded SECRET_KEY in task-def.json (CRIT-5) | CRITICAL | Replaced plaintext value with Secrets Manager reference in `task-def.json`; deterministic pattern regex blocklist in `settings.py`; 17 tests across `test_settings_security.py` and `test_secret_key_not_hardcoded.py` | 2026-03-04 |
| F-29 | Predictable SECRET_KEY in CloudFormation (CRIT-7) | CRITICAL | Removed `!Sub` deterministic pattern from `ecs-services.yaml`; added ECS `Secrets` section with Secrets Manager ARN; `AWS::SecretsManager::Secret` with `GenerateSecretString` in `main-stack.yaml`; IAM `secretsmanager:GetSecretValue` on execution role | 2026-03-04 |
| F-30 | AWS Infrastructure Secrets Exposed in Repository (CRIT-6) | CRITICAL | Replaced all hardcoded AWS account IDs, RDS/ElastiCache endpoints, IAM role ARNs, ECR URIs, personal email with `${PLACEHOLDER}` tokens in `task-def.json`, `cur-bucket-policy.json`, deployment scripts, README docs, and test files; `.gitignore` updated; 27 regression tests in `test_no_infrastructure_secrets.py` | 2026-03-04 |
| F-31 | Database Password in Plaintext ECS Env Vars (CRIT-8) | CRITICAL | Moved `POSTGRES_PASSWORD` from `Environment` to `Secrets` in `ecs-services.yaml`; removed `DATABASE_URL`; added `DatabasePasswordSecret` AWS::SecretsManager::Secret resource and IAM policy in `main-stack.yaml`; updated `task-def.json` secrets section; 10 tests in `test_no_plaintext_db_password.py` | 2026-03-04 |
| F-32 | Unencrypted Sensitive Credentials in Database (CRIT-9) | CRITICAL | Fernet field encryption in `backend/utils/encryption.py` with PBKDF2-HMAC-SHA256 (600k iterations); migration 016 adds `role_arn_encrypted`, `external_id_encrypted`, `credentials_encrypted` columns; `multi_account_service.py` encrypts on write and decrypts on read with backward compat; `FIELD_ENCRYPTION_KEY` setting with production validation; 35+ tests across `test_encryption.py`, `test_multi_account_encryption.py`, `test_settings_security.py` | 2026-03-04 |

---

*Report generated: 2026-03-04 | Next audit recommended: 2026-04-04*
*Total tracked: 74 open + 32 fixed = 106 vulnerabilities across 3 audit cycles*
