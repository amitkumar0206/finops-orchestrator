"""
Tests to ensure SECRET_KEY is never hardcoded in infrastructure config files.

These tests scan infrastructure config files to verify that:
1. task-def.json does not contain plaintext SECRET_KEY values
2. CloudFormation templates use Secrets Manager instead of Environment for SECRET_KEY
3. No deterministic SECRET_KEY patterns exist in any config file
"""

import json
import re
from pathlib import Path

import pytest

# Repo root: 3 directories up from this test file (tests/unit/infrastructure -> repo root)
REPO_ROOT = Path(__file__).resolve().parents[3]
INFRA_DIR = REPO_ROOT / "infrastructure"
CF_DIR = INFRA_DIR / "cloudformation"
CONFIG_DIR = INFRA_DIR / "config"

# Pattern matching the old deterministic format: <anything>-<10-14 digit account>-secret-key-v<N>
DETERMINISTIC_PATTERN = re.compile(r"[\w-]+-\d{10,14}-secret-key-v\d+")


class TestTaskDefJsonSecretKey:
    """Verify task-def.json does not leak SECRET_KEY"""

    @pytest.fixture
    def task_def(self):
        path = CONFIG_DIR / "task-def.json"
        assert path.exists(), f"task-def.json not found at {path}"
        return json.loads(path.read_text())

    def test_no_secret_key_in_environment(self, task_def):
        """SECRET_KEY must not appear in plaintext environment variables"""
        env_vars = task_def["containerDefinitions"][0]["environment"]
        env_names = [var["name"] for var in env_vars]
        assert "SECRET_KEY" not in env_names, (
            "SECRET_KEY must not be in the environment section — "
            "use the secrets section with Secrets Manager instead"
        )

    def test_secret_key_uses_secrets_section(self, task_def):
        """SECRET_KEY should be in the secrets section referencing Secrets Manager"""
        secrets = task_def["containerDefinitions"][0].get("secrets", [])
        secret_names = [s["name"] for s in secrets]
        assert "SECRET_KEY" in secret_names, (
            "SECRET_KEY must be defined in the 'secrets' section of task-def.json "
            "to pull from AWS Secrets Manager"
        )

    def test_secrets_entry_references_secrets_manager(self, task_def):
        """The SECRET_KEY secrets entry must reference an ARN"""
        secrets = task_def["containerDefinitions"][0].get("secrets", [])
        for secret in secrets:
            if secret["name"] == "SECRET_KEY":
                assert "secretsmanager" in secret["valueFrom"], (
                    "SECRET_KEY secret must reference AWS Secrets Manager ARN"
                )
                break
        else:
            pytest.fail("SECRET_KEY not found in secrets section")


