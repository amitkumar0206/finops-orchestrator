"""
CRIT-12 Regression Tests — SQL Injection via Date/Limit Parameters in Athena Queries

Athena does NOT support parameterized queries. Every value that reaches an
f-string MUST be provably safe before interpolation. These tests pin the
validation behaviour across all three affected modules so the vulnerable
pattern cannot silently return.

Covers:
  1. athena_query_service.py  — 6 _generate_*_query methods + module helpers
  2. multi_account_service.py — _build_aggregation_query (direct HTTP attack path
                                 via GET /accounts/aggregate-costs with raw str params)
  3. athena_cur_templates.py  — _build_partition_filter choke-point + the
                                 s3_spike_analysis 4-param gap

See FIXED_SECURITY_ISSUES.md F-36 for the audit entry.
"""

import pytest
from datetime import date

from backend.utils.sql_validation import ValidationError


# ─────────────────────────────────────────────────────────────────────────────
# Injection payloads — each one, if it survived to the f-string, would alter
# query semantics. The regex ^\d{4}-\d{2}-\d{2}$ rejects all of them.
# ─────────────────────────────────────────────────────────────────────────────
SQL_INJECTION_DATES = [
    "2025-01-01' OR '1'='1",         # classic boolean-based
    "2025-01-01'; DROP TABLE x; --", # stacked query
    "2025-01-01' UNION SELECT * FROM information_schema.tables --",
    "'; SELECT * FROM cur_table; --",
    "2025-01-01\\' OR \\'1\\'=\\'1", # escaped-quote bypass attempt
    "2025-13-45",                     # structurally valid regex-wise but month>12
    "not-a-date",
    "",
    "2025/01/01",                     # wrong separator
    "01-01-2025",                     # wrong order
]

SQL_INJECTION_LIMITS = [
    "10; DROP TABLE x",
    "10 OR 1=1",
    "0x0a",
    "1e9",        # float syntax — int() accepts but bounds-check rejects
    -1,
    0,
    99999999,     # above MAX_QUERY_LIMIT
    "abc",
    None,
]

VALID_TIME_RANGE = {"start_date": "2025-01-01", "end_date": "2025-01-31"}


# ═════════════════════════════════════════════════════════════════════════════
# PART 1 — athena_query_service.py  (primary CRIT-12 target)
# ═════════════════════════════════════════════════════════════════════════════

class TestValidateDateParam:
    """Module-level _validate_date_param helper."""

    def test_accepts_iso_string(self):
        from backend.services.athena_query_service import _validate_date_param
        assert _validate_date_param("2025-01-15", "start_date") == "2025-01-15"

    def test_accepts_date_object_via_str_coercion(self):
        """
        API layer (api/athena_queries.py:73-75) calls date.fromisoformat() and
        passes the resulting date object. str(date(2025,1,15)) == '2025-01-15',
        and validate_date() calls str(value).strip() internally — so the service
        layer transparently handles both strings AND date objects. This is the
        defense-in-depth contract: both layers validate independently.
        """
        from backend.services.athena_query_service import _validate_date_param
        result = _validate_date_param(date(2025, 1, 15), "start_date")
        assert result == "2025-01-15"

    def test_rejects_none_with_field_name_in_error(self):
        from backend.services.athena_query_service import _validate_date_param
        with pytest.raises(ValidationError, match="start_date is required"):
            _validate_date_param(None, "start_date")

    @pytest.mark.parametrize("payload", SQL_INJECTION_DATES)
    def test_rejects_injection_payloads(self, payload):
        from backend.services.athena_query_service import _validate_date_param
        with pytest.raises(ValidationError):
            _validate_date_param(payload, "start_date")


class TestValidateLimitParam:
    """Module-level _validate_limit_param helper."""

    def test_accepts_valid_int(self):
        from backend.services.athena_query_service import _validate_limit_param
        assert _validate_limit_param(5) == 5

    def test_accepts_numeric_string(self):
        from backend.services.athena_query_service import _validate_limit_param
        assert _validate_limit_param("5") == 5

    def test_respects_max_query_limit_bound(self):
        from backend.services.athena_query_service import (
            _validate_limit_param,
            MAX_QUERY_LIMIT,
        )
        assert _validate_limit_param(MAX_QUERY_LIMIT) == MAX_QUERY_LIMIT
        with pytest.raises(ValidationError):
            _validate_limit_param(MAX_QUERY_LIMIT + 1)

    @pytest.mark.parametrize("payload", SQL_INJECTION_LIMITS)
    def test_rejects_injection_and_out_of_bounds(self, payload):
        from backend.services.athena_query_service import _validate_limit_param
        with pytest.raises(ValidationError):
            _validate_limit_param(payload)


