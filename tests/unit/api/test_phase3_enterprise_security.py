"""
Security tests for Phase 3 Enterprise API - SSTI Input Validation
Tests the input validation for HIGH-4: Jinja2 Server-Side Template Injection (SSTI)
"""

import pytest
from pydantic import ValidationError

from backend.api.phase3_enterprise import ScheduledReportCreate


class TestScheduledReportCreateValidation:
    """Test suite for ScheduledReportCreate input validation"""

    @pytest.fixture
    def valid_report_data(self):
        """Valid report creation data"""
        return {
            'name': 'Monthly Cost Report',
            'description': 'Monthly AWS cost breakdown',
            'report_type': 'cost_breakdown',
            'query_params': {'time_range': 'last_30_days'},
            'frequency': 'MONTHLY',
            'timezone': 'UTC',
            'format': 'HTML',
            'delivery_methods': ['EMAIL'],
            'recipients': {'emails': ['admin@example.com']},
            'report_template': '<html><body>{{ report_name }}</body></html>'
        }

    def test_valid_template_passes_validation(self, valid_report_data):
        """Test that a safe template passes validation"""
        # Should create successfully
        report = ScheduledReportCreate(**valid_report_data)

        assert report.report_template == valid_report_data['report_template']
        assert report.name == valid_report_data['name']

    def test_none_template_is_allowed(self, valid_report_data):
        """Test that None template is allowed (will use default)"""
        valid_report_data['report_template'] = None

        report = ScheduledReportCreate(**valid_report_data)
        assert report.report_template is None

    def test_template_with_double_underscore_blocked(self, valid_report_data):
        """Test that templates with __ are blocked"""
        valid_report_data['report_template'] = '{{ config.__class__ }}'

        with pytest.raises(ValidationError) as exc_info:
            ScheduledReportCreate(**valid_report_data)

        errors = exc_info.value.errors()
        assert len(errors) > 0
        assert 'report_template' in str(errors[0])
        assert '__' in str(errors[0]['msg'])

    def test_template_with_config_blocked(self, valid_report_data):
        """Test that templates with 'config' are blocked"""
        valid_report_data['report_template'] = '{{ config.items() }}'

        with pytest.raises(ValidationError) as exc_info:
            ScheduledReportCreate(**valid_report_data)

        errors = exc_info.value.errors()
        assert 'config' in str(errors[0]['msg']).lower()

    def test_template_with_import_blocked(self, valid_report_data):
        """Test that templates with 'import' are blocked"""
        valid_report_data['report_template'] = "{% set os = __import__('os') %}"

        with pytest.raises(ValidationError) as exc_info:
            ScheduledReportCreate(**valid_report_data)

        # Verify that a disallowed pattern was detected (__import__ or import)
        error_msg = str(exc_info.value.errors()[0]['msg']).lower()
        assert 'disallowed' in error_msg

    def test_template_with_globals_blocked(self, valid_report_data):
        """Test that templates with 'globals' are blocked"""
        valid_report_data['report_template'] = "{{ ''.__class__.__init__.__globals__ }}"

        with pytest.raises(ValidationError) as exc_info:
            ScheduledReportCreate(**valid_report_data)

        # Verify that a disallowed pattern was detected
        error_msg = str(exc_info.value.errors()[0]['msg']).lower()
        assert 'disallowed' in error_msg

    def test_template_with_getattr_blocked(self, valid_report_data):
        """Test that templates with 'getattr' are blocked"""
        valid_report_data['report_template'] = "{{ getattr(config, 'items')() }}"

        with pytest.raises(ValidationError) as exc_info:
            ScheduledReportCreate(**valid_report_data)

        # Verify that a disallowed pattern was detected
        error_msg = str(exc_info.value.errors()[0]['msg']).lower()
        assert 'disallowed' in error_msg

    def test_template_with_subclasses_blocked(self, valid_report_data):
        """Test that templates with 'subclasses' are blocked"""
        valid_report_data['report_template'] = "{{ ''.__class__.__base__.__subclasses__() }}"

        with pytest.raises(ValidationError) as exc_info:
            ScheduledReportCreate(**valid_report_data)

        # Verify that a disallowed pattern was detected
        error_msg = str(exc_info.value.errors()[0]['msg']).lower()
        assert 'disallowed' in error_msg

    def test_template_with_mro_blocked(self, valid_report_data):
        """Test that templates with 'mro' are blocked"""
        valid_report_data['report_template'] = "{{ ''.__class__.__mro__ }}"

        with pytest.raises(ValidationError) as exc_info:
            ScheduledReportCreate(**valid_report_data)

        # Verify that a disallowed pattern was detected
        error_msg = str(exc_info.value.errors()[0]['msg']).lower()
        assert 'disallowed' in error_msg

    def test_template_with_builtins_blocked(self, valid_report_data):
        """Test that templates with 'builtins' are blocked"""
        valid_report_data['report_template'] = "{{ __builtins__ }}"

        with pytest.raises(ValidationError) as exc_info:
            ScheduledReportCreate(**valid_report_data)

        # Verify that a disallowed pattern was detected
        error_msg = str(exc_info.value.errors()[0]['msg']).lower()
        assert 'disallowed' in error_msg

    def test_template_with_eval_blocked(self, valid_report_data):
        """Test that templates with 'eval' are blocked"""
        valid_report_data['report_template'] = "{{ eval('1+1') }}"

        with pytest.raises(ValidationError) as exc_info:
            ScheduledReportCreate(**valid_report_data)

        errors = exc_info.value.errors()
        assert 'eval' in str(errors[0]['msg']).lower()

    def test_template_with_exec_blocked(self, valid_report_data):
        """Test that templates with 'exec' are blocked"""
        valid_report_data['report_template'] = "{{ exec('print(1)') }}"

        with pytest.raises(ValidationError) as exc_info:
            ScheduledReportCreate(**valid_report_data)

        errors = exc_info.value.errors()
        assert 'exec' in str(errors[0]['msg']).lower()

    def test_template_with_compile_blocked(self, valid_report_data):
        """Test that templates with 'compile' are blocked"""
        valid_report_data['report_template'] = "{{ compile('1+1', '<string>', 'eval') }}"

        with pytest.raises(ValidationError) as exc_info:
            ScheduledReportCreate(**valid_report_data)

        # Verify that a disallowed pattern was detected
        error_msg = str(exc_info.value.errors()[0]['msg']).lower()
        assert 'disallowed' in error_msg

    def test_template_with_open_blocked(self, valid_report_data):
        """Test that templates with 'open' are blocked"""
        valid_report_data['report_template'] = "{{ open('/etc/passwd').read() }}"

        with pytest.raises(ValidationError) as exc_info:
            ScheduledReportCreate(**valid_report_data)

        errors = exc_info.value.errors()
        assert 'open' in str(errors[0]['msg']).lower()

    def test_template_with_file_blocked(self, valid_report_data):
        """Test that templates with 'file' are blocked"""
        valid_report_data['report_template'] = "{{ file('/etc/passwd') }}"

        with pytest.raises(ValidationError) as exc_info:
            ScheduledReportCreate(**valid_report_data)

        errors = exc_info.value.errors()
        assert 'file' in str(errors[0]['msg']).lower()

    def test_template_with_class_blocked(self, valid_report_data):
        """Test that templates with 'class' are blocked"""
        valid_report_data['report_template'] = "{{ ''.__class__ }}"

        with pytest.raises(ValidationError) as exc_info:
            ScheduledReportCreate(**valid_report_data)

        # Verify that a disallowed pattern was detected (__ or class)
        error_msg = str(exc_info.value.errors()[0]['msg']).lower()
        assert 'disallowed' in error_msg

    def test_template_with_base_blocked(self, valid_report_data):
        """Test that templates with 'base' are blocked"""
        valid_report_data['report_template'] = "{{ ''.__class__.__base__ }}"

        with pytest.raises(ValidationError) as exc_info:
            ScheduledReportCreate(**valid_report_data)

        # Verify that a disallowed pattern was detected (__ or class or base)
        error_msg = str(exc_info.value.errors()[0]['msg']).lower()
        assert 'disallowed' in error_msg

    def test_template_with_init_blocked(self, valid_report_data):
        """Test that templates with 'init' are blocked"""
        valid_report_data['report_template'] = "{{ ''.__class__.__init__ }}"

        with pytest.raises(ValidationError) as exc_info:
            ScheduledReportCreate(**valid_report_data)

        # Verify that a disallowed pattern was detected (__ or class or init)
        error_msg = str(exc_info.value.errors()[0]['msg']).lower()
        assert 'disallowed' in error_msg

    def test_template_with_reload_blocked(self, valid_report_data):
        """Test that templates with 'reload' are blocked"""
        valid_report_data['report_template'] = "{{ reload(sys) }}"

        with pytest.raises(ValidationError) as exc_info:
            ScheduledReportCreate(**valid_report_data)

        errors = exc_info.value.errors()
        assert 'reload' in str(errors[0]['msg']).lower()

    def test_case_insensitive_blocking(self, valid_report_data):
        """Test that blocked patterns are case-insensitive"""
        # Test with different case variations
        variations = [
            '{{ CONFIG }}',
            '{{ Config }}',
            '{{ cOnFiG }}',
            '{{ __CLASS__ }}',
            '{{ __Class__ }}',
            '{{ IMPORT }}',
            '{{ Import }}'
        ]

        for template in variations:
            valid_report_data['report_template'] = template

            with pytest.raises(ValidationError) as exc_info:
                ScheduledReportCreate(**valid_report_data)

            errors = exc_info.value.errors()
            assert len(errors) > 0

    def test_oversized_template_blocked(self, valid_report_data):
        """Test that templates exceeding size limit are blocked"""
        # Create a template larger than 50KB
        large_template = '<html><body>' + 'A' * 60000 + '</body></html>'
        valid_report_data['report_template'] = large_template

        with pytest.raises(ValidationError) as exc_info:
            ScheduledReportCreate(**valid_report_data)

        errors = exc_info.value.errors()
        assert 'maximum allowed size' in str(errors[0]['msg']).lower()

    def test_safe_template_with_variables(self, valid_report_data):
        """Test that safe templates with variables pass validation"""
        safe_templates = [
            '<html><body><h1>{{ report_name }}</h1></body></html>',
            '<html><body><p>Generated at: {{ generated_at }}</p></body></html>',
            '<html><body>{% for item in data.items %}<li>{{ item.name }}</li>{% endfor %}</body></html>',
            '<html><body>{{ message | upper }}</body></html>',
            '<html><body>{% if data %}{{ data }}{% endif %}</body></html>'
        ]

        for template in safe_templates:
            valid_report_data['report_template'] = template
            report = ScheduledReportCreate(**valid_report_data)
            assert report.report_template == template

    def test_common_ssti_payloads_blocked(self, valid_report_data):
        """Test that common SSTI attack payloads are blocked"""
        # Common SSTI payloads from security research
        malicious_payloads = [
            "{{7*7}}{{config}}",
            "{{config.items()}}",
            "{{''.__class__.__mro__[2].__subclasses__()}}",
            "{{request.application.__globals__.__builtins__.__import__('os').popen('id').read()}}",
            "{{lipsum.__globals__['os'].popen('ls').read()}}",
            "{{cycler.__init__.__globals__.os.popen('id').read()}}",
            "{%set x=''.__class__.__base__.__subclasses__()%}",
            "{{[].__class__.__base__.__subclasses__()}}",
            "{{ ''.__class__.__mro__[1].__subclasses__()[104].__init__.__globals__['sys'].modules['os'].system('ls') }}",
            "{{ config.__class__.__init__.__globals__['os'].popen('whoami').read() }}"
        ]

        for payload in malicious_payloads:
            valid_report_data['report_template'] = payload

            with pytest.raises(ValidationError):
                ScheduledReportCreate(**valid_report_data)

    def test_validation_error_messages_are_informative(self, valid_report_data):
        """Test that validation error messages are clear and helpful"""
        valid_report_data['report_template'] = '{{ config }}'

        with pytest.raises(ValidationError) as exc_info:
            ScheduledReportCreate(**valid_report_data)

        error_msg = str(exc_info.value.errors()[0]['msg'])

        # Error message should mention:
        # 1. That it's disallowed
        # 2. Which pattern was found
        # 3. That it's for security
        assert 'disallowed' in error_msg.lower()
        assert 'config' in error_msg.lower()
        assert 'security' in error_msg.lower()

    def test_multiple_blocked_patterns_in_template(self, valid_report_data):
        """Test template with multiple blocked patterns"""
        valid_report_data['report_template'] = '{{ config.__class__.__init__.__globals__ }}'

        # Should fail on first blocked pattern found
        with pytest.raises(ValidationError) as exc_info:
            ScheduledReportCreate(**valid_report_data)

        # At least one of the blocked patterns should be mentioned
        error_msg = str(exc_info.value)
        blocked_found = any(pattern in error_msg.lower()
                          for pattern in ['config', '__', 'class', 'init', 'globals'])
        assert blocked_found

    def test_empty_string_template_allowed(self, valid_report_data):
        """Test that empty string template is allowed"""
        valid_report_data['report_template'] = ''

        report = ScheduledReportCreate(**valid_report_data)
        assert report.report_template == ''

    def test_whitespace_only_template_allowed(self, valid_report_data):
        """Test that whitespace-only template is allowed"""
        valid_report_data['report_template'] = '   \n\t   '

        report = ScheduledReportCreate(**valid_report_data)
        assert report.report_template == '   \n\t   '


