"""
Tests to ensure no AWS infrastructure secrets are committed to git (CRIT-6).

These tests scan infrastructure config files, scripts, and documentation to verify
that no real AWS account IDs, RDS/ElastiCache endpoints, IAM role ARNs, personal
identifiers, or other infrastructure secrets are present in tracked files.
"""

import json
import re
from pathlib import Path

import pytest

# Repo root: 3 directories up from this test file (tests/unit/infrastructure -> repo root)
REPO_ROOT = Path(__file__).resolve().parents[3]
INFRA_DIR = REPO_ROOT / "infrastructure"
CONFIG_DIR = INFRA_DIR / "config"
SCRIPTS_DIR = REPO_ROOT / "scripts"
TESTS_DIR = REPO_ROOT / "tests"

# Patterns that indicate hardcoded AWS infrastructure secrets
# 12-digit AWS account IDs (not placeholder patterns like 123456789012 or 000000000000)
AWS_ACCOUNT_ID_PATTERN = re.compile(r"\b\d{12}\b")

# Known placeholder account IDs that are acceptable in test data
ALLOWED_ACCOUNT_IDS = frozenset({
    "123456789012",  # AWS documentation example
    "000000000000",  # Obvious placeholder
    "111111111111",  # Obvious test placeholder
    "999999999999",  # Obvious test placeholder
})

# RDS endpoint pattern: *.rds.amazonaws.com
RDS_ENDPOINT_PATTERN = re.compile(r"[\w.-]+\.rds\.amazonaws\.com")

# ElastiCache endpoint pattern: *.cache.amazonaws.com
ELASTICACHE_ENDPOINT_PATTERN = re.compile(r"[\w.-]+\.cache\.amazonaws\.com")

# Personal email pattern in infrastructure files
PERSONAL_EMAIL_PATTERN = re.compile(r"[\w.+-]+@(?:dazn|company)\.com")

# Hardcoded personal filesystem paths
PERSONAL_PATH_PATTERN = re.compile(r"/Users/[A-Z]\w+\.\w+/")


