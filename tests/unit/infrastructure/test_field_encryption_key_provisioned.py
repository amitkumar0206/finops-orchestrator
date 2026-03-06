"""
HIGH-33 regression tests — FIELD_ENCRYPTION_KEY must be provisioned in infrastructure.

The bug: backend/utils/encryption.py:97 raises ValueError on boot when
ENVIRONMENT=production and FIELD_ENCRYPTION_KEY is unset or shorter than 32
characters. Both ECS deployment artifacts set ENVIRONMENT=production but, prior
to the HIGH-33 fix, neither provisioned FIELD_ENCRYPTION_KEY — so the backend
container crash-looped on the first call to get_field_encryptor().

These tests pin the fix across all three moving parts:
  1. ecs-services.yaml — Secrets block entry (CloudFormation deployment path)
  2. task-def.json     — secrets array entry (direct register-task-definition path)
  3. main-stack.yaml   — Secret resource + IAM grant for the ECS execution role

Plus a CI tripwire that enumerates EVERY env var that hard-crashes in production
and asserts all of them are present in BOTH deployment artifacts, so the next
production-required secret added to the backend can't silently repeat this bug.
"""

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
INFRA_DIR = REPO_ROOT / "infrastructure"
CF_DIR = INFRA_DIR / "cloudformation"
CONFIG_DIR = INFRA_DIR / "config"


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def task_def():
    path = CONFIG_DIR / "task-def.json"
    assert path.exists(), f"task-def.json not found at {path}"
    return json.loads(path.read_text())


@pytest.fixture
def ecs_services_yaml():
    path = CF_DIR / "ecs-services.yaml"
    assert path.exists(), f"ecs-services.yaml not found at {path}"
    return path.read_text()


@pytest.fixture
def main_stack_yaml():
    path = CF_DIR / "main-stack.yaml"
    assert path.exists(), f"main-stack.yaml not found at {path}"
    return path.read_text()


# ─── task-def.json (direct aws ecs register-task-definition path) ────────────

class TestTaskDefJsonFieldEncryptionKey:
    """
    task-def.json is a parallel deployment artifact used with
    `aws ecs register-task-definition --cli-input-json`. It sets
    ENVIRONMENT=production at the environment block, so it needs
    FIELD_ENCRYPTION_KEY just as much as the CloudFormation path does.
    """

    def test_field_encryption_key_in_secrets_section(self, task_def):
        """
        HIGH-33 PRIMARY REGRESSION (task-def.json path).
        Pre-fix: secrets had only SECRET_KEY + POSTGRES_PASSWORD; container
        crashed at encryption.py:97 on first get_field_encryptor() call.
        """
        secrets = task_def["containerDefinitions"][0].get("secrets", [])
        secret_names = {s["name"] for s in secrets}
        assert "FIELD_ENCRYPTION_KEY" in secret_names, (
            "FIELD_ENCRYPTION_KEY missing from task-def.json secrets section. "
            "encryption.py:97 raises ValueError on boot in production without it."
        )

    def test_field_encryption_key_not_in_environment(self, task_def):
        """
        Must be in `secrets` (pulled from Secrets Manager at container start),
        NOT `environment` (plaintext in the task definition, visible in
        `aws ecs describe-task-definition`, ECS console, CloudTrail).
        """
        env_vars = task_def["containerDefinitions"][0].get("environment", [])
        env_names = {v["name"] for v in env_vars}
        assert "FIELD_ENCRYPTION_KEY" not in env_names, (
            "FIELD_ENCRYPTION_KEY must NOT be in the plaintext environment "
            "section — it encrypts sensitive DB columns (role ARNs, external IDs, "
            "ticketing creds). Use the secrets section."
        )

    def test_field_encryption_key_references_secrets_manager(self, task_def):
        """The valueFrom must be a Secrets Manager ARN, not SSM or a literal."""
        secrets = task_def["containerDefinitions"][0].get("secrets", [])
        entry = next(
            (s for s in secrets if s["name"] == "FIELD_ENCRYPTION_KEY"), None
        )
        assert entry is not None, "FIELD_ENCRYPTION_KEY not in secrets"
        assert "secretsmanager" in entry["valueFrom"], (
            f"FIELD_ENCRYPTION_KEY valueFrom must be a Secrets Manager ARN, "
            f"got: {entry['valueFrom']!r}"
        )
        assert "finops/field-encryption-key" in entry["valueFrom"], (
            "FIELD_ENCRYPTION_KEY must reference the finops/field-encryption-key "
            "secret (matches FieldEncryptionKeySecret Name in main-stack.yaml)"
        )


