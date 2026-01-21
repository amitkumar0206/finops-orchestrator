# Security Audit Report - FinOps Orchestrator

**Date:** 2026-01-21
**Auditor:** Automated Security Scan
**Scope:** Backend Application Security Assessment

---

## Executive Summary

This security audit identified **multiple critical vulnerabilities** that require immediate attention before production deployment. The most severe issues are in SQL injection, authentication bypass, and secrets management.

### Risk Summary

| Severity | Count | Status |
|----------|-------|--------|
| CRITICAL | 8 | Requires immediate fix |
| HIGH | 12 | Fix before production |
| MEDIUM | 15 | Fix within 30 days |
| LOW | 6 | Fix when convenient |

---

## 1. CRITICAL VULNERABILITIES

### 1.1 SQL Injection in Athena Queries

**Severity:** CRITICAL
**CVSS:** 9.8
**Location:** `backend/services/athena_cur_templates.py`

**Issue:** User-controlled values are directly interpolated into SQL queries without parameterization or validation.

**Vulnerable Code Examples:**
```python
# Line 170: Tag value injection
conditions.append(f"resource_tags_user_{normalized_key} = '{tag_values[0]}'")

# Line 220: Database engine LIKE injection
conditions.append(f"LOWER(product_database_engine) LIKE '%{engine}%'")

# Line 271: Instance type injection
instance_filter = f"AND {self._col('product_instance_type')} = '{instance_type}'"
```

**Attack Vector:**
- Input: `prod' OR '1'='1' --`
- Result: SQL WHERE clause bypass, data exfiltration

**Remediation:**
1. Implement strict allowlist validation for all filter parameters
2. Use regex pattern matching: `^[a-zA-Z0-9_-]+$`
3. Create a validation layer for all Athena query inputs

---

### 1.2 Authentication Bypass

**Severity:** CRITICAL
**CVSS:** 9.1
**Location:** `backend/middleware/account_scoping.py:64`

**Issue:** Authentication relies solely on the `X-User-Email` header with no verification.

**Vulnerable Code:**
```python
user_email = request.headers.get('X-User-Email', '').strip()
# No JWT validation, no token verification
```

**Attack Vector:** Any attacker who can set HTTP headers can impersonate any user.

**Remediation:**
1. Implement JWT token-based authentication
2. Validate tokens against a secret key
3. Add token expiration and refresh mechanism
4. Remove header-based user identification

---

### 1.3 Hardcoded Default Secret Key

**Severity:** CRITICAL
**CVSS:** 9.0
**Location:** `backend/config/settings.py:26`

**Issue:** Default secret key is hardcoded and visible in source code.

**Vulnerable Code:**
```python
secret_key: str = Field(default="dev-secret-key-change-in-production", env="SECRET_KEY")
```

**Remediation:**
1. Remove default value entirely
2. Require SECRET_KEY environment variable
3. Add startup validation that fails if not set
4. Use cryptographically secure random key generation

---

### 1.4 SSL Certificate Validation Disabled

**Severity:** CRITICAL
**CVSS:** 8.1
**Location:** `backend/services/database.py:37-38`

**Issue:** SSL certificate validation is completely disabled.

**Vulnerable Code:**
```python
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE
```

**Attack Vector:** Man-in-the-middle attacks on database connections.

**Remediation:**
1. Enable certificate validation: `ssl.CERT_REQUIRED`
2. Configure proper CA certificates
3. Use RDS certificate bundle for AWS deployments

---

## 2. HIGH SEVERITY VULNERABILITIES

### 2.1 CORS Misconfiguration

**Location:** `backend/main.py:116-122`

**Issue:**
```python
allow_methods=["*"],  # Allows all HTTP methods
allow_headers=["*"],  # Allows all headers
allow_credentials=True,  # Enables credential sharing
```

**Remediation:**
- Explicitly list allowed methods: `["GET", "POST", "PATCH", "DELETE"]`
- Explicitly list allowed headers
- Review `allowed_origins` setting

---

### 2.2 Missing Security Headers

**Location:** `backend/main.py`

**Missing Headers:**
- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `Content-Security-Policy`
- `Strict-Transport-Security`
- `X-XSS-Protection: 1; mode=block`

**Remediation:** Add security headers middleware:
```python
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
# Add security headers in middleware
```

---

### 2.3 Health Endpoint Information Disclosure

**Location:** `backend/api/health.py:309-356`

**Issue:** Exposes internal infrastructure details:
- Database names
- S3 bucket locations
- Athena table names

**Remediation:**
- Require authentication for detailed health checks
- Create separate internal vs external health endpoints
- Remove sensitive details from public endpoints

---

### 2.4 SQL Injection in Drill-Down Queries

**Location:** `backend/agents/execute_query_v2.py:251-267`

**Issue:** Values from LLM-generated queries are interpolated without validation.

**Remediation:**
- Validate all extracted values against allowlists
- Implement query result sanitization

---

## 3. MEDIUM SEVERITY VULNERABILITIES

### 3.1 Database Credentials in Logs

**Location:** `backend/services/database.py:46`

**Issue:** SQL echo enabled in development logs all queries including connection strings.

```python
echo=settings.is_development,  # Logs SQL with credentials
```

**Remediation:**
- Never log connection strings
- Use masked connection logging
- Ensure `echo=False` in all environments

---

### 3.2 Exception Stack Traces Exposed

**Location:** Multiple files with `traceback.format_exc()`

**Issue:** Full stack traces logged, potentially exposing:
- File paths
- Environment variables
- Internal function names

