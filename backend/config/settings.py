"""
Application settings and configuration management
Uses Pydantic Settings for environment variable handling and validation
"""

from functools import lru_cache
from typing import List, Optional, Any
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, PydanticBaseSettingsSource
import os
import json


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
    secret_key: str = Field(default="dev-secret-key-change-in-production", env="SECRET_KEY")
    allowed_origins_str: str = Field(
        default='["http://localhost:3000","http://127.0.0.1:3000"]',
        env="ALLOWED_ORIGINS"
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
    # Allow legacy header-based auth for backward compatibility during migration
    allow_legacy_header_auth: bool = Field(
        default=False,
        env="ALLOW_LEGACY_HEADER_AUTH",
        description="Allow X-User-Email header auth (INSECURE - for migration only)"
    )
    
    # Database
    postgres_host: str = Field(default="localhost", env="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, env="POSTGRES_PORT")
    postgres_db: str = Field(default="finops", env="POSTGRES_DB")
    postgres_user: str = Field(default="finops", env="POSTGRES_USER")
    postgres_password: str = Field(default="finops", env="POSTGRES_PASSWORD")
    
    # Valkey
    valkey_host: str = Field(default="localhost", env="VALKEY_HOST")
    valkey_port: int = Field(default=6379, env="VALKEY_PORT")
    valkey_db: int = Field(default=0, env="VALKEY_DB")
    valkey_password: Optional[str] = Field(default=None, env="VALKEY_PASSWORD")
    
    # AWS Configuration
    aws_region: str = Field(default="us-east-1", env="AWS_REGION")
    aws_access_key_id: Optional[str] = Field(default=None, env="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: Optional[str] = Field(default=None, env="AWS_SECRET_ACCESS_KEY")
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
        insecure_defaults = [
            "dev-secret-key-change-in-production",
            "secret",
            "changeme",
            "password",
            "123456",
        ]
        return (
            len(self.secret_key) >= 32 and
            self.secret_key.lower() not in [s.lower() for s in insecure_defaults]
        )
    
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

        CRITICAL: In production, this MUST return empty list before deployment.
        """
        issues = []

        if self.is_production:
            # Production security requirements
            if not self.is_secret_key_secure:
                issues.append(
                    "CRITICAL: SECRET_KEY is insecure. Set a secure random key "
                    "(at least 32 characters) via SECRET_KEY environment variable"
                )

            if self.allow_legacy_header_auth:
                issues.append(
                    "CRITICAL: ALLOW_LEGACY_HEADER_AUTH is enabled in production. "
                    "This allows authentication bypass via header spoofing"
                )

            if self.debug:
                issues.append(
                    "WARNING: DEBUG mode is enabled in production"
                )

        return issues


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached application settings
    Uses lru_cache to avoid reading environment variables multiple times
    """
    return Settings()
