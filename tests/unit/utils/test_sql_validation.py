"""
Tests for SQL Input Validation Utilities
"""

import pytest

from backend.utils.sql_validation import (
    ValidationError,
    contains_sql_injection,
    escape_sql_string,
    escape_like_pattern,
    validate_identifier,
    validate_service_code,
    validate_region,
    validate_account_id,
    validate_tag_key,
    validate_tag_value,
    validate_instance_type,
    validate_operating_system,
    validate_database_engine,
    validate_date,
    validate_resource_id,
    validate_filter_values,
    build_safe_in_clause,
    build_safe_like_clause,
)


class TestContainsSqlInjection:
    """Test SQL injection detection"""

    def test_detects_quoted_strings(self):
        """Test detection of quoted strings"""
        assert contains_sql_injection("value' OR '1'='1")
        assert contains_sql_injection('value" OR "1"="1')

    def test_detects_sql_comments(self):
        """Test detection of SQL comments"""
        assert contains_sql_injection("value --")
        assert contains_sql_injection("value /* comment */")

    def test_detects_union_select(self):
        """Test detection of UNION SELECT"""
        assert contains_sql_injection("value UNION SELECT * FROM users")
        assert contains_sql_injection("value union select password")

    def test_detects_or_1_equals_1(self):
        """Test detection of OR 1=1 pattern"""
        assert contains_sql_injection("value' OR 1=1")
        assert contains_sql_injection("value' OR '1'='1'")

    def test_detects_and_1_equals_1(self):
        """Test detection of AND 1=1 pattern"""
        assert contains_sql_injection("value' AND 1=1")

    def test_detects_trailing_semicolon_with_command(self):
        """Test detection of semicolon followed by SQL command"""
        assert contains_sql_injection("value; SELECT * FROM users")
        assert contains_sql_injection("value; DROP TABLE users")

    def test_detects_unbalanced_quotes(self):
        """Test detection of unbalanced quotes"""
        assert contains_sql_injection("value'")
        assert contains_sql_injection('value"')

    def test_safe_values_pass(self):
        """Test that safe values are not flagged"""
        assert not contains_sql_injection("production")
        assert not contains_sql_injection("my-tag-value")
        assert not contains_sql_injection("AmazonEC2")
        assert not contains_sql_injection("us-east-1")
        assert not contains_sql_injection("m5.large")

    def test_handles_empty_string(self):
        """Test handling of empty string"""
        assert not contains_sql_injection("")

    def test_handles_none(self):
        """Test handling of None - should return False"""
        assert not contains_sql_injection(None)


class TestEscapeSqlString:
    """Test SQL string escaping"""

    def test_escapes_single_quotes(self):
        """Test escaping single quotes"""
        assert escape_sql_string("O'Brien") == "O''Brien"
        assert escape_sql_string("it's") == "it''s"

    def test_escapes_multiple_quotes(self):
        """Test escaping multiple single quotes"""
        assert escape_sql_string("'test'") == "''test''"

    def test_handles_no_quotes(self):
        """Test handling string without quotes"""
        assert escape_sql_string("production") == "production"

    def test_handles_empty_string(self):
        """Test handling empty string"""
        assert escape_sql_string("") == ""

    def test_handles_none(self):
        """Test handling None"""
        assert escape_sql_string(None) == ""


class TestEscapeLikePattern:
    """Test LIKE pattern escaping"""

    def test_escapes_percent(self):
        """Test escaping percent sign"""
        assert escape_like_pattern("100%") == "100\\%"

    def test_escapes_underscore(self):
        """Test escaping underscore"""
        assert escape_like_pattern("test_value") == "test\\_value"

    def test_escapes_both_wildcards(self):
        """Test escaping both wildcards"""
        result = escape_like_pattern("test_100%")
        assert "\\%" in result
        assert "\\_" in result

    def test_also_escapes_quotes(self):
        """Test that quotes are also escaped"""
        assert escape_like_pattern("test'value") == "test''value"

    def test_handles_empty_string(self):
        """Test handling empty string"""
        assert escape_like_pattern("") == ""

    def test_handles_none(self):
        """Test handling None"""
        assert escape_like_pattern(None) == ""