**Remediation:**
- Use `sanitize_exception()` from `pii_masking.py` consistently
- Limit traceback depth in logs
- Implement structured error logging

---

### 3.3 No Session Management

**Issue:** No session timeout, token revocation, or logout mechanism.

**Remediation:**
- Implement session service with Redis/Valkey
- Add token expiration (recommended: 15-60 minutes)
- Add refresh token mechanism
- Implement logout/session invalidation

---

### 3.4 Rate Limiting Too Permissive

**Location:** `backend/middleware/rate_limiting.py`

**Issue:** Default 100 requests/minute may be too high.

**Remediation:**
- Review and adjust per-endpoint limits
- Add per-user rate limiting
- Implement progressive rate limiting for abuse

---

## 4. DEPENDENCY VULNERABILITIES

**26 known vulnerabilities found in dependencies:**

| Package | Version | CVE | Fix Version |
|---------|---------|-----|-------------|
| aiohttp | 3.12.15 | CVE-2025-69223+ | 3.13.3 |
| starlette | 0.48.0 | CVE-2025-62727 | 0.49.1 |
| urllib3 | 2.5.0 | CVE-2025-66418+ | 2.6.3 |
| langchain-core | 0.3.76 | CVE-2025-65106 | 0.3.81 |
| langgraph-checkpoint | 2.1.1 | CVE-2025-64439 | 3.0.0 |
| pypdf | 6.0.0 | CVE-2025-62707+ | 6.6.0 |
| filelock | 3.19.1 | CVE-2025-68146 | 3.20.3 |
| marshmallow | 3.26.1 | CVE-2025-68480 | 3.26.2 |
| pip | 25.2 | CVE-2025-8869 | 25.3 |

**Remediation:**
```bash
pip install --upgrade aiohttp>=3.13.3 starlette>=0.49.1 urllib3>=2.6.3 \
    langchain-core>=0.3.81 langgraph-checkpoint>=3.0.0 pypdf>=6.6.0 \
    filelock>=3.20.3 marshmallow>=3.26.2 pip>=25.3
```

---

## 5. LOW SEVERITY ISSUES

### 5.1 Binding to All Interfaces

**Location:** `backend/config/settings.py:22`

**Issue:** Default `host: "0.0.0.0"` binds to all interfaces.

**Status:** Expected for containerized deployments. Ensure proper network policies.

---

### 5.2 OpenAPI Docs in Non-Production

**Location:** `backend/main.py:110-111`

**Status:** Correctly disabled in production. Verify environment detection is reliable.

---

## 6. POSITIVE FINDINGS

The following security measures are correctly implemented:

1. **Account ID Validation** (`request_context.py:92-106`)
   - Whitelist validation with regex
   - Proper denial on invalid input

2. **PII Masking Utilities** (`utils/pii_masking.py`)
   - Email masking
   - Exception sanitization
   - Query masking for logs

3. **Error Response Handling** (`utils/errors.py`)
   - User-friendly error messages
   - Internal details not exposed
   - Proper HTTP status codes

4. **Rate Limiting on Ingest** (`middleware/rate_limiting.py`)
   - 5 requests/hour limit on expensive endpoint

5. **Parameterized Queries in PostgreSQL** (`opportunities_service.py`)
   - Proper use of `%s` placeholders with psycopg2

---

## 7. REMEDIATION PRIORITY

### Immediate (Before Any Production Use)
1. Fix authentication - implement JWT tokens
2. Add SQL input validation for Athena queries
3. Remove hardcoded secret key default
4. Enable SSL certificate validation
5. Update vulnerable dependencies

### Before GA Release
6. Add security headers
7. Fix CORS configuration
8. Protect health endpoints
9. Implement session management
10. Add comprehensive input validation

### Within 30 Days
11. Review and tighten rate limits
12. Implement audit logging
13. Add HTTPS enforcement
14. Review all logging for sensitive data
15. Conduct penetration testing

---

## 8. TESTING RECOMMENDATIONS

### SQL Injection Testing
```bash
# Test tag filter injection
curl -X GET "http://localhost:8000/api/costs?tag_environment=prod' OR '1'='1"

# Test service filter injection
curl -X GET "http://localhost:8000/api/costs?service=AmazonEC2' OR TRUE --"
```

### Authentication Testing
```bash
# Test header spoofing
curl -H "X-User-Email: admin@company.com" http://localhost:8000/api/opportunities
```

### CORS Testing
```javascript
// From different origin
fetch('http://localhost:8000/api/sensitive', {
  method: 'DELETE',
  credentials: 'include'
});
```

---

## 9. COMPLIANCE NOTES

This application should address the following compliance requirements before handling production data:

- **SOC 2:** Authentication, encryption, audit logging
- **GDPR:** PII handling, data retention, right to erasure
- **PCI DSS:** If processing payment data - encryption, access controls
- **HIPAA:** If healthcare data - encryption, audit trails, access controls

---

## 10. CONCLUSION

The FinOps Orchestrator has **critical security vulnerabilities** that must be addressed before production deployment. The most urgent issues are:

1. **SQL Injection** in Athena query generation
2. **Authentication Bypass** via header spoofing
3. **Hardcoded Secrets** in configuration
4. **Disabled SSL Validation** on database connections

The application has a solid foundation with proper error handling, PII masking utilities, and rate limiting, but these strengths are undermined by the critical vulnerabilities identified.

**Recommendation:** Do not deploy to production until CRITICAL and HIGH severity issues are resolved.

---

*Report generated by automated security analysis. Manual penetration testing recommended before production deployment.*
