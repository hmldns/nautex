"""Pydantic models for configuration management."""

from typing import Optional
from pydantic import BaseModel, SecretStr, Field
from pydantic_settings import BaseSettings
from .api_models import AccountInfo


class NautexConfig(BaseSettings):
    """Main configuration model using pydantic-settings for .env support.

    This model manages all configuration settings for the Nautex CLI,
    supporting both JSON file storage and environment variable overrides.
    """
    api_host: str = Field("https://api.nautex.ai", description="Base URL for the Nautex.ai API")
    api_token: Optional[SecretStr] = Field(None, description="Bearer token for Nautex.ai API authentication")
    agent_instance_name: str = Field("Coding Agent", description="User-defined name for this CLI instance")
    project_id: Optional[str] = Field(None, description="Selected Nautex.ai project ID")
    plan_id: Optional[str] = Field(None, description="Selected implementation plan ID")

    api_test_mode: bool = Field(False, description="Enable test mode for API client to use dummy responses",
                                exclude=True)

    class Config:
        """Pydantic configuration for environment variables and JSON files."""
        env_file = ".env"
        env_file_encoding = "utf-8"
        env_prefix = "NAUTEX_"  # Environment variables should be prefixed with NAUTEX_
        case_sensitive = False
        extra = "ignore"  # Ignore extra environment variables that don't match our model
        json_schema_extra = {
            "example": {
                "api_host": "http://localhost:8000",
                "api_token": "your-secret-token-here",
                "agent_instance_name": "my-dev-agent",
                "project_id": "PROJ-123",
                "implementation_plan_id": "PLAN-456",
                "api_test_mode": True,
                "account_details": {
                    "profile_email": "user@example.com",
                    "api_version": "1.0.0"
                }
            }
        }


    def get_token(self):
        """Get the API token from the config."""
        return self.api_token.get_secret_value() if self.api_token else None