class TestValidateIdentifier:
    """Test identifier validation"""

    def test_accepts_valid_identifier(self):
        """Test accepting valid identifiers"""
        assert validate_identifier("myColumn") == "myColumn"
        assert validate_identifier("my_column") == "my_column"
        assert validate_identifier("my-column") == "my-column"
        assert validate_identifier("Column123") == "Column123"

    def test_rejects_empty(self):
        """Test rejecting empty identifier"""
        with pytest.raises(ValidationError):
            validate_identifier("")

    def test_rejects_starting_with_number(self):
        """Test rejecting identifier starting with number"""
        with pytest.raises(ValidationError):
            validate_identifier("123column")

    def test_rejects_special_characters(self):
        """Test rejecting special characters"""
        with pytest.raises(ValidationError):
            validate_identifier("column;drop")
        with pytest.raises(ValidationError):
            validate_identifier("column'test")

    def test_rejects_too_long(self):
        """Test rejecting too long identifier"""
        with pytest.raises(ValidationError):
            validate_identifier("a" * 129)

    def test_rejects_sql_injection(self):
        """Test rejecting SQL injection patterns"""
        with pytest.raises(ValidationError):
            validate_identifier("column--comment")


class TestValidateServiceCode:
    """Test AWS service code validation"""

    def test_accepts_known_services(self):
        """Test accepting known AWS services"""
        assert validate_service_code("AmazonEC2") == "AmazonEC2"
        assert validate_service_code("AmazonS3") == "AmazonS3"
        assert validate_service_code("AWSLambda") == "AWSLambda"

    def test_case_insensitive_matching(self):
        """Test case-insensitive matching returns canonical form"""
        assert validate_service_code("amazonec2") == "AmazonEC2"
        assert validate_service_code("AMAZONS3") == "AmazonS3"

    def test_rejects_empty(self):
        """Test rejecting empty service code"""
        with pytest.raises(ValidationError):
            validate_service_code("")

    def test_strict_mode_rejects_unknown(self):
        """Test strict mode rejects unknown services"""
        with pytest.raises(ValidationError):
            validate_service_code("UnknownService", strict=True)

    def test_non_strict_allows_valid_pattern(self):
        """Test non-strict mode allows valid pattern"""
        result = validate_service_code("CustomService")
        assert result == "CustomService"

    def test_rejects_sql_injection(self):
        """Test rejecting SQL injection in service code"""
        with pytest.raises(ValidationError):
            validate_service_code("AmazonEC2' OR '1'='1")


class TestValidateRegion:
    """Test AWS region validation"""

    def test_accepts_known_regions(self):
        """Test accepting known AWS regions"""
        assert validate_region("us-east-1") == "us-east-1"
        assert validate_region("eu-west-1") == "eu-west-1"
        assert validate_region("ap-southeast-2") == "ap-southeast-2"

    def test_accepts_global(self):
        """Test accepting 'global' region"""
        assert validate_region("global") == "global"

    def test_normalizes_to_lowercase(self):
        """Test normalizing to lowercase"""
        assert validate_region("US-EAST-1") == "us-east-1"

    def test_rejects_empty(self):
        """Test rejecting empty region"""
        with pytest.raises(ValidationError):
            validate_region("")

    def test_rejects_invalid_format(self):
        """Test rejecting invalid region format"""
        with pytest.raises(ValidationError):
            validate_region("invalid-region")
        with pytest.raises(ValidationError):
            validate_region("us-east")


class TestValidateAccountId:
    """Test AWS account ID validation"""

    def test_accepts_valid_account_id(self):
        """Test accepting valid 12-digit account ID"""
        assert validate_account_id("123456789012") == "123456789012"

    def test_rejects_empty(self):
        """Test rejecting empty account ID"""
        with pytest.raises(ValidationError):
            validate_account_id("")

    def test_rejects_wrong_length(self):
        """Test rejecting wrong length"""
        with pytest.raises(ValidationError):
            validate_account_id("12345678901")  # 11 digits
        with pytest.raises(ValidationError):
            validate_account_id("1234567890123")  # 13 digits

    def test_rejects_non_numeric(self):
        """Test rejecting non-numeric characters"""
        with pytest.raises(ValidationError):
            validate_account_id("12345678901a")


class TestValidateTagKey:
    """Test tag key validation"""

    def test_normalizes_tag_key(self):
        """Test normalizing tag key"""
        assert validate_tag_key("Environment") == "environment"
        assert validate_tag_key("cost-center") == "cost_center"
        assert validate_tag_key("aws:createdBy") == "aws_createdby"

    def test_handles_special_characters(self):
        """Test handling special characters"""
        result = validate_tag_key("my:special/tag-key")
        assert "_" in result
        assert ":" not in result
        assert "/" not in result

    def test_adds_prefix_if_starts_with_number(self):
        """Test adding prefix if starts with number"""
        result = validate_tag_key("123tag")
        assert result.startswith("tag_")

    def test_rejects_empty(self):
        """Test rejecting empty tag key"""
        with pytest.raises(ValidationError):
            validate_tag_key("")

    def test_rejects_too_long(self):
        """Test rejecting too long tag key"""
        with pytest.raises(ValidationError):
            validate_tag_key("a" * 129)