class TestTaskDefJsonNoSecrets:
    """Verify task-def.json uses placeholders instead of real infrastructure values"""

    @pytest.fixture
    def task_def_content(self):
        path = CONFIG_DIR / "task-def.json"
        assert path.exists(), f"task-def.json not found at {path}"
        return path.read_text()

    @pytest.fixture
    def task_def(self, task_def_content):
        return json.loads(task_def_content)

    def test_no_real_aws_account_id(self, task_def_content):
        """task-def.json must not contain real AWS account IDs"""
        for match in AWS_ACCOUNT_ID_PATTERN.finditer(task_def_content):
            account_id = match.group()
            assert account_id in ALLOWED_ACCOUNT_IDS, (
                f"Real AWS account ID '{account_id}' found in task-def.json. "
                f"Use ${{AWS_ACCOUNT_ID}} placeholder instead."
            )

    def test_no_rds_endpoint(self, task_def_content):
        """task-def.json must not contain real RDS endpoints"""
        match = RDS_ENDPOINT_PATTERN.search(task_def_content)
        assert match is None, (
            f"Real RDS endpoint '{match.group()}' found in task-def.json. "
            f"Use ${{RDS_ENDPOINT}} placeholder instead."
        )

    def test_no_elasticache_endpoint(self, task_def_content):
        """task-def.json must not contain real ElastiCache endpoints"""
        match = ELASTICACHE_ENDPOINT_PATTERN.search(task_def_content)
        assert match is None, (
            f"Real ElastiCache endpoint '{match.group()}' found in task-def.json. "
            f"Use ${{ELASTICACHE_ENDPOINT}} placeholder instead."
        )

    def test_no_personal_email(self, task_def_content):
        """task-def.json must not contain personal email addresses"""
        match = PERSONAL_EMAIL_PATTERN.search(task_def_content)
        assert match is None, (
            f"Personal email '{match.group()}' found in task-def.json. "
            f"Use ${{DEPLOYER_ROLE}} placeholder instead."
        )

    def test_postgres_host_uses_placeholder(self, task_def):
        """POSTGRES_HOST must be a placeholder, not a real endpoint"""
        env_vars = task_def["containerDefinitions"][0]["environment"]
        for var in env_vars:
            if var["name"] == "POSTGRES_HOST":
                assert ".rds.amazonaws.com" not in var["value"], (
                    "POSTGRES_HOST contains a real RDS endpoint"
                )
                break

    def test_redis_host_uses_placeholder(self, task_def):
        """REDIS_HOST must be a placeholder, not a real endpoint"""
        env_vars = task_def["containerDefinitions"][0]["environment"]
        for var in env_vars:
            if var["name"] == "REDIS_HOST":
                assert ".cache.amazonaws.com" not in var["value"], (
                    "REDIS_HOST contains a real ElastiCache endpoint"
                )
                break

    def test_database_url_uses_placeholder(self, task_def):
        """DATABASE_URL must not contain real RDS endpoints"""
        env_vars = task_def["containerDefinitions"][0]["environment"]
        for var in env_vars:
            if var["name"] == "DATABASE_URL":
                assert ".rds.amazonaws.com" not in var["value"], (
                    "DATABASE_URL contains a real RDS endpoint"
                )
                break

    def test_ecr_image_uses_placeholder(self, task_def):
        """Container image URI must use placeholder for account ID"""
        image = task_def["containerDefinitions"][0]["image"]
        for match in AWS_ACCOUNT_ID_PATTERN.finditer(image):
            assert match.group() in ALLOWED_ACCOUNT_IDS, (
                f"Real account ID in ECR image URI: {image}"
            )

    def test_task_role_arn_uses_placeholder(self, task_def):
        """taskRoleArn must use placeholder for account ID and role name"""
        arn = task_def.get("taskRoleArn", "")
        for match in AWS_ACCOUNT_ID_PATTERN.finditer(arn):
            assert match.group() in ALLOWED_ACCOUNT_IDS, (
                f"Real account ID in taskRoleArn: {arn}"
            )

    def test_execution_role_arn_uses_placeholder(self, task_def):
        """executionRoleArn must use placeholder for account ID and role name"""
        arn = task_def.get("executionRoleArn", "")
        for match in AWS_ACCOUNT_ID_PATTERN.finditer(arn):
            assert match.group() in ALLOWED_ACCOUNT_IDS, (
                f"Real account ID in executionRoleArn: {arn}"
            )


class TestCurBucketPolicyNoSecrets:
    """Verify cur-bucket-policy.json uses placeholders"""

    @pytest.fixture
    def policy_content(self):
        path = CONFIG_DIR / "cur-bucket-policy.json"
        assert path.exists(), f"cur-bucket-policy.json not found at {path}"
        return path.read_text()

    def test_no_real_aws_account_id(self, policy_content):
        """cur-bucket-policy.json must not contain real AWS account IDs"""
        for match in AWS_ACCOUNT_ID_PATTERN.finditer(policy_content):
            account_id = match.group()
            assert account_id in ALLOWED_ACCOUNT_IDS, (
                f"Real AWS account ID '{account_id}' found in cur-bucket-policy.json. "
                f"Use ${{BILLING_ACCOUNT_ID}} placeholder instead."
            )

    def test_no_hardcoded_bucket_name_with_id(self, policy_content):
        """Bucket names must not contain real numeric identifiers"""
        # Match bucket names that end with a long numeric suffix (actual bucket IDs)
        bucket_id_pattern = re.compile(r"finops-intelligence-platform-\w+-\d{10,}")
        match = bucket_id_pattern.search(policy_content)
        assert match is None, (
            f"Hardcoded bucket name with numeric ID found: '{match.group()}'. "
            f"Use ${{CUR_BUCKET_NAME}} placeholder instead."
        )