# ── Service instance fixture ─────────────────────────────────────────────────
# __init__ calls create_aws_session() → boto3, which fails without credentials.
# The _generate_*_query methods are pure string builders that never touch
# self.athena_client, so we bypass __init__ entirely.

@pytest.fixture
def query_service():
    from backend.services.athena_query_service import AthenaQueryService
    return AthenaQueryService.__new__(AthenaQueryService)


# All 6 _generate_*_query methods. _generate_default_query delegates to
# _generate_top_services_query so it is covered implicitly.
QUERY_METHODS = [
    "_generate_top_services_query",
    "_generate_daily_costs_query",
    "_generate_service_breakdown_query",
    "_generate_region_breakdown_query",
    "_generate_account_breakdown_query",
    "_generate_comprehensive_query",
]


class TestQueryMethodsRejectDateInjection:
    """Every _generate_*_query method must reject malformed dates BEFORE f-string."""

    @pytest.mark.parametrize("method_name", QUERY_METHODS)
    @pytest.mark.parametrize("payload", SQL_INJECTION_DATES)
    def test_rejects_malformed_start_date(self, query_service, method_name, payload):
        method = getattr(query_service, method_name)
        with pytest.raises(ValidationError):
            method({"start_date": payload, "end_date": "2025-01-31"})

    @pytest.mark.parametrize("method_name", QUERY_METHODS)
    @pytest.mark.parametrize("payload", SQL_INJECTION_DATES)
    def test_rejects_malformed_end_date(self, query_service, method_name, payload):
        method = getattr(query_service, method_name)
        with pytest.raises(ValidationError):
            method({"start_date": "2025-01-01", "end_date": payload})

    @pytest.mark.parametrize("method_name", QUERY_METHODS)
    def test_rejects_missing_dates(self, query_service, method_name):
        method = getattr(query_service, method_name)
        with pytest.raises(ValidationError):
            method({})  # no start_date, no end_date


class TestQueryMethodsHappyPath:
    """Valid dates produce valid SQL with the dates interpolated exactly once each."""

    @pytest.mark.parametrize("method_name", QUERY_METHODS)
    def test_valid_string_dates(self, query_service, method_name):
        method = getattr(query_service, method_name)
        sql = method(VALID_TIME_RANGE)
        assert "DATE '2025-01-01'" in sql
        assert "DATE '2025-01-31'" in sql
        # No injection artefacts survived
        assert "OR '1'='1" not in sql
        assert "DROP" not in sql.upper() or "DROP" in method_name.upper()

    @pytest.mark.parametrize("method_name", QUERY_METHODS)
    def test_valid_date_objects(self, query_service, method_name):
        """API layer passes date objects — service layer must accept them."""
        method = getattr(query_service, method_name)
        sql = method({"start_date": date(2025, 1, 1), "end_date": date(2025, 1, 31)})
        assert "DATE '2025-01-01'" in sql
        assert "DATE '2025-01-31'" in sql


class TestTopServicesLimit:
    """Only _generate_top_services_query accepts a limit param — verify coercion."""

    def test_valid_limit_interpolated(self, query_service):
        sql = query_service._generate_top_services_query(VALID_TIME_RANGE, limit=7)
        assert "LIMIT 7" in sql

    @pytest.mark.parametrize("payload", SQL_INJECTION_LIMITS)
    def test_rejects_malformed_limit(self, query_service, payload):
        with pytest.raises(ValidationError):
            query_service._generate_top_services_query(VALID_TIME_RANGE, limit=payload)

    def test_default_query_delegates_and_inherits_validation(self, query_service):
        """_generate_default_query → _generate_top_services_query(time_range, 10)"""
        with pytest.raises(ValidationError):
            query_service._generate_default_query({"start_date": "'; DROP", "end_date": "x"})


# ═════════════════════════════════════════════════════════════════════════════
# PART 2 — multi_account_service.py  (CRIT-12 sibling, MORE exploitable)
#
# api/phase3_enterprise.py:280 declares start_date/end_date as raw ``str`` query
# params with ZERO upstream validation. This is a direct HTTP → f-string path.
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def multi_account_service():
    from backend.services.multi_account_service import MultiAccountService
    # __init__ sets up DB connections; _build_aggregation_query is pure.
    return MultiAccountService.__new__(MultiAccountService)


VALID_AGG_ARGS = dict(
    database="cost_db",
    table="cur_table",
    start_date="2025-01-01",
    end_date="2025-01-31",
    group_by="service",
    account_id="123456789012",
)