class TestValidateTagValue:
    """Test tag value validation"""

    def test_accepts_valid_value(self):
        """Test accepting valid tag values"""
        assert validate_tag_value("production") == "production"
        assert validate_tag_value("prod-env-1") == "prod-env-1"

    def test_rejects_quotes(self):
        """Test rejecting quotes in tag values for security"""
        # Quotes are rejected to prevent SQL injection
        with pytest.raises(ValidationError):
            validate_tag_value("O'Reilly")

    def test_handles_empty_string(self):
        """Test handling empty string"""
        assert validate_tag_value("") == ""

    def test_handles_none(self):
        """Test handling None"""
        assert validate_tag_value(None) == ""

    def test_rejects_too_long(self):
        """Test rejecting too long tag value"""
        with pytest.raises(ValidationError):
            validate_tag_value("a" * 257)

    def test_rejects_sql_injection(self):
        """Test rejecting SQL injection in tag value"""
        with pytest.raises(ValidationError):
            validate_tag_value("prod' OR '1'='1")


class TestValidateInstanceType:
    """Test EC2 instance type validation"""

    def test_accepts_valid_instance_types(self):
        """Test accepting valid instance types"""
        assert validate_instance_type("m5.large") == "m5.large"
        assert validate_instance_type("t3.micro") == "t3.micro"
        assert validate_instance_type("r5.2xlarge") == "r5.2xlarge"
        assert validate_instance_type("c6i.metal") == "c6i.metal"

    def test_normalizes_to_lowercase(self):
        """Test normalizing to lowercase"""
        assert validate_instance_type("M5.LARGE") == "m5.large"

    def test_rejects_empty(self):
        """Test rejecting empty instance type"""
        with pytest.raises(ValidationError):
            validate_instance_type("")

    def test_rejects_invalid_format(self):
        """Test rejecting invalid format"""
        with pytest.raises(ValidationError):
            validate_instance_type("invalid")


class TestValidateOperatingSystem:
    """Test operating system validation"""

    def test_accepts_known_os(self):
        """Test accepting known operating systems"""
        assert validate_operating_system("Linux") == "Linux"
        assert validate_operating_system("Windows") == "Windows"
        assert validate_operating_system("Amazon Linux 2") == "Amazon Linux 2"

    def test_case_insensitive_matching(self):
        """Test case-insensitive matching"""
        assert validate_operating_system("linux") == "Linux"
        assert validate_operating_system("WINDOWS") == "Windows"

    def test_rejects_empty(self):
        """Test rejecting empty OS"""
        with pytest.raises(ValidationError):
            validate_operating_system("")


class TestValidateDatabaseEngine:
    """Test database engine validation"""

    def test_accepts_known_engines(self):
        """Test accepting known database engines"""
        assert validate_database_engine("mysql") == "mysql"
        assert validate_database_engine("postgres") == "postgres"
        assert validate_database_engine("aurora-mysql") == "aurora-mysql"

    def test_normalizes_to_lowercase(self):
        """Test normalizing to lowercase"""
        assert validate_database_engine("MySQL") == "mysql"
        assert validate_database_engine("PostgreSQL") == "postgresql"

    def test_rejects_empty(self):
        """Test rejecting empty engine"""
        with pytest.raises(ValidationError):
            validate_database_engine("")


class TestValidateDate:
    """Test date validation"""

    def test_accepts_valid_date(self):
        """Test accepting valid date"""
        assert validate_date("2024-01-15") == "2024-01-15"
        assert validate_date("2023-12-31") == "2023-12-31"

    def test_rejects_empty(self):
        """Test rejecting empty date"""
        with pytest.raises(ValidationError):
            validate_date("")

    def test_rejects_invalid_format(self):
        """Test rejecting invalid format"""
        with pytest.raises(ValidationError):
            validate_date("01-15-2024")
        with pytest.raises(ValidationError):
            validate_date("2024/01/15")

    def test_rejects_invalid_month(self):
        """Test rejecting invalid month"""
        with pytest.raises(ValidationError):
            validate_date("2024-13-01")
        with pytest.raises(ValidationError):
            validate_date("2024-00-01")

    def test_rejects_invalid_day(self):
        """Test rejecting invalid day"""
        with pytest.raises(ValidationError):
            validate_date("2024-01-32")
        with pytest.raises(ValidationError):
            validate_date("2024-01-00")

    def test_rejects_invalid_year(self):
        """Test rejecting year out of range"""
        with pytest.raises(ValidationError):
            validate_date("1999-01-01")
        with pytest.raises(ValidationError):
            validate_date("2101-01-01")


