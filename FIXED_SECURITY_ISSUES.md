# Fixed Security Issues — Historical Record

This document is the permanent audit trail of vulnerabilities that have been identified and **confirmed remediated** in the FinOps AI Cost Intelligence Platform. Entries are retained for compliance (SOC 2, ISO 27001) and regression-test traceability.

For currently **open** issues, see [`SECURITY_AUDIT_REPORT.md`](./SECURITY_AUDIT_REPORT.md).

| | |
|---|---|
| **Total Fixed** | 35 |
| **First Fix Recorded** | 2026-01-31 |
| **Most Recent Fix** | 2026-03-05 |
| **Last Reviewed** | 2026-03-05 |

---

## Summary by Fix Date

| Date | Count | Severity Breakdown |
|:-----|:-----:|:-------------------|
| 2026-01-31 | 18 | 5 CRITICAL, 12 HIGH, 1 LOW |
| 2026-02-08 | 7 | 1 CRITICAL, 4 HIGH, 1 MEDIUM, 1 LOW |
| 2026-03-04 | 7 | 6 CRITICAL, 1 HIGH |
| 2026-03-05 | 3 | 2 CRITICAL, 1 MEDIUM |

---

## Fixed on 2026-03-05 (3 issues)

| # | Issue | Severity | What Was Done |
|:--|:------|:--------:|:--------------|
| F-33 | Unauthenticated Streaming Endpoint with Cross-Tenant Access (CRIT-10) | CRITICAL | Rewrote `backend/api/chat.py` with **centralized ownership helpers** — `require_conversation_owner()` and `resolve_owned_conversation()` — and applied them uniformly across **all four chat endpoints** (`POST /chat`, `POST /stream`, `GET /conversations/{id}`, `DELETE /conversations/{id}`). Changes: (1) `Depends(get_request_context)` now on every endpoint — `/chat`'s IP/anon fallback removed; (2) single ownership-check code path with 404/403 semantics and a unified `unauthorized_conversation_attempt` audit event (differentiated by `action` field); (3) `organization_id` + `allowed_account_ids` always passed to `execute_multi_agent_query`; (4) new threads always owned by `context.user_id`. `user_email` removed from success logs (MED-28 improvement). 45 regression tests in `tests/unit/api/test_chat_security.py` covering helper unit tests, auth-dependency signatures, anon-fallback tripwires, tenant-scope forwarding, ownership IDOR, and audit event shape. |
| F-34 | SSE Stream Data Injection (MED-5) | MEDIUM | `backend/api/chat.py:437` — the streaming error handler now emits a static `'An error occurred processing your request.'` message. Exception details are logged server-side (`chat_stream_error` event) but never written into the SSE frame. Resolved as part of the F-33 rewrite. |
| F-35 | Unauthenticated Reports Endpoints (CRIT-11) | CRITICAL | `backend/api/reports.py` — both `GET /` and `POST /generate` now require `Depends(get_request_context)` (401 on missing auth). Responses carry `organization_id` + `account_ids` to establish the tenant-scoping contract before real implementation lands. Audit events `reports_listed` / `report_generation_requested` log `user_id` + `organization_id` (no `user_email` — MED-28 compliant). 15 tests in `tests/unit/api/test_reports_security.py` including a **router-level tripwire** that asserts every route on the reports router carries the auth dependency — adding a new unauthenticated endpoint will break the test. |

---

## Fixed on 2026-01-31 (18 issues)