class TestBuildAggregationQuery:

    def test_happy_path_produces_expected_sql(self, multi_account_service):
        sql = multi_account_service._build_aggregation_query(**VALID_AGG_ARGS)
        assert "cost_db.cur_table" in sql
        assert "DATE '2025-01-01'" in sql
        assert "DATE '2025-01-31'" in sql
        assert "OR '1'='1" not in sql

    @pytest.mark.parametrize("payload", SQL_INJECTION_DATES)
    def test_rejects_malformed_start_date(self, multi_account_service, payload):
        args = {**VALID_AGG_ARGS, "start_date": payload}
        with pytest.raises(ValidationError):
            multi_account_service._build_aggregation_query(**args)

    @pytest.mark.parametrize("payload", SQL_INJECTION_DATES)
    def test_rejects_malformed_end_date(self, multi_account_service, payload):
        args = {**VALID_AGG_ARGS, "end_date": payload}
        with pytest.raises(ValidationError):
            multi_account_service._build_aggregation_query(**args)

    @pytest.mark.parametrize("payload", [
        "123456789012' OR '1'='1",
        "'; DROP TABLE x; --",
        "not-an-account-id",
        "12345",        # too short
        "1234567890123", # too long
    ])
    def test_rejects_malformed_account_id(self, multi_account_service, payload):
        """account_id is f-stringed into SELECT clause — must be exactly 12 digits."""
        args = {**VALID_AGG_ARGS, "account_id": payload}
        with pytest.raises(ValidationError):
            multi_account_service._build_aggregation_query(**args)

    @pytest.mark.parametrize("field,payload", [
        ("database", "cost_db; DROP TABLE x"),
        ("database", "cost_db' OR '1'='1"),
        ("table", "cur_table; DROP TABLE x"),
        ("table", "cur_table WHERE 1=1 --"),
    ])
    def test_rejects_malformed_identifiers(self, multi_account_service, field, payload):
        """
        database/table come from the aws_accounts row, which is populated by
        register_account() from caller input. Even stored values must be validated
        before FROM-clause interpolation.
        """
        args = {**VALID_AGG_ARGS, field: payload}
        with pytest.raises(ValidationError):
            multi_account_service._build_aggregation_query(**args)


# ═════════════════════════════════════════════════════════════════════════════
# PART 3 — athena_cur_templates.py  (CRIT-12 sibling, choke-point pattern)
#
# ~20 query methods all call _build_partition_filter(start_date, end_date) FIRST,
# before any f-string. Validating at the choke-point covers every caller — except
# s3_spike_analysis, which takes 4 date params and only min()/max() reached it.
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def cur_templates():
    from backend.services.athena_cur_templates import AthenaCURTemplates
    return AthenaCURTemplates(database="cost_db", table="cur_table")


class TestPartitionFilterChokePoint:
    """_build_partition_filter is the universal validation gate."""

    def test_valid_dates_pass(self, cur_templates):
        result, years, months = cur_templates._build_partition_filter("2025-01-01", "2025-01-31")
        assert result == "1=1"

    def test_accepts_date_objects(self, cur_templates):
        result, _, _ = cur_templates._build_partition_filter(date(2025, 1, 1), date(2025, 1, 31))
        assert result == "1=1"

    @pytest.mark.parametrize("payload", SQL_INJECTION_DATES)
    def test_rejects_malformed_start(self, cur_templates, payload):
        with pytest.raises(ValidationError):
            cur_templates._build_partition_filter(payload, "2025-01-31")

    @pytest.mark.parametrize("payload", SQL_INJECTION_DATES)
    def test_rejects_malformed_end(self, cur_templates, payload):
        with pytest.raises(ValidationError):
            cur_templates._build_partition_filter("2025-01-01", payload)


class TestChokePointCoversDownstreamMethods:
    """
    Sample of query methods that rely on the choke-point. If any of these
    stop routing through _build_partition_filter, the test will still fail
    because validate_date() would never fire.
    """

    @pytest.mark.parametrize("payload", [
        "2025-01-01' OR '1'='1",
        "'; DROP TABLE x; --",
    ])
    def test_ec2_cost_by_instance_type_rejects_injection(self, cur_templates, payload):
        with pytest.raises(ValidationError):
            cur_templates.ec2_cost_by_instance_type(payload, "2025-01-31")

    @pytest.mark.parametrize("payload", [
        "2025-01-01' OR '1'='1",
        "'; DROP TABLE x; --",
    ])
    def test_top_n_services_rejects_injection(self, cur_templates, payload):
        with pytest.raises(ValidationError):
            cur_templates.top_n_services(payload, "2025-01-31")

    def test_ec2_cost_happy_path(self, cur_templates):
        sql = cur_templates.ec2_cost_by_instance_type("2025-01-01", "2025-01-31")
        assert "2025-01-01" in sql
        assert "OR '1'='1" not in sql