# ─── ecs-services.yaml (CloudFormation deployment path) ──────────────────────

class TestEcsServicesYamlFieldEncryptionKey:
    """
    CFN intrinsics (!Sub with a list, !If, !ImportValue) break naive YAML
    parsing, so these tests scan raw text — same approach as
    test_secret_key_not_hardcoded.py::TestCloudFormationSecretKey.
    """

    def test_field_encryption_key_in_secrets_block(self, ecs_services_yaml):
        """
        HIGH-33 PRIMARY REGRESSION (CloudFormation path).
        Pre-fix: Secrets block had SECRET_KEY + POSTGRES_PASSWORD only.
        """
        lines = ecs_services_yaml.splitlines()
        in_secrets = False
        found = False
        for line in lines:
            stripped = line.strip()
            if stripped == "Secrets:":
                in_secrets = True
            elif in_secrets and stripped.startswith("- Name: FIELD_ENCRYPTION_KEY"):
                found = True
                break
            # Leave the Secrets block when we hit a sibling key at the same
            # or shallower indent that isn't a list item or Name/ValueFrom.
            elif in_secrets and stripped and not stripped.startswith(("-", "Name:", "ValueFrom:", "#")):
                in_secrets = False
        assert found, (
            "FIELD_ENCRYPTION_KEY not found in ecs-services.yaml Secrets block. "
            "With ENVIRONMENT=production at line ~151, encryption.py:97 raises "
            "ValueError on boot without it."
        )

    def test_field_encryption_key_not_in_environment_block(self, ecs_services_yaml):
        """
        The key encrypts role ARNs / external IDs / ticketing creds.
        Plaintext in the Environment block → visible in CloudFormation console,
        describe-stacks, and drift-detection output.
        """
        lines = ecs_services_yaml.splitlines()
        in_environment = False
        for i, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped == "Environment:":
                in_environment = True
            elif stripped == "Secrets:":
                in_environment = False
            elif in_environment and "FIELD_ENCRYPTION_KEY" in stripped and not stripped.startswith("#"):
                pytest.fail(
                    f"FIELD_ENCRYPTION_KEY found in Environment block at "
                    f"ecs-services.yaml:{i}. Must be in Secrets block only."
                )

    def test_field_encryption_key_valuefrom_references_secrets_manager(self, ecs_services_yaml):
        """
        The ValueFrom line immediately following the Name line must reference
        the finops/field-encryption-key secret via Secrets Manager ARN.
        """
        lines = ecs_services_yaml.splitlines()
        for i, line in enumerate(lines):
            if line.strip() == "- Name: FIELD_ENCRYPTION_KEY":
                # Next non-comment line should be the ValueFrom
                for next_line in lines[i + 1:]:
                    ns = next_line.strip()
                    if ns.startswith("#"):
                        continue
                    assert ns.startswith("ValueFrom:"), (
                        f"Expected ValueFrom after FIELD_ENCRYPTION_KEY Name, got: {ns!r}"
                    )
                    assert "secretsmanager" in ns, (
                        "FIELD_ENCRYPTION_KEY ValueFrom must be a Secrets Manager ARN"
                    )
                    assert "finops/field-encryption-key" in ns, (
                        "FIELD_ENCRYPTION_KEY must reference finops/field-encryption-key "
                        "(matches FieldEncryptionKeySecret Name in main-stack.yaml)"
                    )
                    return
        pytest.fail("FIELD_ENCRYPTION_KEY Name line not found in ecs-services.yaml")


# ─── main-stack.yaml (Secret resource + IAM grant) ───────────────────────────

