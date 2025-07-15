"""Pydantic models for configuration management."""
from pathlib import Path
from typing import Optional, Dict
from pydantic import SecretStr, Field
from pydantic_settings import BaseSettings


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
    documents_path: Optional[str] = Field(None, description="Path to store downloaded documents")

    agent_type: Optional[str] = Field("cursor", description="AI agent to guide")

    class Config:
        """Pydantic configuration for environment variables and JSON files."""
        env_file = [] # we got custom loading calls
        env_file_encoding = "utf-8"
        env_prefix = "NAUTEX_"  # Environment variables should be prefixed with NAUTEX_k
        case_sensitive = False
        extra = "ignore"  # Ignore extra environment variables that don't match our model


    def get_token(self):
        """Get the API token from the config."""
        return self.api_token.get_secret_value() if self.api_token else None


    def to_config_dict(self) -> Dict:
        return self.model_dump(exclude_none=True,
                               exclude={"api_host", "api_token"} # don't serializing these 2
                              )


    def get_agent_mcp_folder(self) -> Path:
        """Get the MCP folder path for the configured agent type.

        Returns:
            Path object pointing to the MCP folder for the agent type.

        Raises:
            ValueError: If the agent type is not supported.
        """
        if self.agent_type == "cursor":
            return Path(".cursor")
        else:
            raise ValueError(f"Unsupported agent type: {self.agent_type}")

    def get_agent_rules_folder(self) -> Path:
        """Get the rules folder path for the configured agent type.

        Returns:
            Path object pointing to the rules folder for the agent type.

        Raises:
            ValueError: If the agent type is not supported.
        """
        if self.agent_type == "cursor":
            return Path(".cursor/rules")
        else:
            raise ValueError(f"Unsupported agent type: {self.agent_type}")