class TestCloudFormationSecretKey:
    """Verify CloudFormation templates use Secrets Manager for SECRET_KEY"""

    @pytest.fixture
    def ecs_services_yaml(self):
        path = CF_DIR / "ecs-services.yaml"
        assert path.exists(), f"ecs-services.yaml not found at {path}"
        return path.read_text()

    @pytest.fixture
    def main_stack_yaml(self):
        path = CF_DIR / "main-stack.yaml"
        assert path.exists(), f"main-stack.yaml not found at {path}"
        return path.read_text()

    def test_no_secret_key_in_environment_section(self, ecs_services_yaml):
        """SECRET_KEY must not appear in the Environment block of ecs-services.yaml"""
        # Find all Environment blocks and ensure SECRET_KEY is not there
        lines = ecs_services_yaml.splitlines()
        in_environment = False
        in_secrets = False
        for line in lines:
            stripped = line.strip()
            if stripped == "Environment:":
                in_environment = True
                in_secrets = False
            elif stripped == "Secrets:":
                in_secrets = True
                in_environment = False
            elif stripped and not stripped.startswith("-") and not stripped.startswith("Name:") and not stripped.startswith("Value"):
                if not stripped.startswith("'") and not stripped.startswith('"') and not stripped.startswith("!"):
                    in_environment = False
                    in_secrets = False

            if in_environment and "SECRET_KEY" in stripped:
                pytest.fail(
                    "SECRET_KEY found in Environment section of ecs-services.yaml. "
                    "It must only be in the Secrets section."
                )

    def test_secret_key_in_secrets_section(self, ecs_services_yaml):
        """SECRET_KEY must be in the Secrets section of the backend container"""
        assert "Secrets:" in ecs_services_yaml, "Missing Secrets section in ecs-services.yaml"
        # Check SECRET_KEY appears after a Secrets: line
        lines = ecs_services_yaml.splitlines()
        in_secrets = False
        found = False
        for line in lines:
            stripped = line.strip()
            if stripped == "Secrets:":
                in_secrets = True
            elif in_secrets and "SECRET_KEY" in stripped:
                found = True
                break
        assert found, "SECRET_KEY not found in Secrets section of ecs-services.yaml"

    def test_secrets_manager_arn_in_secrets_section(self, ecs_services_yaml):
        """The Secrets section must reference secretsmanager ARN"""
        assert "secretsmanager" in ecs_services_yaml, (
            "ecs-services.yaml must reference AWS Secrets Manager for SECRET_KEY"
        )

    def test_no_deterministic_pattern_in_cloudformation(self, ecs_services_yaml):
        """No deterministic secret-key-v1 pattern should exist"""
        assert not DETERMINISTIC_PATTERN.search(ecs_services_yaml), (
            "Found deterministic SECRET_KEY pattern in ecs-services.yaml"
        )

    def test_main_stack_has_secrets_manager_resource(self, main_stack_yaml):
        """main-stack.yaml must define a Secrets Manager secret resource"""
        assert "AWS::SecretsManager::Secret" in main_stack_yaml, (
            "main-stack.yaml must include an AWS::SecretsManager::Secret resource "
            "for the JWT secret key"
        )

    def test_main_stack_has_secrets_manager_iam_policy(self, main_stack_yaml):
        """ECS execution role must have secretsmanager:GetSecretValue permission"""
        assert "secretsmanager:GetSecretValue" in main_stack_yaml, (
            "main-stack.yaml must grant secretsmanager:GetSecretValue to ECS execution role"
        )

    def test_main_stack_secret_uses_generated_string(self, main_stack_yaml):
        """The secret should use GenerateSecretString for random generation"""
        assert "GenerateSecretString" in main_stack_yaml, (
            "SecretKeySecret must use GenerateSecretString for cryptographically random values"
        )


class TestNoHardcodedSecretsInRepo:
    """Broad scan: no deterministic SECRET_KEY patterns in any config file"""

    def test_no_deterministic_pattern_in_json_configs(self):
        """Scan all JSON files under infrastructure/ for deterministic SECRET_KEY values"""
        if not INFRA_DIR.exists():
            pytest.skip("Infrastructure directory not found")

        for json_file in INFRA_DIR.rglob("*.json"):
            content = json_file.read_text()
            match = DETERMINISTIC_PATTERN.search(content)
            assert match is None, (
                f"Deterministic SECRET_KEY pattern found in {json_file.relative_to(REPO_ROOT)}: "
                f"'{match.group()}'"
            )

    def test_no_deterministic_pattern_in_yaml_configs(self):
        """Scan all YAML files under infrastructure/ for deterministic SECRET_KEY values"""
        if not INFRA_DIR.exists():
            pytest.skip("Infrastructure directory not found")

        for yaml_file in list(INFRA_DIR.rglob("*.yaml")) + list(INFRA_DIR.rglob("*.yml")):
            content = yaml_file.read_text()
            match = DETERMINISTIC_PATTERN.search(content)
            assert match is None, (
                f"Deterministic SECRET_KEY pattern found in {yaml_file.relative_to(REPO_ROOT)}: "
                f"'{match.group()}'"
            )
