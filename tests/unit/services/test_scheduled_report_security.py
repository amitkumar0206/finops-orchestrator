"""
Security tests for Scheduled Report Service - SSTI Protection
Tests the fix for HIGH-4: Jinja2 Server-Side Template Injection (SSTI)
"""

import pytest
from jinja2.sandbox import SandboxedEnvironment
from jinja2.exceptions import SecurityError, UndefinedError
import jinja2

from backend.services.scheduled_report_service import ScheduledReportService


class TestScheduledReportSSTIProtection:
    """Test suite for SSTI protection in scheduled reports"""

    @pytest.fixture
    def service(self):
        """Create ScheduledReportService instance"""
        return ScheduledReportService()

    @pytest.fixture
    def mock_report(self):
        """Mock report data"""
        return {
            'name': 'Test Report',
            'report_template': None,
            'delivery_methods': ['EMAIL'],
            'recipients': {'emails': ['test@example.com']}
        }

    @pytest.fixture
    def mock_result(self):
        """Mock query result data"""
        return {
            'data': {'cost': 1000, 'savings': 200},
            'charts': [],
            'message': 'Report generated successfully'
        }

    def test_sandboxed_environment_is_used(self, service):
        """Test that SandboxedEnvironment is being used instead of regular Template"""
        # This test verifies the implementation uses SandboxedEnvironment
        import inspect
        source = inspect.getsource(service._generate_html)

        assert 'SandboxedEnvironment' in source, "Should use SandboxedEnvironment"
        assert 'autoescape=True' in source, "Should enable autoescape"
        assert 'StrictUndefined' in source, "Should use StrictUndefined"

    @pytest.mark.asyncio
    async def test_safe_template_renders_successfully(self, service, mock_report, mock_result, mocker):
        """Test that safe templates render without issues"""
        # Mock S3 upload
        mocker.patch.object(service.s3_service, 'upload', return_value=None)

        # Safe template
        mock_report['report_template'] = """
        <html>
            <body>
                <h1>{{ report_name }}</h1>
                <p>Generated at: {{ generated_at }}</p>
                <p>Message: {{ message }}</p>
            </body>
        </html>
        """

        # Should render successfully
        file_path, size = await service._generate_html(mock_report, mock_result, 'test-exec-123')

        assert file_path == 'reports/test-exec-123.html'
        assert size > 0

    @pytest.mark.asyncio
    async def test_ssti_attack_with_config_access_blocked(self, service, mock_report, mock_result, mocker):
        """Test that SSTI attack using config.__class__ is blocked"""
        mocker.patch.object(service.s3_service, 'upload', return_value=None)

        # Malicious template attempting to access config
        mock_report['report_template'] = """
        <html>
            <body>
                {{ config.__class__.__init__.__globals__['os'].popen('id').read() }}
            </body>
        </html>
        """

        # Should raise SecurityError or UndefinedError (config is not accessible in sandbox)
        with pytest.raises((SecurityError, UndefinedError)):
            await service._generate_html(mock_report, mock_result, 'test-exec-123')

    @pytest.mark.asyncio
    async def test_ssti_attack_with_builtins_blocked(self, service, mock_report, mock_result, mocker):
        """Test that SSTI attack using __builtins__ is blocked"""
        mocker.patch.object(service.s3_service, 'upload', return_value=None)

        # Malicious template attempting to access builtins
        mock_report['report_template'] = """
        {{ ''.__class__.__mro__[1].__subclasses__()[104].__init__.__globals__['sys'].modules['os'].system('ls') }}
        """

        # Should raise SecurityError (attribute access blocked in sandbox)
        with pytest.raises(SecurityError):
            await service._generate_html(mock_report, mock_result, 'test-exec-123')

    @pytest.mark.asyncio
    async def test_ssti_attack_with_import_blocked(self, service, mock_report, mock_result, mocker):
        """Test that SSTI attack using import is blocked"""
        mocker.patch.object(service.s3_service, 'upload', return_value=None)

        # Malicious template attempting to import os
        mock_report['report_template'] = """
        {% set os = __import__('os') %}
        {{ os.popen('whoami').read() }}
        """

        # Should raise SecurityError (__import__ not available in sandbox)
        with pytest.raises((SecurityError, UndefinedError)):
            await service._generate_html(mock_report, mock_result, 'test-exec-123')

    @pytest.mark.asyncio
    async def test_ssti_attack_with_getattr_blocked(self, service, mock_report, mock_result, mocker):
        """Test that dangerous getattr usage is blocked"""
        mocker.patch.object(service.s3_service, 'upload', return_value=None)

        # Malicious template using getattr
        mock_report['report_template'] = """
        {{ ''.__class__ | attr('__mro__') }}
        """

        # Should raise SecurityError or UndefinedError (both indicate SSTI is blocked)
        with pytest.raises((SecurityError, UndefinedError)):
            await service._generate_html(mock_report, mock_result, 'test-exec-123')

    @pytest.mark.asyncio
    async def test_ssti_attack_with_exec_blocked(self, service, mock_report, mock_result, mocker):
        """Test that exec/eval functions are blocked"""
        mocker.patch.object(service.s3_service, 'upload', return_value=None)

        # Malicious template attempting to use exec
        mock_report['report_template'] = """
        {{ exec("import os; os.system('ls')") }}
        """

        # Should raise UndefinedError (exec not available in sandbox)
        with pytest.raises(UndefinedError):
            await service._generate_html(mock_report, mock_result, 'test-exec-123')

    @pytest.mark.asyncio
    async def test_undefined_variable_raises_error(self, service, mock_report, mock_result, mocker):
        """Test that undefined variables raise StrictUndefined error"""
        mocker.patch.object(service.s3_service, 'upload', return_value=None)

        # Template with undefined variable
        mock_report['report_template'] = """
        <html>
            <body>
                {{ undefined_variable }}
            </body>
        </html>
        """

        # Should raise UndefinedError due to StrictUndefined
        with pytest.raises(UndefinedError):
            await service._generate_html(mock_report, mock_result, 'test-exec-123')

    @pytest.mark.asyncio
    async def test_xss_protection_via_autoescape(self, service, mock_report, mock_result, mocker):
        """Test that autoescape protects against XSS"""
        mocker.patch.object(service.s3_service, 'upload', return_value=None)

        # Result with HTML/JavaScript in message
        mock_result['message'] = '<script>alert("XSS")</script>'

        mock_report['report_template'] = """
        <html>
            <body>
                <p>{{ message }}</p>
            </body>
        </html>
        """

        # Should escape the HTML
        file_path, size = await service._generate_html(mock_report, mock_result, 'test-exec-123')

        # Verify S3 upload was called with escaped content
        upload_call = service.s3_service.upload.call_args
        uploaded_content = upload_call[0][1].decode('utf-8')

        # Check that HTML is escaped
        assert '&lt;script&gt;' in uploaded_content
        assert '<script>' not in uploaded_content

    @pytest.mark.asyncio
    async def test_default_template_is_safe(self, service, mock_report, mock_result, mocker):
        """Test that default template (when report_template is None) is safe"""
        mocker.patch.object(service.s3_service, 'upload', return_value=None)

        # No custom template provided
        mock_report['report_template'] = None

        # Should use default template and render successfully
        file_path, size = await service._generate_html(mock_report, mock_result, 'test-exec-123')

        assert file_path == 'reports/test-exec-123.html'
        assert size > 0

    @pytest.mark.asyncio
    async def test_complex_safe_template_with_loops(self, service, mock_report, mock_result, mocker):
        """Test that complex safe templates with loops work correctly"""
        mocker.patch.object(service.s3_service, 'upload', return_value=None)

        # Use a list directly, not a dict with 'items' key (since dict.items is a method)
        mock_result['data'] = {
            'cost_items': [
                {'name': 'Item 1', 'cost': 100},
                {'name': 'Item 2', 'cost': 200}
            ]
        }

        mock_report['report_template'] = """
        <html>
            <body>
                <h1>{{ report_name }}</h1>
                <ul>
                {% for item in data.cost_items %}
                    <li>{{ item.name }}: ${{ item.cost }}</li>
                {% endfor %}
                </ul>
            </body>
        </html>
        """

        # Should render successfully
        file_path, size = await service._generate_html(mock_report, mock_result, 'test-exec-123')

        assert file_path == 'reports/test-exec-123.html'
        assert size > 0

        # Verify content
        upload_call = service.s3_service.upload.call_args
        uploaded_content = upload_call[0][1].decode('utf-8')
        assert 'Item 1' in uploaded_content
        assert 'Item 2' in uploaded_content

    def test_sandboxed_environment_configuration(self):
        """Test that SandboxedEnvironment is configured correctly"""
        # Create environment as done in the service
        env = SandboxedEnvironment(
            autoescape=True,
            undefined=jinja2.StrictUndefined
        )

        # Verify configuration
        assert env.autoescape == True
        assert env.undefined == jinja2.StrictUndefined

        # Verify dangerous operations are blocked
        template = env.from_string("{{ ''.__class__ }}")
        with pytest.raises(SecurityError):
            template.render()

    @pytest.mark.asyncio
    async def test_template_with_safe_filters(self, service, mock_report, mock_result, mocker):
        """Test that safe Jinja2 filters work correctly"""
        mocker.patch.object(service.s3_service, 'upload', return_value=None)

        mock_report['report_template'] = """
        <html>
            <body>
                <p>{{ report_name | upper }}</p>
                <p>{{ report_name | lower }}</p>
                <p>{{ report_name | title }}</p>
            </body>
        </html>
        """

        # Should render successfully with filters
        file_path, size = await service._generate_html(mock_report, mock_result, 'test-exec-123')

        assert file_path == 'reports/test-exec-123.html'
        assert size > 0