class TestMainStackFieldEncryptionKeySecret:
    """
    The Secrets block in an ECS task definition is resolved by the
    **Execution Role** at container-launch time, not the Task Role.
    So main-stack.yaml needs:
      - The AWS::SecretsManager::Secret resource itself
      - secretsmanager:GetSecretValue on that ARN for ECSTaskExecutionRole
    """

    def test_field_encryption_key_secret_resource_exists(self, main_stack_yaml):
        """The secret resource must be defined for the ValueFrom ARN to resolve."""
        assert "FieldEncryptionKeySecret:" in main_stack_yaml, (
            "main-stack.yaml must define FieldEncryptionKeySecret resource. "
            "Without it, ECS container-launch fails with "
            "'ResourceNotFoundException: Secrets Manager can't find the specified secret'."
        )

    def test_secret_name_matches_task_def_references(self, main_stack_yaml):
        """
        The secret Name must be exactly 'finops/field-encryption-key' —
        both ecs-services.yaml and task-def.json hard-code this in their
        ValueFrom ARNs (partial-ARN resolution, no random suffix).
        """
        # Find the Name: line within the FieldEncryptionKeySecret resource block
        lines = main_stack_yaml.splitlines()
        in_resource = False
        for line in lines:
            if "FieldEncryptionKeySecret:" in line:
                in_resource = True
            elif in_resource and re.match(r"^\s{2}\w", line):
                # Hit the next top-level resource (2-space indent, non-continuation)
                break
            elif in_resource and "Name:" in line and "finops/field-encryption-key" in line:
                return
        pytest.fail(
            "FieldEncryptionKeySecret must have Name: finops/field-encryption-key "
            "to match the ValueFrom ARNs in ecs-services.yaml and task-def.json"
        )

    def test_secret_uses_generate_secret_string(self, main_stack_yaml):
        """
        Must generate, not store a passed-in parameter. GenerateSecretString
        produces cryptographically random values and keeps the key out of
        CloudFormation parameter history.
        """
        lines = main_stack_yaml.splitlines()
        in_resource = False
        found_generate = False
        for line in lines:
            if "FieldEncryptionKeySecret:" in line:
                in_resource = True
            elif in_resource and re.match(r"^\s{2}\w", line):
                break
            elif in_resource and "GenerateSecretString:" in line:
                found_generate = True
                break
        assert found_generate, (
            "FieldEncryptionKeySecret must use GenerateSecretString, not a "
            "stored parameter — keeps the key out of CFN parameter history."
        )

    def test_generated_key_length_meets_encryption_requirement(self, main_stack_yaml):
        """
        encryption.py:97 requires len(key) >= 32.
        Audit brief asked for >= 48.
        """
        lines = main_stack_yaml.splitlines()
        in_resource = False
        for line in lines:
            if "FieldEncryptionKeySecret:" in line:
                in_resource = True
            elif in_resource and re.match(r"^\s{2}\w", line):
                break
            elif in_resource and "PasswordLength:" in line:
                m = re.search(r"PasswordLength:\s*(\d+)", line)
                assert m, f"Could not parse PasswordLength from: {line!r}"
                length = int(m.group(1))
                assert length >= 32, (
                    f"PasswordLength={length} is below the 32-char minimum "
                    f"enforced by encryption.py:97"
                )
                assert length >= 48, (
                    f"PasswordLength={length} is below the 48-char minimum "
                    f"recommended by the HIGH-33 audit brief"
                )
                return
        pytest.fail(
            "FieldEncryptionKeySecret block missing PasswordLength — "
            "cannot verify key meets encryption.py's 32-char minimum"
        )

    def test_execution_role_can_read_field_encryption_key_secret(self, main_stack_yaml):
        """
        ECS resolves the Secrets block using the **Execution Role**, not the
        Task Role. If the grant is missing, container-launch fails with
        AccessDeniedException before the app code ever runs.

        The existing SecretsManagerAccess policy lists resources as
        `- !Ref <SecretLogicalId>`. Check ours is there.
        """
        assert "!Ref FieldEncryptionKeySecret" in main_stack_yaml, (
            "ECSTaskExecutionRole's SecretsManagerAccess policy must include "
            "'!Ref FieldEncryptionKeySecret' in its Resource list. Without it, "
            "ECS container-launch fails with AccessDeniedException when "
            "resolving the Secrets block."
        )

    def test_field_encryption_key_secret_arn_is_exported(self, main_stack_yaml):
        """
        Exported for cross-stack reference, matching SecretKeySecretArn and
        DatabasePasswordSecretArn. Not strictly required for the fix but
        keeps the three secrets symmetric for downstream stacks.
        """
        assert "FieldEncryptionKeySecretArn:" in main_stack_yaml, (
            "main-stack.yaml should export FieldEncryptionKeySecretArn "
            "(matching SecretKeySecretArn / DatabasePasswordSecretArn pattern)"
        )


# ─── CI tripwire — every production hard-crash var is provisioned ────────────

