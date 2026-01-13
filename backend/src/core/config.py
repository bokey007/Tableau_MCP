# =============================================================================
# Configuration Management
# =============================================================================
"""Centralized configuration using Pydantic Settings."""

from functools import lru_cache
from typing import List, Optional
from urllib.parse import quote_plus

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # Application
    app_name: str = Field(default="tableau-mcp-backend")
    app_env: str = Field(default="development")
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")
    secret_key: str = Field(default="dev-secret-change-in-production")
    
    # API
    backend_host: str = Field(default="0.0.0.0")
    backend_port: int = Field(default=8000)
    api_prefix: str = Field(default="/api/v1")
    cors_origins: str = Field(default="http://localhost:8501")
    
    # LLM Provider Configuration
    llm_provider: str = Field(default="openai")  # "openai" or "azure"
    
    # OpenAI Configuration
    openai_api_key: str = Field(default="")
    openai_model: str = Field(default="gpt-4-turbo-preview")
    openai_temperature: float = Field(default=0.0)  # 0 for consistent query generation
    openai_max_retries: int = Field(default=3)
    
    # Azure OpenAI Configuration
    azure_openai_api_key: str = Field(default="")
    azure_openai_endpoint: str = Field(default="")  # e.g., https://your-resource.openai.azure.com/
    azure_openai_deployment: str = Field(default="")  # Your deployment name
    azure_openai_api_version: str = Field(default="2024-02-15-preview")
    
    # Tableau MCP Server
    mcp_server_url: str = Field(default="http://mcp:3927")
    mcp_request_timeout: int = Field(default=240)  # 4 minutes for complex Tableau API calls
    
    # Tableau Cloud Configuration
    tableau_server: Optional[str] = Field(default=None)
    tableau_site_name: Optional[str] = Field(default=None)
    tableau_auth_method: str = Field(default="connected_app")  # 'connected_app' or 'pat'
    
    # Tableau Connected Apps (JWT) Authentication
    tableau_connected_app_client_id: Optional[str] = Field(default=None)
    tableau_connected_app_secret_id: Optional[str] = Field(default=None)
    tableau_connected_app_secret_value: Optional[str] = Field(default=None)
    tableau_username: Optional[str] = Field(default=None)  # User to impersonate
    
    # Tableau Personal Access Token (PAT) Authentication
    tableau_pat_name: Optional[str] = Field(default=None)
    tableau_pat_value: Optional[str] = Field(default=None)
    
    # PostgreSQL Database
    postgres_host: str = Field(default="localhost")
    postgres_port: int = Field(default=5432)
    postgres_user: str = Field(default="tableau_mcp")
    postgres_password: str = Field(default="password")
    postgres_db: str = Field(default="tableau_mcp_db")
    
    # Activity Tracking
    enable_activity_tracking: bool = Field(default=True)
    activity_retention_days: int = Field(default=90)
    
    # Cache
    cache_ttl: int = Field(default=300)
    cache_max_size: int = Field(default=1000)
    
    @property
    def database_url(self) -> str:
        """Construct async database URL."""
        password_encoded = quote_plus(self.postgres_password)
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{password_encoded}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
    
    @property
    def sync_database_url(self) -> str:
        """Construct sync database URL for Alembic."""
        password_encoded = quote_plus(self.postgres_password)
        return (
            f"postgresql://{self.postgres_user}:{password_encoded}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
    
    @property
    def cors_origins_list(self) -> List[str]:
        """Get CORS origins as list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]
    
    @property
    def is_production(self) -> bool:
        """Check if production environment."""
        return self.app_env.lower() == "production"
    
    @property
    def openai_configured(self) -> bool:
        """Check if OpenAI is properly configured."""
        return bool(self.openai_api_key and self.openai_api_key.startswith("sk-"))
    
    @property
    def azure_openai_configured(self) -> bool:
        """Check if Azure OpenAI is properly configured."""
        return all([
            self.azure_openai_api_key,
            self.azure_openai_endpoint,
            self.azure_openai_deployment,
        ])
    
    @property
    def llm_configured(self) -> bool:
        """Check if the selected LLM provider is properly configured."""
        if self.llm_provider == "azure":
            return self.azure_openai_configured
        return self.openai_configured
    
    @property
    def tableau_configured(self) -> bool:
        """Check if Tableau authentication is properly configured."""
        if not self.tableau_server or not self.tableau_site_name:
            return False
        
        if self.tableau_auth_method == "connected_app":
            return all([
                self.tableau_connected_app_client_id,
                self.tableau_connected_app_secret_id,
                self.tableau_connected_app_secret_value,
                self.tableau_username,
            ])
        else:  # PAT
            return all([
                self.tableau_pat_name,
                self.tableau_pat_value,
            ])
    
    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level."""
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v = v.upper()
        if v not in valid:
            raise ValueError(f"Invalid log level: {v}. Must be one of: {valid}")
        return v
    
    @field_validator("app_env")
    @classmethod
    def validate_app_env(cls, v: str) -> str:
        """Validate application environment."""
        valid = {"development", "staging", "production", "test"}
        v = v.lower()
        if v not in valid:
            raise ValueError(f"Invalid app_env: {v}. Must be one of: {valid}")
        return v


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings singleton."""
    return Settings()


# Global settings instance
settings = get_settings()
