"""
Tests verifying CRIT-8 remediation: POSTGRES_PASSWORD must NOT appear as a
plaintext environment variable in ECS task definitions, and must instead be
injected via AWS Secrets Manager.
"""

import json
import os
import re

import pytest
import yaml

# Paths (relative to repo root)
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_ECS_SERVICES = os.path.join(_REPO_ROOT, "infrastructure", "cloudformation", "ecs-services.yaml")
_MAIN_STACK = os.path.join(_REPO_ROOT, "infrastructure", "cloudformation", "main-stack.yaml")
_TASK_DEF = os.path.join(_REPO_ROOT, "infrastructure", "config", "task-def.json")


def _load_yaml(path: str) -> dict:
    with open(path) as f:
        # Use a safe loader that ignores CloudFormation intrinsics
        class _CFLoader(yaml.SafeLoader):
            pass

        # Register all !Ref, !Sub, !If, etc. as plain strings
        for tag in (
            "!Ref", "!Sub", "!If", "!GetAtt", "!Select", "!Split",
            "!Equals", "!Not", "!And", "!Or", "!ImportValue",
            "!FindInMap", "!Join", "!Condition",
        ):
            _CFLoader.add_constructor(
                tag, lambda loader, node: loader.construct_scalar(node)
            )
            _CFLoader.add_multi_constructor(
                tag, lambda loader, suffix, node: loader.construct_mapping(node)
            )
        return yaml.load(f, Loader=_CFLoader)


# ---------------------------------------------------------------------------
# ecs-services.yaml
# ---------------------------------------------------------------------------

class TestEcsServicesNoDatabasePasswordPlaintext:
    """POSTGRES_PASSWORD must NOT be in Environment and MUST be in Secrets."""

    @pytest.fixture(autouse=True)
    def _load(self):
        with open(_ECS_SERVICES) as f:
            self.raw = f.read()

    def test_postgres_password_not_in_environment_block(self):
        """POSTGRES_PASSWORD must not appear as a plaintext env var."""
        # Find the Environment section and check it doesn't have POSTGRES_PASSWORD
        # with a direct Value (not under Secrets)
        env_block = re.search(
            r"Environment:\s*\n((?:\s+-.*\n)*)", self.raw
        )
        assert env_block, "Could not find Environment block"
        env_text = env_block.group(1)
        assert "POSTGRES_PASSWORD" not in env_text, (
            "POSTGRES_PASSWORD still present as a plaintext environment variable"
        )

    def test_database_url_not_in_environment_block(self):
        """DATABASE_URL (contains embedded password) must not appear."""
        env_block = re.search(
            r"Environment:\s*\n((?:\s+-.*\n)*)", self.raw
        )
        assert env_block, "Could not find Environment block"
        env_text = env_block.group(1)
        assert "DATABASE_URL" not in env_text, (
            "DATABASE_URL still present — app constructs it from components"
        )

    def test_postgres_password_in_secrets_block(self):
        """POSTGRES_PASSWORD must be injected via Secrets Manager."""
        # Find everything after "Secrets:" up to the next top-level key
        secrets_match = re.search(
            r"Secrets:\s*\n((?:[ \t]+.*\n)*)", self.raw
        )
        assert secrets_match, "Could not find Secrets block"
        secrets_text = secrets_match.group(1)
        assert "POSTGRES_PASSWORD" in secrets_text, (
            "POSTGRES_PASSWORD missing from Secrets section"
        )

    def test_secrets_reference_uses_secrets_manager_arn(self):
        """The ValueFrom must point to Secrets Manager, not a plaintext value."""
        assert "finops/database-password" in self.raw, (
            "Secrets Manager reference 'finops/database-password' not found"
        )


# ---------------------------------------------------------------------------
# main-stack.yaml
# ---------------------------------------------------------------------------

class TestMainStackDatabasePasswordSecret:
    """main-stack.yaml must declare a DatabasePasswordSecret resource."""

    @pytest.fixture(autouse=True)
    def _load(self):
        with open(_MAIN_STACK) as f:
            self.raw = f.read()

    def test_database_password_secret_resource_exists(self):
        assert "DatabasePasswordSecret:" in self.raw

    def test_database_password_secret_is_secrets_manager_type(self):
        assert "AWS::SecretsManager::Secret" in self.raw

    def test_database_password_secret_name(self):
        assert "finops/database-password" in self.raw

    def test_iam_policy_covers_both_secrets(self):
        """The SecretsManager IAM policy must reference both secrets."""
        assert "SecretKeySecret" in self.raw
        assert "DatabasePasswordSecret" in self.raw
        # Both should appear in the Resource list of the policy
        policy_section = self.raw[self.raw.index("SecretsManagerAccess"):]
        resource_section = policy_section[:policy_section.index("ECSTaskRole")]
        assert "SecretKeySecret" in resource_section
        assert "DatabasePasswordSecret" in resource_section

    def test_database_password_secret_arn_output(self):
        """Output exporting the secret ARN must exist."""
        assert "DatabasePasswordSecretArn:" in self.raw


# ---------------------------------------------------------------------------
# task-def.json
# ---------------------------------------------------------------------------

class TestTaskDefNoDatabasePasswordPlaintext:
    """task-def.json must not have DATABASE_URL in env and must have
    POSTGRES_PASSWORD in the secrets section."""

    @pytest.fixture(autouse=True)
    def _load(self):
        with open(_TASK_DEF) as f:
            self.data = json.load(f)
        self.container = self.data["containerDefinitions"][0]

    def test_no_database_url_in_environment(self):
        env_names = [e["name"] for e in self.container["environment"]]
        assert "DATABASE_URL" not in env_names, (
            "DATABASE_URL should not be in environment — app constructs it"
        )

    def test_postgres_password_in_secrets(self):
        secret_names = [s["name"] for s in self.container["secrets"]]
        assert "POSTGRES_PASSWORD" in secret_names, (
            "POSTGRES_PASSWORD must be in the secrets section"
        )

    def test_postgres_password_secret_points_to_secrets_manager(self):
        for s in self.container["secrets"]:
            if s["name"] == "POSTGRES_PASSWORD":
                assert "finops/database-password" in s["valueFrom"]
                break
        else:
            pytest.fail("POSTGRES_PASSWORD not found in secrets")
