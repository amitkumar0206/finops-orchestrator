"""
Security tests for Auth API - PII Masking in Logs
Tests the fix for HIGH-6: Unmasked PII (Email) in Authentication Logs
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import HTTPException
import structlog
from structlog.testing import LogCapture

from backend.api.auth import router, LoginRequest
from backend.utils.pii_masking import mask_email


class TestEmailMaskingInAuthLogs:
    """Test suite for email masking in authentication logs"""

    def test_mask_email_function_works_correctly(self):
        """Test that the mask_email utility works as expected"""
        test_cases = [
            ("john.doe@example.com", "jo***@ex***.com"),
            ("alice@test.org", "al***@te***.org"),
            ("a@b.com", "a***@b***.com"),
            ("test.user@company.co.uk", "te***@co***.uk"),
            ("", "unknown"),
            (None, "unknown"),
        ]

        for email, expected_masked in test_cases:
            result = mask_email(email)
            assert result == expected_masked, f"Failed for {email}"

    @pytest.mark.asyncio
    async def test_login_failed_user_not_found_masks_email(self):
        """Test that email is masked when user is not found"""
        from backend.api.auth import login

        request = LoginRequest(email="nonexistent@example.com", password="password123")

        # Mock database to return no user
        with patch('backend.api.auth.get_db', new_callable=AsyncMock) as mock_get_db:
            mock_db = MagicMock()
            mock_conn = AsyncMock()
            mock_result = MagicMock()  # Result is NOT async
            mock_mappings = MagicMock()
            mock_mappings.first.return_value = None
            mock_result.mappings.return_value = mock_mappings

            # Create an async mock that returns the non-async result
            async def mock_execute(*args, **kwargs):
                return mock_result
            mock_conn.execute = mock_execute

            mock_conn.__aenter__.return_value = mock_conn
            mock_db.engine.begin.return_value = mock_conn
            mock_get_db.return_value = mock_db

            # Capture logs
            with patch('backend.api.auth.logger') as mock_logger:
                with pytest.raises(HTTPException) as exc_info:
                    await login(request)

                # Verify 401 status
                assert exc_info.value.status_code == 401

                # Verify logger was called with masked email
                mock_logger.warning.assert_called_once()
                call_args = mock_logger.warning.call_args
                assert call_args[0][0] == "login_failed_user_not_found"
                assert call_args[1]['email'] == "no***@ex***.com"  # Masked
                assert "nonexistent@example.com" not in str(call_args)  # Raw email not present

    @pytest.mark.asyncio
    async def test_login_failed_user_inactive_masks_email(self):
        """Test that email is masked when user is inactive"""
        from backend.api.auth import login

        request = LoginRequest(email="inactive@example.com", password="password123")

        # Mock database to return inactive user
        with patch('backend.api.auth.get_db', new_callable=AsyncMock) as mock_get_db:
            mock_db = MagicMock()
            mock_conn = AsyncMock()
            mock_result = MagicMock()  # Result is NOT async
            mock_mappings = MagicMock()
            mock_mappings.first.return_value = {
                'id': '123',
                'email': 'inactive@example.com',
                'is_active': False,  # User is inactive
                'password_hash': 'hash',
                'password_salt': 'salt',
                'is_admin': False,
                'default_organization_id': None
            }
            mock_result.mappings.return_value = mock_mappings

            # Create an async mock that returns the non-async result
            async def mock_execute(*args, **kwargs):
                return mock_result
            mock_conn.execute = mock_execute

            mock_conn.__aenter__.return_value = mock_conn
            mock_db.engine.begin.return_value = mock_conn
            mock_get_db.return_value = mock_db

            # Capture logs
            with patch('backend.api.auth.logger') as mock_logger:
                with pytest.raises(HTTPException) as exc_info:
                    await login(request)

                # Verify 401 status
                assert exc_info.value.status_code == 401

                # Verify logger was called with masked email
                mock_logger.warning.assert_called_once()
                call_args = mock_logger.warning.call_args
                assert call_args[0][0] == "login_failed_user_inactive"
                assert call_args[1]['email'] == "in***@ex***.com"  # Masked
                assert "inactive@example.com" not in str(call_args)  # Raw email not present

    @pytest.mark.asyncio
    async def test_login_failed_no_password_masks_email(self):
        """Test that email is masked when user has no password set"""
        from backend.api.auth import login

        request = LoginRequest(email="nopass@example.com", password="password123")

        # Mock database to return user without password
        with patch('backend.api.auth.get_db', new_callable=AsyncMock) as mock_get_db:
            mock_db = MagicMock()
            mock_conn = AsyncMock()
            mock_result = MagicMock()  # Result is NOT async
            mock_mappings = MagicMock()
            mock_mappings.first.return_value = {
                'id': '123',
                'email': 'nopass@example.com',
                'is_active': True,
                'password_hash': None,  # No password set
                'password_salt': None,
                'is_admin': False,
                'default_organization_id': None
            }
            mock_result.mappings.return_value = mock_mappings

            # Create an async mock that returns the non-async result
            async def mock_execute(*args, **kwargs):
                return mock_result
            mock_conn.execute = mock_execute

            mock_conn.__aenter__.return_value = mock_conn
            mock_db.engine.begin.return_value = mock_conn
            mock_get_db.return_value = mock_db

            # Capture logs
            with patch('backend.api.auth.logger') as mock_logger:
                with pytest.raises(HTTPException) as exc_info:
                    await login(request)

                # Verify 401 status
                assert exc_info.value.status_code == 401

                # Verify logger was called with masked email
                mock_logger.warning.assert_called_once()
                call_args = mock_logger.warning.call_args
                assert call_args[0][0] == "login_failed_no_password"
                assert call_args[1]['email'] == "no***@ex***.com"  # Masked
                assert "nopass@example.com" not in str(call_args)  # Raw email not present

    @pytest.mark.asyncio
    async def test_login_failed_wrong_password_masks_email(self):
        """Test that email is masked when password is wrong"""
        from backend.api.auth import login

        request = LoginRequest(email="wrongpass@example.com", password="wrongpassword")

        # Mock database to return user with password
        with patch('backend.api.auth.get_db', new_callable=AsyncMock) as mock_get_db:
            mock_db = MagicMock()
            mock_conn = AsyncMock()
            mock_result = MagicMock()  # Result is NOT async
            mock_mappings = MagicMock()
            mock_mappings.first.return_value = {
                'id': '123',
                'email': 'wrongpass@example.com',
                'is_active': True,
                'password_hash': 'correcthash',
                'password_salt': 'salt',
                'is_admin': False,
                'default_organization_id': None
            }
            mock_result.mappings.return_value = mock_mappings

            # Create an async mock that returns the non-async result
            async def mock_execute(*args, **kwargs):
                return mock_result
            mock_conn.execute = mock_execute

            mock_conn.__aenter__.return_value = mock_conn
            mock_db.engine.begin.return_value = mock_conn
            mock_get_db.return_value = mock_db

            # Mock password verification to fail
            with patch('backend.api.auth.verify_password', return_value=False):
                # Capture logs
                with patch('backend.api.auth.logger') as mock_logger:
                    with pytest.raises(HTTPException) as exc_info:
                        await login(request)

                    # Verify 401 status
                    assert exc_info.value.status_code == 401

                    # Verify logger was called with masked email
                    mock_logger.warning.assert_called_once()
                    call_args = mock_logger.warning.call_args
                    assert call_args[0][0] == "login_failed_wrong_password"
                    assert call_args[1]['email'] == "wr***@ex***.com"  # Masked
                    assert "wrongpass@example.com" not in str(call_args)  # Raw email not present

    @pytest.mark.asyncio
    async def test_login_successful_masks_email(self):
        """Test that email is masked on successful login"""
        from backend.api.auth import login

        request = LoginRequest(email="success@example.com", password="correctpassword")

        # Mock database
        with patch('backend.api.auth.get_db', new_callable=AsyncMock) as mock_get_db:
            mock_db = MagicMock()
            mock_conn = AsyncMock()

            # Mock user query result
            mock_user_result = MagicMock()  # Result is NOT async
            mock_user_mappings = MagicMock()
            mock_user_mappings.first.return_value = {
                'id': '123',
                'email': 'success@example.com',
                'is_active': True,
                'full_name': 'Test User',
                'password_hash': 'correcthash',
                'password_salt': 'salt',
                'is_admin': False,
                'default_organization_id': '456'
            }
            mock_user_result.mappings.return_value = mock_user_mappings

            # Mock org query result
            mock_org_result = MagicMock()  # Result is NOT async
            mock_org_mappings = MagicMock()
            mock_org_mappings.first.return_value = {
                'name': 'Test Org'
            }
            mock_org_result.mappings.return_value = mock_org_mappings

            # Mock update result (doesn't need mappings)
            mock_update_result = MagicMock()

            # Setup execute to return different results based on call order
            execute_calls = [mock_user_result, mock_org_result, mock_update_result]
            call_count = [0]

            async def mock_execute(*args, **kwargs):
                result = execute_calls[call_count[0]]
                call_count[0] += 1
                return result

            mock_conn.execute = mock_execute
            mock_conn.__aenter__.return_value = mock_conn
            mock_db.engine.begin.return_value = mock_conn
            mock_get_db.return_value = mock_db

            # Mock password verification to succeed
            with patch('backend.api.auth.verify_password', return_value=True):
                # Mock authenticator
                with patch('backend.api.auth.get_authenticator') as mock_get_auth:
                    mock_auth = MagicMock()
                    mock_token_pair = MagicMock()
                    mock_token_pair.access_token = "access123"
                    mock_token_pair.refresh_token = "refresh123"
                    mock_auth.create_token_pair.return_value = mock_token_pair
                    mock_get_auth.return_value = mock_auth

                    # Mock settings
                    with patch('backend.api.auth.get_settings') as mock_get_settings:
                        mock_settings = MagicMock()
                        mock_settings.jwt_access_token_expiry_minutes = 60
                        mock_get_settings.return_value = mock_settings

                        # Capture logs
                        with patch('backend.api.auth.logger') as mock_logger:
                            response = await login(request)

                            # Verify successful response
                            assert response.access_token == "access123"
                            assert response.refresh_token == "refresh123"

                            # Verify logger.info was called with masked email
                            mock_logger.info.assert_called_once()
                            call_args = mock_logger.info.call_args
                            assert call_args[0][0] == "login_successful"
                            assert call_args[1]['email'] == "su***@ex***.com"  # Masked
                            assert "success@example.com" not in str(call_args)  # Raw email not present

    @pytest.mark.asyncio
    async def test_token_refresh_masks_email(self):
        """Test that email is masked when token is refreshed"""
        from backend.api.auth import refresh_token, RefreshRequest

        request = RefreshRequest(refresh_token="valid_refresh_token")

        # Mock authenticator to decode token
        with patch('backend.api.auth.get_authenticator') as mock_get_auth:
            mock_auth = MagicMock()

            # Mock token payload
            mock_payload = MagicMock()
            mock_payload.user_id = "123"
            mock_payload.email = "refresh@example.com"
            mock_auth.validate_refresh_token.return_value = mock_payload
            mock_auth.create_access_token.return_value = "new_access_token"
            mock_get_auth.return_value = mock_auth

            # Mock jwt.decode for jti extraction
            with patch('jwt.decode') as mock_jwt_decode:
                mock_jwt_decode.return_value = {"jti": "test-jti-123", "exp": 1234567890}

                # Mock database
                with patch('backend.api.auth.get_db', new_callable=AsyncMock) as mock_get_db:
                    mock_db = MagicMock()
                    mock_conn = AsyncMock()
                    mock_result = MagicMock()  # Result is NOT async
                    mock_mappings = MagicMock()
                    mock_mappings.first.return_value = {
                        'is_active': True,
                        'is_admin': False,
                        'default_organization_id': '456'
                    }
                    mock_result.mappings.return_value = mock_mappings

                    # Create an async mock that returns the non-async result
                    async def mock_execute(*args, **kwargs):
                        return mock_result
                    mock_conn.execute = mock_execute

                    mock_conn.__aenter__.return_value = mock_conn
                    mock_db.engine.begin.return_value = mock_conn
                    mock_get_db.return_value = mock_db

                    # Mock cache service
                    with patch('backend.api.auth.get_cache_service') as mock_get_cache:
                        mock_cache = AsyncMock()
                        mock_cache.is_refresh_token_blacklisted.return_value = False
                        mock_get_cache.return_value = mock_cache

                        # Mock settings
                        with patch('backend.api.auth.get_settings') as mock_get_settings:
                            mock_settings = MagicMock()
                            mock_settings.jwt_access_token_expiry_minutes = 60
                            mock_settings.secret_key = "test-secret"
                            mock_settings.jwt_issuer = "test-issuer"
                            mock_get_settings.return_value = mock_settings

                            # Capture logs
                            with patch('backend.api.auth.logger') as mock_logger:
                                response = await refresh_token(request)

                                # Verify successful response
                                assert response.access_token == "new_access_token"

                                # Verify logger.debug was called with masked email
                                mock_logger.debug.assert_called_once()
                                call_args = mock_logger.debug.call_args
                                assert call_args[0][0] == "token_refreshed"
                                assert call_args[1]['email'] == "re***@ex***.com"  # Masked
                                assert "refresh@example.com" not in str(call_args)  # Raw email not present


class TestPIIMaskingRegressionTests:
    """Regression tests to ensure PII masking stays in place"""

    def test_mask_email_import_exists(self):
        """Test that mask_email is imported in auth.py"""
        import backend.api.auth as auth_module
        assert hasattr(auth_module, 'mask_email')

    def test_auth_module_uses_mask_email(self):
        """Test that auth.py uses mask_email in logger calls"""
        import inspect
        from backend.api.auth import login, refresh_token

        # Check login function source
        login_source = inspect.getsource(login)
        assert "mask_email" in login_source, "login function should use mask_email"
        assert login_source.count("mask_email") >= 5, "Should have at least 5 mask_email calls in login"

        # Check refresh_token function source
        refresh_source = inspect.getsource(refresh_token)
        assert "mask_email" in refresh_source, "refresh_token function should use mask_email"

    def test_no_raw_email_in_logger_calls(self):
        """Test that logger calls don't use raw email directly"""
        import inspect
        from backend.api.auth import login, refresh_token

        # Check login function
        login_source = inspect.getsource(login)

        # These patterns should NOT exist (raw email in logger)
        bad_patterns = [
            'logger.warning("login_failed_user_not_found", email=request.email)',
            'logger.warning("login_failed_user_inactive", email=request.email)',
            'logger.warning("login_failed_no_password", email=request.email)',
            'logger.warning("login_failed_wrong_password", email=request.email)',
            'logger.info("login_successful", user_id=user_id, email=request.email',
        ]

        for pattern in bad_patterns:
            # Remove whitespace for comparison
            normalized_source = login_source.replace(" ", "").replace("\n", "")
            normalized_pattern = pattern.replace(" ", "")
            assert normalized_pattern not in normalized_source, \
                f"Found unmasked email pattern: {pattern}"

        # Check refresh_token function - look for logger calls with raw email
        refresh_source = inspect.getsource(refresh_token)
        # Check that logger calls use mask_email, not raw email
        # We specifically check for logger.* followed by email= without mask_email
        normalized_refresh = refresh_source.replace(" ", "").replace("\n", "")
        # Pattern: logger.<level>(... email=payload.email ...) without mask_email
        bad_refresh_patterns = [
            'logger.debug("token_refreshed",user_id=payload.user_id,email=payload.email',
            'logger.info("token_refreshed",user_id=payload.user_id,email=payload.email',
            'logger.warning("token_refreshed",user_id=payload.user_id,email=payload.email',
        ]
        for pattern in bad_refresh_patterns:
            normalized_pattern = pattern.replace(" ", "")
            assert normalized_pattern not in normalized_refresh, \
                f"refresh_token should use mask_email in logger calls, found: {pattern}"

    def test_all_auth_log_statements_analyzed(self):
        """Test that we've covered all authentication log statements"""
        import inspect
        from backend.api.auth import login, refresh_token

        login_source = inspect.getsource(login)
        refresh_source = inspect.getsource(refresh_token)

        # Count logger calls in login
        login_logger_calls = login_source.count('logger.')

        # We expect:
        # - 4 warning calls (failed login scenarios)
        # - 1 info call (successful login)
        # Total: 5 logger calls
        assert login_logger_calls >= 5, f"Expected at least 5 logger calls in login, found {login_logger_calls}"

        # Count logger calls in refresh_token
        refresh_logger_calls = refresh_source.count('logger.')

        # We expect at least 1 debug call for token refresh
        assert refresh_logger_calls >= 1, f"Expected at least 1 logger call in refresh_token, found {refresh_logger_calls}"

    def test_mask_email_function_quality(self):
        """Test that mask_email function handles edge cases properly"""
        # Test edge cases
        assert mask_email(None) == "unknown"
        assert mask_email("") == "unknown"
        assert mask_email("not-an-email") == "no***"

        # Test that actual emails are masked, not leaked
        result = mask_email("sensitive@private.com")
        assert "sensitive" not in result
        assert "private" not in result
        assert "***" in result
        assert "@" in result
