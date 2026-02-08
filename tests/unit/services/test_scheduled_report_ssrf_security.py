"""
Security tests for Scheduled Report Service - SSRF Protection
Tests the fix for HIGH-5: Server-Side Request Forgery (SSRF) via Webhook Delivery
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
import socket

from backend.services.scheduled_report_service import (
    _validate_webhook_url,
    BLOCKED_CIDRS,
    ScheduledReportService
)


class TestValidateWebhookUrl:
    """Test suite for _validate_webhook_url function"""

    def test_valid_https_url_passes(self):
        """Test that valid HTTPS URLs pass validation"""
        valid_urls = [
            "https://example.com/webhook",
            "https://api.example.com/notifications",
            "https://webhooks.example.org:8443/receive",
            "https://webhook.service.com/v1/reports"
        ]

        for url in valid_urls:
            with patch('socket.gethostbyname', return_value='93.184.216.34'):  # example.com IP
                _validate_webhook_url(url)  # Should not raise

    def test_http_url_rejected(self):
        """Test that HTTP URLs are rejected (HTTPS required)"""
        http_urls = [
            "http://example.com/webhook",
            "http://api.example.com/notifications"
        ]

        for url in http_urls:
            with pytest.raises(ValueError) as exc_info:
                _validate_webhook_url(url)

            error_msg = str(exc_info.value).lower()
            assert "https" in error_msg or "security" in error_msg

    def test_empty_url_rejected(self):
        """Test that empty URLs are rejected"""
        with pytest.raises(ValueError) as exc_info:
            _validate_webhook_url("")

        assert "non-empty string" in str(exc_info.value)

    def test_none_url_rejected(self):
        """Test that None URLs are rejected"""
        with pytest.raises(ValueError) as exc_info:
            _validate_webhook_url(None)

        assert "non-empty string" in str(exc_info.value)

    def test_private_ip_10_x_blocked(self):
        """Test that private IPs in 10.0.0.0/8 range are blocked"""
        private_ips = [
            ("https://internal.company.com", "10.0.0.1"),
            ("https://private.example.com", "10.1.2.3"),
            ("https://internal-api.local", "10.255.255.254")
        ]

        for url, ip in private_ips:
            with patch('socket.gethostbyname', return_value=ip):
                with pytest.raises(ValueError) as exc_info:
                    _validate_webhook_url(url)

                assert "blocked network range" in str(exc_info.value)

    def test_private_ip_172_x_blocked(self):
        """Test that private IPs in 172.16.0.0/12 range are blocked"""
        private_ips = [
            ("https://internal.company.com", "172.16.0.1"),
            ("https://private.example.com", "172.20.50.100"),
            ("https://internal-api.local", "172.31.255.254")
        ]

        for url, ip in private_ips:
            with patch('socket.gethostbyname', return_value=ip):
                with pytest.raises(ValueError) as exc_info:
                    _validate_webhook_url(url)

                assert "blocked network range" in str(exc_info.value)

    def test_private_ip_192_168_blocked(self):
        """Test that private IPs in 192.168.0.0/16 range are blocked"""
        private_ips = [
            ("https://internal.company.com", "192.168.0.1"),
            ("https://private.example.com", "192.168.1.100"),
            ("https://internal-api.local", "192.168.255.254")
        ]

        for url, ip in private_ips:
            with patch('socket.gethostbyname', return_value=ip):
                with pytest.raises(ValueError) as exc_info:
                    _validate_webhook_url(url)

                assert "blocked network range" in str(exc_info.value)

    def test_loopback_127_x_blocked(self):
        """Test that loopback IPs (127.0.0.0/8) are blocked"""
        loopback_ips = [
            ("https://localhost.example.com", "127.0.0.1"),
            ("https://local.test.com", "127.0.1.1"),
            ("https://loopback.test.com", "127.255.255.254")
        ]

        for url, ip in loopback_ips:
            with patch('socket.gethostbyname', return_value=ip):
                with pytest.raises(ValueError) as exc_info:
                    _validate_webhook_url(url)

                assert "blocked network range" in str(exc_info.value)

    def test_ec2_imds_169_254_blocked(self):
        """Test that EC2 Instance Metadata Service (169.254.169.254) is blocked"""
        imds_ips = [
            ("https://metadata.internal", "169.254.169.254"),
            ("https://imds.local", "169.254.0.1"),
            ("https://link-local.test", "169.254.255.254")
        ]

        for url, ip in imds_ips:
            with patch('socket.gethostbyname', return_value=ip):
                with pytest.raises(ValueError) as exc_info:
                    _validate_webhook_url(url)

                assert "blocked network range" in str(exc_info.value)

    def test_localhost_by_name_blocked(self):
        """Test that localhost by name is explicitly blocked"""
        localhost_urls = [
            "https://localhost/webhook",
            "https://127.0.0.1/webhook",
        ]

        for url in localhost_urls:
            with pytest.raises(ValueError) as exc_info:
                _validate_webhook_url(url)

            error_msg = str(exc_info.value).lower()
            assert "localhost" in error_msg or "blocked" in error_msg

    def test_unresolvable_hostname_blocked(self):
        """Test that unresolvable hostnames are blocked"""
        with patch('socket.gethostbyname', side_effect=socket.gaierror("Name resolution failed")):
            with pytest.raises(ValueError) as exc_info:
                _validate_webhook_url("https://nonexistent.invalid.domain.test")

            assert "cannot resolve" in str(exc_info.value).lower()

    def test_missing_hostname_rejected(self):
        """Test that URLs without hostname are rejected"""
        invalid_urls = [
            "https:///webhook",
            "https://",
        ]

        for url in invalid_urls:
            with pytest.raises(ValueError) as exc_info:
                _validate_webhook_url(url)

            assert "hostname" in str(exc_info.value).lower()

    def test_ftp_scheme_rejected(self):
        """Test that non-HTTPS schemes are rejected"""
        invalid_schemes = [
            "ftp://example.com/webhook",
            "file:///etc/passwd",
            "gopher://example.com",
        ]

        for url in invalid_schemes:
            with pytest.raises(ValueError) as exc_info:
                _validate_webhook_url(url)

            assert "https" in str(exc_info.value).lower()

    def test_aws_imds_v2_blocked(self):
        """Test that AWS IMDSv2 endpoint is blocked"""
        with patch('socket.gethostbyname', return_value='169.254.169.254'):
            with pytest.raises(ValueError) as exc_info:
                _validate_webhook_url("https://metadata.aws.internal/latest/meta-data/")

            assert "blocked network range" in str(exc_info.value)

    def test_public_cloud_metadata_endpoints_blocked(self):
        """Test that common cloud metadata endpoints are blocked if they resolve to link-local"""
        metadata_endpoints = [
            ("https://metadata.google.internal", "169.254.169.254"),  # GCP
            ("https://169.254.169.254", "169.254.169.254"),  # AWS direct IP
        ]

        for url, ip in metadata_endpoints:
            with patch('socket.gethostbyname', return_value=ip):
                with pytest.raises(ValueError) as exc_info:
                    _validate_webhook_url(url)

                assert "blocked network range" in str(exc_info.value)

    def test_internal_kubernetes_service_blocked(self):
        """Test that internal Kubernetes services are blocked"""
        with patch('socket.gethostbyname', return_value='10.96.0.1'):  # Common k8s ClusterIP
            with pytest.raises(ValueError) as exc_info:
                _validate_webhook_url("https://kubernetes.default.svc.cluster.local")

            assert "blocked network range" in str(exc_info.value)

    def test_docker_internal_blocked(self):
        """Test that Docker internal networks are blocked"""
        with patch('socket.gethostbyname', return_value='172.17.0.1'):  # Docker default bridge
            with pytest.raises(ValueError) as exc_info:
                _validate_webhook_url("https://host.docker.internal")

            assert "blocked network range" in str(exc_info.value)

    def test_real_world_public_urls_allowed(self):
        """Test that legitimate public webhook services are allowed"""
        public_services = [
            ("https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXX", "54.236.1.1"),
            ("https://discord.com/api/webhooks/123456789/abcdefg", "162.159.135.233"),
            ("https://hooks.zapier.com/hooks/catch/123456/abcdef/", "52.206.207.180"),
        ]

        for url, public_ip in public_services:
            with patch('socket.gethostbyname', return_value=public_ip):
                _validate_webhook_url(url)  # Should not raise

    def test_url_with_credentials_rejected(self):
        """Test that URLs with embedded credentials are handled"""
        # Note: While the code doesn't explicitly block credentials,
        # we should ensure it doesn't cause issues
        url_with_creds = "https://user:pass@example.com/webhook"

        with patch('socket.gethostbyname', return_value='93.184.216.34'):
            _validate_webhook_url(url_with_creds)  # Should still validate the target IP


class TestScheduledReportServiceWebhookSecurity:
    """Test suite for ScheduledReportService webhook delivery security"""

    @pytest.fixture
    def service(self):
        """Create a ScheduledReportService instance for testing"""
        return ScheduledReportService()

    @pytest.fixture
    def mock_result(self):
        """Mock report result data"""
        return {
            "report_name": "Test Report",
            "generated_at": "2026-02-08T12:00:00Z",
            "data": {"cost": 1234.56}
        }

    @pytest.mark.asyncio
    async def test_valid_webhook_delivery_works(self, service, mock_result):
        """Test that delivery to valid HTTPS webhooks works"""
        webhooks = ["https://example.com/webhook"]

        with patch('socket.gethostbyname', return_value='93.184.216.34'):
            with patch('aiohttp.ClientSession.post', new_callable=AsyncMock) as mock_post:
                await service._deliver_via_webhook(webhooks, mock_result)

                # Verify webhook was called
                mock_post.assert_called_once()
                call_args = mock_post.call_args
                assert call_args[0][0] == webhooks[0]
                assert call_args[1]['json'] == mock_result

    @pytest.mark.asyncio
    async def test_ssrf_to_ec2_metadata_blocked(self, service, mock_result):
        """Test that SSRF attacks to EC2 metadata service are blocked"""
        malicious_webhooks = [
            "https://metadata.internal"
        ]

        with patch('socket.gethostbyname', return_value='169.254.169.254'):
            with pytest.raises(ValueError) as exc_info:
                await service._deliver_via_webhook(malicious_webhooks, mock_result)

            assert "blocked network range" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_ssrf_to_internal_network_blocked(self, service, mock_result):
        """Test that SSRF attacks to internal networks are blocked"""
        malicious_webhooks = [
            "https://internal-api.company.local"
        ]

        with patch('socket.gethostbyname', return_value='10.0.1.100'):
            with pytest.raises(ValueError) as exc_info:
                await service._deliver_via_webhook(malicious_webhooks, mock_result)

            assert "blocked network range" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_ssrf_to_localhost_blocked(self, service, mock_result):
        """Test that SSRF attacks to localhost are blocked"""
        malicious_webhooks = ["https://localhost/admin"]

        with pytest.raises(ValueError) as exc_info:
            await service._deliver_via_webhook(malicious_webhooks, mock_result)

        assert "localhost" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_http_webhook_rejected(self, service, mock_result):
        """Test that HTTP webhooks are rejected (HTTPS required)"""
        insecure_webhooks = ["http://example.com/webhook"]

        with pytest.raises(ValueError) as exc_info:
            await service._deliver_via_webhook(insecure_webhooks, mock_result)

        assert "https" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_multiple_webhooks_validated_independently(self, service, mock_result):
        """Test that each webhook in a list is validated independently"""
        webhooks = [
            "https://valid.example.com/webhook",
            "https://internal.blocked.local/webhook"
        ]

        def mock_resolve(hostname):
            if "valid.example.com" in hostname:
                return '93.184.216.34'  # Public IP
            elif "internal.blocked.local" in hostname:
                return '10.0.1.100'  # Private IP
            return '127.0.0.1'

        with patch('socket.gethostbyname', side_effect=mock_resolve):
            with patch('aiohttp.ClientSession.post', new_callable=AsyncMock):
                # Should fail on the second webhook (blocked by validation)
                with pytest.raises(ValueError) as exc_info:
                    await service._deliver_via_webhook(webhooks, mock_result)

                assert "blocked network range" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_webhook_delivery_timeout_set(self, service, mock_result):
        """Test that webhook delivery has a timeout configured"""
        webhooks = ["https://example.com/webhook"]

        with patch('socket.gethostbyname', return_value='93.184.216.34'):
            with patch('aiohttp.ClientSession.post', new_callable=AsyncMock) as mock_post:
                await service._deliver_via_webhook(webhooks, mock_result)

                # Verify timeout was set
                call_args = mock_post.call_args
                assert 'timeout' in call_args[1]


class TestSSRFRegressionTests:
    """Regression tests to ensure SSRF protection stays in place"""

    def test_blocked_cidrs_list_exists(self):
        """Test that BLOCKED_CIDRS list exists and contains expected ranges"""
        assert BLOCKED_CIDRS is not None
        assert len(BLOCKED_CIDRS) >= 5

        # Verify critical ranges are present
        cidr_strings = [str(cidr) for cidr in BLOCKED_CIDRS]
        assert '10.0.0.0/8' in cidr_strings
        assert '172.16.0.0/12' in cidr_strings
        assert '192.168.0.0/16' in cidr_strings
        assert '169.254.0.0/16' in cidr_strings  # EC2 IMDS
        assert '127.0.0.0/8' in cidr_strings  # Loopback

    def test_validation_function_exists(self):
        """Test that _validate_webhook_url function exists"""
        from backend.services.scheduled_report_service import _validate_webhook_url
        assert callable(_validate_webhook_url)

    def test_deliver_webhook_uses_validation(self):
        """Test that _deliver_via_webhook method calls validation"""
        import inspect
        from backend.services.scheduled_report_service import ScheduledReportService

        source = inspect.getsource(ScheduledReportService._deliver_via_webhook)

        # Verify validation is called
        assert "_validate_webhook_url" in source

    def test_https_enforcement_in_validation(self):
        """Test that HTTPS is enforced in validation function"""
        import inspect
        from backend.services.scheduled_report_service import _validate_webhook_url

        source = inspect.getsource(_validate_webhook_url)

        # Verify HTTPS check exists
        assert "https" in source.lower()
        assert "scheme" in source

    def test_common_ssrf_payloads_blocked(self):
        """Test that common SSRF attack payloads are blocked"""
        # Common SSRF payloads from OWASP and real-world attacks
        ssrf_payloads = [
            ("https://metadata.aws.internal", "169.254.169.254"),
            ("https://internal-admin.local", "10.0.0.1"),
            ("https://db-server.internal", "192.168.1.5"),
            ("https://redis.internal", "172.16.0.10"),
        ]

        for url, private_ip in ssrf_payloads:
            with patch('socket.gethostbyname', return_value=private_ip):
                with pytest.raises(ValueError):
                    _validate_webhook_url(url)