class TestS3SpikeAnalysisGap:
    """
    THE GAP: s3_spike_analysis takes FOUR date params (aug_start, aug_end,
    sep_start, sep_end). Before the fix, only min(aug_start, sep_start) and
    max(aug_end, sep_end) reached _build_partition_filter — but {sep_start}
    and {aug_start} are f-stringed DIRECTLY at lines ~504-507.

    Exploit scenario: aug_start="2025-08-01" (valid, lexicographically smaller),
    sep_start="2025-09-01' OR '1'='1". min() returns the valid aug_start, the
    choke-point passes, and {sep_start} is interpolated raw.

    Fix: validate all 4 params individually BEFORE min()/max().
    """

    def test_happy_path_all_four_valid(self, cur_templates):
        sql = cur_templates.s3_spike_analysis(
            aug_start="2025-08-01", aug_end="2025-08-31",
            sep_start="2025-09-01", sep_end="2025-09-30",
        )
        assert "DATE '2025-08-01'" in sql
        assert "DATE '2025-09-01'" in sql
        assert "OR '1'='1" not in sql
        assert "DROP" not in sql.upper()

    def test_the_gap_malformed_sep_start_with_valid_aug_start(self, cur_templates):
        """
        This is the exact bypass case. aug_start sorts BEFORE the payload
        (lexicographic '2025-08-01' < '2025-09-01...'), so min() would pick
        aug_start, the choke-point would see only valid dates, and sep_start
        would reach the f-string raw. The per-param validation closes this.
        """
        with pytest.raises(ValidationError):
            cur_templates.s3_spike_analysis(
                aug_start="2025-08-01",  # valid, min() picks this
                aug_end="2025-08-31",
                sep_start="2025-09-01' OR '1'='1",  # bypasses choke-point via min()
                sep_end="2025-09-30",
            )

    def test_the_gap_malformed_aug_end_with_valid_sep_end(self, cur_templates):
        """Mirror case for max(): sep_end > aug_end payload, so max() picks sep_end."""
        with pytest.raises(ValidationError):
            cur_templates.s3_spike_analysis(
                aug_start="2025-08-01",
                aug_end="2025-08-31'; DROP TABLE x; --",  # bypasses choke-point via max()
                sep_start="2025-09-01",
                sep_end="2025-09-30",  # valid, max() picks this
            )

    @pytest.mark.parametrize("bad_param", ["aug_start", "aug_end", "sep_start", "sep_end"])
    def test_each_param_individually_validated(self, cur_templates, bad_param):
        params = dict(
            aug_start="2025-08-01", aug_end="2025-08-31",
            sep_start="2025-09-01", sep_end="2025-09-30",
        )
        params[bad_param] = "'; DROP TABLE x; --"
        with pytest.raises(ValidationError):
            cur_templates.s3_spike_analysis(**params)


# ═════════════════════════════════════════════════════════════════════════════
# PART 4 — Tripwire: no raw f-string date interpolation can be reintroduced
#          without validation being visible in the source.
# ═════════════════════════════════════════════════════════════════════════════

class TestNoRegressionTripwire:
    """
    Source-level assertions that catch accidental removal of the validation
    calls. These are intentionally simple string checks — they will break
    loudly if someone deletes a validate_date() call during a refactor.
    """

    def test_athena_query_service_imports_validate_date(self):
        import backend.services.athena_query_service as mod
        import inspect
        src = inspect.getsource(mod)
        assert "from backend.utils.sql_validation import" in src
        assert "validate_date" in src
        assert "_validate_date_param" in src
        assert "_validate_limit_param" in src

    def test_multi_account_service_imports_validators(self):
        import backend.services.multi_account_service as mod
        import inspect
        src = inspect.getsource(mod)
        assert "validate_date" in src
        assert "validate_account_id" in src
        assert "validate_identifier" in src

    def test_cur_templates_choke_point_calls_validate_date(self):
        from backend.services.athena_cur_templates import AthenaCURTemplates
        import inspect
        src = inspect.getsource(AthenaCURTemplates._build_partition_filter)
        assert "validate_date(start_date)" in src
        assert "validate_date(end_date)" in src

    def test_s3_spike_analysis_validates_all_four_params(self):
        from backend.services.athena_cur_templates import AthenaCURTemplates
        import inspect
        src = inspect.getsource(AthenaCURTemplates.s3_spike_analysis)
        # All four params must be validated before min()/max()
        assert "validate_date(aug_start)" in src
        assert "validate_date(aug_end)" in src
        assert "validate_date(sep_start)" in src
        assert "validate_date(sep_end)" in src
        # And the validation must precede the f-string
        validate_pos = src.index("validate_date(aug_start)")
        fstring_pos = src.index('f"""')
        assert validate_pos < fstring_pos, "validation must run BEFORE f-string"
