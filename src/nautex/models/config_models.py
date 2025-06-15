"""Pydantic models for configuration management."""

from typing import Optional
from pydantic import BaseModel, SecretStr, Field
from pydantic_settings import BaseSettings


class AccountInfo(BaseModel):
    """Account information from Nautex.ai API.
    
    This model represents the account details returned from the 
    Nautex.ai /d/v1/info/account endpoint after successful token validation.
    """
    profile_email: str = Field(..., description="User's profile email address")
    api_version: str = Field(..., description="API version from the response")
    response_latency: Optional[float] = Field(None, description="API response latency in seconds")
    
    class Config:
        """Pydantic configuration."""
        json_schema_extra = {
            "example": {
                "profile_email": "user@example.com",
                "api_version": "1.0.0",
                "response_latency": 0.245
            }
        }


class NautexConfig(BaseSettings):
    """Main configuration model using pydantic-settings for .env support.
    
    This model manages all configuration settings for the Nautex CLI,
    supporting both JSON file storage and environment variable overrides.
    """
    api_token: SecretStr = Field(..., description="Bearer token for Nautex.ai API authentication")
    agent_instance_name: str = Field(..., description="User-defined name for this CLI instance")
    project_id: Optional[str] = Field(None, description="Selected Nautex.ai project ID")
    implementation_plan_id: Optional[str] = Field(None, description="Selected implementation plan ID")
    account_details: Optional[AccountInfo] = Field(None, description="Account information from API validation")
    api_test_mode: bool = Field(True, description="Enable test mode for API client to use dummy responses")
    
    class Config:
        """Pydantic configuration for environment variables and JSON files."""
        env_file = ".env"
        env_file_encoding = "utf-8"
        env_prefix = "NAUTEX_"  # Environment variables should be prefixed with NAUTEX_
        case_sensitive = False
        extra = "ignore"  # Ignore extra environment variables that don't match our model
        json_schema_extra = {
            "example": {
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