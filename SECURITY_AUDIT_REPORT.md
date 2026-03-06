# Security Audit Report

## FinOps AI Cost Intelligence Platform

| | |
|---|---|
| **Report Date** | 2026-03-06 (Rev 7) |
| **Previous Audits** | 2026-03-06 (Rev 6 · Rev 5 · Rev 4 · Rev 3 · Rev 2 · Rev 1), 2026-03-05, 2026-03-04, 2026-02-08, 2026-01-31 |
| **Methodology** | Penetration test, static code analysis, shell script audit, dependency scanning, infrastructure review |
| **Scope** | Backend (Python/FastAPI), Frontend (React/TypeScript), Infrastructure (CloudFormation, Docker, Nginx), Deployment Scripts (deploy.sh + scripts/), Database Models & Migrations |

---

## Table of Contents

| # | Section |
|---|---------|
| 1 | [Executive Summary](#1--executive-summary) |
| 2 | [Complete Vulnerability Status Table](#2--complete-vulnerability-status-table) |
| 3 | [Open — Critical](#3--critical-vulnerabilities-0-open) |
| 4 | [Open — High](#4--high-vulnerabilities-21-open) |
| 5 | [Open — Medium](#5--medium-vulnerabilities-36-open) |
| 6 | [Open — Low](#6--low-vulnerabilities-18-open) |
| 7 | [SaaS Multi-Tenant Checklist](#7--saas-multi-tenant-security-checklist) |
| 8 | [Remediation Roadmap](#8--prioritized-remediation-roadmap) |

For remediated vulnerabilities, see [`FIXED_SECURITY_ISSUES.md`](./FIXED_SECURITY_ISSUES.md).

---

## 1 — Executive Summary

**75 open vulnerabilities** as of Rev 7. No open CRITICAL findings. The HIGH tier is dominated by **tenant isolation gaps** (HIGH-16/28 — organization IDOR, and 7 DB tables without `org_id`), **infrastructure hardening** (HIGH-21/22/23/24/25/26 — root containers, missing Nginx headers, Valkey plaintext transit, wildcard IAM, exposed ports), and **race conditions** in cost/views/org services (HIGH-4/5/10/11). The MEDIUM tier is dominated by **PII log leakage** — 15+ unmasked-email sites across MED-16/28/30/31/33 with no CI tripwire to prevent reintroduction. The recently-audited deployment scripts (`deploy.sh`, 140KB) carry four new findings (MED-36/37, LOW-15/18) — `eval` with user input, plaintext DB password on the deploy host, predictable `/tmp` paths.

### Risk Dashboard

```
 CRITICAL     0 open
 HIGH      █████████████████████  21 open
 MEDIUM    ████████████████████████████████████  36 open
 LOW       ██████████████████  18 open
 ────────────────────────────────────────────
 TOTAL OPEN: 75
```

| Severity | Open |
|:---------|:----:|
| CRITICAL | **0** |
| HIGH | **21** |
| MEDIUM | **36** |
| LOW | **18** |
| **Total** | **75** |

### Top Systemic Risks

> **1. Tenant Isolation Incomplete Across the Data Plane**
> Organization details (HIGH-16) have no membership check — any authenticated user can fetch any org's metadata by UUID. Seven database tables (HIGH-28) lack an `organization_id` column entirely, so there is no row to filter on even if the API layer wanted to. These are distinct bugs but share one root cause: tenant scoping was added incrementally endpoint-by-endpoint rather than enforced at the data layer. Row-level security on Postgres + a mandatory `org_id` column on every table would make the unscoped-query path structurally impossible.

> **2. Deployment Scripts Hold Admin Credentials With No Hardening**
> `deploy.sh` (140KB), `rebuild-backend.sh`, `find_ecs_cluster.sh`, and `scripts/` were outside prior audit scope. Findings: `eval` with user input, plaintext DB password written to `deployment.env` on the deploy host (MED-36), predictable `/tmp/` paths without `mktemp` (MED-37), and unquoted shell variables. None are remote-exploitable, but all violate secure-by-default on a host that holds AWS admin credentials — compromise of the deploy host is compromise of production.

> **3. PII Leakage in Logs is Endemic**
> 15+ unmasked email log sites remain across MED-16/28/30/31/33. `login_throttle.py` logs raw client IPs (LOW-16) — GDPR classifies IP addresses as personal data. There is no CI tripwire to catch reintroduction; every new `logger.info(..., email=user.email)` is another leak. The tripwire proposed in MED-28 should be prioritized ahead of the individual masking fixes — fixing 15 sites without a guard means a 16th lands next sprint.

---

## 2 — Complete Vulnerability Status Table

All currently open vulnerabilities. For remediated issues see [`FIXED_SECURITY_ISSUES.md`](./FIXED_SECURITY_ISSUES.md).

### OPEN — Critical (0)

*No open CRITICAL findings.*

### OPEN — High (21)

| ID | Title | CVSS | Location | Discovered | Status |
|:---|:------|:----:|:---------|:----------:|:------:|
| HIGH-4 | Race Condition in Opportunity Cost Calculations | 7.8 | `services/opportunities_service.py:150-200` | 2026-02-08 | OPEN |
| HIGH-5 | TOCTOU in Saved Views Access Control | 7.5 | `services/saved_views_service.py:142-170` | 2026-02-08 | OPEN |
| HIGH-6 | Mass Assignment in Opportunity Updates | 7.5 | `api/opportunities.py:307` | 2026-02-08 | OPEN |
| HIGH-7 | In-Memory Rate Limiting Ineffective Across Instances | 7.5 | `middleware/rate_limiting.py:23-51` | 2026-02-08 | OPEN |
| HIGH-9 | Dynamic SQL Column Names in opportunities_service | 7.8 | `services/opportunities_service.py:446-462` | 2026-02-08 | OPEN |
| HIGH-10 | Race Condition in Saved Views Default Flag | 7.5 | `services/saved_views_service.py:76-84` | 2026-02-08 | OPEN |
| HIGH-11 | TOCTOU in Organization Member Limit | 6.8 | `services/organization_service.py:336-352` | 2026-02-08 | OPEN |
| HIGH-16 | IDOR on Organization Details | 7.5 | `api/organizations.py:147-165` | 2026-03-04 | OPEN |
| HIGH-18 | Arbitrary Permission Strings in Role Creation | 7.8 | `api/phase3_enterprise.py:93-96` | 2026-03-04 | OPEN |
| HIGH-19 | Path/Body Param Mismatch in Account Perms | 7.5 | `api/phase3_enterprise.py:241-258` | 2026-03-04 | OPEN |
| HIGH-21 | Backend Docker Container Runs as Root | 7.0 | `backend/Dockerfile` | 2026-03-04 | OPEN |
| HIGH-22 | Frontend Docker Container Runs as Root | 7.0 | `frontend/Dockerfile` | 2026-03-04 | OPEN |
| HIGH-23 | No Security Headers in Nginx | 7.5 | `frontend/nginx.conf` | 2026-03-04 | OPEN |
| HIGH-24 | Valkey Transit Encryption Disabled | 7.5 | `cloudformation/main-stack.yaml:412` | 2026-03-04 | OPEN |
| HIGH-25 | Overly Broad IAM Policies (Wildcards) | 7.5 | `cloudformation/main-stack.yaml:520-588` | 2026-03-04 | OPEN |
| HIGH-26 | Database/Cache Ports Exposed to Host | 7.0 | `docker-compose.yml:12-13,28-29` | 2026-03-04 | OPEN |
| HIGH-27 | Supply Chain: Non-Registry Dependency (xlsx) | 7.0 | `frontend/package.json:36` | 2026-03-04 | OPEN |
| HIGH-28 | Missing org_id on Multiple DB Tables | 8.0 | `alembic/versions/006,009_*.py` | 2026-03-04 | OPEN |
| HIGH-29 | Prompt Injection in Text-to-SQL Service | 7.8 | `services/text_to_sql_service.py:632-659` | 2026-03-04 | OPEN |
| HIGH-30 | SSTI Blocklist Bypass in Report Templates | 7.5 | `api/phase3_enterprise.py:42-68` | 2026-03-04 | OPEN |
| HIGH-31 | Password Hash Column Indexed | 7.0 | `alembic/versions/013_*.py:39` | 2026-03-04 | OPEN |

### OPEN — Medium (36)

| ID | Title | CVSS | Location | Discovered | Status |
|:---|:------|:----:|:---------|:----------:|:------:|
| **MED-34** | **Unicode Normalization Bypass in Login Throttle** | **5.8** | **`middleware/login_throttle.py:99`** | **2026-03-06** | **🆕 OPEN** |
| **MED-35** | **Unsalted SHA-256 Keys → Email Enumeration via Valkey** | **5.5** | **`middleware/login_throttle.py:88`** | **2026-03-06** | **🆕 OPEN** |
| **MED-36** | **DB Password Plaintext on Deploy Host** | **5.5** | **`deploy.sh:123` → `deployment.env`** | **2026-03-06** | **🆕 OPEN** |
| **MED-37** | **Predictable /tmp Paths Without mktemp (TOCTOU)** | **5.0** | **`deploy.sh:382,819,835` + `scripts/setup/*.sh`** | **2026-03-06** | **🆕 OPEN** |
| MED-1 | Account Scoping Fails Open | 6.5 | `middleware/account_scoping.py:111-122` | 2026-01-31 | OPEN |
| MED-2 | Unauthenticated Prometheus Metrics | 6.5 | `main.py:278-281` | 2026-01-31 | OPEN |
| MED-3 | LLM Response Preview Still Logged | 5.0 | `services/text_to_sql_service.py:661` | 2026-01-31 | OPEN |
| MED-4 | Weak Password Policy | 6.5 | `api/auth.py:42` | 2026-01-31 | OPEN |
| MED-6 | Missing Rate Limit on Token Validation | 5.3 | `api/auth.py` | 2026-01-31 | OPEN |
| MED-7 | Default SSL Mode Unverified | 5.9 | `services/database.py:67-77` | 2026-01-31 | OPEN |
| MED-8 | Production Sourcemaps Exposed | 5.3 | `frontend/vite.config.ts:24` | 2026-01-31 | OPEN |
| MED-9 | Unvalidated Cron Expression | 5.3 | `services/scheduled_report_service.py:380` | 2026-01-31 | OPEN |
| MED-10 | Internal Error Details in Chat Response | 6.2 | `agents/multi_agent_workflow.py` | 2026-01-31 | OPEN |
| MED-11 | Stack Traces in Development Mode | 6.5 | `main.py:240-252` | 2026-02-08 | OPEN |
| MED-12 | Race Condition in Org Member Management | 6.8 | `services/organization_service.py:286-367` | 2026-02-08 | OPEN |
| MED-13 | TOCTOU in Org Member Removal | 6.5 | `services/organization_service.py:369-436` | 2026-02-08 | OPEN |
| MED-14 | No Validation in Cost Aggregation | 6.2 | `services/multi_account_service.py:166-205` | 2026-02-08 | OPEN |
| MED-15 | Account Enumeration via "Account is disabled" | 5.3 | `api/auth.py:218-220` | 2026-03-04 | OPEN |
| MED-16 | Inconsistent PII Masking Across Codebase | 5.3 | Multiple (see MED-28 inventory) | 2026-03-04 | OPEN |
| MED-17 | Salt Reused During Password Hash Migration | 5.5 | `api/auth.py:246-250` | 2026-03-04 | OPEN |
| MED-18 | JWT is_admin Not Re-Verified Per Request | 6.0 | `middleware/authentication.py:224-230` | 2026-03-04 | OPEN |
| MED-19 | Unbounded Memory Growth in Rate Limiter | 5.5 | `middleware/rate_limiting.py:49-50` | 2026-03-04 | OPEN |
| MED-20 | CSV Injection in Frontend Export | 5.5 | `frontend/src/utils/exportUtils.ts:90-99` | 2026-03-04 | OPEN |
| MED-21 | CORS Includes localhost in Production | 5.0 | `cloudformation/ecs-services.yaml:160` | 2026-03-04 | OPEN |
| MED-22 | 7-Day Log Retention Insufficient | 5.0 | `cloudformation/ecs-services.yaml:90,96` | 2026-03-04 | OPEN |
| MED-23 | WAF Removed from Infrastructure | 6.0 | `cloudformation/main-stack.yaml:495` | 2026-03-04 | OPEN |
| MED-24 | Unbounded RBAC Permission Cache | 5.5 | `services/rbac_service.py:25-78` | 2026-03-04 | OPEN |
| MED-25 | Auto-Create User on First Login | 6.0 | `services/rbac_service.py:260-285` | 2026-03-04 | OPEN |
| MED-26 | Singleton Service with Mutable Org ID | 6.5 | `services/opportunities_service.py:999-1012` | 2026-03-04 | OPEN |
| MED-27 | Database Connection Leak on Exception | 5.5 | `services/opportunities_service.py:261-474` | 2026-03-04 | OPEN |
| MED-28 | Unmasked Emails in Rate-Limit Code Paths | 5.3 | `rate_limiting.py:461,485` + 10 files | 2026-03-05 | OPEN |
| MED-29 | Unvalidated Role String in Rate-Limit Admin | 5.0 | `api/admin/rate_limits.py:33` | 2026-03-05 | OPEN |
| MED-30 | Unmasked Email in Logout Handler | 5.3 | `api/auth.py:538` | 2026-03-06 | OPEN |
| MED-31 | Unmasked Email in Revoked-Token Warning | 5.3 | `middleware/authentication.py:215` | 2026-03-06 | OPEN |
| MED-32 | CSV Formula Injection in Backend Export | 5.5 | `api/opportunities.py:589-604` | 2026-03-06 | OPEN |
| MED-33 | Unmasked NL Query in Athena Log | 5.3 | `api/athena_queries.py:65` | 2026-03-06 | OPEN |

### OPEN — Low (18)

| ID | Title | CVSS | Location | Discovered | Status |
|:---|:------|:----:|:---------|:----------:|:------:|
| **LOW-15** | **eval with User Input in deploy.sh safe_read()** | **4.0** | **`deploy.sh:157-159`** | **2026-03-06** | **🆕 OPEN** |
| **LOW-16** | **Client IP Logged Unmasked in Login Throttle (GDPR)** | **3.5** | **`middleware/login_throttle.py:139`** | **2026-03-06** | **🆕 OPEN** |
| **LOW-17** | **Google Fonts CSS Without SRI** | **3.1** | **`frontend/index.html:9-12`** | **2026-03-06** | **🆕 OPEN** |
| **LOW-18** | **Unquoted Shell Variables in find_ecs_cluster.sh** | **3.0** | **`find_ecs_cluster.sh:29,40-41,63,67-68`** | **2026-03-06** | **🆕 OPEN** |
| LOW-1 | Weak Default Passwords in docker-compose | 4.3 | `docker-compose.yml:10,30,55,58` | 2026-01-31 | OPEN |
| LOW-2 | Unbounded Audit Query Parameters | 4.3 | `api/phase3_enterprise.py:390-423` | 2026-01-31 | OPEN |
| LOW-3 | Short Hash in PII Masking (32 bits) | 4.3 | `utils/pii_masking.py:74-76` | 2026-02-08 | OPEN |
| LOW-4 | Organization Slug Collision Risk | 3.1 | `services/organization_service.py:68-80` | 2026-02-08 | OPEN |
| LOW-5 | Default DB Credentials in Settings | 4.0 | `config/settings.py:136-139` | 2026-03-04 | OPEN |
| LOW-6 | HSTS Disabled by Default | 4.0 | `config/settings.py:68-72` | 2026-03-04 | OPEN |
| LOW-7 | Missing JWT Audience Claim | 3.5 | `utils/auth.py:158-173` | 2026-03-04 | OPEN |
| LOW-8 | No Refresh Token Rotation | 4.3 | `api/auth.py:327-412` | 2026-03-04 | OPEN |
| LOW-9 | Insecure Default Secret Accepted | 4.0 | `utils/auth.py:121-132` | 2026-03-04 | OPEN |
| LOW-10 | Permission Names in Error Messages | 3.1 | `services/rbac_service.py:208-252` | 2026-03-04 | OPEN |
| LOW-11 | Redundant is_admin Flag vs RBAC | 3.5 | `alembic/versions/008_*.py:39` | 2026-03-04 | OPEN |
| LOW-12 | Nginx Server Version Disclosure | 3.0 | `frontend/nginx.conf` | 2026-03-04 | OPEN |
| LOW-13 | Empty SECRET_KEY Default in Compose | 4.3 | `docker-compose.yml:59` | 2026-03-04 | OPEN |
| LOW-14 | Unmasked Recipients in Email Service Stub | 3.5 | `services/email_service.py:40` | 2026-03-06 | OPEN |

---

## 3 — Critical Vulnerabilities (0 Open)

No open CRITICAL findings.

---

## 4 — High Vulnerabilities (21 Open)

### Authentication & Access Control

### Tenant Isolation

#### HIGH-16 — IDOR on Organization Details
**File:** `backend/api/organizations.py:147-165` | **CVSS:** 7.5

**Verified still present 2026-03-06:**
```python
@router.get("/organizations/{org_id}")
async def get_organization(org_id: UUID, ...):
    org = await organization_service.get_organization(org_id)  # no membership check
    return OrganizationResponse(**org)
```
**Remediation:** Verify membership before returning org details.

#### HIGH-28 — Missing org_id on Multiple DB Tables
**Files:** `alembic/versions/006_*.py`, `009_*.py` | **CVSS:** 8.0

Missing `organization_id` FK on: `scheduled_reports`, `report_executions`, `dashboard_templates`, `cost_allocation_rules`, `chargeback_reports`, `ticketing_integrations`, `tickets`.

**Remediation:** New migration adding `organization_id NOT NULL` FK to each. **SaaS-critical** — per-client data isolation impossible without this.

---

### Injection & Input Validation

#### HIGH-9 — Dynamic SQL Column Names in opportunities_service
**File:** `backend/services/opportunities_service.py:446-462` | **CVSS:** 7.8

```python
columns = list(data.keys())
query = f"INSERT INTO opportunities ({', '.join(columns)}) VALUES ..."
```
**Remediation:** `ALLOWED_COLUMNS` frozenset; reject unknown keys before query build.

#### HIGH-18 — Arbitrary Permission Strings in Role Creation
**File:** `backend/api/phase3_enterprise.py:93-96` | **CVSS:** 7.8

`permissions: List[str]` with no allowlist. **Remediation:** Validate each entry against `config/rbac_config.yaml`'s known permission set.

#### HIGH-19 — Path/Body Parameter Mismatch in Account Permissions
**File:** `backend/api/phase3_enterprise.py:241-258` | **CVSS:** 7.5

Line 253 uses `permission.account_id` (body) instead of path `account_id`. **Remediation:** Assert equality or drop body field.

#### HIGH-29 — Prompt Injection in Text-to-SQL Service
**File:** `backend/services/text_to_sql_service.py:632-659` | **CVSS:** 7.8

`UNION SELECT` and SQL comments only warn, never block. Account filter bypassed if keyword already present. **Remediation:** Block on dangerous patterns; verify account filter references only allowed accounts.

#### HIGH-30 — SSTI Blocklist Bypass in Report Templates
**File:** `backend/api/phase3_enterprise.py:42-68` | **CVSS:** 7.5

Blocklist bypassable via Unicode homoglyphs, `|attr` filter chains, unlisted objects (`request`, `cycler`, `joiner`, `namespace`). **Remediation:** `SandboxedEnvironment` + allowlist of safe variables/filters.

---

### Race Conditions

| ID | Title | File | Fix |
|:---|:------|:-----|:----|
| HIGH-4 | Race in Opportunity Cost Calculations | `opportunities_service.py:150-200` | `SELECT ... FOR UPDATE` in transaction |
| HIGH-5 | TOCTOU in Saved Views Access Control | `saved_views_service.py:142-170` | `SELECT ... FOR UPDATE` |
| HIGH-6 | Mass Assignment in Opportunity Updates | `opportunities.py:307` — `body.model_dump(exclude_none=True)` | Explicit allowlist of updatable fields |
| HIGH-7 | In-Memory Rate Limiting Ineffective | `rate_limiting.py:23-51` | Valkey `INCR` + `EXPIRE` (distributed) |
| HIGH-10 | Race in Saved Views Default Flag | `saved_views_service.py:76-84` | Unique partial index or `FOR UPDATE` |
| HIGH-11 | TOCTOU in Org Member Limit | `organization_service.py:336-352` | `INSERT ... WHERE (SELECT COUNT(*)) < limit` |

---

### Infrastructure

#### HIGH-21 & HIGH-22 — Docker Containers Run as Root
**Files:** `backend/Dockerfile`, `frontend/Dockerfile` | **CVSS:** 7.0

**Verified still present 2026-03-06** — neither file has a `USER` directive.

```dockerfile
# Backend — add before CMD:
RUN adduser --disabled-password --gecos '' appuser && chown -R appuser:appuser /app
USER appuser

# Frontend — add before CMD:
RUN adduser -D -g '' appuser && chown -R appuser:appuser /usr/share/nginx/html /var/cache/nginx
USER appuser
```

#### HIGH-23 — No Security Headers in Nginx
**File:** `frontend/nginx.conf` | **CVSS:** 7.5

**Verified still present 2026-03-06** — missing CSP, X-Frame-Options, HSTS, X-Content-Type-Options, Referrer-Policy, `server_tokens off`.

```nginx
server_tokens off;
add_header X-Frame-Options "DENY" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Content-Security-Policy "default-src 'self'; style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com;" always;
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;
```

#### HIGH-24 — Valkey Transit Encryption Disabled
**File:** `infrastructure/cloudformation/main-stack.yaml:412` | **CVSS:** 7.5

**Verified still present 2026-03-06** — `TransitEncryptionEnabled: false`. Cache traffic (session tokens, blacklist hashes) plaintext within VPC.

**Fix:** `TransitEncryptionEnabled: true` + update `cache_service.py` client to use `ssl=True`.

#### HIGH-25 — Overly Broad IAM Policies with Wildcard Resources
**File:** `infrastructure/cloudformation/main-stack.yaml:520-588` | **CVSS:** 7.5

`Resource: '*'` for CloudWatch Logs, Glue, Athena, Cost Explorer. **Compound risk:** `logs:*` on `*` + MED-28/30/31/33 unmasked PII = cross-tenant log reads by anyone assuming the task role.

**Fix:** Scope each to specific ARNs per-tenant (requires per-client CloudFormation parameter).

#### HIGH-26 — Database/Cache Ports Exposed to Host
**File:** `docker-compose.yml:12-13,28-29` | **CVSS:** 7.0

`5432:5432` and `6379:6379` bound to host. **Fix:** Remove `ports`; use Docker network only.

#### HIGH-27 — Supply Chain: Non-Registry Dependency
**File:** `frontend/package.json:36` | **CVSS:** 7.0

**Verified still present 2026-03-06:**
```json
"xlsx": "https://cdn.sheetjs.com/xlsx-0.20.3/xlsx-0.20.3.tgz"
```
Bypasses npm integrity. **Fix:** Pin integrity hash in lockfile or vendor locally.

#### HIGH-31 — Password Hash Column Indexed
**File:** `alembic/versions/013_add_password_fields_secure_hashing.py:39` | **CVSS:** 7.0

**Verified still present 2026-03-06:**
```python
op.create_index('idx_users_password_hash', 'users', ['password_hash'])
```
No legitimate lookup path. Index contents may leak via `pg_stat_*` views. **Fix:** `op.drop_index` in a new migration.

---

## 5 — Medium Vulnerabilities (36 Open)

### 🆕 NEW — Discovered This Cycle (Rev 2)

---

#### MED-34 — Unicode Normalization Bypass in Login Throttle

| | |
|---|---|
| **File** | `backend/middleware/login_throttle.py:99` |
| **CVSS** | 5.8 |
| **Relationship** | Weakens the login throttle's per-email counter |

```python
def _email_fail_key(self, email: str) -> str:
    # .lower() is LOAD-BEARING: Alice@Example.com and alice@example.com
    # must share a counter...
    return f"{self.EMAIL_KEY_PREFIX}{self._hash(email.lower())}"
```

The comment is right about ASCII case — but `.lower()` doesn't perform **Unicode normalization**. These all pass Pydantic's `EmailStr` validation and all `.lower()` to **different** strings:

| Input | `.lower()` result | Hash |
|:------|:------|:-----|
| `admin@target.com` | `admin@target.com` | `h1` |
| `admın@target.com` (U+0131 dotless i) | `admın@target.com` | `h2` |
| `ａdmin@target.com` (U+FF41 fullwidth a) | `ａdmin@target.com` | `h3` |
| `ADMİN@target.com` (U+0130 dotted İ) | `admi̇n@target.com` | `h4` |

Each variant gets its own counter → attacker multiplies attempt budget. Most mail servers normalize these on delivery, so they all reach the same mailbox.

**Remediation:**
```python
import unicodedata
def _normalize_email(self, email: str) -> str:
    # NFKC: compatibility decomposition + canonical composition.
    # Collapses fullwidth→ASCII, ligatures, dotted-i variants, etc.
    return unicodedata.normalize('NFKC', email).lower()
```

**Claude Code Fix Instructions:**
```
1. In backend/middleware/login_throttle.py, add _normalize_email() helper as above.
2. Replace all 3 `email.lower()` calls (lines ~99, 102, 105) with
   self._normalize_email(email).
3. Add test: 5 attempts spread across U+0131, U+FF41, U+0130 variants of the
   same email → 6th attempt blocked (shared counter).
```

---

#### MED-35 — Unsalted SHA-256 Keys → Email Enumeration via Valkey Export

| | |
|---|---|
| **File** | `backend/middleware/login_throttle.py:88` |
| **CVSS** | 5.5 |
| **Relationship** | Partially defeats the login throttle's "no PII in Valkey" design goal |

```python
@staticmethod
def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
```

The `login_throttle.py` docstring (line 81-86) says hashing ensures "no PII-at-rest in Valkey". **This is only true against casual inspection.** SHA-256 without a salt is a **deterministic lookup** — anyone with read access to Valkey (backup file, `KEYS login:email:*`, Valkey RDB on disk) can pre-compute hashes of likely emails and recover which accounts are under attack:

```python
targets = ["ceo@client.com", "cfo@client.com", "admin@client.com", ...]
leaked_keys = {"login:email:a3f2...": 4}  # from KEYS + GET
for email in targets:
    h = hashlib.sha256(email.lower().encode()).hexdigest()
    if f"login:email:{h}" in leaked_keys:
        print(f"{email} has {leaked_keys[...]} failed attempts")  # enumeration
```

**Remediation:**
```python
# Use HMAC with a per-deployment pepper — settings.login_throttle_pepper,
# provisioned per-client via Secrets Manager (SaaS: each tenant's Valkey
# namespace uses a different pepper → cross-tenant key collision impossible).
def _hash(self, value: str) -> str:
    return hmac.new(
        self._pepper.encode(),  # loaded once from settings in __init__
        value.encode(),
        hashlib.sha256
    ).hexdigest()
```

**Claude Code Fix Instructions:**
```
1. Add `login_throttle_pepper: SecretStr` to config/settings.py with
   production-fatal validation (same pattern as FIELD_ENCRYPTION_KEY).
2. Provision in main-stack.yaml as a 32-byte GenerateSecretString secret +
   ECS Secrets entry in ecs-services.yaml + task-def.json (same provisioning
   path as FIELD_ENCRYPTION_KEY — secret resource, execution-role grant,
   Secrets: block in both deployment artifacts).
3. In LoginThrottle.__init__, load self._pepper = settings.login_throttle_pepper.get_secret_value().
4. Convert _hash from @staticmethod to instance method using HMAC.
5. Test: two LoginThrottle instances with different peppers produce different
   keys for the same email.
```

---

#### MED-36 — DB Password Plaintext on Deploy Host

| | |
|---|---|
| **File** | `deploy.sh:123` → writes `deployment.env` |
| **CVSS** | 5.5 |
| **Mitigating Factor** | `.gitignore:217` excludes `deployment.env` from version control |

```bash
# deploy.sh — DB password generated with good entropy...
DB_PASSWORD=$(openssl rand -base64 32 | tr -dc 'A-Za-z0-9!#$%&*+<=>?^_~' | head -c 32)
# ...then written to plaintext file on the deploy host:
update_deployment_state "DB_PASSWORD" "$DB_PASSWORD"   # appends to deployment.env
```

The password IS correctly stored in SSM Parameter Store for the application. But `deployment.env` persists on the operator's filesystem with **default umask permissions** (typically `644` — world-readable). On a shared bastion/deploy host, any user can `cat deployment.env`.

**Remediation:**
```bash
# At top of update_deployment_state():
umask 077  # files created 600
touch deployment.env
chmod 600 deployment.env

# After SSM upload completes, scrub the local copy:
sed -i.bak 's/^DB_PASSWORD=.*/DB_PASSWORD=<stored-in-ssm>/' deployment.env
shred -u deployment.env.bak 2>/dev/null || rm -f deployment.env.bak
```

**Claude Code Fix Instructions:**
```
1. In deploy.sh, add `umask 077` at the top of the script (after set -euo pipefail).
2. After update_deployment_state() writes DB_PASSWORD, add chmod 600 deployment.env.
3. After the SSM put-parameter succeeds, overwrite DB_PASSWORD in deployment.env
   with a placeholder. Do NOT delete the file — other vars are still needed.
4. Apply the same umask to rebuild-backend.sh and scripts/deployment/*.sh.
```

---

#### MED-37 — Predictable /tmp Paths Without mktemp (TOCTOU)

| | |
|---|---|
| **Files** | `deploy.sh:382,819,835,841` · `scripts/setup/setup_cur_pipeline.sh:91,145,160` · `scripts/setup/setup-cur.sh` |
| **CVSS** | 5.0 |

```bash
# deploy.sh:819
cat > /tmp/lifecycle-config.json << 'LIFECYCLE_EOF'
{ ... }
LIFECYCLE_EOF
aws s3api put-bucket-lifecycle-configuration \
    --lifecycle-configuration file:///tmp/lifecycle-config.json  # ← TOCTOU window
rm -f /tmp/lifecycle-config.json
```

On a multi-user deploy host, another process can:
1. **Pre-create** `/tmp/lifecycle-config.json` as a symlink → deploy.sh overwrites the target
2. **Replace** the file between `cat >` and `aws s3api` → attacker-controlled S3 lifecycle policy applied to client's bucket

**Full inventory of hardcoded `/tmp/` paths:**

| File | Lines | Path |
|:-----|:------|:-----|
| `deploy.sh` | 382 | `/tmp/bedrock-test.json` |
| `deploy.sh` | 819, 835, 841 | `/tmp/lifecycle-config.json` |
| `scripts/setup/setup_cur_pipeline.sh` | 91 | `/tmp/create_cur_from_manifest.sql` |
| `scripts/setup/setup_cur_pipeline.sh` | ~95 | `/tmp/_create_only.sql` |
| `scripts/setup/setup_cur_pipeline.sh` | 145 | `/tmp/lambda-trust.json` |
| `scripts/setup/setup_cur_pipeline.sh` | 160 | `/tmp/s3-notify.json` |
| `scripts/setup/setup_cur_pipeline.sh` | ~170 | `/tmp/cur-archiver.zip` |
| `scripts/setup/setup-cur.sh` | — | `glue-trust-policy.json` |

**Remediation (pattern for all sites):**
```bash
TMPDIR=$(mktemp -d -t finops-deploy.XXXXXXXX)
trap 'rm -rf "$TMPDIR"' EXIT
cat > "$TMPDIR/lifecycle-config.json" << 'EOF'
...
EOF
aws s3api put-bucket-lifecycle-configuration \
    --lifecycle-configuration "file://$TMPDIR/lifecycle-config.json"
```

**Claude Code Fix Instructions:**
```
1. At the top of deploy.sh (after set -euo pipefail), add:
   TMPDIR=$(mktemp -d -t finops-deploy.XXXXXXXX)
   Update the existing `trap cleanup EXIT` at line ~3013 to also rm -rf "$TMPDIR".
2. Replace every /tmp/<name> with "$TMPDIR/<name>" at the 4 sites listed.
3. Repeat for scripts/setup/setup_cur_pipeline.sh (5 sites) and setup-cur.sh.
4. Add shellcheck to CI — SC2186 catches this pattern.
```

---

### Previously-Identified Medium Findings

#### MED-30 — Unmasked Email in Logout Handler
**File:** `backend/api/auth.py:538` | **CVSS:** 5.3

**Re-verified still open 2026-03-06:**
```python
logger.info(
    "user_logout",
    user_id=user.user_id,
    email=user.email,   # ← STILL not masked (line 538)
```
`mask_email` is already imported at line 31. **One-line fix:** `email=mask_email(user.email)`.

#### MED-31 — Unmasked Email in Revoked-Token Warning
**File:** `backend/middleware/authentication.py:215` | **CVSS:** 5.3

**Re-verified still open 2026-03-06:**
```python
logger.warning("revoked_token_used", user_id=payload.user_id, email=payload.email)
```
Token replay is a **security-relevant event** forwarded to SIEM → data-processor contract risk.

**Fix:** Import `mask_email` from `utils.pii_masking`; change to `email=mask_email(payload.email)`.

#### MED-32 — CSV Formula Injection in Backend Opportunities Export
**File:** `backend/api/opportunities.py:589-604` | **CVSS:** 5.5

Server-side sibling of MED-20. No `= + - @ \t \r` escaping. An opportunity titled `=cmd|'/c calc'!A1` becomes a live formula in Excel. Title is user-controlled via HIGH-6's mass-assignment.

```python
def _csv_safe(v):
    if isinstance(v, str) and v and v[0] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + v
    return v
```

#### MED-33 — Unmasked Natural-Language Query in Athena Log
**File:** `backend/api/athena_queries.py:65` | **CVSS:** 5.3

`user_query=request.user_query` logged at INFO on every request. NL questions contain emails, account IDs, cost figures. `utils/pii_masking.py:mask_query_for_logging()` exists for exactly this.

#### MED-28 — Unmasked Emails: Full Inventory (Extended Scope)
**CVSS:** 5.3

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

**CI Tripwire (add to pre-commit / GitHub Actions):**
```bash
grep -rnE 'logger\.(info|warning|error|debug)\(' backend/ \
  | grep -E '(user_email|[^_]email|created_by|added_by)\s*=' \
  | grep -v 'mask_email(' \
  && { echo "FAIL: unmasked email in log"; exit 1; } || exit 0
```

#### MED-29 — Unvalidated Role String in Rate-Limit Admin API
**File:** `api/admin/rate_limits.py:33` | **CVSS:** 5.0

`role: str` accepts any string. **Fix:** `role: Literal['owner', 'admin', 'member']`.

---

### Compact Table: Remaining Medium Findings

| ID | Title | File | Remediation |
|:---|:------|:-----|:------------|
| MED-1 | Account scoping fails open | `middleware/account_scoping.py:111-122` | Change to fail-closed |
| MED-2 | Unauthenticated `/metrics` | `main.py:278-281` | Add auth or restrict to VPC-internal |
| MED-3 | LLM response preview still logged | `services/text_to_sql_service.py:661` | Remove preview or add PII scrubbing |
| MED-4 | Weak password policy | `api/auth.py:43` | Length enforced (`min_length=8, max_length=128`). Complexity regex still missing — this item stays open for that. |
| MED-6 | No rate limit on `/validate` | `api/auth.py` | Rate-limit to prevent token enumeration |
| MED-7 | Default SSL mode unverified | `services/database.py:67-77` | Default to `verify-full` |
| MED-8 | Production sourcemaps exposed | `frontend/vite.config.ts:24` | `sourcemap: false` or `'hidden'` |
| MED-9 | Unvalidated cron expression | `services/scheduled_report_service.py:380` | Validate against safe patterns |
| MED-10 | Internal error details in chat response | `agents/multi_agent_workflow.py` | Sanitize agent errors before returning |
| MED-11 | Stack traces in dev mode | `main.py:240-252` | Enforce `ENVIRONMENT=production` in deployed envs |
| MED-12 | Race in org member management | `services/organization_service.py:286-367` | `FOR UPDATE` or serializable |
| MED-13 | TOCTOU in org member removal | `services/organization_service.py:369-436` | Atomic operations |
| MED-14 | No validation in cost aggregation | `services/multi_account_service.py:166-205` | Validate account IDs and date ranges |
| MED-15 | Enumeration via "Account is disabled" | `api/auth.py:218-220` | Return identical "Invalid email or password" |
| MED-16 | Inconsistent PII masking | Multiple | See MED-28 inventory |
| MED-17 | Salt reused in hash migration | `api/auth.py:246-250` | `generate_salt()` during migration |
| MED-18 | JWT `is_admin` not re-verified | `middleware/authentication.py:224-230` | Re-check admin on sensitive ops |
| MED-19 | Unbounded memory in rate limiter | `middleware/rate_limiting.py:49-50` | Periodic cleanup or Valkey TTL |
| MED-20 | CSV injection in frontend export | `frontend/src/utils/exportUtils.ts:90-99` | Prefix `= + - @` with `'` |
| MED-21 | CORS includes localhost in prod | `ecs-services.yaml:160` | Remove localhost origins |
| MED-22 | 7-day log retention | `ecs-services.yaml:90,96` | 90+ days for SOC 2 |
| MED-23 | WAF removed | `main-stack.yaml:495` | Reinstate AWS WAF |
| MED-24 | Unbounded RBAC permission cache | `services/rbac_service.py:25-78` | TTL eviction + max entries |
| MED-25 | Auto-create user on first login | `services/rbac_service.py:260-285` | Require explicit provisioning (per-tenant toggle) |
| MED-26 | Singleton with mutable org ID | `services/opportunities_service.py:999-1012` | Request-scoped instances |
| MED-27 | DB connection leak on exception | `services/opportunities_service.py:261-474` | `try/finally` or context manager |

---

## 6 — Low Vulnerabilities (18 Open)

### 🆕 NEW — Discovered This Cycle (Rev 2)

| ID | Title | File | Remediation |
|:---|:------|:-----|:------------|
| **LOW-15** | `eval` with user input in `safe_read()` | `deploy.sh:157-159` | Replace `eval "$var=\"$input\""` with `printf -v "$var" '%s' "$input"`. Risk is low because it requires an interactive operator to type a malicious value at their own prompt — but the pattern is a bad habit. |
| **LOW-16** | Client IP logged unmasked in login throttle | `middleware/login_throttle.py:139` | `client_ip=ip` → `client_ip=mask_ip(ip)` (add `mask_ip()` to `utils/pii_masking.py` — hash or truncate last octet). GDPR Recital 30 explicitly lists IP addresses as personal data. |
| **LOW-17** | Google Fonts CSS without SRI | `frontend/index.html:9-12` | Self-host fonts or add `<link crossorigin integrity="sha384-...">`. CSS-based exfiltration is weak but real (attribute-value selectors). Also: HIGH-23's CSP fix must allowlist `fonts.googleapis.com` + `fonts.gstatic.com` or this breaks. |
| **LOW-18** | Unquoted shell variables | `find_ecs_cluster.sh:29,40-41,63,67-68` | Wrap `$cluster_name`, `$service_name` in double quotes. ECS names are unlikely to contain shell metacharacters, but `set -u` + quoting is cheap. Run `shellcheck` in CI. |

### Previously-Identified Low Findings

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
| LOW-14 | Unmasked recipients in email service stub | `services/email_service.py:40` | `recipients=[mask_email(r) for r in to]` — fix before real SMTP lands |

---

## 7 — SaaS Multi-Tenant Security Checklist

This is a SaaS platform serving multiple client organizations. **All configurations must be tenant-aware.**

| Area | Current State | Required State | Priority |
|:-----|:-------------|:---------------|:--------:|
| Database Row-Level Security | Partial — 7 tables lack `organization_id` (HIGH-28) | ALL tables must have `organization_id NOT NULL` with FK | **P0** |
| API Route Scoping | Analytics now CE-filtered; org details still IDOR (HIGH-16) | ALL data endpoints filter by `context.organization_id` | **P0** |
| AWS Account Isolation | ✅ Cost Explorer filtered by `context.allowed_account_ids` (fail-closed on empty scope) | All AWS API calls scoped; CI tripwire enforces `Filter=` on every `get_cost_and_usage` | ✓ |
| Log PII Policy | Endemic unmasked email (15+ sites) | Per-tenant log-retention + CI tripwire | **P0** |
| Trusted Proxy Depth | ✅ Per-client via `TRUSTED_PROXY_COUNT` env var | `settings.trusted_proxy_count` + CloudFormation Parameter — 0=direct, 1=ALB, 2=CloudFront+ALB | ✓ |
| Login Throttle Pepper | **None** — unsalted SHA-256 (MED-35) | **Per-tenant pepper** from Secrets Manager | P1 |
| Conversation Isolation | ✅ API layer + service layer both enforced | Defense-in-depth: API 403s with audit log; service layer filters/raises for bypassing callers | ✓ |
| Rate Limits | Per-user layer works; still single-instance (HIGH-7) | Per-org configurable limits in Valkey (distributed) | P1 |
| Reports | Auth + org-scope contract at API layer | Enforce at service layer | P1 |
| Audit Logs | `organization_id` nullable | NOT NULL | P1 |
| Field Encryption | Provisioned | Key rotation (90-day) + per-tenant DEKs | P2 |
| Secret Key | Single key for all tenants | Per-tenant JWT signing keys | P2 |
| RBAC Roles | Global | Per-organization custom roles | P2 |
| Cache Keys | Analytics keys carry a scope-hash segment; other namespaces still global | Consistent `org:{org_id}:` or scope-hash prefix across all cache writers | P2 |

---

## 8 — Prioritized Remediation Roadmap

*Phase 1 (immediate-priority) is complete. Roadmap begins at Phase 2.*

### Phase 2 — Within 2 Weeks

| # | Action | Issues Resolved |
|:--|:-------|:---------------|
| 1 | PII log sweep (CI tripwire + mask all MED-28 sites + client IPs) | MED-16, MED-28, MED-30, MED-31, MED-33, LOW-14, **LOW-16** |
| 2 | Login throttle hardening (Unicode NFKC + HMAC pepper) | **MED-34**, **MED-35** |
| 3 | Tenant isolation across remaining services | HIGH-16, HIGH-28 |
| 4 | Dynamic SQL column-name allowlist | HIGH-9 |
| 5 | Container security (non-root users) | HIGH-21, HIGH-22 |
| 6 | Nginx hardening | HIGH-23, LOW-12, **LOW-17** |
| 7 | Infra hardening (Valkey TLS, IAM scope, port binding) | HIGH-24, HIGH-25, HIGH-26 |
| 8 | CSV formula injection (backend + frontend) | MED-20, MED-32 |
| 9 | Deploy script hardening (`mktemp`, `umask 077`, `printf -v`) | **MED-36**, **MED-37**, **LOW-15**, **LOW-18** |

### Phase 3 — Within 1 Month

| # | Action | Issues Resolved |
|:--|:-------|:---------------|
| 1 | Distributed rate limiting (Valkey backend) | HIGH-7, MED-19 |
| 2 | Password policy strengthening (complexity regex) | MED-4 |
| 3 | Race-condition hardening | HIGH-4, HIGH-5, HIGH-10, HIGH-11 |
| 4 | Infra compliance (log retention, WAF) | MED-22, MED-23 |
| 5 | Admin-API input validation | MED-29, HIGH-18 |

### Phase 4 — Ongoing

| # | Action | Issues Resolved |
|:--|:-------|:---------------|
| 1 | All remaining LOW findings | LOW-1 → LOW-13 |
| 2 | Refresh-token rotation | LOW-8 |
| 3 | JWT audience claims | LOW-7 |
| 4 | RBAC cleanup | LOW-11 |
| 5 | `shellcheck` in CI for all `.sh` files | (prevents reintroduction) |

---

*Report generated: 2026-03-06 (Rev 7) | Next audit recommended: 2026-04-06*
*75 open vulnerabilities across 10 audit iterations*
