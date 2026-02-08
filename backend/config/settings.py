"""
Application settings and configuration management
Uses Pydantic Settings for environment variable handling and validation
"""

from functools import lru_cache
from typing import ClassVar, FrozenSet, List, Optional, Any
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, PydanticBaseSettingsSource
import os
import json
import secrets
import warnings

from backend.utils.aws_constants import DEFAULT_AWS_REGION


class Settings(BaseSettings):
    """Application settings with environment variable support"""
    
    # Application
    app_name: str = "FinOps AI Cost Intelligence Platform"
    environment: str = Field(default="development", env="ENVIRONMENT")
    debug: bool = Field(default=False, env="DEBUG")
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    host: str = Field(default="0.0.0.0", env="HOST")
    port: int = Field(default=8000, env="PORT")
    
    # Security
    # SECURITY: No default value - must be set via SECRET_KEY environment variable
    # In production, the application will fail to start without a secure secret key
    secret_key: Optional[str] = Field(default=None, env="SECRET_KEY")
    allowed_origins_str: str = Field(
        default='["http://localhost:3000","http://127.0.0.1:3000"]',
        env="ALLOWED_ORIGINS"
    )

    # CORS Security Configuration
    # Explicitly define allowed methods and headers to prevent overly permissive CORS
    cors_allow_methods_str: str = Field(
        default='["GET","POST","PUT","PATCH","DELETE","OPTIONS"]',
        env="CORS_ALLOW_METHODS",
        description="Allowed HTTP methods for CORS (JSON array or comma-separated)"
    )
    cors_allow_headers_str: str = Field(
        default='["Authorization","Content-Type","Accept","Origin","X-Requested-With"]',
        env="CORS_ALLOW_HEADERS",
        description="Allowed HTTP headers for CORS (JSON array or comma-separated)"
    )
    cors_allow_credentials: bool = Field(
        default=True,
        env="CORS_ALLOW_CREDENTIALS",
        description="Allow credentials (cookies, authorization headers) in CORS requests"
    )
    cors_max_age: int = Field(
        default=600,
        env="CORS_MAX_AGE",
        description="Max age (seconds) for CORS preflight cache"
    )

    # Security Headers Configuration
    security_headers_enabled: bool = Field(
        default=True,
        env="SECURITY_HEADERS_ENABLED",
        description="Enable security headers middleware"
    )
    hsts_enabled: bool = Field(
        default=False,
        env="HSTS_ENABLED",
        description="Enable HTTP Strict Transport Security (only for HTTPS)"
    )
    hsts_max_age: int = Field(
        default=31536000,
        env="HSTS_MAX_AGE",
        description="HSTS max-age in seconds (default: 1 year)"
    )
    hsts_include_subdomains: bool = Field(
        default=True,
        env="HSTS_INCLUDE_SUBDOMAINS",
        description="Include subdomains in HSTS policy"
    )
    hsts_preload: bool = Field(
        default=False,
        env="HSTS_PRELOAD",
        description="Enable HSTS preload (requires preload list submission)"
    )
    csp_enabled: bool = Field(
        default=True,
        env="CSP_ENABLED",
        description="Enable Content-Security-Policy header"
    )
    csp_policy: Optional[str] = Field(
        default=None,
        env="CSP_POLICY",
        description="Custom Content-Security-Policy (uses default if not set)"
    )
    x_frame_options: str = Field(
        default="DENY",
        env="X_FRAME_OPTIONS",
        description="X-Frame-Options header value (DENY, SAMEORIGIN)"
    )
    x_content_type_options: str = Field(
        default="nosniff",
        env="X_CONTENT_TYPE_OPTIONS",
        description="X-Content-Type-Options header value"
    )

    # JWT Authentication
    jwt_access_token_expiry_minutes: int = Field(
        default=15,
        env="JWT_ACCESS_TOKEN_EXPIRY_MINUTES",
        description="Access token expiration in minutes"
    )
    jwt_refresh_token_expiry_days: int = Field(
        default=7,
        env="JWT_REFRESH_TOKEN_EXPIRY_DAYS",
        description="Refresh token expiration in days"
    )
    jwt_issuer: str = Field(
        default="finops-platform",
        env="JWT_ISSUER",
        description="JWT token issuer identifier"
    )
    # SECURITY: Legacy header-based auth (X-User-Email) has been REMOVED
    # JWT tokens are now the ONLY supported authentication method
    
    # Database
    postgres_host: str = Field(default="localhost", env="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, env="POSTGRES_PORT")
    postgres_db: str = Field(default="finops", env="POSTGRES_DB")
    postgres_user: str = Field(default="finops", env="POSTGRES_USER")
    postgres_password: str = Field(default="finops", env="POSTGRES_PASSWORD")

    # Database SSL Configuration
    # SECURITY: SSL is required for production/RDS connections
    postgres_ssl_mode: str = Field(
        default="prefer",
        env="POSTGRES_SSL_MODE",
        description="SSL mode: disable, allow, prefer, require, verify-ca, verify-full"
    )
    postgres_ssl_ca_cert_path: Optional[str] = Field(
        default=None,
        env="POSTGRES_SSL_CA_CERT_PATH",
        description="Path to CA certificate bundle (e.g., AWS RDS global-bundle.pem)"
    )
    postgres_ssl_cert_path: Optional[str] = Field(
        default=None,
        env="POSTGRES_SSL_CERT_PATH",
        description="Path to client certificate (for mutual TLS)"
    )
    postgres_ssl_key_path: Optional[str] = Field(
        default=None,
        env="POSTGRES_SSL_KEY_PATH",
        description="Path to client private key (for mutual TLS)"
    )

    # Valkey
    valkey_host: str = Field(default="localhost", env="VALKEY_HOST")
    valkey_port: int = Field(default=6379, env="VALKEY_PORT")
    valkey_db: int = Field(default=0, env="VALKEY_DB")
    valkey_password: Optional[str] = Field(default=None, env="VALKEY_PASSWORD")
    
    # AWS Configuration
    aws_region: str = Field(default=DEFAULT_AWS_REGION, env="AWS_REGION")
    # DEPRECATED: Explicit AWS credentials are insecure and will be ignored.
    # Use IAM roles for EC2/ECS/Lambda or the default credential chain for local development.
    # These settings will be removed in a future version.
    aws_access_key_id: Optional[str] = Field(
        default=None,
        env="AWS_ACCESS_KEY_ID",
        deprecated="Use IAM roles instead. Explicit credentials are ignored for security."
    )
    aws_secret_access_key: Optional[str] = Field(
        default=None,
        env="AWS_SECRET_ACCESS_KEY",
        deprecated="Use IAM roles instead. Explicit credentials are ignored for security."
    )
    aws_s3_bucket: str = Field(default="finops-intelligence-platform-data-${AWS_ACCOUNT_ID}", env="AWS_S3_BUCKET")
    
    # AWS Athena & CUR Configuration
    aws_cur_database: str = Field(default="cost_usage_db", env="AWS_CUR_DATABASE")
    aws_cur_table: str = Field(default="cur_data", env="AWS_CUR_TABLE")
    cur_s3_bucket: str = Field(default="finops-intelligence-platform-data-${AWS_ACCOUNT_ID}", env="CUR_S3_BUCKET")
    cur_s3_prefix: str = Field(default="cost-exports/finops-cost-export", env="CUR_S3_PREFIX")
    athena_output_location: str = Field(
        default="s3://finops-intelligence-platform-data-${AWS_ACCOUNT_ID}/athena-results/",
        env="ATHENA_OUTPUT_LOCATION"
    )
    athena_workgroup: str = Field(default="finops-workgroup", env="ATHENA_WORKGROUP")
    
    # AWS Bedrock Configuration
    bedrock_model_id: str = Field(
        default="us.amazon.nova-premier-v1:0", 
        env="BEDROCK_MODEL_ID",
        description="Bedrock cross-region inference profile for Amazon Nova Premier"
    )
    
    # Available models for dynamic switching (use inference profiles for Nova models)
    available_models: list = [
        "us.amazon.nova-premier-v1:0",                   # Amazon Nova Premier - DEFAULT (most powerful, requires inference profile)
        "us.amazon.nova-pro-v1:0",                        # Amazon Nova 1 Pro (legacy, requires inference profile)
        "us.amazon.nova-lite-v1:0",                       # Amazon Nova 1 Lite (legacy, requires inference profile)
        "us.amazon.nova-micro-v1:0",                      # Amazon Nova 1 Micro (legacy, requires inference profile)
        "us.amazon.nova-2-lite-v1:0",                     # Amazon Nova 2 Lite (requires inference profile)
        "amazon.nova-2-sonic-v1:0",                       # Amazon Nova 2 Sonic (model ID works)
        "meta.llama3-70b-instruct-v1:0",                  # Meta Llama 3 70B (open source alternative)
        "meta.llama3-8b-instruct-v1:0",                   # Meta Llama 3 8B (lighter alternative)
        "mistral.mistral-large-2402-v1:0",                # Mistral Large (European alternative)
        "mistral.mixtral-8x7b-instruct-v0:1",             # Mistral Mixtral 8x7B (MoE model)
        "cohere.command-r-plus-v1:0",                     # Cohere Command R+ (enterprise focused)
        "amazon.titan-text-express-v1",                   # Amazon Titan Text Express (legacy)
    ]
    
    max_tokens: int = Field(default=4000, env="MAX_TOKENS", description="Maximum tokens for LLM responses")
    temperature: float = Field(default=0.7, env="TEMPERATURE", description="Temperature for LLM responses")
    
    # Model Configuration
    default_llm_model: str = Field(default="us.amazon.nova-premier-v1:0", env="DEFAULT_LLM_MODEL")
    embedding_model: str = Field(default="sentence-transformers/all-MiniLM-L6-v2", env="EMBEDDING_MODEL")
    
    # Vector Store
    chroma_db_path: str = Field(default="./data/chroma", env="CHROMA_DB_PATH")
    chroma_collection_name: str = Field(default="cost_intelligence", env="CHROMA_COLLECTION_NAME")
    
    # Cache Configuration
    cache_ttl: int = Field(default=3600, env="CACHE_TTL")  # 1 hour
    
    # Rate Limiting
    rate_limit_requests: int = Field(default=100, env="RATE_LIMIT_REQUESTS")
    rate_limit_window: int = Field(default=60, env="RATE_LIMIT_WINDOW")  # seconds

    # Athena Export Rate Limits (per organization, per hour)
    athena_export_limit_free: int = Field(default=10, env="ATHENA_EXPORT_LIMIT_FREE")
    athena_export_limit_standard: int = Field(default=50, env="ATHENA_EXPORT_LIMIT_STANDARD")
    athena_export_limit_enterprise: int = Field(default=200, env="ATHENA_EXPORT_LIMIT_ENTERPRISE")
    athena_export_window: int = Field(default=3600, env="ATHENA_EXPORT_WINDOW")  # 1 hour

    # Athena Export Per-User Limits (prevents resource hogging within organization)
    # Enterprise tier per-user limits (default: org=200/hour)
    athena_export_per_user_limit_enterprise_owner: int = Field(default=100, env="ATHENA_EXPORT_PER_USER_LIMIT_ENTERPRISE_OWNER")
    athena_export_per_user_limit_enterprise_admin: int = Field(default=100, env="ATHENA_EXPORT_PER_USER_LIMIT_ENTERPRISE_ADMIN")
    athena_export_per_user_limit_enterprise_member: int = Field(default=50, env="ATHENA_EXPORT_PER_USER_LIMIT_ENTERPRISE_MEMBER")

    # Standard tier per-user limits (default: org=50/hour)
    athena_export_per_user_limit_standard_owner: int = Field(default=30, env="ATHENA_EXPORT_PER_USER_LIMIT_STANDARD_OWNER")
    athena_export_per_user_limit_standard_admin: int = Field(default=30, env="ATHENA_EXPORT_PER_USER_LIMIT_STANDARD_ADMIN")
    athena_export_per_user_limit_standard_member: int = Field(default=15, env="ATHENA_EXPORT_PER_USER_LIMIT_STANDARD_MEMBER")

    # Free tier per-user limits (default: org=10/hour)
    athena_export_per_user_limit_free_owner: int = Field(default=5, env="ATHENA_EXPORT_PER_USER_LIMIT_FREE_OWNER")
    athena_export_per_user_limit_free_admin: int = Field(default=5, env="ATHENA_EXPORT_PER_USER_LIMIT_FREE_ADMIN")
    athena_export_per_user_limit_free_member: int = Field(default=3, env="ATHENA_EXPORT_PER_USER_LIMIT_FREE_MEMBER")

    # Background Jobs
    celery_broker_url: Optional[str] = Field(default=None, env="CELERY_BROKER_URL")
    celery_result_backend: Optional[str] = Field(default=None, env="CELERY_RESULT_BACKEND")
    
    # Conversation Understanding
    use_llm_conversation_understanding: bool = Field(
        default=True, 
        env="USE_LLM_CONVERSATION_UNDERSTANDING",
        description="Use LLM to understand entire conversation context instead of rule-based parameter extraction"
    )
    
    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_parse_none_str="null"
    )

    # List of known insecure secret key values that must be rejected
    INSECURE_SECRET_KEYS: ClassVar[FrozenSet[str]] = frozenset([
        "dev-secret-key-change-in-production",
        "secret",
        "changeme",
        "password",
        "123456",
        "your-secret-key",
        "change-me",
        "test-secret",
    ])

    @model_validator(mode='after')
    def validate_and_set_secret_key(self) -> 'Settings':
        """
        Validate and set secret key based on environment.

        SECURITY POLICY:
        - Production: MUST have a secure SECRET_KEY env var (32+ chars, not in insecure list)
        - Development: Auto-generates temporary key with warning if not set
        - Testing (PYTEST): Auto-generates temporary key for tests

        This prevents:
        1. Running production with hardcoded/default secrets
        2. Accidentally deploying with insecure configuration
        """
        # Check if running in test mode (pytest sets this)
        is_testing = (
            os.environ.get("PYTEST_CURRENT_TEST") is not None or
            os.environ.get("TESTING", "").lower() in ("1", "true", "yes")
        )

        # Determine if we're in production (check both self.environment and env var)
        env_from_var = os.environ.get("ENVIRONMENT", "").lower()
        is_production = (
            self.environment.lower() == "production" or
            env_from_var == "production"
        )

        if self.secret_key is None:
            if is_production:
                raise ValueError(
                    "CRITICAL SECURITY ERROR: SECRET_KEY environment variable is required "
                    "in production. Generate a secure key with: "
                    "python -c \"import secrets; print(secrets.token_urlsafe(64))\""
                )
            else:
                # Development or testing: generate temporary key
                generated_key = secrets.token_urlsafe(64)
                object.__setattr__(self, 'secret_key', generated_key)

                if not is_testing:
                    warnings.warn(
                        "\n" + "=" * 70 + "\n"
                        "WARNING: No SECRET_KEY set. Using auto-generated temporary key.\n"
                        "This key will change on every restart, invalidating all tokens.\n"
                        "Set SECRET_KEY environment variable for persistent sessions.\n"
                        "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(64))\"\n"
                        + "=" * 70,
                        UserWarning,
                        stacklevel=2
                    )
        else:
            # Secret key was provided - validate it
            if self.secret_key.lower() in self.INSECURE_SECRET_KEYS:
                if is_production:
                    raise ValueError(
                        f"CRITICAL SECURITY ERROR: SECRET_KEY is set to a known insecure value. "
                        f"Generate a secure key with: "
                        f"python -c \"import secrets; print(secrets.token_urlsafe(64))\""
                    )
                elif not is_testing:
                    warnings.warn(
                        f"WARNING: Using insecure SECRET_KEY. This must be changed for production.",
                        UserWarning,
                        stacklevel=2
                    )

            if len(self.secret_key) < 32:
                if is_production:
                    raise ValueError(
                        f"CRITICAL SECURITY ERROR: SECRET_KEY must be at least 32 characters. "
                        f"Current length: {len(self.secret_key)}. "
                        f"Generate a secure key with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
                    )
                elif not is_testing:
                    warnings.warn(
                        f"WARNING: SECRET_KEY is too short ({len(self.secret_key)} chars). "
                        f"Use at least 32 characters for production.",
                        UserWarning,
                        stacklevel=2
                    )

        return self

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Customize settings sources to exclude .env file loading"""
        # Only use init_settings and env_settings, skip dotenv_settings
        return init_settings, env_settings, file_secret_settings
    
    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v):
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of {valid_levels}")
        return v.upper()
    
    @property
    def allowed_origins(self) -> List[str]:
        """Parse and return allowed_origins as a list"""
        if isinstance(self.allowed_origins_str, list):
            return self.allowed_origins_str
        
        if isinstance(self.allowed_origins_str, str):
            raw = self.allowed_origins_str.strip()
            
            # Try JSON parsing first
            if raw.startswith('[') and raw.endswith(']'):
                try:
                    return json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    pass
            
            # Fall back to comma-separated
            if ',' in raw:
                return [origin.strip() for origin in raw.split(",") if origin.strip()]
            
            # Single value
            if raw:
                return [raw]
        
        # Default fallback
        return ["http://localhost:3000", "http://127.0.0.1:3000"]

    def _parse_string_list(self, value: str, default: List[str]) -> List[str]:
        """Parse a string into a list (JSON array or comma-separated)"""
        if isinstance(value, list):
            return value

        if isinstance(value, str):
            raw = value.strip()

            # Try JSON parsing first
            if raw.startswith('[') and raw.endswith(']'):
                try:
                    return json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    pass

            # Fall back to comma-separated
            if ',' in raw:
                return [item.strip() for item in raw.split(",") if item.strip()]

            # Single value
            if raw:
                return [raw]

        return default

    @property
    def cors_allow_methods(self) -> List[str]:
        """Parse and return CORS allowed methods as a list"""
        default = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
        return self._parse_string_list(self.cors_allow_methods_str, default)

    @property
    def cors_allow_headers(self) -> List[str]:
        """Parse and return CORS allowed headers as a list"""
        default = ["Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With"]
        return self._parse_string_list(self.cors_allow_headers_str, default)

    @property
    def database_url(self) -> str:
        """Construct PostgreSQL database URL with SSL support for RDS"""
        # For asyncpg, SSL is configured via connect_args, not URL params
        # Keep DSN clean; SSL will be enforced in DatabaseService when in production or RDS
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
    
    @property
    def valkey_url(self) -> str:
        """Construct Valkey URL"""
        auth = f":{self.valkey_password}@" if self.valkey_password else ""
        return f"redis://{auth}{self.valkey_host}:{self.valkey_port}/{self.valkey_db}"
    
    @property
    def is_production(self) -> bool:
        """Check if running in production environment"""
        return self.environment.lower() == "production"
    
    @property
    def is_development(self) -> bool:
        """Check if running in development environment"""
        return self.environment.lower() == "development"
    
    @property
    def cur_s3_location(self) -> str:
        """Full S3 path to CUR data"""
        return f"s3://{self.cur_s3_bucket}/{self.cur_s3_prefix}/"

    @property
    def is_secret_key_secure(self) -> bool:
        """Check if secret key meets security requirements"""
        if not self.secret_key:
            return False
        return (
            len(self.secret_key) >= 32 and
            self.secret_key.lower() not in self.INSECURE_SECRET_KEYS
        )

    @property
    def is_rds_database(self) -> bool:
        """Check if database host is AWS RDS"""
        return "rds.amazonaws.com" in self.postgres_host.lower()

    @property
    def requires_ssl_verification(self) -> bool:
        """
        Determine if SSL certificate verification is required.

        Returns True if:
        - Environment is production, OR
        - Database host is AWS RDS, OR
        - SSL mode is verify-ca or verify-full
        """
        strict_modes = {"verify-ca", "verify-full"}
        return (
            self.is_production or
            self.is_rds_database or
            self.postgres_ssl_mode.lower() in strict_modes
        )

    @property
    def ssl_mode_requires_cert(self) -> bool:
        """Check if the SSL mode requires a CA certificate"""
        return self.postgres_ssl_mode.lower() in {"verify-ca", "verify-full"}

    def validate_database_ssl_configuration(self) -> list[str]:
        """
        Validate database SSL configuration.
        Returns list of issues (empty if all valid).
        """
        issues = []

        valid_ssl_modes = {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
        if self.postgres_ssl_mode.lower() not in valid_ssl_modes:
            issues.append(
                f"Invalid POSTGRES_SSL_MODE: '{self.postgres_ssl_mode}'. "
                f"Must be one of: {', '.join(sorted(valid_ssl_modes))}"
            )

        # Check CA cert requirement
        if self.ssl_mode_requires_cert and not self.postgres_ssl_ca_cert_path:
            issues.append(
                f"POSTGRES_SSL_CA_CERT_PATH is required when SSL mode is "
                f"'{self.postgres_ssl_mode}'. Download the AWS RDS CA bundle from: "
                f"https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem"
            )

        # Check if CA cert file exists when specified
        if self.postgres_ssl_ca_cert_path:
            import os
            if not os.path.isfile(self.postgres_ssl_ca_cert_path):
                issues.append(
                    f"SSL CA certificate file not found: {self.postgres_ssl_ca_cert_path}"
                )

        # Warn about insecure configurations in production
        if self.is_production:
            if self.postgres_ssl_mode.lower() == "disable":
                issues.append(
                    "CRITICAL: SSL is disabled in production. "
                    "Set POSTGRES_SSL_MODE to 'verify-full' for secure connections."
                )
            elif self.postgres_ssl_mode.lower() in {"allow", "prefer", "require"}:
                issues.append(
                    f"WARNING: SSL mode '{self.postgres_ssl_mode}' does not verify certificates. "
                    f"Consider using 'verify-full' for production to prevent MITM attacks."
                )

        # RDS-specific checks
        if self.is_rds_database:
            if self.postgres_ssl_mode.lower() not in {"verify-ca", "verify-full"}:
                issues.append(
                    f"WARNING: AWS RDS detected but SSL mode is '{self.postgres_ssl_mode}'. "
                    f"Recommend 'verify-full' with AWS RDS CA bundle for secure connections."
                )

        return issues

    def validate_cur_configuration(self) -> list[str]:
        """
        Validate CUR-related configuration and return list of issues.
        Returns empty list if all valid.
        """
        issues = []
        
        if not self.aws_cur_database:
            issues.append("AWS_CUR_DATABASE is not configured")
        
        if not self.aws_cur_table:
            issues.append("AWS_CUR_TABLE is not configured")
        
        if not self.cur_s3_bucket:
            issues.append("CUR_S3_BUCKET is not configured")
        
        if not self.cur_s3_prefix:
            issues.append("CUR_S3_PREFIX is not configured")
        
        if not self.athena_output_location:
            issues.append("ATHENA_OUTPUT_LOCATION is not configured")
        
        # Check for placeholder values that weren't replaced
        if "${AWS_ACCOUNT_ID}" in self.cur_s3_bucket:
            issues.append("CUR_S3_BUCKET contains unreplaced placeholder ${AWS_ACCOUNT_ID}")
        
        if "${AWS_ACCOUNT_ID}" in self.athena_output_location:
            issues.append("ATHENA_OUTPUT_LOCATION contains unreplaced placeholder ${AWS_ACCOUNT_ID}")

        return issues

    def validate_security_configuration(self) -> list[str]:
        """
        Validate security-related configuration.
        Returns list of issues (empty if all valid).

        NOTE: In production, insecure SECRET_KEY will cause startup to fail
        via the model_validator. This method provides additional warnings.
        """
        issues = []

        if self.is_production:
            # Production security requirements
            # Note: Insecure secret key will have already failed in model_validator
            # This is a secondary check for runtime validation
            if not self.is_secret_key_secure:
                issues.append(
                    "CRITICAL: SECRET_KEY is insecure. Set a secure random key "
                    "(at least 32 characters) via SECRET_KEY environment variable. "
                    "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
                )

            if self.debug:
                issues.append(
                    "WARNING: DEBUG mode is enabled in production"
                )
        else:
            # Non-production warnings
            if not self.is_secret_key_secure:
                issues.append(
                    "WARNING: SECRET_KEY is not secure. For development this is acceptable, "
                    "but ensure a secure key is set for production."
                )

        # Include CORS validation issues
        cors_issues = self.validate_cors_configuration()
        issues.extend(cors_issues)

        # Include database SSL validation issues
        ssl_issues = self.validate_database_ssl_configuration()
        issues.extend(ssl_issues)

        return issues

    def validate_cors_configuration(self) -> list[str]:
        """
        Validate CORS configuration.
        Returns list of issues (empty if all valid).
        """
        issues = []

        # Check for overly permissive origins
        origins = self.allowed_origins
        if "*" in origins:
            if self.is_production:
                issues.append(
                    "CRITICAL: CORS allows all origins ('*') in production. "
                    "This is a security risk. Set specific origins via ALLOWED_ORIGINS."
                )
            else:
                issues.append(
                    "WARNING: CORS allows all origins ('*'). "
                    "This should not be used in production."
                )

        # Check for credentials with wildcard origin
        if "*" in origins and self.cors_allow_credentials:
            issues.append(
                "CRITICAL: CORS allows credentials with wildcard origin. "
                "This is blocked by browsers and indicates misconfiguration."
            )

        # Validate HTTP methods
        valid_methods = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}
        for method in self.cors_allow_methods:
            if method.upper() not in valid_methods:
                issues.append(f"WARNING: Unknown HTTP method in CORS config: {method}")

        # Production-specific checks
        if self.is_production:
            # Warn about localhost origins in production
            for origin in origins:
                if "localhost" in origin.lower() or "127.0.0.1" in origin:
                    issues.append(
                        f"WARNING: Localhost origin '{origin}' in production CORS config. "
                        f"This may indicate development configuration in production."
                    )

        return issues


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached application settings
    Uses lru_cache to avoid reading environment variables multiple times
    """
    return Settings()


def clear_settings_cache() -> None:
    """
    Clear the settings cache. Used primarily for testing.
    After calling this, the next call to get_settings() will
    create a new Settings instance with fresh environment variables.
    """
    get_settings.cache_clear()