class TestScheduledReportCreateRegressionTests:
    """Regression tests to ensure SSTI input validation stays in place"""

    def test_blocked_patterns_list_is_comprehensive(self):
        """Test that BLOCKED_PATTERNS list includes all dangerous patterns"""
        # Ensure the class has all necessary blocked patterns
        expected_patterns = [
            '__', 'config', 'import', 'globals', 'getattr', 'subclasses', 'mro',
            'builtins', 'class', 'base', 'init', 'eval', 'exec', 'compile',
            'open', 'file', 'input', 'raw_input', 'reload'
        ]

        for pattern in expected_patterns:
            assert pattern in ScheduledReportCreate.BLOCKED_PATTERNS, \
                f"Pattern '{pattern}' should be in BLOCKED_PATTERNS"

    def test_field_validator_decorator_is_present(self):
        """Test that field_validator decorator is applied to validate_template"""
        import inspect

        # Get the validate_template method
        method = getattr(ScheduledReportCreate, 'validate_template')

        # Check that it's a classmethod
        assert isinstance(inspect.getattr_static(ScheduledReportCreate, 'validate_template'),
                         classmethod)

        # Verify it has the field_validator decorator by checking source
        source = inspect.getsource(ScheduledReportCreate)
        assert '@field_validator' in source
        assert "'report_template'" in source

    def test_validation_occurs_before_service_layer(self):
        """Test that validation happens at API layer, not service layer"""
        # This ensures defense in depth - validation at API boundary
        # Try to create invalid model
        invalid_data = {
            'name': 'Test',
            'report_type': 'test',
            'query_params': {},
            'frequency': 'DAILY',
            'format': 'HTML',
            'delivery_methods': ['EMAIL'],
            'recipients': {'emails': []},
            'report_template': '{{ config }}'  # Invalid
        }

        # Should fail at model validation, not reach service
        with pytest.raises(ValidationError):
            ScheduledReportCreate(**invalid_data)