class TestScheduledReportSSTIRegressionTests:
    """Regression tests to ensure SSTI vulnerability stays fixed"""

    @pytest.mark.asyncio
    async def test_common_ssti_payloads_are_blocked(self, mocker):
        """Test common SSTI attack payloads from OWASP are blocked"""
        service = ScheduledReportService()
        mocker.patch.object(service.s3_service, 'upload', return_value=None)

        # Common SSTI payloads
        malicious_payloads = [
            "{{7*7}}{{config}}",
            "{{config.items()}}",
            "{{''.__class__.__mro__[2].__subclasses__()}}",
            "{{request.application.__globals__.__builtins__.__import__('os').popen('id').read()}}",
            "{{lipsum.__globals__['os'].popen('ls').read()}}",
            "{{cycler.__init__.__globals__.os.popen('id').read()}}",
            "{%set x=''.__class__.__base__.__subclasses__()%}",
            "{{[].__class__.__base__.__subclasses__()}}",
        ]

        report = {
            'name': 'Test Report',
            'report_template': None,
            'delivery_methods': [],
            'recipients': {}
        }

        result = {'data': {}, 'charts': [], 'message': ''}

        for payload in malicious_payloads:
            report['report_template'] = payload

            # All payloads should raise SecurityError or UndefinedError
            with pytest.raises((SecurityError, UndefinedError)):
                await service._generate_html(report, result, f'test-{hash(payload)}')