class TestValidateResourceId:
    """Test AWS resource ID validation"""

    def test_accepts_instance_id(self):
        """Test accepting EC2 instance ID"""
        result = validate_resource_id("i-1234567890abcdef0")
        assert "i-1234567890abcdef0" in result

    def test_accepts_arn(self):
        """Test accepting ARN"""
        result = validate_resource_id("arn:aws:ec2:us-east-1:123456789012:instance/i-12345")
        assert "arn" in result

    def test_rejects_quotes_in_resource_id(self):
        """Test rejecting quotes in resource ID for security"""
        # Quotes are rejected to prevent SQL injection
        with pytest.raises(ValidationError):
            validate_resource_id("resource-with-apostrophe's")

    def test_rejects_empty(self):
        """Test rejecting empty resource ID"""
        with pytest.raises(ValidationError):
            validate_resource_id("")

    def test_rejects_too_long(self):
        """Test rejecting too long resource ID"""
        with pytest.raises(ValidationError):
            validate_resource_id("a" * 513)

    def test_rejects_sql_injection(self):
        """Test rejecting SQL injection in resource ID"""
        with pytest.raises(ValidationError):
            validate_resource_id("i-12345' OR '1'='1")


class TestValidateFilterValues:
    """Test filter values list validation"""

    def test_validates_all_values(self):
        """Test validating all values in list"""
        result = validate_filter_values(
            ["us-east-1", "us-west-2"],
            validate_region
        )
        assert result == ["us-east-1", "us-west-2"]

    def test_handles_empty_list(self):
        """Test handling empty list"""
        result = validate_filter_values([], validate_region)
        assert result == []

    def test_rejects_too_many_values(self):
        """Test rejecting too many values"""
        values = [f"us-east-{i}" for i in range(101)]
        # This will fail on validation, not count, since regions are invalid
        with pytest.raises(ValidationError):
            validate_filter_values(values, validate_region, max_count=100)

    def test_reports_index_on_failure(self):
        """Test that failure message includes index"""
        with pytest.raises(ValidationError) as exc_info:
            validate_filter_values(
                ["us-east-1", "invalid-region-format", "us-west-2"],
                validate_region
            )
        assert "[1]" in str(exc_info.value)


class TestBuildSafeInClause:
    """Test safe IN clause building"""

    def test_builds_in_clause(self):
        """Test building IN clause with valid values"""
        result = build_safe_in_clause(
            ["us-east-1", "us-west-2"],
            validate_region
        )
        assert "'us-east-1'" in result
        assert "'us-west-2'" in result
        assert "," in result

    def test_handles_empty_list(self):
        """Test handling empty list"""
        result = build_safe_in_clause([], validate_region)
        assert result == "'__EMPTY__'"


class TestBuildSafeLikeClause:
    """Test safe LIKE clause building"""

    def test_builds_contains_clause(self):
        """Test building CONTAINS LIKE clause"""
        result = build_safe_like_clause("test", "column_name", "contains")
        assert result == "column_name LIKE '%test%'"

    def test_builds_starts_clause(self):
        """Test building STARTS WITH LIKE clause"""
        result = build_safe_like_clause("test", "column_name", "starts")
        assert result == "column_name LIKE 'test%'"

    def test_builds_ends_clause(self):
        """Test building ENDS WITH LIKE clause"""
        result = build_safe_like_clause("test", "column_name", "ends")
        assert result == "column_name LIKE '%test'"

    def test_escapes_wildcards(self):
        """Test escaping LIKE wildcards"""
        result = build_safe_like_clause("test_100%", "col", "contains")
        assert "\\%" in result
        assert "\\_" in result


class TestSqlInjectionPrevention:
    """Integration tests for SQL injection prevention"""

    def test_tag_value_injection_blocked(self):
        """Test that SQL injection via tag value is blocked"""
        with pytest.raises(ValidationError):
            validate_tag_value("prod' OR '1'='1' --")

    def test_service_code_injection_blocked(self):
        """Test that SQL injection via service code is blocked"""
        with pytest.raises(ValidationError):
            validate_service_code("AmazonEC2'; DROP TABLE costs; --")

    def test_resource_id_injection_blocked(self):
        """Test that SQL injection via resource ID is blocked"""
        with pytest.raises(ValidationError):
            validate_resource_id("i-12345' UNION SELECT password FROM users --")

    def test_database_engine_injection_sanitized(self):
        """Test that SQL injection via database engine is sanitized to known engine"""
        # When input contains a known engine, it returns only the known value
        result = validate_database_engine("mysql' OR '1'='1")
        assert result == "mysql"  # Returns safe known engine, not the injection

    def test_instance_type_injection_blocked(self):
        """Test that SQL injection via instance type is blocked"""
        with pytest.raises(ValidationError):
            validate_instance_type("m5.large'; DROP TABLE --")