| # | Issue | Severity | What Was Done |
|:--|:------|:--------:|:--------------|
| F-1 | Auth bypass via `X-User-Email` header | HIGH | Removed the header-based auth path from `middleware/authentication.py`; JWT is now the only accepted credential source. |
| F-2 | Hardcoded `SECRET_KEY` default in settings | HIGH | Added startup validation at `config/settings.py:275-280` — app crashes if key is unset or shorter than 32 chars. |
| F-3 | SSL `CERT_NONE` on DB connections | HIGH | Updated `services/database.py:100-120` to support `verify-full` mode; certificate verification now enforced. |
| F-4 | CORS wildcard with credentials | HIGH | Replaced `*` with explicit origin allowlist at `main.py:149-156` and `settings.py:610-654`. |
| F-5 | Missing backend security headers | HIGH | Added `middleware/security_headers.py` emitting CSP, HSTS, X-Frame-Options, X-Content-Type-Options. |
| F-6 | SQL injection in athena_query_service (service codes) | HIGH | Introduced `validate_service_code()` allowlist; service-code params now whitelisted before query construction. |
| F-7 | Token revocation — logout did nothing | HIGH | Implemented SHA-256 token blacklist in `cache_service.py`; auth middleware checks blacklist on every request. |
| F-8 | Exposed `ANTHROPIC_AUTH_TOKEN` in repo | HIGH | Removed from git tracking in commit `ac0a3a2`; key rotated. |
| F-9 | Conversation IDOR (CRIT-1) | CRITICAL | Commit `c6a72a1` — chat endpoints now verify conversation ownership before read/write. |
| F-10 | Opportunities IDOR (CRIT-2) | CRITICAL | Commit `99a19f2` — per-user ownership check added to all opportunity CRUD operations. |
| F-11 | Saved Views IDOR (CRIT-3) | CRITICAL | Commit `60e313c` — comprehensive ownership validation on all saved-view endpoints. |
| F-12 | Unauthenticated Analytics (CRIT-4) | CRITICAL | Commit `cd50a7f` — `Depends(require_auth)` added to every analytics route. |
| F-13 | LLM-Generated SQL Injection (CRIT-6) | CRITICAL | Commit `54a5983` — output SQL from the LLM is now validated against an allowlist of tables/columns and dangerous keywords are blocked. |
| F-16 | Internal exception details exposed | HIGH | Replaced 24 instances of `str(e)` in HTTP responses with generic error messages; backed by 33 regression tests. |
| F-17 | Health endpoint information disclosure | HIGH | Stripped public liveness/readiness probes down to minimal payloads (no version, no dependency details); 26 tests. |
| F-18 | AWS credentials via env vars instead of IAM role | HIGH | Migrated all 6 AWS-client files to `create_aws_session()` which uses the ECS task IAM role; verified by AST-based tests. |
| F-19 | Command injection in migration script | CRITICAL | Added `validate_postgres_identifier()` (regex allowlist) and `shlex.quote()` for all shell-interpolated values; 31 tests. *(fix commit landed 2026-02-08 but backdated to the 01-31 batch in prior reports — retained here as-is)* |
| F-20 | SSRF via webhook delivery | HIGH | Enforced HTTPS-only, blocked 8 private/reserved IP ranges, added hostname validation against allowlist; 31 tests. *(same batch note as F-19)* |

> **Note on F-19/F-20:** These two items were historically grouped with the 2026-01-31 cohort in prior audit reports. Their commits actually landed in the 2026-02-08 window but are preserved under 01-31 here to maintain continuity with earlier report versions.

---

## Fixed on 2026-02-08 (7 issues)

| # | Issue | Severity | What Was Done |
|:--|:------|:--------:|:--------------|
| F-14 | Hardcoded RBAC role checks | MEDIUM | Commit `ab4a347` — replaced `if role == "admin"` patterns with a config-driven RBAC service reading permissions from YAML. |
| F-15 | Deprecated `regex` validator | LOW | Replaced Pydantic v1 `regex=` kwarg with v2 `pattern=` at `phase3_enterprise.py:42`. |
| F-21 | Unmasked PII in auth logs | HIGH | Applied `mask_email()` to 6 logger statements in `api/auth.py`; 13 regression tests ensure masking. |
| F-22 | Unauthenticated Athena endpoints | HIGH | Added authentication, rate limiting, and audit logging to all 4 Athena query endpoints; 20 tests. |
| F-24 | Insufficient PBKDF2 iterations | HIGH | Raised iteration count to 600,000 (OWASP 2023+ recommendation) at `api/auth.py:110`; existing hashes upgraded transparently on next login. |
| F-25 | Token blacklist fails open (cache_service layer) | MEDIUM | `cache_service.py:211-249` now returns `True` (revoked) when the cache lookup itself errors — fail-closed at the service layer. |
| F-19/F-20 | *(see 2026-01-31 batch note above)* | — | — |