class TestAllProductionRequiredSecretsProvisioned:
    """
    Sibling-sweep guard. The HIGH-33 bug pattern: backend code adds a
    production-required env var with a hard-crash check, but nobody updates
    the infrastructure files. This tripwire enumerates every such var and
    asserts it's provisioned in BOTH deployment artifacts.

    Scope — only vars that HARD CRASH (raise) when ENVIRONMENT=production:
      - SECRET_KEY           settings.py:~324-384   raise ValueError (4 variants)
      - FIELD_ENCRYPTION_KEY encryption.py:97       raise ValueError

    NOT in scope (soft — issues.append, container boots but degraded):
      - SSL, CORS validations in settings.py:~580+, ~698+, ~723+

    When you add a new production hard-crash env var, add it here.
    If this test fails on your PR, you forgot to update the infrastructure.
    """

    # Env var name → where the crash is. Kept explicit (not dynamically
    # discovered) so the test doubles as documentation and so adding a new
    # hard-crash var is a deliberate 2-line PR change here.
    PRODUCTION_REQUIRED_SECRETS = {
        "SECRET_KEY": "backend/config/settings.py — raise ValueError if unset/weak/short",
        "FIELD_ENCRYPTION_KEY": "backend/utils/encryption.py:97 — raise ValueError if unset or len<32",
    }

    def test_all_required_secrets_in_task_def_json(self, task_def):
        """Every production hard-crash var provisioned in task-def.json secrets."""
        secrets = task_def["containerDefinitions"][0].get("secrets", [])
        provisioned = {s["name"] for s in secrets}
        missing = set(self.PRODUCTION_REQUIRED_SECRETS) - provisioned
        assert not missing, (
            f"task-def.json is missing production-required secrets: {sorted(missing)}. "
            f"These vars hard-crash on boot when ENVIRONMENT=production:\n"
            + "\n".join(
                f"  {k}: {self.PRODUCTION_REQUIRED_SECRETS[k]}" for k in sorted(missing)
            )
        )

    def test_all_required_secrets_in_ecs_services_yaml(self, ecs_services_yaml):
        """Every production hard-crash var provisioned in ecs-services.yaml Secrets."""
        lines = ecs_services_yaml.splitlines()
        provisioned = set()
        in_secrets = False
        for line in lines:
            stripped = line.strip()
            if stripped == "Secrets:":
                in_secrets = True
            elif in_secrets and stripped.startswith("- Name:"):
                name = stripped.removeprefix("- Name:").strip()
                provisioned.add(name)
            elif in_secrets and stripped and not stripped.startswith(("-", "Name:", "ValueFrom:", "#")):
                in_secrets = False

        missing = set(self.PRODUCTION_REQUIRED_SECRETS) - provisioned
        assert not missing, (
            f"ecs-services.yaml Secrets block is missing: {sorted(missing)}. "
            f"These vars hard-crash on boot when ENVIRONMENT=production:\n"
            + "\n".join(
                f"  {k}: {self.PRODUCTION_REQUIRED_SECRETS[k]}" for k in sorted(missing)
            )
        )

    def test_no_required_secret_leaks_into_plaintext_environment(self, task_def, ecs_services_yaml):
        """
        None of the hard-crash secrets may appear in plaintext environment
        sections of EITHER artifact. Catches the 'helpful' anti-pattern of
        someone adding a fallback plaintext value 'just to unblock the deploy'.
        """
        # task-def.json environment
        env_names = {
            v["name"] for v in task_def["containerDefinitions"][0].get("environment", [])
        }
        leaked_json = set(self.PRODUCTION_REQUIRED_SECRETS) & env_names
        assert not leaked_json, (
            f"Production secrets in task-def.json PLAINTEXT environment: "
            f"{sorted(leaked_json)}. Move to secrets section."
        )

        # ecs-services.yaml Environment block
        lines = ecs_services_yaml.splitlines()
        in_environment = False
        for i, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped == "Environment:":
                in_environment = True
            elif stripped == "Secrets:":
                in_environment = False
            elif in_environment and not stripped.startswith("#"):
                for secret_name in self.PRODUCTION_REQUIRED_SECRETS:
                    if f"Name: {secret_name}" in stripped:
                        pytest.fail(
                            f"Production secret {secret_name} in PLAINTEXT "
                            f"Environment block at ecs-services.yaml:{i}. "
                            f"Move to Secrets block."
                        )