class TestScriptsNoSecrets:
    """Verify scripts do not contain hardcoded infrastructure secrets"""

    def test_no_real_account_id_in_deployment_scripts(self):
        """Deployment scripts must not contain hardcoded AWS account IDs"""
        deployment_dir = SCRIPTS_DIR / "deployment"
        if not deployment_dir.exists():
            pytest.skip("scripts/deployment not found")

        for script in deployment_dir.rglob("*.sh"):
            content = script.read_text()
            for match in AWS_ACCOUNT_ID_PATTERN.finditer(content):
                account_id = match.group()
                assert account_id in ALLOWED_ACCOUNT_IDS, (
                    f"Real AWS account ID '{account_id}' found in "
                    f"{script.relative_to(REPO_ROOT)}"
                )

    def test_no_personal_paths_in_scripts(self):
        """Scripts must not contain hardcoded personal filesystem paths"""
        for script in REPO_ROOT.glob("*.sh"):
            content = script.read_text()
            match = PERSONAL_PATH_PATTERN.search(content)
            assert match is None, (
                f"Hardcoded personal path '{match.group()}' found in "
                f"{script.relative_to(REPO_ROOT)}"
            )


class TestTestFilesNoSecrets:
    """Verify test files do not contain hardcoded personal paths or real secrets"""

    def test_no_personal_paths_in_test_files(self):
        """Test files must not contain hardcoded personal filesystem paths"""
        for test_file in TESTS_DIR.rglob("*.py"):
            content = test_file.read_text()
            match = PERSONAL_PATH_PATTERN.search(content)
            assert match is None, (
                f"Hardcoded personal path '{match.group()}' found in "
                f"{test_file.relative_to(REPO_ROOT)}"
            )

    def test_no_real_account_ids_in_test_settings(self):
        """Test settings files must not use real AWS account IDs"""
        test_config_dir = TESTS_DIR / "unit" / "config"
        if not test_config_dir.exists():
            pytest.skip("tests/unit/config not found")

        for test_file in test_config_dir.rglob("*.py"):
            content = test_file.read_text()
            for match in AWS_ACCOUNT_ID_PATTERN.finditer(content):
                account_id = match.group()
                assert account_id in ALLOWED_ACCOUNT_IDS, (
                    f"Real AWS account ID '{account_id}' found in "
                    f"{test_file.relative_to(REPO_ROOT)}. "
                    f"Use a placeholder like '123456789012' instead."
                )


class TestBroadSecretsScan:
    """Broad scan across all infrastructure config files for sensitive data"""

    def test_no_rds_endpoints_in_any_config(self):
        """No infrastructure config file should contain real RDS endpoints"""
        if not INFRA_DIR.exists():
            pytest.skip("Infrastructure directory not found")

        for config_file in list(INFRA_DIR.rglob("*.json")) + list(INFRA_DIR.rglob("*.yaml")) + list(INFRA_DIR.rglob("*.yml")):
            content = config_file.read_text()
            match = RDS_ENDPOINT_PATTERN.search(content)
            assert match is None, (
                f"Real RDS endpoint found in "
                f"{config_file.relative_to(REPO_ROOT)}: '{match.group()}'"
            )

    def test_no_elasticache_endpoints_in_any_config(self):
        """No infrastructure config file should contain real ElastiCache endpoints"""
        if not INFRA_DIR.exists():
            pytest.skip("Infrastructure directory not found")

        for config_file in list(INFRA_DIR.rglob("*.json")) + list(INFRA_DIR.rglob("*.yaml")) + list(INFRA_DIR.rglob("*.yml")):
            content = config_file.read_text()
            match = ELASTICACHE_ENDPOINT_PATTERN.search(content)
            assert match is None, (
                f"Real ElastiCache endpoint found in "
                f"{config_file.relative_to(REPO_ROOT)}: '{match.group()}'"
            )

    def test_no_personal_emails_in_any_config(self):
        """No infrastructure config file should contain personal email addresses"""
        if not INFRA_DIR.exists():
            pytest.skip("Infrastructure directory not found")

        for config_file in list(INFRA_DIR.rglob("*.json")) + list(INFRA_DIR.rglob("*.yaml")) + list(INFRA_DIR.rglob("*.yml")):
            content = config_file.read_text()
            match = PERSONAL_EMAIL_PATTERN.search(content)
            assert match is None, (
                f"Personal email found in "
                f"{config_file.relative_to(REPO_ROOT)}: '{match.group()}'"
            )