---

## Fixed on 2026-03-04 (7 issues)

| # | Issue | Severity | What Was Done |
|:--|:------|:--------:|:--------------|
| F-23 | Timing attack in password verification | CRITICAL | Replaced `==` string compare with `secrets.compare_digest()` at `api/auth.py:164` to ensure constant-time comparison. |
| F-26 | SQL Injection in Audit Log Service (CRIT-3) | CRITICAL | `audit_log_service.py:227-277` — `hours` interval now built with parameterized `make_interval(hours => $N)` and `int(hours)` coercion; 15 tests in `test_audit_log_service_security.py`. |
| F-27 | Missing User ORM Model (CRIT-4) | CRITICAL | Added `User` SQLAlchemy class to `database_models.py` with all 15 columns matching migrations 008/011/013; 50 tests in `test_user_model.py`. |
| F-28 | Hardcoded `SECRET_KEY` in task-def.json (CRIT-5) | CRITICAL | Replaced plaintext value with a Secrets Manager ARN reference in `task-def.json`; added a deterministic-pattern regex blocklist in `settings.py`; 17 tests across `test_settings_security.py` and `test_secret_key_not_hardcoded.py`. |
| F-29 | Predictable `SECRET_KEY` in CloudFormation (CRIT-7) | CRITICAL | Removed the deterministic `!Sub` template from `ecs-services.yaml`; added ECS `Secrets` entry pointing at a Secrets Manager ARN; created `AWS::SecretsManager::Secret` with `GenerateSecretString` in `main-stack.yaml`; granted `secretsmanager:GetSecretValue` to the task execution role. |
| F-30 | AWS Infrastructure Secrets Exposed in Repository (CRIT-6) | CRITICAL | Replaced all hardcoded AWS account IDs, RDS/ElastiCache endpoints, IAM role ARNs, ECR URIs, and personal emails with `${PLACEHOLDER}` tokens across `task-def.json`, `cur-bucket-policy.json`, deployment scripts, README docs, and test files; updated `.gitignore`; 27 regression tests in `test_no_infrastructure_secrets.py`. |
| F-31 | Database Password in Plaintext ECS Env Vars (CRIT-8) | CRITICAL | Moved `POSTGRES_PASSWORD` from the `Environment` section to `Secrets` at `ecs-services.yaml:166-167`; removed the assembled `DATABASE_URL` env var; added `DatabasePasswordSecret` resource and IAM policy at `main-stack.yaml:521-530`; updated `task-def.json`; 10 tests in `test_no_plaintext_db_password.py`. |
| F-32 | Unencrypted Sensitive Credentials in Database (CRIT-9) | CRITICAL | Implemented Fernet field-level encryption in `backend/utils/encryption.py` with PBKDF2-HMAC-SHA256 key derivation (600k iterations). Migration 016 adds `role_arn_encrypted`, `external_id_encrypted`, `credentials_encrypted` columns. `multi_account_service.py` encrypts on write and decrypts on read with backward-compatible fallback. `FIELD_ENCRYPTION_KEY` setting added with production-fatal validation at `settings.py:667-676` and `encryption.py:95-101`. 35+ tests across `test_encryption.py`, `test_multi_account_encryption.py`, `test_settings_security.py`. **⚠️ Follow-up open: see [HIGH-33](./SECURITY_AUDIT_REPORT.md#high-33--field_encryption_key-missing-from-infrastructure-configuration) — the key is not yet provisioned in the ECS task definition.** |

---

## Verification Standard

All entries in this document meet the following bar:

1. **Code verified** — the vulnerable pattern no longer exists at the referenced location.
2. **Test coverage** — a regression test exists (test file named in the entry where applicable).
3. **No known bypass** — the fix has been reviewed for workarounds in the same codepath.

If any of these conditions regress, the item is **removed from this file** and **re-opened** in `SECURITY_AUDIT_REPORT.md` with a new ID.

---

*Last reviewed: 2026-03-05 · Maintained alongside SECURITY_AUDIT_REPORT.md*
